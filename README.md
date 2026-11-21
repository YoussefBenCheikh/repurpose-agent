# repurpose-agent

A **LangGraph multi-agent pipeline** that turns any article into platform-native posts for Pinterest, X and LinkedIn. It writes them, critiques them, rewrites them, and waits for your approval.

```
START → ingest → analyze ─┬─► write (pinterest) ─┐
                          ├─► write (x)          ├─► critique ──► human_review ──► END
                          └─► write (linkedin)  ─┘      │   ▲           │
                                ▲                       │   │           │
                                └── score < 8 & budget ─┘   └─ revise ──┘
```

## What it shows

| Concept | Where |
|---|---|
| **LangGraph** state graph, reducers, parallel fan-out (`Send`), conditional loops | [`graph.py`](src/repurpose_agent/graph.py) |
| **Human-in-the-loop** with `interrupt()` and `Command(resume=...)`, checkpointed | `human_review` node, [`cli.py`](src/repurpose_agent/cli.py) |
| **Pydantic v2** contracts for every LLM output, with validators | [`schemas.py`](src/repurpose_agent/schemas.py) |
| **Self-repair**: validation errors are fed back to the model for a retry | [`llm.py`](src/repurpose_agent/llm.py) |
| **LangChain + Claude** native structured outputs (`json_schema`) | [`llm.py`](src/repurpose_agent/llm.py) |
| **Testable agents**: the full graph runs in CI against a fake LLM | [`tests/`](tests) |

## Quick start

```bash
uv sync
cp .env.example .env        # add your ANTHROPIC_API_KEY

uv run repurpose https://example.com/some-article
uv run repurpose -f notes.txt -p x -p linkedin -o posts.json
```

The graph pauses after the critic pass. You can approve everything, or leave
feedback for individual platforms, and only those get rewritten.

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `REPURPOSE_MODEL` | `claude-opus-5-5` | Any Claude model id |
| `REPURPOSE_EFFORT` | `medium` | `low` … `max` reasoning effort |
| `REPURPOSE_PASS_SCORE` | `8` | Critic score (1-10) needed to skip a rewrite |
| `REPURPOSE_MAX_REVISIONS` | `2` | Automatic rewrites per platform |

## Development

```bash
uv run pytest
uv run ruff check . && uv run ruff format .
```

## Roadmap

- [x] Ingest → analyze → parallel writers → critic loop → human review
- [ ] Brand-voice RAG over past posts (pgvector)
- [ ] FastAPI with SSE streaming of graph events
- [ ] Postgres checkpointer so a run can be resumed later
- [ ] Next.js review UI
- [ ] Eval suite (LLM-as-judge + rule checks) in CI
- [ ] Tracing with LangSmith or Langfuse
