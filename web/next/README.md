# Port 25 Next.js console

The FastAPI-mounted `../index.html` is intentionally retained as the no-build
fallback. This directory is the main Next.js/CopilotKit console.

```bash
# terminal 1 — from port25/backend
uvicorn app.main:app --reload --port 8000

# terminal 2 — from port25/web/next
cp .env.example .env.local
npm install
npm run dev
```

Open `http://localhost:3000` for the Next.js console. It polls the FastAPI API
at `http://localhost:8000`; change `NEXT_PUBLIC_PORT25_API` only when the API
lives elsewhere.

Set `OPENAI_API_KEY` in `.env.local` to enable the CopilotKit agent trace. The
agent can call `render_negotiation_progression`, a typed generative-UI tool that
renders the message lifecycle as a real React progression card instead of text.
