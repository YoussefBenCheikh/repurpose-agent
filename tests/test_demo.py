import uuid

from langgraph.types import Command

from repurpose_agent.config import Settings
from repurpose_agent.demo import DemoLLM
from repurpose_agent.graph import build_graph
from repurpose_agent.schemas import Platform

TEXT = (
    "Postgres can run your background jobs. SKIP LOCKED lets many workers share one table. "
    "You avoid running Redis just for a queue. Retries and scheduling fit in plain SQL. "
) * 3


def test_demo_run_shows_rewrite_loop_and_valid_drafts():
    settings = Settings()
    graph = build_graph(DemoLLM(delay=0), settings)
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    graph.invoke({"text": TEXT, "title": "Postgres queues"}, config)
    state = graph.get_state(config).values

    assert state["drafts"][Platform.PINTEREST].revision == 1  # failed once, rewritten
    assert state["critiques"][Platform.PINTEREST].score >= settings.pass_score
    assert state["drafts"][Platform.X].revision == 0

    graph.invoke(Command(resume={"approved": False, "feedback": {"linkedin": "shorter"}}), config)
    assert graph.get_state(config).values["drafts"][Platform.LINKEDIN].revision == 1
