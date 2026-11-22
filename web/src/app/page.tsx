"use client";

import { useEffect, useRef, useState } from "react";
import { DraftCard } from "@/components/DraftCard";
import { Timeline, type TimelineEntry } from "@/components/Timeline";
import {
  health,
  PLATFORM_LABEL,
  PLATFORMS,
  resumeRun,
  startRun,
  type Critiques,
  type Drafts,
  type NodeUpdate,
  type Platform,
  type StreamEvent,
  type Usage,
} from "@/lib/api";

type Phase = "idle" | "running" | "review" | "done" | "error";
type Source = "url" | "text";

const names = (ps: Platform[]) => ps.map((p) => PLATFORM_LABEL[p]).join(", ");

const EMPTY_USAGE: Usage = { calls: 0, input_tokens: 0, output_tokens: 0, cost_usd: 0 };

function addUsage(a: Usage, b?: Usage): Usage {
  if (!b) return a;
  return {
    calls: a.calls + b.calls,
    input_tokens: a.input_tokens + b.input_tokens,
    output_tokens: a.output_tokens + b.output_tokens,
    cost_usd: a.cost_usd === null || b.cost_usd === null ? null : a.cost_usd + b.cost_usd,
  };
}

function formatUsage(u: Usage): string {
  const tokens = u.input_tokens + u.output_tokens;
  const k = tokens >= 1000 ? `${(tokens / 1000).toFixed(1)}k` : String(tokens);
  const cost =
    u.cost_usd === null ? "" : ` · ~$${u.cost_usd.toFixed(u.cost_usd < 0.01 ? 4 : 2)}`;
  return `${u.calls} LLM calls · ${k} tokens${cost}`;
}

function describe({ node, update }: NodeUpdate): Omit<TimelineEntry, "id"> {
  switch (node) {
    case "ingest": {
      const s = update.source!;
      return {
        label: `Read “${s.title}”`,
        detail: `${s.chars.toLocaleString()} characters${s.truncated ? " (truncated)" : ""}`,
      };
    }
    case "analyze":
      return {
        label: `Extracted ${update.insights?.key_points.length ?? 0} key points`,
        detail: `Audience: ${update.insights?.audience}`,
      };
    case "write": {
      const [p, d] = Object.entries(update.drafts ?? {})[0] as [Platform, { revision: number }];
      return {
        label: d.revision ? `Rewrote ${PLATFORM_LABEL[p]}` : `Drafted ${PLATFORM_LABEL[p]}`,
        detail: d.revision ? `revision ${d.revision}` : undefined,
      };
    }
    case "critique": {
      const scores = Object.entries(update.critiques ?? {})
        .map(([p, c]) => `${PLATFORM_LABEL[p as Platform]} ${c!.score}/10`)
        .join(" · ");
      const retry = update.pending ?? [];
      return retry.length
        ? { label: `Critic: rewriting ${names(retry)}`, detail: scores, tone: "warn" }
        : { label: "Critic approved all drafts", detail: scores, tone: "ok" };
    }
    case "human_review":
      return update.approved
        ? { label: "You approved the drafts", tone: "ok" }
        : { label: `You requested changes to ${names(update.pending ?? [])}` };
  }
}

