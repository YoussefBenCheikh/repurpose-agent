import type { Draft } from "@/lib/api";

function Tags({ tags }: { tags: string[] }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {tags.map((t) => (
        <span key={t} className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs text-zinc-600">
          #{t}
        </span>
      ))}
    </div>
  );
}

function CharCount({ value, max }: { value: string; max: number }) {
  const over = value.length > max * 0.9;
  return (
    <span className={`text-xs tabular-nums ${over ? "text-amber-600" : "text-zinc-400"}`}>
      {value.length}/{max}
    </span>
  );
}

export function DraftPreview({ draft }: { draft: Draft }) {
  switch (draft.platform) {
    case "pinterest": {
      const c = draft.content;
      return (
        <div className="space-y-3">
          <div className="flex aspect-[2/3] max-h-56 w-full items-end rounded-xl bg-gradient-to-br from-rose-100 via-orange-50 to-amber-100 p-3">
            <p className="text-xs italic text-zinc-500">🖼 {c.image_prompt}</p>
          </div>
          <div>
            <div className="flex items-start justify-between gap-2">
              <h4 className="font-semibold leading-snug">{c.title}</h4>
              <CharCount value={c.title} max={100} />
            </div>
            <p className="mt-1 text-sm text-zinc-600">{c.description}</p>
          </div>
          <Tags tags={c.hashtags} />
          <p className="text-xs text-zinc-500">
            Board: <span className="font-medium text-zinc-700">{c.board_suggestion}</span>
          </p>
        </div>
      );
    }
    case "x":
      return (
        <ol className="space-y-2">
          {draft.content.tweets.map((t, i) => (
            <li key={i} className="relative rounded-xl border border-zinc-200 p-3 text-sm">
              <p className="whitespace-pre-wrap">{t}</p>
              <div className="mt-1 flex justify-between text-xs text-zinc-400">
                <span>
                  {i + 1}/{draft.content.tweets.length}
                </span>
                <CharCount value={t} max={280} />
              </div>
            </li>
          ))}
        </ol>
      );
    case "linkedin":
      return (
        <div className="space-y-3">
          <p className="whitespace-pre-wrap text-sm leading-relaxed">{draft.content.body}</p>
          <Tags tags={draft.content.hashtags} />
          <div className="text-right">
            <CharCount value={draft.content.body} max={3000} />
          </div>
        </div>
      );
  }
}
