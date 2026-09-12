# Port 25

Two agents at different organisations negotiate by email, because email is the
only interoperability protocol every company already has. A human supervises
through a console and steers by moving the mandate, not by reading every message.

Agent interoperability has a protocol problem. It was solved in 1982.

---

## Run it in 60 seconds

No API keys needed. The mock transport plays a scripted counterparty.

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python run_demo.py            # prints a whole negotiation, proves the loop
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000 for the console.

Copy `.env.example` to `.env` and fill in keys as you get them. Everything
degrades gracefully: no `OPENAI_API_KEY` means stubbed model output, no
`EXA_API_KEY` means no market context, and neither crashes the loop.

---

## How it works

An inbound email is tagged by a cheap classifier, then routed one of three ways.

| Tier | What it means | What happens |
|---|---|---|
| routine | they restated or conceded within known terms | fast model drafts, sends itself |
| complex | they introduced a new argument or trade-off | stronger model via OpenRouter, still sends itself |
| escalate | outside the mandate, or a structural change | drafted and parked for a human |

We route on **consequence**, not complexity. The same ladder decides both which
model runs and whether a person gets interrupted.

The mandate check in `state.py::is_within_mandate` is code, not a model
decision. The classifier can raise a turn to `escalate`; it can never lower one.

---

## Who owns what

Everyone reads `backend/app/state.py` first. That file is the contract. If a
field needs to change, say it out loud — all three workstreams touch it.

**Person A — transport.** `app/transport/`
Provision two Ambiguous coworkers, get one email round-tripping A to B to A.
**Hard gate at 00:50**: if it hasn't happened, set `PORT25_TRANSPORT=smtp` and
move on. The SMTP fallback is still real email, so the pitch survives.

**Person B — brain.** `app/brain/`
Start with `python test_classifier.py` — it runs against fixtures and needs no
transport and no console. Then the routing table, then drafting. Exa last.

**Person C — console.** `web/`
The static console in this repo already works. Build the CopilotKit version
alongside it, pointing at the same API. You also own the video: script it at
02:10, record at 02:30.

---

## Timeline

| Time | Milestone |
|---|---|
| 00:20 | contract agreed, keys distributed, split |
| 00:50 | **hard gate** — email round-trips, or switch to SMTP |
| 01:20 | agent drafts a real offer with market context |
| 01:40 | tier routing live, model choice visible |
| 02:10 | console shows the thread, approve and reject work |
| 02:30 | **the demo beat** — slider changes the next email. Record after this |
| 02:50 | repo, description, social post |

---

## The demo beat

Mid-negotiation, drag the walk-away floor upward. The agent's next email visibly
hardens, and the turn after that escalates to tier 3 because the new floor puts
the counterparty's ask out of bounds. Fifteen seconds, and it shows a person
steering a live agent rather than reading its output.

Rehearse it twice before recording. Start recording with the thread already two
turns deep so the video opens at the interesting part.

---

## API

```
GET    /health                     transport name and whether credentials work
POST   /negotiation                open a thread, send the opening offer
GET    /negotiation                current state (console polls this)
PATCH  /negotiation/mandate        move the floor — the demo beat
POST   /negotiation/approve        send the parked draft, optionally edited
POST   /negotiation/reject         walk away
```

---

## Things that will bite you

Two polite agents will email each other until the credits run out. `max_turns`
is 6. Do not raise it for the demo.

Email latency kills video. Pre-warm the Exa call and start recording with the
thread already in progress.

The `reason` string from the classifier is not debug output — it appears on
screen and is a large part of what judges read. Write the prompt so it comes
back in plain language.
