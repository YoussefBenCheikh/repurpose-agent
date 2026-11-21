"""Pick a LangGraph checkpointer: Postgres when configured, in-memory otherwise."""

from collections.abc import Iterator
from contextlib import contextmanager

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

from repurpose_agent.config import Settings


@contextmanager
def open_checkpointer(settings: Settings) -> Iterator[BaseCheckpointSaver]:
    if not settings.database_url:
        yield InMemorySaver()
        return

    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    with ConnectionPool(
        settings.database_url,
        max_size=10,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    ) as pool:
        saver = PostgresSaver(pool)
        saver.setup()  # creates checkpoint tables on first run; no-op afterwards
        yield saver
