"""Usage tracking end to end: a LangChain chat model inside the graph, metered via callbacks."""

import uuid

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.types import Command

from repurpose_agent.config import Settings
from repurpose_agent.graph import build_graph
from repurpose_agent.usage import PRICES, Usage, UsageTracker, run_config

from .fakes import FakeLLM


def metered_message(_):
    return AIMessage(
        content="ok",
        usage_metadata={"input_tokens": 1000, "output_tokens": 200, "total_tokens": 1200},
        response_metadata={"model_name": "claude-opus-5-5"},
    )


class ChatBackedLLM(FakeLLM):
    """Canned structured outputs, but each call also goes through a LangChain chat
    model with the node's config, like AnthropicLLM does."""

    def __init__(self) -> None:
        super().__init__()
        self.chat = GenericFakeChatModel(messages=iter(metered_message(i) for i in range(1000)))

    def generate(self, schema, system, user, config=None):
        self.chat.invoke(user, config=config)
        return super().generate(schema, system, user, config)


def test_tracker_meters_every_call_including_parallel_critics():
    llm, tracker = ChatBackedLLM(), UsageTracker()
    graph = build_graph(llm, Settings())
    config = run_config(str(uuid.uuid4()), tracker)

    graph.invoke({"text": "Postgres is a great queue. " * 20}, config)
    graph.invoke(Command(resume={"approved": True}), config)

    # analyze + 3 writers + 3 critics, all passing first time
    u = tracker.summary()
    assert u.calls == 7
    assert (u.input_tokens, u.output_tokens) == (7000, 1400)
    in_price, out_price = PRICES["claude-opus-5-5"]
    assert u.cost_usd == (7000 * in_price + 1400 * out_price) / 1_000_000
    assert all("thread_id" in c["metadata"] for c in llm.configs)


def test_unknown_model_cost_is_none():
    assert (Usage(cost_usd=1.0) + Usage(cost_usd=None)).cost_usd is None
