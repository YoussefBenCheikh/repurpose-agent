"use client";

import { useEffect, useState } from "react";
import { addBrandPosts, brandCounts, PLATFORM_LABEL, PLATFORMS, type Platform } from "@/lib/api";

export function BrandVoice() {
  const [counts, setCounts] = useState<Partial<Record<Platform, number>> | null>(null);
  const [open, setOpen] = useState(false);
  const [platform, setPlatform] = useState<Platform>("linkedin");
  const [text, setText] = useState("");
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    brandCounts().then(setCounts);
  }, []);

  async function add() {
    try {
      const { added } = await addBrandPosts([{ platform, text: text.trim() }]);
      setStatus(added ? "Added. Future runs will match this style." : "Already stored.");
      setText("");
      setCounts(await brandCounts());
    } catch (e) {
      setStatus((e as Error).message);
    }
  }

  const total = counts ? Object.values(counts).reduce((a, b) => a + (b ?? 0), 0) : 0;

  return (
    <section className="rounded-2xl border border-zinc-200 bg-white p-4 shadow-sm">
      <button onClick={() => setOpen((o) => !o)} className="flex w-full items-center justify-between">
        <h2 className="text-sm font-semibold text-zinc-500">Brand voice</h2>
        <span className="text-xs text-zinc-400">
          {counts === null ? "unavailable" : `${total} past posts`} {open ? "▴" : "▾"}
        </span>
      </button>

      {open && (
        <div className="mt-3 space-y-3">
          <p className="text-xs text-zinc-500">
            Writers retrieve your most similar past posts per platform and match their style.
          </p>
          {counts && (
            <ul className="flex gap-3 text-xs text-zinc-600">
              {PLATFORMS.map((p) => (
                <li key={p}>
                  {PLATFORM_LABEL[p]}: <span className="font-semibold tabular-nums">{counts[p] ?? 0}</span>
                </li>
              ))}
            </ul>
          )}
          <select
            value={platform}
            onChange={(e) => setPlatform(e.target.value as Platform)}
            className="w-full rounded-lg border border-zinc-200 px-2 py-1.5 text-sm"
          >
            {PLATFORMS.map((p) => (
              <option key={p} value={p}>
                {PLATFORM_LABEL[p]}
              </option>
            ))}
          </select>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Paste a past post you're proud of…"
            rows={4}
            className="w-full resize-y rounded-lg border border-zinc-200 px-3 py-2 text-sm outline-none focus:border-zinc-400"
          />
          <button
            onClick={add}
            disabled={!text.trim()}
            className="w-full rounded-lg border border-zinc-300 py-2 text-sm font-medium disabled:opacity-40"
          >
            Add past post
          </button>
          {status && <p className="text-xs text-zinc-500">{status}</p>}
        </div>
      )}
    </section>
  );
}
