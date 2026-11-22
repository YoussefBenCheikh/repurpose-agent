"""The LangGraph pipeline.

START -> ingest -> analyze -> [write x N platforms, in parallel] -> critique
                                     ^                               |
                                     |-- score < pass & budget left -+
                                     |                               v
                                     +------- revise ------- human_review -> END
"""

import json
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send, interrupt

from repurpose_agent import prompts
from repurpose_agent.config import Settings
from repurpose_agent.ingest import fetch_url, make_document
from repurpose_agent.llm import StructuredLLM
from repurpose_agent.schemas import (
    DRAFT_SCHEMAS,
    Critique,
    Draft,
    KeyInsights,
    Platform,
    ReviewDecision,
    SourceDocument,
)


def merge_dicts(left: dict | None, right: dict | None) -> dict:
    return {**(left or {}), **(right or {})}


class GraphState(TypedDict, total=False):
    # inputs: either a url, or raw text (+ optional title)
    url: str | None
    text: str | None
    title: str | None
    platforms: list[Platform]

    source: SourceDocument
    insights: KeyInsights
    drafts: Annotated[dict[Platform, Draft], merge_dicts]
    critiques: Annotated[dict[Platform, Critique], merge_dicts]
    feedback: Annotated[dict[Platform, str], merge_dicts]
    pending: list[Platform]  # platforms that need a (re)write next
    approved: bool


class WriteTask(TypedDict):
    platform: Platform
    insights: KeyInsights
    previous: Draft | None
    feedback: str | None


def _dump(model: Any) -> str:
    return json.dumps(model.model_dump(mode="json"), indent=2, ensure_ascii=False)


def build_graph(
    llm: StructuredLLM,
    settings: Settings,
    checkpointer: BaseCheckpointSaver | None = None,
):
    # ------------------------------------------------------------------ nodes

    def ingest(state: GraphState) -> dict:
        if state.get("text"):
            doc = make_document(
                state.get("title") or "Untitled",
                state["text"],
                state.get("url"),
                settings.max_source_chars,
            )
        elif state.get("url"):
            doc = fetch_url(
                state["url"],
                timeout=settings.http_timeout,
                max_chars=settings.max_source_chars,
            )
        else:
            raise ValueError("Provide either 'url' or 'text'.")
        return {"source": doc}

    def analyze(state: GraphState) -> dict:
        src = state["source"]
        insights = llm.generate(
            KeyInsights, prompts.ANALYST_SYSTEM, prompts.analyst_prompt(src.title, src.text)
        )
        platforms = state.get("platforms") or list(Platform)
        return {"insights": insights, "platforms": platforms, "pending": platforms}

    def write(task: WriteTask) -> dict:
        platform, prev = task["platform"], task["previous"]
        content = llm.generate(
            DRAFT_SCHEMAS[platform],
            prompts.WRITER_SYSTEM,
            prompts.writer_prompt(
                str(platform),
                _dump(task["insights"]),
                _dump(prev.content) if prev else None,
                task["feedback"],
            ),
        )
        revision = prev.revision + 1 if prev else 0
        draft = Draft(platform=platform, content=content, revision=revision)
        return {"drafts": {platform: draft}}

    def critique(state: GraphState) -> dict:
        insights_json = _dump(state["insights"])
        targets = state["pending"]

        def review(p: Platform) -> Critique:
            return llm.generate(
                Critique,
                prompts.CRITIC_SYSTEM,
                prompts.critic_prompt(str(p), insights_json, _dump(state["drafts"][p].content)),
            )

        with ThreadPoolExecutor(max_workers=len(targets) or 1) as pool:
            results = dict(zip(targets, pool.map(review, targets), strict=True))

        retry = [
            p
            for p, c in results.items()
            if c.score < settings.pass_score
            and state["drafts"][p].revision < settings.max_revisions
        ]
        feedback = {p: "\n".join(f"- {i}" for i in results[p].issues) for p in retry}
        return {"critiques": results, "pending": retry, "feedback": feedback}

    def human_review(state: GraphState) -> dict:
        raw = interrupt(
            {
                "drafts": {str(p): d.model_dump(mode="json") for p, d in state["drafts"].items()},
                "critiques": {
                    str(p): c.model_dump(mode="json") for p, c in state["critiques"].items()
                },
            }
        )
        decision = ReviewDecision.model_validate(raw)
        if decision.approved or not decision.feedback:
            return {"approved": True, "pending": []}
        return {
            "approved": False,
            "pending": list(decision.feedback),
            "feedback": decision.feedback,
        }

    # ---------------------------------------------------------------- routing

    def send_writes(state: GraphState) -> list[Send]:
        drafts = state.get("drafts") or {}
        feedback = state.get("feedback") or {}
        return [
            Send(
                "write",
                WriteTask(
                    platform=p,
                    insights=state["insights"],
                    previous=drafts.get(p),
                    feedback=feedback.get(p) if p in drafts else None,
                ),
            )
            for p in state["pending"]
        ]

    def after_critique(state: GraphState) -> list[Send] | str:
        return send_writes(state) if state["pending"] else "human_review"

    def after_review(state: GraphState) -> list[Send] | str:
        return END if state.get("approved") else send_writes(state)

    # ------------------------------------------------------------------ graph

    g = StateGraph(GraphState)
    g.add_node("ingest", ingest)
    g.add_node("analyze", analyze)
    g.add_node("write", write)
    g.add_node("critique", critique)
    g.add_node("human_review", human_review)

    g.add_edge(START, "ingest")
    g.add_edge("ingest", "analyze")
    g.add_conditional_edges("analyze", send_writes, ["write"])
    g.add_edge("write", "critique")
    g.add_conditional_edges("critique", after_critique, ["write", "human_review"])
    g.add_conditional_edges("human_review", after_review, ["write", END])

    from repurpose_agent.checkpoint import memory_saver  # local: checkpoint imports schemas

    return g.compile(checkpointer=checkpointer or memory_saver())
