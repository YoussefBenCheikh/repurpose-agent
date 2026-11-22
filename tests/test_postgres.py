"""Runs only when TEST_DATABASE_URL points at a Postgres instance (it does in CI)."""

import os
import uuid

import pytest
from langgraph.types import Command

from repurpose_agent.checkpoint import open_checkpointer
from repurpose_agent.config import Settings
from repurpose_agent.graph import build_graph
from repurpose_agent.schemas import Platform
from repurpose_agent.voice import BrandPost, open_voice_store

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


def test_pgvector_voice_store():
    settings = Settings(database_url=DB_URL, embeddings="hash", brand_file=None)
    tag = uuid.uuid4().hex  # keep this run's rows distinguishable
    with open_voice_store(settings) as store:
        before = store.count(Platform.X)
        posts = [
            BrandPost(platform="x", text=f"postgres queues are underrated {tag}"),
            BrandPost(platform="x", text=f"my morning routine {tag}"),
        ]
        assert store.add(posts) == 2
        assert store.add(posts[:1]) == 0  # unique (platform, md5(text))
        assert store.count(Platform.X) == before + 2
        assert store.search(f"postgres queue {tag}", Platform.X, k=1) == [posts[0].text]
