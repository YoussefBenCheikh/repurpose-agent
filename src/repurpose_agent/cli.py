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
