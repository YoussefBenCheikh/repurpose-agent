"""Scripted LLM for demos: no API key, no cost, deterministic.

Enable with REPURPOSE_DEMO=true. Outputs are built from the source text so the
UI looks realistic, and the first Pinterest critique fails on purpose so the
critic -> rewrite loop is visible.
"""

import re
import time

from pydantic import BaseModel

from repurpose_agent.evals.judge import JudgeScore
from repurpose_agent.schemas import (
    Critique,
    KeyInsights,
    LinkedInPost,
    PinterestPin,
    XThread,
)


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))
    return [p for p in parts if 20 <= len(p) <= 240] or ["This source has a useful idea."]


def _clip(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


class DemoLLM:
    def __init__(self, delay: float = 0.6) -> None:
        self.delay = delay

    def generate(self, schema: type[BaseModel], system: str, user: str):
        time.sleep(self.delay)
        if schema is KeyInsights:
            return self._insights(user)
        if schema is Critique:
            return self._critique(user)
        if schema is JudgeScore:
            return JudgeScore(
                rationale="Demo judge: fixed scores.", faithfulness=4, platform_fit=4, engagement=4
            )
        insights = KeyInsights.model_validate_json(_between(user, "<insights>", "</insights>"))
        revised = "<feedback>" in user
        if schema is PinterestPin:
            return self._pin(insights, revised)
        if schema is XThread:
            return self._thread(insights)
        if schema is LinkedInPost:
            return self._linkedin(insights)
        raise ValueError(f"DemoLLM can't produce {schema.__name__}")

    # ---------------------------------------------------------------- builders

    def _insights(self, user: str) -> KeyInsights:
        title = re.search(r"<source title=(['\"])(.*?)\1>", user)  # repr() picks either quote
        sents = _sentences(user)
        points = (sents * 3)[: max(3, min(5, len(sents)))]
        topic = title.group(2) if title else "this topic"
        return KeyInsights(
            summary=" ".join(sents[:2]),
            audience="Builders and founders who want practical takeaways",
            key_points=points,
            hooks=[f"What nobody tells you about {topic}", f"{topic}: the short version"],
            tone="practical and upbeat",
        )

    def _pin(self, i: KeyInsights, revised: bool) -> PinterestPin:
        title = i.hooks[1] if revised else i.hooks[0]  # revision switches to the keyword hook
        return PinterestPin(
            title=_clip(title, 100),
            description=_clip(f"{i.summary} Save this for later.", 500),
            hashtags=["productivity", "startup", "tips", "learning"],
            image_prompt=f"Clean vertical 2:3 illustration, text overlay: '{_clip(title, 40)}'",
            board_suggestion="Founder Tips",
        )

    def _thread(self, i: KeyInsights) -> XThread:
        tweets = [_clip(i.hooks[0] + " 🧵", 280)]
        tweets += [_clip(f"{n}. {p}", 280) for n, p in enumerate(i.key_points[:4], 1)]
        tweets.append("That's the gist. Follow for more breakdowns like this.")
        return XThread(tweets=tweets)

    def _linkedin(self, i: KeyInsights) -> LinkedInPost:
        bullets = "\n".join(f"→ {p}" for p in i.key_points[:4])
        body = f"{i.hooks[0]}.\n\n{i.summary}\n\n{bullets}\n\nWhat would you add?"
        return LinkedInPost(body=_clip(body, 3000), hashtags=["leadership", "startups", "growth"])

    def _critique(self, user: str) -> Critique:
        draft = _between(user, "<draft>", "</draft>")
        # first Pinterest draft uses the generic hook -> fail it to show the rewrite loop
        if "Platform: Pinterest" in user and "What nobody tells you" in draft:
            return Critique(
                score=6,
                strengths=["Clear value proposition"],
                issues=["Title is vague; lead with the search keyword people would type."],
            )
        return Critique(score=9, strengths=["Strong hook", "Native to the platform"], issues=[])


def _between(s: str, start: str, end: str) -> str:
    return s.split(start, 1)[1].split(end, 1)[0]
