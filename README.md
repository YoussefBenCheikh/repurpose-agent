# repurpose-agent

[![CI](https://github.com/YoussefBenCheikh/repurpose-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/YoussefBenCheikh/repurpose-agent/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12+-blue)
![LangGraph](https://img.shields.io/badge/LangGraph-1.x-1c3c3c)
![Next.js](https://img.shields.io/badge/Next.js-16-black)

A **LangGraph multi-agent pipeline** that turns any article into platform-native posts for Pinterest, X and LinkedIn. It writes them, critiques them, rewrites them, and waits for your approval.

```
START → ingest → analyze → brand_voice ─┬─► write (pinterest) ─┐
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
| **FastAPI + SSE**: watch each node finish live, resume after review | [`api.py`](src/repurpose_agent/api.py) |
| **Durable runs**: Postgres checkpointer, so a run survives restarts | [`checkpoint.py`](src/repurpose_agent/checkpoint.py) |
| **Live review UI** in Next.js: SSE stream parsed from `fetch`, per-platform feedback | [`web/`](web) |
| **Demo mode**: a scripted LLM, so anyone can try it with no API key | [`demo.py`](src/repurpose_agent/demo.py) |
| **RAG for brand voice**: past posts embedded locally, retrieved per platform (pgvector) | [`voice.py`](src/repurpose_agent/voice.py) |
| **Observability**: per-run token and cost tracking, LangSmith tracing with run metadata | [`usage.py`](src/repurpose_agent/usage.py) |
| **Eval suite**: rule checks (e.g. no invented numbers) + LLM-as-judge, gated in CI | [`evals/`](src/repurpose_agent/evals) |
| **Testable agents**: the full graph and API run in CI against a fake LLM | [`tests/`](tests) |

## Try it in 1 minute (no API key)

```bash
REPURPOSE_DEMO=true docker compose up --build
# open http://localhost:3000
```

Or without Docker: `REPURPOSE_DEMO=true uv run repurpose serve` in one terminal and
`cd web && npm install && npm run dev` in another.

Demo mode swaps Claude for a scripted LLM. The graph, critic loop, human review and
persistence are all real.

## Quick start

```bash
uv sync
cp .env.example .env        # add your ANTHROPIC_API_KEY

uv run repurpose run https://example.com/some-article
uv run repurpose run -f notes.txt -p x -p linkedin -o posts.json
```

The graph pauses after the critic pass. You can approve everything, or leave
feedback for individual platforms, and only those get rewritten.

## HTTP API

```bash
uv run repurpose serve            # in-memory runs
docker compose up --build         # API + web UI + Postgres, runs persist across restarts
```

| Endpoint | What it does |
|---|---|
| `POST /runs` | Start a run from `{"url": ...}` or `{"text": ..., "title": ...}`. Streams SSE. |
| `POST /runs/{thread_id}/resume` | Send `{"approved": true}` or `{"approved": false, "feedback": {"x": "..."}}`. Streams SSE. |
| `GET /runs/{thread_id}` | Status (`running` / `awaiting_review` / `completed`), drafts and critiques. |

SSE events: `run` (thread id) → `node` (one per finished node) → `review` (paused for you) → `done`, or `error`.

```bash
curl -N -X POST localhost:8000/runs -H 'content-type: application/json' \
  -d '{"url": "https://example.com/some-article", "platforms": ["x", "linkedin"]}'
```

Interactive docs at http://localhost:8000/docs.

## Evals

```bash
uv run repurpose eval --demo           # free: scripted LLM, rule checks + fixed judge
uv run repurpose eval                  # real model + LLM judge (uses your API key)
uv run repurpose eval --no-judge --only pricing-page
```

The dataset is [`evals/cases.json`](evals/cases.json): a few original articles, each with the
terms the posts must mention. Each approved draft is scored two ways:

| Rule check (deterministic) | What it catches |
|---|---|
| `no_invented_numbers` | stats or figures that aren't in the source |
| `mentions_key_term` | drafts that drift off-topic |
| `x_hook_has_no_hashtag` | hashtag spam in the hook post |
| `linkedin_hook_fits_preview` | a hook that gets cut off by "see more" |
| `linkedin_invites_comments` | posts that don't end with a question |
| `pinterest_title_has_keyword` | titles that won't match a search |

The **LLM judge** scores faithfulness, platform fit and engagement from 1 to 5 against a rubric.

CI runs the demo eval on every push and fails below a 100% rule pass rate. The
[Evals (Claude)](.github/workflows/evals.yml) workflow runs the real thing on demand: add an
`ANTHROPIC_API_KEY` repository secret, then trigger it from the Actions tab. A full run is
about 50 model calls.

## Brand voice (RAG)

The `brand_voice` node embeds the article's key points and retrieves your most similar
past posts for each platform. Writers get them as style examples ("match the tone and
rhythm, never copy the facts"), and the critic flags drafts that don't sound like you.

- **Embeddings** run locally with [fastembed](https://github.com/qdrant/fastembed)
  (`BAAI/bge-small-en-v1.5`, downloaded once). No API key, no per-call cost.
- **Storage** is in memory, or Postgres + **pgvector** (HNSW index, cosine distance)
  when `REPURPOSE_DATABASE_URL` is set.
- **Your posts**: edit [`brand/posts.json`](brand/posts.json) (loaded at startup), use
  the Brand voice panel in the UI, or the CLI:

```bash
uv run repurpose brand add my-posts.jsonl       # {"platform": "x", "text": "..."} per line
uv run repurpose brand search "postgres queues" -p linkedin
```

The shipped `brand/posts.json` is a sample voice; replace it with your own posts.

## Observability

Every run gets a usage tracker (a LangChain callback carried in the LangGraph config),
so token counts and estimated cost show up with no extra service:

- the CLI prints them when a run finishes
- the API includes them in each `done` event, and the web UI shows a running total
- `repurpose eval` reports them per case and in the summary

For full traces, set these in `.env` and every node and LLM call appears in
[LangSmith](https://smith.langchain.com), tagged with the thread id and phase:

```bash
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_...
LANGSMITH_PROJECT=repurpose-agent
```

This works because each node passes its `RunnableConfig` on to the model call,
including the critic calls that run in worker threads.

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `REPURPOSE_MODEL` | `claude-opus-5-5` | Any Claude model id |
| `REPURPOSE_EFFORT` | `medium` | `low` … `max` reasoning effort |
| `REPURPOSE_PASS_SCORE` | `8` | Critic score (1-10) needed to skip a rewrite |
| `REPURPOSE_MAX_REVISIONS` | `2` | Automatic rewrites per platform |
| `REPURPOSE_DATABASE_URL` | unset | Postgres URL for durable runs (in-memory if unset) |
| `REPURPOSE_DEMO` | `false` | Use the scripted demo LLM instead of Claude |
| `REPURPOSE_VOICE_EXAMPLES` | `3` | Past posts retrieved per platform (0 disables) |
| `REPURPOSE_BRAND_FILE` | `brand/posts.json` | Posts loaded into the voice store at startup |
| `REPURPOSE_EMBEDDINGS` | `fastembed` | `fastembed` (local model) or `hash` (keyword, for tests) |

## Development

```bash
uv run pytest                    # Postgres test runs if TEST_DATABASE_URL is set
uv run ruff check . && uv run ruff format .
cd web && npm run lint && npm run build   # build includes type-checking
```

## Roadmap

- [x] Ingest → analyze → parallel writers → critic loop → human review
- [x] Brand-voice RAG over past posts (pgvector)
- [x] FastAPI with SSE streaming of graph events
- [x] Postgres checkpointer so a run can be resumed later
- [x] Next.js review UI
- [x] Eval suite (LLM-as-judge + rule checks) in CI
- [x] Tracing (LangSmith) and per-run token/cost tracking
- [ ] Voice-match criterion in the eval suite
- [ ] Publish approved posts via platform APIs (scheduling)
