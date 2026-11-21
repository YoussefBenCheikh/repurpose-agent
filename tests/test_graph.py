import uuid

from langgraph.types import Command

from repurpose_agent.config import Settings
from repurpose_agent.graph import build_graph
from repurpose_agent.schemas import Platform

from .fakes import FakeLLM

SETTINGS = Settings(pass_score=8, max_revisions=2)
INPUT = {"text": "Postgres is a great queue. " * 20, "title": "Queues"}


def run_until_interrupt(llm, inputs=INPUT):
    graph = build_graph(llm, SETTINGS)
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    graph.invoke(inputs, config)
    return graph, config


def test_happy_path_pauses_for_human_then_finishes():
    llm = FakeLLM()
    graph, config = run_until_interrupt(llm)

    snap = graph.get_state(config)
    assert snap.interrupts, "graph should pause at human_review"
    assert set(snap.interrupts[0].value["drafts"]) == {"pinterest", "x", "linkedin"}
    assert llm.calls["Critique"] == 3

    graph.invoke(Command(resume={"approved": True}), config)
    final = graph.get_state(config)
    assert not final.next and final.values["approved"] is True


def test_low_score_triggers_rewrite_with_feedback():
    llm = FakeLLM(scores={"pinterest": [5]})  # fails once, then passes
    graph, config = run_until_interrupt(llm)

    state = graph.get_state(config).values
    assert state["drafts"][Platform.PINTEREST].revision == 1
    assert state["drafts"][Platform.X].revision == 0
    assert llm.calls["PinterestPin"] == 2
    assert any("Hook is weak" in p for p in llm.prompts)


def test_revision_budget_is_respected():
    llm = FakeLLM(scores={"x": [3] * 10})
    graph, config = run_until_interrupt(llm, INPUT | {"platforms": [Platform.X]})

    state = graph.get_state(config).values
    assert state["drafts"][Platform.X].revision == SETTINGS.max_revisions
    assert graph.get_state(config).interrupts  # still reaches the human


def test_human_feedback_rewrites_only_that_platform():
    llm = FakeLLM()
    graph, config = run_until_interrupt(llm)

    graph.invoke(Command(resume={"approved": False, "feedback": {"x": "Make it punchier"}}), config)

    state = graph.get_state(config).values
    assert state["drafts"][Platform.X].revision == 1
    assert state["drafts"][Platform.LINKEDIN].revision == 0
    assert any("Make it punchier" in p for p in llm.prompts)
    assert graph.get_state(config).interrupts  # back to human after rewrite
