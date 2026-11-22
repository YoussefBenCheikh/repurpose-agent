"""Deterministic checks on approved drafts. Cheap, fast, and run on every CI build."""

import re
from collections.abc import Callable

from pydantic import BaseModel

from repurpose_agent.schemas import Draft, LinkedInPost, PinterestPin, Platform, XThread


class RuleResult(BaseModel):
    rule: str
    platform: Platform
    passed: bool
    detail: str = ""


_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_ENUMERATION = re.compile(r"^\s*\d+\s*[.)/]|\b\d+/\d+\b", re.MULTILINE)  # "1." "2)" "3/7"


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in _NUMBER.findall(_ENUMERATION.sub(" ", text))}


def draft_text(draft: Draft) -> str:
    """All reader-facing text in a draft (the image prompt is not shown to readers)."""
    c = draft.content
    match c:
        case PinterestPin():
            return f"{c.title}\n{c.description}"
        case XThread():
            return "\n".join(c.tweets)
        case LinkedInPost():
            return c.body
    raise TypeError(type(c))


# ------------------------------------------------------------------- rules
# Each rule returns (passed, detail). `source` is the article, `terms` the case's must_mention.

Rule = Callable[[Draft, str, list[str]], tuple[bool, str]]


def no_invented_numbers(draft: Draft, source: str, terms: list[str]) -> tuple[bool, str]:
    invented = _numbers(draft_text(draft)) - _numbers(source)
    return not invented, f"not in source: {sorted(invented)}" if invented else ""


def mentions_key_term(draft: Draft, source: str, terms: list[str]) -> tuple[bool, str]:
    text = draft_text(draft).lower()
    hits = [t for t in terms if t.lower() in text]
    return bool(hits), f"mentions {hits}" if hits else f"none of {terms}"


def x_hook_has_no_hashtag(draft: Draft, source: str, terms: list[str]) -> tuple[bool, str]:
    assert isinstance(draft.content, XThread)
    hook = draft.content.tweets[0]
    return "#" not in hook, "" if "#" not in hook else f"hook: {hook[:60]!r}"


def linkedin_hook_fits_preview(draft: Draft, source: str, terms: list[str]) -> tuple[bool, str]:
    assert isinstance(draft.content, LinkedInPost)
    first = draft.content.body.strip().splitlines()[0]
    return len(first) <= 150, f"first line is {len(first)} chars"


def linkedin_invites_comments(draft: Draft, source: str, terms: list[str]) -> tuple[bool, str]:
    assert isinstance(draft.content, LinkedInPost)
    tail = draft.content.body.strip()[-300:]
    return "?" in tail, "" if "?" in tail else "no question near the end"


def pinterest_title_has_keyword(draft: Draft, source: str, terms: list[str]) -> tuple[bool, str]:
    assert isinstance(draft.content, PinterestPin)
    title = draft.content.title.lower()
    hits = [t for t in terms if t.lower() in title]
    return bool(hits), f"title: {draft.content.title!r}"


COMMON_RULES: list[Rule] = [no_invented_numbers, mentions_key_term]
PLATFORM_RULES: dict[Platform, list[Rule]] = {
    Platform.X: [x_hook_has_no_hashtag],
    Platform.LINKEDIN: [linkedin_hook_fits_preview, linkedin_invites_comments],
    Platform.PINTEREST: [pinterest_title_has_keyword],
}


def check_draft(draft: Draft, source: str, terms: list[str]) -> list[RuleResult]:
    platform = Platform(draft.platform)
    results = []
    for rule in COMMON_RULES + PLATFORM_RULES.get(platform, []):
        passed, detail = rule(draft, source, terms)
        results.append(
            RuleResult(rule=rule.__name__, platform=platform, passed=passed, detail=detail)
        )
    return results
