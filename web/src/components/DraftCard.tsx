import { PLATFORM_LABEL, type Critique, type Draft, type Platform } from "@/lib/api";
import { DraftPreview } from "./DraftPreview";

function ScoreBadge({ score }: { score: number }) {
  const color =
    score >= 8
      ? "bg-emerald-100 text-emerald-700"
      : score >= 6
        ? "bg-amber-100 text-amber-700"
        : "bg-rose-100 text-rose-700";
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-semibold tabular-nums ${color}`}>
      {score}/10
    </span>
  );
}

type Props = {
  platform: Platform;
  draft?: Draft;
  critique?: Critique;
  busy: boolean;
  reviewing: boolean;
  feedback: string;
  onFeedback: (value: string) => void;
};

export function DraftCard({ platform, draft, critique, busy, reviewing, feedback, onFeedback }: Props) {
  return (
    <article className="flex flex-col rounded-2xl border border-zinc-200 bg-white shadow-sm">
      <header className="flex items-center justify-between border-b border-zinc-100 px-4 py-3">
        <h3 className="font-semibold">{PLATFORM_LABEL[platform]}</h3>
        <div className="flex items-center gap-2">
          {draft && draft.revision > 0 && (
            <span className="text-xs text-zinc-500">rev {draft.revision}</span>
          )}
          {critique && <ScoreBadge score={critique.score} />}
        </div>
      </header>

      <div className="flex-1 p-4">
        {draft ? (
          <DraftPreview draft={draft} />
        ) : (
          <div className="space-y-2">
            {[80, 95, 60].map((w) => (
              <div
                key={w}
                className={`h-3 rounded bg-zinc-100 ${busy ? "animate-pulse" : ""}`}
                style={{ width: `${w}%` }}
              />
            ))}
          </div>
        )}
      </div>

      {critique && critique.issues.length > 0 && (
        <div className="mx-4 mb-3 rounded-lg bg-amber-50 p-3 text-xs text-amber-800">
          <p className="mb-1 font-semibold">Critic notes</p>
          <ul className="list-disc space-y-0.5 pl-4">
            {critique.issues.map((i) => (
              <li key={i}>{i}</li>
            ))}
          </ul>
        </div>
      )}

      {reviewing && draft && (
        <div className="border-t border-zinc-100 p-4">
          <textarea
            value={feedback}
            onChange={(e) => onFeedback(e.target.value)}
            placeholder="Request changes (leave blank to keep)"
            rows={2}
            className="w-full resize-none rounded-lg border border-zinc-200 p-2 text-sm outline-none focus:border-zinc-400"
          />
        </div>
      )}
    </article>
  );
}
