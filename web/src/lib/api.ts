// Types mirror the Pydantic models in src/repurpose_agent/schemas.py

export const PLATFORMS = ["pinterest", "x", "linkedin"] as const;
export type Platform = (typeof PLATFORMS)[number];

export const PLATFORM_LABEL: Record<Platform, string> = {
  pinterest: "Pinterest",
  x: "X thread",
  linkedin: "LinkedIn",
};

export type PinterestPin = {
  title: string;
  description: string;
  hashtags: string[];
  image_prompt: string;
  board_suggestion: string;
};
export type XThread = { tweets: string[] };
export type LinkedInPost = { body: string; hashtags: string[] };

export type Draft =
  | { platform: "pinterest"; content: PinterestPin; revision: number }
  | { platform: "x"; content: XThread; revision: number }
  | { platform: "linkedin"; content: LinkedInPost; revision: number };

export type Critique = { score: number; strengths: string[]; issues: string[] };

export type Drafts = Partial<Record<Platform, Draft>>;
export type Critiques = Partial<Record<Platform, Critique>>;

export type RunStatus = "running" | "awaiting_review" | "completed";

export type NodeUpdate = {
  node: "ingest" | "analyze" | "write" | "critique" | "human_review";
  update: {
    source?: { title: string; chars: number; truncated: boolean };
    insights?: { key_points: string[]; audience: string };
    drafts?: Drafts;
    critiques?: Critiques;
    pending?: Platform[];
    approved?: boolean;
  };
};

export type StreamEvent =
  | { event: "run"; data: { thread_id: string } }
  | { event: "node"; data: NodeUpdate }
  | { event: "review"; data: { drafts: Drafts; critiques: Critiques } }
  | { event: "done"; data: { thread_id: string; status: RunStatus } }
  | { event: "error"; data: { message: string } };

export type RunInput = {
  url?: string;
  text?: string;
  title?: string;
  platforms: Platform[];
};

export type ReviewDecision = {
  approved: boolean;
  feedback?: Partial<Record<Platform, string>>;
};

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function health(): Promise<{ ok: boolean; demo: boolean } | null> {
  try {
    const res = await fetch(`${API_URL}/health`);
    return res.ok ? await res.json() : null;
  } catch {
    return null;
  }
}

/** POST JSON and parse the text/event-stream response. */
async function streamPost(
  path: string,
  body: unknown,
  onEvent: (e: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) {
    const detail = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${detail || res.statusText}`);
  }

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      let event = "message";
      let data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7);
        else if (line.startsWith("data: ")) data += line.slice(6);
      }
      if (data) onEvent({ event, data: JSON.parse(data) } as StreamEvent);
    }
  }
}

export const startRun = (input: RunInput, onEvent: (e: StreamEvent) => void, signal?: AbortSignal) =>
  streamPost("/runs", input, onEvent, signal);

export const resumeRun = (
  threadId: string,
  decision: ReviewDecision,
  onEvent: (e: StreamEvent) => void,
  signal?: AbortSignal,
) => streamPost(`/runs/${threadId}/resume`, decision, onEvent, signal);
