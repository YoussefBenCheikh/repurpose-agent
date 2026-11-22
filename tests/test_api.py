import json

import pytest
from fastapi.testclient import TestClient

from repurpose_agent.api import create_app
from repurpose_agent.checkpoint import memory_saver
from repurpose_agent.config import Settings

from .fakes import FakeLLM

TEXT = "Postgres is a great queue. " * 20


def parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


@pytest.fixture
def client():
    app = create_app(FakeLLM(), Settings(cors_origins=[]), memory_saver())
    with TestClient(app) as c:
        yield c


def start(client, **body):
    resp = client.post("/runs", json={"text": TEXT, "title": "Queues"} | body)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    return resp.headers["x-thread-id"], parse_sse(resp.text)


def test_run_streams_nodes_then_pauses_for_review(client):
    thread_id, events = start(client)
    names = [e for e, _ in events]

    assert names[0] == "run" and names[-1] == "done"
    nodes = [d["node"] for e, d in events if e == "node"]
    assert nodes[:2] == ["ingest", "analyze"] and nodes.count("write") == 3
    assert "review" in names
    assert events[-1][1]["status"] == "awaiting_review"

    ingest = next(d for e, d in events if e == "node" and d["node"] == "ingest")
    assert "text" not in ingest["update"]["source"]  # full source text is not echoed

    status = client.get(f"/runs/{thread_id}").json()
    assert status["status"] == "awaiting_review"
    assert set(status["drafts"]) == {"pinterest", "x", "linkedin"}


def test_resume_with_approval_completes(client):
    thread_id, _ = start(client)
    events = parse_sse(client.post(f"/runs/{thread_id}/resume", json={"approved": True}).text)

    event, data = events[-1]
    assert event == "done" and data["status"] == "completed"
    assert data["usage"]["calls"] == 0  # FakeLLM bypasses LangChain, so nothing is metered
    assert client.get(f"/runs/{thread_id}").json()["status"] == "completed"
    # a finished run can't be resumed again
    assert client.post(f"/runs/{thread_id}/resume", json={"approved": True}).status_code == 409


def test_resume_with_feedback_rewrites_and_pauses_again(client):
    thread_id, _ = start(client, platforms=["x", "linkedin"])
    body = {"approved": False, "feedback": {"x": "punchier"}}
    events = parse_sse(client.post(f"/runs/{thread_id}/resume", json=body).text)

    writes = [d for e, d in events if e == "node" and d["node"] == "write"]
    assert len(writes) == 1 and "x" in writes[0]["update"]["drafts"]
    assert events[-1][1]["status"] == "awaiting_review"


def test_validation_and_unknown_runs(client):
    assert client.post("/runs", json={"title": "no input"}).status_code == 422
    assert client.post("/runs", json={"text": "x", "platforms": ["tiktok"]}).status_code == 422
    assert client.get("/runs/nope").status_code == 404
    assert client.post("/runs/nope/resume", json={"approved": True}).status_code == 404


def test_errors_are_sent_as_sse_event(client):
    events = parse_sse(client.post("/runs", json={"url": "http://127.0.0.1:9/nothing"}).text)
    assert events[-1][0] == "error"