export default function Home() {
  const [source, setSource] = useState<Source>("url");
  const [url, setUrl] = useState("");
  const [text, setText] = useState("");
  const [platforms, setPlatforms] = useState<Platform[]>([...PLATFORMS]);

  const [phase, setPhase] = useState<Phase>("idle");
  const [threadId, setThreadId] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Drafts>({});
  const [critiques, setCritiques] = useState<Critiques>({});
  const [timeline, setTimeline] = useState<TimelineEntry[]>([]);
  const [feedback, setFeedback] = useState<Partial<Record<Platform, string>>>({});
  const [error, setError] = useState<string | null>(null);
  const [server, setServer] = useState<{ ok: boolean; demo: boolean } | null | undefined>();
  const [runPlatforms, setRunPlatforms] = useState<Platform[]>([]);
  const [usage, setUsage] = useState<Usage>(EMPTY_USAGE);

  const abort = useRef<AbortController | null>(null);
  const nextId = useRef(0);

  useEffect(() => {
    health().then(setServer);
  }, []);

  const busy = phase === "running";
  const canRun = !busy && platforms.length > 0 && (source === "url" ? url.trim() : text.trim());

  function onEvent(e: StreamEvent) {
    switch (e.event) {
      case "run":
        setThreadId(e.data.thread_id);
        break;
      case "node": {
        const { update } = e.data;
        if (update.drafts) setDrafts((d) => ({ ...d, ...update.drafts }));
        if (update.critiques) setCritiques((c) => ({ ...c, ...update.critiques }));
        setTimeline((t) => [...t, { id: nextId.current++, ...describe(e.data) }]);
        break;
      }
      case "review":
        setDrafts(e.data.drafts);
        setCritiques(e.data.critiques);
        break;
      case "done":
        setUsage((u) => addUsage(u, e.data.usage));
        setPhase(e.data.status === "completed" ? "done" : "review");
        break;
      case "error":
        setUsage((u) => addUsage(u, e.data.usage));
        setError(e.data.message);
        setPhase("error");
        break;
    }
  }

  async function run(stream: (signal: AbortSignal) => Promise<void>) {
    abort.current?.abort();
    abort.current = new AbortController();
    setPhase("running");
    setError(null);
    try {
      await stream(abort.current.signal);
    } catch (err) {
      if ((err as Error).name === "AbortError") return;
      setError((err as Error).message);
      setPhase("error");
    }
  }

  function onStart() {
    setDrafts({});
    setCritiques({});
    setTimeline([]);
    setFeedback({});
    setThreadId(null);
    setUsage(EMPTY_USAGE);
    setRunPlatforms(platforms);
    const input =
      source === "url" ? { url: url.trim(), platforms } : { text, title: "Pasted text", platforms };
    run((signal) => startRun(input, onEvent, signal));
  }

  function onReview(approved: boolean) {
    if (!threadId) return;
    const notes = Object.fromEntries(
      Object.entries(feedback).filter(([, v]) => v?.trim()),
    ) as Partial<Record<Platform, string>>;
    setFeedback({});
    run((signal) =>
      resumeRun(threadId, approved ? { approved: true } : { approved: false, feedback: notes }, onEvent, signal),
    );
  }

  function download() {
    const blob = new Blob([JSON.stringify(drafts, null, 2)], { type: "application/json" });
    const a = Object.assign(document.createElement("a"), {
      href: URL.createObjectURL(blob),
      download: "posts.json",
    });
    a.click();
    URL.revokeObjectURL(a.href);
  }

  const hasFeedback = Object.values(feedback).some((v) => v?.trim());
  const shown = runPlatforms.length ? runPlatforms : platforms;

  return (
    <div className="min-h-screen bg-zinc-50 text-zinc-900">
      <header className="border-b border-zinc-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
          <div>
            <h1 className="text-lg font-bold">repurpose-agent</h1>
            <p className="text-sm text-zinc-500">One article in, platform-ready posts out.</p>
          </div>
          <div className="flex items-center gap-2 text-xs">
            {server === null && (
              <span className="rounded-full bg-rose-100 px-2.5 py-1 font-medium text-rose-700">
                API offline
              </span>
            )}
            {server?.demo && (
              <span className="rounded-full bg-violet-100 px-2.5 py-1 font-medium text-violet-700">
                Demo mode
              </span>
            )}
          </div>
        </div>
      </header>

      <main className="mx-auto grid max-w-7xl gap-6 px-6 py-6 lg:grid-cols-[340px_1fr]">
        <aside className="space-y-6">
          <section className="space-y-4 rounded-2xl border border-zinc-200 bg-white p-4 shadow-sm">
            <div className="grid grid-cols-2 rounded-lg bg-zinc-100 p-1 text-sm">
              {(["url", "text"] as const).map((s) => (
                <button
                  key={s}
                  onClick={() => setSource(s)}
                  className={`rounded-md py-1.5 font-medium ${source === s ? "bg-white shadow-sm" : "text-zinc-500"}`}
                >
                  {s === "url" ? "URL" : "Paste text"}
                </button>
              ))}
            </div>

            {source === "url" ? (
              <input
                type="url"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://example.com/article"
                className="w-full rounded-lg border border-zinc-200 px-3 py-2 text-sm outline-none focus:border-zinc-400"
              />
            ) : (
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="Paste an article, notes or a transcript…"
                rows={8}
                className="w-full resize-y rounded-lg border border-zinc-200 px-3 py-2 text-sm outline-none focus:border-zinc-400"
              />
            )}

            <fieldset className="flex flex-wrap gap-2">
              {PLATFORMS.map((p) => {
                const on = platforms.includes(p);
                return (
                  <button
                    key={p}
                    type="button"
                    aria-pressed={on}
                    onClick={() =>
                      setPlatforms((ps) => (on ? ps.filter((x) => x !== p) : [...ps, p]))
                    }
                    className={`rounded-full border px-3 py-1 text-sm ${on ? "border-zinc-900 bg-zinc-900 text-white" : "border-zinc-200 text-zinc-600"}`}
                  >
                    {PLATFORM_LABEL[p]}
                  </button>
                );
              })}
            </fieldset>

            <button
              onClick={onStart}
              disabled={!canRun}
              className="w-full rounded-lg bg-zinc-900 py-2.5 text-sm font-semibold text-white disabled:opacity-40"
            >
              {busy ? "Agents working…" : "Generate posts"}
            </button>
          </section>

          {timeline.length > 0 && (
            <section className="rounded-2xl border border-zinc-200 bg-white p-4 shadow-sm">
              <h2 className="mb-3 text-sm font-semibold text-zinc-500">Agent activity</h2>
              <Timeline entries={timeline} busy={busy} />
              {usage.calls > 0 && (
                <p className="mt-4 border-t border-zinc-100 pt-3 text-xs tabular-nums text-zinc-500">
                  {formatUsage(usage)}
                </p>
              )}
            </section>
          )}

          {error && (
            <p className="rounded-lg bg-rose-50 p-3 text-sm text-rose-700">
              <span className="font-semibold">Error:</span> {error}
            </p>
          )}
        </aside>

        <section className="space-y-4">
          {phase === "idle" ? (
            <div className="flex h-full min-h-80 items-center justify-center rounded-2xl border-2 border-dashed border-zinc-200 text-sm text-zinc-400">
              Drafts appear here as the agents write them.
            </div>
          ) : (
            <>
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                {shown.map((p) => (
                  <DraftCard
                    key={p}
                    platform={p}
                    draft={drafts[p]}
                    critique={critiques[p]}
                    busy={busy}
                    reviewing={phase === "review"}
                    feedback={feedback[p] ?? ""}
                    onFeedback={(v) => setFeedback((f) => ({ ...f, [p]: v }))}
                  />
                ))}
              </div>

              {phase === "review" && (
                <div className="sticky bottom-4 flex items-center justify-between gap-4 rounded-2xl border border-zinc-200 bg-white/90 p-4 shadow-lg backdrop-blur">
                  <p className="text-sm text-zinc-600">
                    Review the drafts. Approve them, or write notes on any card and request changes.
                  </p>
                  <div className="flex shrink-0 gap-2">
                    <button
                      onClick={() => onReview(false)}
                      disabled={!hasFeedback}
                      className="rounded-lg border border-zinc-300 px-4 py-2 text-sm font-medium disabled:opacity-40"
                    >
                      Request changes
                    </button>
                    <button
                      onClick={() => onReview(true)}
                      className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white"
                    >
                      Approve all
                    </button>
                  </div>
                </div>
              )}

              {phase === "done" && (
                <div className="flex items-center justify-between rounded-2xl bg-emerald-50 p-4">
                  <p className="text-sm font-medium text-emerald-800">Approved and ready to publish.</p>
                  <button
                    onClick={download}
                    className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white"
                  >
                    Download JSON
                  </button>
                </div>
              )}
            </>
          )}
        </section>
      </main>
    </div>
  );
}
