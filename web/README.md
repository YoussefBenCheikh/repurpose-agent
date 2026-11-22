# repurpose-agent web UI

Next.js review UI for the repurpose-agent API: paste a URL, watch the agents work live (SSE), then approve or request changes per platform.

```bash
cp .env.example .env.local   # NEXT_PUBLIC_API_URL, default http://localhost:8000
npm install
npm run dev                  # http://localhost:3000
```

Start the API first from the repo root: `REPURPOSE_DEMO=true uv run repurpose serve` (no API key needed) or `uv run repurpose serve`.
