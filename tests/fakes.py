import threading
from collections import defaultdict

from pydantic import BaseModel

from repurpose_agent.prompts import PLATFORM_GUIDES
from repurpose_agent.schemas import Critique, KeyInsights, LinkedInPost, PinterestPin, XThread

INSIGHTS = KeyInsights(
    summary="Postgres can replace Redis for job queues in small apps.",
    audience="Indie SaaS developers",
    key_points=["SKIP LOCKED avoids double work", "One less service to run", "Scales far"],
    hooks=["You don't need Redis", "Your database is already a queue"],
    tone="practical",
)

DRAFTS: dict[type[BaseModel], BaseModel] = {
    PinterestPin: PinterestPin(
        title="Postgres job queue guide",
        description="Learn how to run background jobs without Redis.",
        hashtags=["#Postgres", "devtips", "SaaS"],
        image_prompt="Minimal elephant illustration with text overlay",
        board_suggestion="Developer Tips",
    ),
    XThread: XThread(tweets=["You don't need Redis.", "Postgres has SKIP LOCKED. Here's how."]),
    LinkedInPost: LinkedInPost(
        body="Most apps add Redis too early.\n\nHere's why.", hashtags=["postgres", "dev", "saas"]
    ),
}


class FakeLLM:
    """Returns canned outputs.

    `scores` maps platform -> queue of critic scores (default 9 once exhausted).
    Thread-safe because the critic node reviews platforms concurrently.
    """

    def __init__(self, scores: dict[str, list[int]] | None = None) -> None:
        self.scores = {k: list(v) for k, v in (scores or {}).items()}
        self.calls: dict[str, int] = defaultdict(int)
        self.prompts: list[str] = []
        self._lock = threading.Lock()
        self.configs: list = []

    def generate(self, schema, system, user, config=None):
        if config is not None:
            self.configs.append(config)
        with self._lock:
            return self._generate(schema, user)

    def _generate(self, schema, user):
        self.calls[schema.__name__] += 1
        self.prompts.append(user)
        if schema is KeyInsights:
            return INSIGHTS
        if schema is Critique:
            platform = next(p for p, guide in PLATFORM_GUIDES.items() if guide in user)
            queue = self.scores.get(platform, [])
            score = queue.pop(0) if queue else 9
            issues = [] if score >= 8 else ["Hook is weak"]
            return Critique(score=score, strengths=["clear"], issues=issues)
        return DRAFTS[schema]
