"""Runs only when TEST_DATABASE_URL points at a Postgres instance (it does in CI)."""

import os
import uuid

import pytest
from langgraph.types import Command

from repurpose_agent.checkpoint import open_checkpointer
from repurpose_agent.config import Settings
from repurpose_agent.graph import build_graph
from repurpose_agent.schemas import Platform

from .fakes import FakeLLM

DB_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set")


def test_run_survives_restart():
    settings = Settings(database_url=DB_URL)
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    inputs = {"text": "Postgres is a great queue. " * 20, "platforms": [Platform.X]}

    # first "process": run until the human review pause
    with open_checkpointer(settings) as saver:
        build_graph(FakeLLM(), settings, saver).invoke(inputs, config)

    # second "process": fresh pool + graph, resume from the stored checkpoint
    with open_checkpointer(settings) as saver:
        graph = build_graph(FakeLLM(), settings, saver)
        snap = graph.get_state(config)
        assert snap.interrupts
        assert snap.values["drafts"][Platform.X].revision == 0

        graph.invoke(Command(resume={"approved": True}), config)
        assert graph.get_state(config).values["approved"] is True
