export type TimelineEntry = { id: number; label: string; detail?: string; tone?: "warn" | "ok" };

export function Timeline({ entries, busy }: { entries: TimelineEntry[]; busy: boolean }) {
  if (!entries.length) return null;
  return (
    <ol className="space-y-3">
      {entries.map((e, i) => {
        const last = i === entries.length - 1;
        const dot =
          e.tone === "warn" ? "bg-amber-500" : e.tone === "ok" ? "bg-emerald-500" : "bg-zinc-400";
        return (
          <li key={e.id} className="flex gap-3">
            <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${dot}`} />
            <div className="min-w-0">
              <p className="text-sm font-medium">{e.label}</p>
              {e.detail && <p className="truncate text-xs text-zinc-500">{e.detail}</p>}
            </div>
            {last && busy && (
              <span className="ml-auto mt-1 h-3 w-3 animate-spin rounded-full border-2 border-zinc-300 border-t-zinc-700" />
            )}
          </li>
        );
      })}
    </ol>
  );
}
