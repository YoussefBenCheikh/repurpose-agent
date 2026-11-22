"""Token usage and cost per run, with no external service needed.

A `UsageMetadataCallbackHandler` rides along in the LangGraph config, so it sees
every Claude call in the run (including the parallel critic calls).
"""

from langchain_core.callbacks import UsageMetadataCallbackHandler
from pydantic import BaseModel

# USD per million tokens (input, output). Cache reads/writes are ignored, so treat
# the cost as an estimate. Update when prices change.
PRICES: dict[str, tuple[float, float]] = {
    "claude-fable-5-2": (8.00, 40.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}


class Usage(BaseModel):
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = 0.0  # None if a model has no known price

    def __add__(self, other: "Usage") -> "Usage":
        cost = (
            None
            if self.cost_usd is None or other.cost_usd is None
            else round(self.cost_usd + other.cost_usd, 6)
        )
        return Usage(
            calls=self.calls + other.calls,
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cost_usd=cost,
        )


def _price(model: str) -> tuple[float, float] | None:
    # response model names may carry a suffix; match on the longest known prefix
    for name in sorted(PRICES, key=len, reverse=True):
        if model.startswith(name):
            return PRICES[name]
    return None


class UsageTracker(UsageMetadataCallbackHandler):
    """Also counts calls; `summary()` turns the raw per-model metadata into a Usage."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def on_llm_end(self, response, **kwargs) -> None:
        super().on_llm_end(response, **kwargs)
        with self._lock:
            self.calls += 1

    def summary(self) -> Usage:
        total = Usage(calls=self.calls)
        for model, meta in self.usage_metadata.items():
            inp, out = meta.get("input_tokens", 0), meta.get("output_tokens", 0)
            price = _price(model)
            cost = None if price is None else (inp * price[0] + out * price[1]) / 1_000_000
            total = total + Usage(input_tokens=inp, output_tokens=out, cost_usd=cost)
        return total


def run_config(thread_id: str, tracker: UsageTracker | None = None, **metadata) -> dict:
    """LangGraph config for one run. Name, tags and metadata show up in LangSmith."""
    return {
        "configurable": {"thread_id": thread_id},
        "callbacks": [tracker] if tracker else [],
        "run_name": "repurpose",
        "tags": ["repurpose-agent"],
        "metadata": {"thread_id": thread_id, **metadata},
    }
