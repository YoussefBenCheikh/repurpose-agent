"""Pick a LangGraph checkpointer: Postgres when configured, in-memory otherwise."""

from collections.abc import Iterator
from contextlib import contextmanager

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from repurpose_agent.config import Settings
from repurpose_agent.schemas import (
    Critique,
    Draft,
    KeyInsights,
    LinkedInPost,
    PinterestPin,
    Platform,
    SourceDocument,
    XThread,
)

# Checkpoints are deserialized with msgpack. Only these app types (plus LangGraph's
# built-in safe types) may be rebuilt, so a tampered checkpoint can't instantiate
# arbitrary classes.
STATE_TYPES = [
    Platform,
    SourceDocument,
    KeyInsights,
    Draft,
    Critique,
    PinterestPin,
    XThread,
    LinkedInPost,
]


def make_serde() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=STATE_TYPES)


def memory_saver() -> InMemorySaver:
    return InMemorySaver(serde=make_serde())


@contextmanager
def open_checkpointer(settings: Settings) -> Iterator[BaseCheckpointSaver]:
    if not settings.database_url:
        yield memory_saver()
        return

    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    with ConnectionPool(
        settings.database_url,
        max_size=10,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    ) as pool:
        saver = PostgresSaver(pool, serde=make_serde())
        saver.setup()  # creates checkpoint tables on first run; no-op afterwards
        yield saver
