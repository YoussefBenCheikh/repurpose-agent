"""LLM-as-judge: scores what rules can't (faithfulness, platform fit, engagement)."""

import json

from pydantic import BaseModel, Field, field_validator

from repurpose_agent.llm import StructuredLLM
from repurpose_agent.prompts import PLATFORM_GUIDES
from repurpose_agent.schemas import Draft, Platform

JUDGE_SYSTEM = """\
You are an impartial evaluator of social media content generated from a source article. \
Grade strictly against the rubric. Judge only what is written; do not reward length. \
Write the rationale before deciding the scores."""

RUBRIC = """\
Score each criterion from 1 to 5:

faithfulness: 5 = every claim is supported by the source; 3 = minor stretch or vague \
claim; 1 = contains facts, numbers or quotes not in the source.
platform_fit: 5 = reads like a strong native post for this platform per the guide; \
3 = acceptable but generic; 1 = wrong format or tone for the platform.
engagement: 5 = a target reader would stop scrolling and act (save, reply, click); \
3 = fine but forgettable; 1 = no reason to engage."""


class JudgeScore(BaseModel):
    rationale: str = Field(description="2-4 sentences justifying the scores.")
    faithfulness: int = Field(description="1-5")
    platform_fit: int = Field(description="1-5")
    engagement: int = Field(description="1-5")

    @field_validator("faithfulness", "platform_fit", "engagement")
    @classmethod
    def _range(cls, v: int) -> int:
        if not 1 <= v <= 5:
            raise ValueError("scores must be 1-5")
        return v

    @property
    def mean(self) -> float:
        return (self.faithfulness + self.platform_fit + self.engagement) / 3


def judge_draft(llm: StructuredLLM, draft: Draft, source: str) -> JudgeScore:
    platform = Platform(draft.platform)
    content = json.dumps(draft.content.model_dump(mode="json"), indent=2, ensure_ascii=False)
    user = "\n\n".join(
        [
            f"<source>\n{source}\n</source>",
            f"<platform_guide>\n{PLATFORM_GUIDES[platform]}\n</platform_guide>",
            f"<draft>\n{content}\n</draft>",
            RUBRIC,
        ]
    )
    return llm.generate(JudgeScore, JUDGE_SYSTEM, user)
