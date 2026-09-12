# Person B (brain) — implementation plan

Scope: `backend/app/brain/` only (`classifier.py`, `router.py`, `drafting.py`,
`context.py`, `llm.py`). No changes to `state.py`, `loop.py`, `main.py`,
`transport/`, or `web/` without flagging it first — those are other people's
files or the shared contract.

## What's already in the repo (read, not assumed)

Everything in `brain/` is already scaffolded and structurally works:
- `classifier.py` — calls `complete()`, hardcodes `CLASSIFIER_MODEL = "gpt-4o-mini"`,
  does **not** pass `via_openrouter`, so it defaults to `False` → requires
  `OPENAI_API_KEY`.
- `router.py` — `ROUTING_TABLE`: `ROUTINE` → `("gpt-4o-mini", False, ...)` (also
  OpenAI, no OpenRouter). `COMPLEX` and `ESCALATE` → `("anthropic/claude-sonnet-4.5",
  True, ...)` (already OpenRouter).
- `drafting.py` — reads model/via_openrouter from `pick_model()`, no hardcoded
  provider. Needs no change once the table is fixed.
- `context.py` — Exa "cheap version" (one call at thread start) is already
  implemented and already fails soft (`EXA_API_KEY` unset → returns `""`,
  never raises). This matches the brief; nothing to build here for the
  baseline.
- `llm.py` — `complete()` already branches on `via_openrouter` to pick
  `OPENROUTER_API_KEY`/`OPENAI_API_KEY` and the right base URL, and falls
  back to a stub string when no key is set. This function is fine as-is.

**The actual gap**: you have `OPENROUTER_API_KEY` but no `OPENAI_API_KEY`, and
the "routine" tier + the classifier are the only two things still wired to
OpenAI. Everything else already goes through OpenRouter.

## Decision this plan is making (flagging it, not hiding it)

Route the "routine" tier through OpenRouter using `openai/gpt-4o-mini` (same
model, proxied by OpenRouter) instead of hitting OpenAI directly. This keeps
the pitch line true ("fast cheap model for routine turns") and means **only
`OPENROUTER_API_KEY` is required** — `OPENAI_API_KEY` becomes fully optional.
If you'd rather use a non-OpenAI cheap model (e.g. a Gemini Flash or Llama
variant on OpenRouter) instead of `openai/gpt-4o-mini`, say so before step 1
— it's a one-line change either way.

The classifier currently has its own model constant, separate from the
routing table, even though "classify cheaply" and "routine tier" are the same
job. Plan keeps them as two constants (matches the existing file boundary /
contract) but points both at OpenRouter so there's one credential to manage.

## Steps

### 1. Fix credentials wiring (no new deps, ~5 min)
- `router.py`: change `ROUTINE` entry to
  `("openai/gpt-4o-mini", True, "Routine restatement of a known position — fast model is enough")`.
- `classifier.py`: change `CLASSIFIER_MODEL = "gpt-4o-mini"` →
  `CLASSIFIER_MODEL = "openai/gpt-4o-mini"`, and pass `via_openrouter=True` in
  the `complete(...)` call.
- Create `backend/.env` from `.env.example` (gitignored already — confirmed
  `.gitignore` present) with `PORT25_TRANSPORT=mock` and `OPENROUTER_API_KEY`
  filled in; leave `OPENAI_API_KEY` blank on purpose.

### 2. Verify the classifier in isolation (target: green before moving on)
- `cd backend && python test_classifier.py`
- This is real judgment, not just wiring: with `OPENROUTER_API_KEY` set it
  makes live calls against the 6 fixtures in
  `backend/fixtures/inbound_emails.json`. Iterate on the `SYSTEM` prompt in
  `classifier.py` (tier definitions, or the "breaches mandate" phrasing) until
  6/6 pass.
- Sanity-check the mandate override independent of the model: feed it a body
  where `unit_price_eur` is clearly above `floor_price_eur` (fixtures 5 and 6
  already do this) and confirm tier comes back `escalate` even if you
  deliberately make the prompt say something else — `is_within_mandate()` in
  `state.py` must be the thing that wins, not the model.
- Note for later: with **no** key at all (`OPENROUTER_API_KEY` unset), `_stub()`
  in `llm.py` always returns `tier: "routine"` and no `extracted` prices, so
  every fixture will "pass" only if its expected tier is `routine` — that's
  expected stub behavior, not a bug, and it's why the real check needs the key.

### 3. Confirm routing table end-to-end (~5 min)
- `python -c "from app.brain.router import pick_model; from app.state import Tier; print(pick_model(Tier.ROUTINE)); print(pick_model(Tier.COMPLEX)); print(pick_model(Tier.ESCALATE))"`
  from `backend/` — confirm all three now show `via_openrouter=True`.

### 4. Verify drafting produces a plausible email (~10 min)
- Quick manual check, no test file needed (brief says don't build tooling we
  won't reuse): in a `python -i` shell or a throwaway script, call
  `draft_reply(new_negotiation(), fixtures[2]["body"], Tier.COMPLEX)` and read
  the output for: four sentences max, cites a specific number, cites market
  context if present, never accepts below floor.

### 5. Run the full loop against the mock transport (~5 min)
- `cd backend && python run_demo.py`
- This exercises `loop.start` → `loop.handle_inbound` end to end against
  `MockTransport`, with the real classifier/router/drafting/context wiring.
  If this prints a full thread ending in either `closed` or `awaiting
  approval`, the brain package is integration-ready.

### 6. Hand-off point (~01:40 in the brief's schedule)
- Interface Person A/C depend on (`classify`, `draft_reply`,
  `fetch_market_context`, exported from `app/brain/__init__.py`) is unchanged
  — only internals moved from OpenAI to OpenRouter. No coordination needed for
  that reason alone.
- Flag to the team: opening offer / classifier reasons will now visibly cite
  `openai/gpt-4o-mini` and `anthropic/claude-sonnet-4.5` as the model names
  shown in the console — confirm that's what should render, since Person C's
  thread view stamps each turn with `model_used`.

### 7. Stretch only — Exa "good version" (only start if ahead of schedule)
- Brief: fire a fresh Exa call when tier comes back `complex`, so evidence is
  fetched exactly when stakes rise, instead of only once at thread start.
- This needs a decision before touching it: `context.py` only exposes
  `fetch_market_context(query)`, called today from `loop.start()`. Firing it
  again on `COMPLEX` means either (a) `loop.handle_inbound` calls it after
  `classify()` returns a tier — a change to `loop.py`, which is the shared
  integration seam — or (b) `classify()` itself calls it internally when it
  decides `COMPLEX`, keeping the change inside `brain/`. Recommend (b): it
  stays inside your workstream and needs no sign-off from A/C. **Do this only
  after step 6 hand-off, and only if the fixed 15-minute version is already
  solid** — brief explicitly says don't build this first.

## Env vars needed for this workstream

```
OPENROUTER_API_KEY=<required — both tiers now depend on it>
OPENAI_API_KEY=            (leave blank, no longer required)
EXA_API_KEY=               (optional — blank means no market context, never crashes)
```

## Out of scope / explicitly not doing

- Not touching `state.py` (per Block 0 hard rule — ask first, didn't ask, so
  don't).
- Not touching `loop.py`, `main.py`, `transport/`, or `web/` in steps 1–6.
- Not adding a second classifier/router test harness beyond
  `test_classifier.py` — brief says stop tuning once it's green and go help
  integrate.
- Not building anything speculative beyond the routing table that isn't
  step 7's stretch goal.
