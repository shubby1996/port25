# Port 25 Next.js console

This is the live Next.js console. The FastAPI-mounted `../index.html` remains
available at port 8000 as a no-build fallback.

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

Keep Gmail credentials, `OPENROUTER_API_KEY`, and `EXA_API_KEY` in the repository
root `.env`, loaded by the backend. The frontend only needs the public API URL;
it does not need any provider keys. Local environment files are ignored by Git.

Set `PORT25_TRANSPORT=smtp`, `PORT25_DEMO_PAIR=true`, and `PORT25_DEMO_AI=true`
in the root `.env` for the two-account AI-assisted demo. OpenRouter drafts wording
for both sides and classifies incoming supplier replies; Exa supplies market
context. Demo prices remain bounded by the explicit policy in the backend.

The console shows the actual single negotiation, emails, model labels, and
timestamps. Start a thread, adjust the buyer's maximum price, review and edit
parked replies, or stop both agents. After a run closes, **New negotiation**
starts a fresh email subject. An API failure is shown without substituting
sample conversations. An approval or limit change includes the displayed thread
ID so a stale browser cannot modify a newer thread.

Run `npm test` for console behavior checks and `npm run build` for the production
build. `npm start` serves the built console. Run a single backend worker because
the current negotiation is held in memory.
