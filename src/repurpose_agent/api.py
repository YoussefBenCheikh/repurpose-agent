"""HTTP API: start a run, stream its progress over SSE, resume it after review.

    POST /runs                     start a run      -> text/event-stream
    POST /runs/{thread_id}/resume  approve / revise -> text/event-stream
    GET  /runs/{thread_id}         current status, drafts and critiques
    POST /brand/posts              add past posts for brand-voice retrieval
    GET  /brand/posts/count        how many past posts are stored, per platform
    GET  /brand/search?q=&platform= preview what retrieval returns

SSE events: `run` (thread id), `node` (a node finished), `review` (paused,
waiting for a human), `done` (final status), `error`.
"""

import json
import logging
import uuid
from collections.abc import Iterator
from contextlib import ExitStack, asynccontextmanager
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command
from pydantic import BaseModel, HttpUrl, model_validator

from repurpose_agent.checkpoint import open_checkpointer
from repurpose_agent.config import Settings, get_settings
from repurpose_agent.demo import DemoLLM
from repurpose_agent.graph import build_graph
from repurpose_agent.llm import AnthropicLLM, StructuredLLM
from repurpose_agent.schemas import Platform, ReviewDecision
from repurpose_agent.usage import UsageTracker, run_config
from repurpose_agent.voice import BrandPost, VoiceStore, open_voice_store

log = logging.getLogger(__name__)

RunStatusName = Literal["running", "awaiting_review", "completed"]


class RunRequest(BaseModel):
    url: HttpUrl | None = None
    text: str | None = None
    title: str | None = None
    platforms: list[Platform] = list(Platform)

    @model_validator(mode="after")
    def _url_or_text(self) -> "RunRequest":
        if not self.url and not self.text:
            raise ValueError("Provide either 'url' or 'text'.")
        return self


class RunStatus(BaseModel):
    thread_id: str
    status: RunStatusName
    drafts: dict[str, Any] = {}
    critiques: dict[str, Any] = {}


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(jsonable_encoder(data), ensure_ascii=False)}\n\n"


def _summarize(node: str, update: dict | None) -> dict:
    """Keep SSE payloads small: never echo the full source text."""
    update = dict(update or {})
    if src := update.get("source"):
        update["source"] = {"title": src.title, "chars": len(src.text), "truncated": src.truncated}
    return {"node": node, "update": update}


def _status(values: dict, interrupted: bool, has_next: bool) -> RunStatusName:
    if interrupted:
        return "awaiting_review"
    if has_next or not values.get("approved"):
        return "running"
    return "completed"


def create_app(
    llm: StructuredLLM | None = None,
    settings: Settings | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    voice_store: VoiceStore | None = None,
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        with ExitStack() as stack:
            saver = checkpointer or stack.enter_context(open_checkpointer(settings))
            store = voice_store or stack.enter_context(open_voice_store(settings))
            model = llm or (DemoLLM() if settings.demo else AnthropicLLM(settings))
            app.state.voice = store
            app.state.graph = build_graph(model, settings, saver, store)
            yield

    app = FastAPI(title="repurpose-agent", version="0.3.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def stream_run(
        request: Request, graph_input: Any, thread_id: str, phase: str
    ) -> StreamingResponse:
        graph = request.app.state.graph
        tracker = UsageTracker()
        config = run_config(thread_id, tracker, phase=phase)

        # Sync generator: Starlette runs it in a worker thread, which suits the
        # sync graph (the critic node already parallelises with threads).
        def events() -> Iterator[str]:
            yield _sse("run", {"thread_id": thread_id})
            try:
                for chunk in graph.stream(graph_input, config, stream_mode="updates"):
                    for node, update in chunk.items():
                        if node == "__interrupt__":
                            yield _sse("review", update[0].value)
                        else:
                            yield _sse("node", _summarize(node, update))
                snap = graph.get_state(config)
                status = _status(snap.values, bool(snap.interrupts), bool(snap.next))
                yield _sse(
                    "done", {"thread_id": thread_id, "status": status, "usage": tracker.summary()}
                )
            except Exception as e:  # surface failures to the client instead of a dropped stream
                log.exception("run %s failed", thread_id)
                yield _sse(
                    "error",
                    {"thread_id": thread_id, "message": str(e), "usage": tracker.summary()},
                )

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"X-Thread-Id": thread_id, "Cache-Control": "no-cache"},
        )

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "demo": settings.demo and llm is None}

    @app.post("/brand/posts")
    def add_brand_posts(posts: list[BrandPost], request: Request) -> dict:
        return {"added": request.app.state.voice.add(posts)}

    @app.get("/brand/posts/count")
    def count_brand_posts(request: Request) -> dict[str, int]:
        store: VoiceStore = request.app.state.voice
        return {str(p): store.count(p) for p in Platform}

    @app.get("/brand/search")
    def search_brand(q: str, platform: Platform, request: Request, k: int = 3) -> list[str]:
        return request.app.state.voice.search(q, platform, min(k, 10))

    @app.post("/runs")
    def start_run(body: RunRequest, request: Request) -> StreamingResponse:
        graph_input = body.model_dump(mode="json") | {"platforms": body.platforms}
        return stream_run(request, graph_input, str(uuid.uuid4()), phase="start")

    @app.get("/runs/{thread_id}")
    def get_run(thread_id: str, request: Request) -> RunStatus:
        snap = request.app.state.graph.get_state({"configurable": {"thread_id": thread_id}})
        if not snap.values:
            raise HTTPException(404, "Run not found")
        v = snap.values
        return RunStatus(
            thread_id=thread_id,
            status=_status(v, bool(snap.interrupts), bool(snap.next)),
            drafts={str(p): d.model_dump(mode="json") for p, d in v.get("drafts", {}).items()},
            critiques={
                str(p): c.model_dump(mode="json") for p, c in v.get("critiques", {}).items()
            },
        )

    @app.post("/runs/{thread_id}/resume")
    def resume_run(thread_id: str, body: ReviewDecision, request: Request) -> StreamingResponse:
        snap = request.app.state.graph.get_state({"configurable": {"thread_id": thread_id}})
        if not snap.values:
            raise HTTPException(404, "Run not found")
        if not snap.interrupts:
            raise HTTPException(409, "Run is not waiting for review")
        decision = body.model_dump(mode="json")
        return stream_run(request, Command(resume=decision), thread_id, phase="resume")

    return app


def app_factory() -> FastAPI:
    """Entry point for `uvicorn --factory repurpose_agent.api:app_factory`."""
    return create_app()
