"""Typed contracts for every LLM output in the graph.

Length limits live in field descriptions (so the model sees them) and are enforced
by validators after parsing. Validation errors are fed back to the model for a
retry, see `llm.AnthropicLLM.generate`.
"""

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field, field_validator


class Platform(StrEnum):
    PINTEREST = "pinterest"
    X = "x"
    LINKEDIN = "linkedin"


# --------------------------------------------------------------------------- source


class SourceDocument(BaseModel):
    url: str | None = None
    title: str
    text: str
    truncated: bool = False


# --------------------------------------------------------------------------- analysis


class KeyInsights(BaseModel):
    """What the source is about, distilled for content writers."""

    summary: str = Field(description="2-3 sentence summary of the source.")
    audience: str = Field(description="Who this content is for, as specific as possible.")
    key_points: list[str] = Field(description="3-7 standalone takeaways, one sentence each.")
    hooks: list[str] = Field(description="3-5 attention-grabbing angles or opening lines.")
    tone: str = Field(description="Recommended tone, e.g. 'practical and upbeat'.")

    @field_validator("key_points")
    @classmethod
    def _key_points_len(cls, v: list[str]) -> list[str]:
        if not 3 <= len(v) <= 7:
            raise ValueError(f"key_points must have 3-7 items, got {len(v)}")
        return v


# --------------------------------------------------------------------------- drafts


def _normalize_hashtags(tags: list[str]) -> list[str]:
    seen: list[str] = []
    for t in tags:
        clean = t.strip().lstrip("#").replace(" ", "").lower()
        if clean and clean not in seen:
            seen.append(clean)
    return seen


class PinterestPin(BaseModel):
    title: str = Field(description="Pin title, max 100 characters, keyword-rich.")
    description: str = Field(description="Pin description, max 500 characters.")
    hashtags: list[str] = Field(description="3-5 hashtags without the # symbol.")
    image_prompt: str = Field(description="Prompt for a vertical 2:3 image generator.")
    board_suggestion: str = Field(description="Name of a Pinterest board this fits.")

    @field_validator("title")
    @classmethod
    def _title_len(cls, v: str) -> str:
        if len(v) > 100:
            raise ValueError(f"title is {len(v)} chars, max is 100")
        return v

    @field_validator("description")
    @classmethod
    def _desc_len(cls, v: str) -> str:
        if len(v) > 500:
            raise ValueError(f"description is {len(v)} chars, max is 500")
        return v

    @field_validator("hashtags")
    @classmethod
    def _hashtags(cls, v: list[str]) -> list[str]:
        v = _normalize_hashtags(v)
        if not 3 <= len(v) <= 5:
            raise ValueError(f"need 3-5 unique hashtags, got {len(v)}")
        return v


class XThread(BaseModel):
    tweets: list[str] = Field(description="2-8 posts, each max 280 characters. First is the hook.")

    @field_validator("tweets")
    @classmethod
    def _tweets(cls, v: list[str]) -> list[str]:
        if not 2 <= len(v) <= 8:
            raise ValueError(f"thread must have 2-8 posts, got {len(v)}")
        too_long = [i for i, t in enumerate(v, 1) if len(t) > 280]
        if too_long:
            raise ValueError(f"posts {too_long} exceed 280 characters")
        return v


class LinkedInPost(BaseModel):
    body: str = Field(description="Post body, max 3000 characters, short paragraphs.")
    hashtags: list[str] = Field(description="3-5 hashtags without the # symbol.")

    @field_validator("body")
    @classmethod
    def _body_len(cls, v: str) -> str:
        if len(v) > 3000:
            raise ValueError(f"body is {len(v)} chars, max is 3000")
        return v

    @field_validator("hashtags")
    @classmethod
    def _hashtags(cls, v: list[str]) -> list[str]:
        v = _normalize_hashtags(v)
        if not 3 <= len(v) <= 5:
            raise ValueError(f"need 3-5 unique hashtags, got {len(v)}")
        return v


DraftContent = PinterestPin | XThread | LinkedInPost

DRAFT_SCHEMAS: dict[Platform, type[BaseModel]] = {
    Platform.PINTEREST: PinterestPin,
    Platform.X: XThread,
    Platform.LINKEDIN: LinkedInPost,
}


class Draft(BaseModel):
    platform: Platform
    content: DraftContent
    revision: int = 0


# --------------------------------------------------------------------------- review


class Critique(BaseModel):
    score: Annotated[
        int, Field(description="Overall quality from 1 (unusable) to 10 (publish now).")
    ]
    strengths: list[str] = Field(description="What works, 1-3 items.")
    issues: list[str] = Field(description="Concrete problems to fix. Empty if none.")

    @field_validator("score")
    @classmethod
    def _score_range(cls, v: int) -> int:
        if not 1 <= v <= 10:
            raise ValueError("score must be between 1 and 10")
        return v


class ReviewDecision(BaseModel):
    """What a human sends back when the graph pauses for review."""

    approved: bool
    feedback: dict[Platform, str] = Field(
        default_factory=dict,
        description="Per-platform change requests. Only used when approved is false.",
    )
