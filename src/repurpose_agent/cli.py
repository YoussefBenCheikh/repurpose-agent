import json
import logging
import uuid
from pathlib import Path
from typing import Annotated

import typer
from langgraph.types import Command
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from repurpose_agent.config import get_settings
from repurpose_agent.demo import DemoLLM
from repurpose_agent.graph import build_graph
from repurpose_agent.llm import AnthropicLLM
from repurpose_agent.schemas import Platform

app = typer.Typer(add_completion=False, help="Turn any article into platform-ready posts.")
console = Console()


def _show(payload: dict) -> None:
    for platform, draft in payload["drafts"].items():
        crit = payload["critiques"].get(platform, {})
        body = json.dumps(draft["content"], indent=2, ensure_ascii=False)
        issues = "\n".join(f"  • {i}" for i in crit.get("issues", [])) or "  (none)"
        console.print(
            Panel(
                f"{body}\n\n[bold]Critic score:[/] {crit.get('score', '?')}/10"
                f"  (revision {draft['revision']})\n[bold]Issues:[/]\n{issues}",
                title=f"[cyan]{platform}[/]",
            )
        )


@app.command()
def run(
    url: Annotated[str | None, typer.Argument(help="Article URL to repurpose.")] = None,
    text_file: Annotated[
        Path | None, typer.Option("--text-file", "-f", help="Use a local text file instead.")
    ] = None,
    platform: Annotated[
        list[Platform] | None, typer.Option("--platform", "-p", help="Repeat to pick several.")
    ] = None,
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write approved JSON here.")
    ] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
    demo: Annotated[bool, typer.Option(help="Use the scripted demo LLM (no API key).")] = False,
) -> None:
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING)
    if not url and not text_file:
        raise typer.BadParameter("Pass a URL or --text-file.")

    settings = get_settings()
    llm = DemoLLM() if demo or settings.demo else AnthropicLLM(settings)
    graph = build_graph(llm, settings)
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    inputs: dict = {"url": url, "platforms": platform or list(Platform)}
    if text_file:
        inputs |= {"text": text_file.read_text(), "title": text_file.stem}

    stream_input: dict | Command = inputs
    while True:
        with console.status("[bold green]Agents working..."):
            for update in graph.stream(stream_input, config, stream_mode="updates"):
                for node in update:
                    if node != "__interrupt__":
                        console.log(f"✓ {node}")

        snapshot = graph.get_state(config)
        if not snapshot.interrupts:
            break

        _show(snapshot.interrupts[0].value)
        if Confirm.ask("Approve all drafts?", default=True):
            stream_input = Command(resume={"approved": True})
            continue

        feedback = {}
        for p in snapshot.values["drafts"]:
            note = Prompt.ask(f"Changes for [cyan]{p}[/] (blank to keep)", default="")
            if note.strip():
                feedback[str(p)] = note.strip()
        stream_input = Command(resume={"approved": not feedback, "feedback": feedback})

    final = graph.get_state(config).values
    result = {str(p): d.model_dump(mode="json") for p, d in final["drafts"].items()}
    console.print("[bold green]Approved.[/]")
    if out:
        out.write_text(json.dumps(result, indent=2, ensure_ascii=False))
        console.print(f"Saved to {out}")
    else:
        console.print_json(data=result)


@app.command("eval")
def eval_cmd(
    cases: Annotated[Path, typer.Option(help="Eval dataset.")] = Path("evals/cases.json"),
    demo: Annotated[bool, typer.Option(help="Use the scripted demo LLM (no API key).")] = False,
    judge: Annotated[bool, typer.Option(help="Also score drafts with an LLM judge.")] = True,
    judge_model: Annotated[str | None, typer.Option(help="Defaults to REPURPOSE_MODEL.")] = None,
    only: Annotated[list[str] | None, typer.Option(help="Run only these case ids.")] = None,
    out: Annotated[Path, typer.Option(help="Where to write the JSON report.")] = Path(
        "evals/results/latest.json"
    ),
    min_pass_rate: Annotated[float, typer.Option(help="Exit 1 below this rule pass rate.")] = 0.9,
) -> None:
    """Run the eval suite: rule checks + optional LLM-as-judge."""
    import os

    from rich.table import Table

    from repurpose_agent.evals.runner import load_cases, run_eval

    settings = get_settings()
    dataset = [c for c in load_cases(cases) if not only or c.id in only]
    if demo:
        llm = judge_llm = DemoLLM(delay=0)
        model_name = "demo"
    else:
        llm = AnthropicLLM(settings)
        judge_settings = settings.model_copy(update={"model": judge_model or settings.model})
        judge_llm = AnthropicLLM(judge_settings)
        model_name = settings.model

    with console.status(f"Running {len(dataset)} cases..."):
        report = run_eval(dataset, llm, settings, judge_llm if judge else None, model_name)

    table = Table(title="Eval results")
    for col in ["case", "platform", "rev", "critic", "rules", "judge"]:
        table.add_column(col)
    for c in report.cases:
        if c.error:
            table.add_row(c.case_id, "[red]error[/]", "", "", "", c.error[:60])
        for d in c.drafts:
            failed = [r.rule for r in d.rules if not r.passed]
            table.add_row(
                c.case_id,
                str(d.platform),
                str(d.revisions),
                str(d.critic_score),
                "[green]ok[/]" if not failed else f"[red]{', '.join(failed)}[/]",
                f"{d.judge.mean:.1f}" if d.judge else "-",
            )
    console.print(table)
    console.print_json(data=report.summary())

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report.model_dump_json(indent=2))
    if summary_file := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary_file, "a") as f:
            f.write(report.to_markdown() + "\n")

    if report.errors or report.rule_pass_rate < min_pass_rate:
        console.print(f"[red]Failed: pass rate {report.rule_pass_rate:.0%} < {min_pass_rate:.0%}")
        raise typer.Exit(1)


@app.command()
def serve(
    host: Annotated[str, typer.Option()] = "127.0.0.1",
    port: Annotated[int, typer.Option()] = 8000,
    reload: Annotated[bool, typer.Option()] = False,
) -> None:
    """Start the HTTP API (SSE streaming)."""
    import uvicorn

    uvicorn.run(
        "repurpose_agent.api:app_factory", factory=True, host=host, port=port, reload=reload
    )


if __name__ == "__main__":
    app()
