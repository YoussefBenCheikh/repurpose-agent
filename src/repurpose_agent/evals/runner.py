"""Run the full graph on every eval case, auto-approve, and score the result."""

import json
import time
import uuid
from pathlib import Path

from langgraph.types import Command
from pydantic import BaseModel

from repurpose_agent.checkpoint import memory_saver
from repurpose_agent.config import Settings
from repurpose_agent.evals.judge import JudgeScore, judge_draft
from repurpose_agent.evals.rules import RuleResult, check_draft
from repurpose_agent.graph import build_graph
from repurpose_agent.llm import StructuredLLM
from repurpose_agent.schemas import Draft, Platform
from repurpose_agent.usage import Usage, UsageTracker, run_config


class EvalCase(BaseModel):
    id: str
    title: str
    text: str
    must_mention: list[str]
    platforms: list[Platform] = list(Platform)


class DraftResult(BaseModel):
    platform: Platform
    revisions: int
    critic_score: int | None
    rules: list[RuleResult]
    judge: JudgeScore | None = None

    @property
    def rules_passed(self) -> bool:
        return all(r.passed for r in self.rules)


class CaseResult(BaseModel):
    case_id: str
    seconds: float
    usage: Usage = Usage()  # pipeline calls only; judge calls are not included
    drafts: list[DraftResult] = []
    error: str | None = None


class EvalReport(BaseModel):
    model: str
    cases: list[CaseResult]

    @property
    def draft_results(self) -> list[DraftResult]:
        return [d for c in self.cases for d in c.drafts]

    @property
    def rule_pass_rate(self) -> float:
        rules = [r for d in self.draft_results for r in d.rules]
        return sum(r.passed for r in rules) / len(rules) if rules else 0.0

    @property
    def errors(self) -> int:
        return sum(c.error is not None for c in self.cases)

    def judge_means(self) -> dict[str, float]:
        scores = [d.judge for d in self.draft_results if d.judge]
        if not scores:
            return {}
        keys = ["faithfulness", "platform_fit", "engagement"]
        return {k: sum(getattr(s, k) for s in scores) / len(scores) for k in keys}

    def summary(self) -> dict:
        drafts = self.draft_results
        return {
            "model": self.model,
            "cases": len(self.cases),
            "errors": self.errors,
            "drafts": len(drafts),
            "rule_pass_rate": round(self.rule_pass_rate, 3),
            "mean_revisions": round(sum(d.revisions for d in drafts) / len(drafts), 2)
            if drafts
            else 0,
            "judge": {k: round(v, 2) for k, v in self.judge_means().items()},
            "usage": sum((c.usage for c in self.cases), Usage()).model_dump(),
        }

    def to_markdown(self) -> str:
        s = self.summary()
        lines = [
            "## Eval results",
            "",
            f"Model `{s['model']}`, {s['cases']} cases, {s['drafts']} drafts, "
            f"{s['errors']} errors. Rule pass rate **{s['rule_pass_rate']:.0%}**, "
            f"mean revisions {s['mean_revisions']}.",
        ]
        if s["judge"]:
            lines += ["", "| Judge criterion | Mean (1-5) |", "|---|---|"]
            lines += [f"| {k} | {v:.2f} |" for k, v in s["judge"].items()]
        failures = [
            (c.case_id, r) for c in self.cases for d in c.drafts for r in d.rules if not r.passed
        ]
        if failures:
            lines += ["", "| Case | Platform | Failed rule | Detail |", "|---|---|---|---|"]
            lines += [f"| {cid} | {r.platform} | {r.rule} | {r.detail} |" for cid, r in failures]
        for c in self.cases:
            if c.error:
                lines.append(f"\n**{c.case_id} errored:** {c.error}")
        return "\n".join(lines)


def load_cases(path: Path) -> list[EvalCase]:
    return [EvalCase.model_validate(c) for c in json.loads(path.read_text())]


def run_case(
    case: EvalCase, llm: StructuredLLM, judge: StructuredLLM | None, settings: Settings
) -> CaseResult:
    start = time.perf_counter()
    graph = build_graph(llm, settings, memory_saver())
    tracker = UsageTracker()
    config = run_config(str(uuid.uuid4()), tracker, source="eval", case_id=case.id)
    try:
        graph.invoke({"text": case.text, "title": case.title, "platforms": case.platforms}, config)
        graph.invoke(Command(resume={"approved": True}), config)
        state = graph.get_state(config).values

        results = []
        for p, draft in state["drafts"].items():
            draft: Draft
            critique = state.get("critiques", {}).get(p)
            results.append(
                DraftResult(
                    platform=Platform(p),
                    revisions=draft.revision,
                    critic_score=critique.score if critique else None,
                    rules=check_draft(draft, case.text, case.must_mention),
                    judge=judge_draft(judge, draft, case.text) if judge else None,
                )
            )
        return CaseResult(
            case_id=case.id,
            seconds=time.perf_counter() - start,
            drafts=results,
            usage=tracker.summary(),
        )
    except Exception as e:  # one bad case shouldn't hide the others' results
        return CaseResult(
            case_id=case.id,
            seconds=time.perf_counter() - start,
            error=repr(e),
            usage=tracker.summary(),
        )


def run_eval(
    cases: list[EvalCase],
    llm: StructuredLLM,
    settings: Settings,
    judge: StructuredLLM | None = None,
    model_name: str | None = None,
) -> EvalReport:
    return EvalReport(
        model=model_name or settings.model,
        cases=[run_case(c, llm, judge, settings) for c in cases],
    )
