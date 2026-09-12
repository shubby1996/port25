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

### Automatic demo with two inboxes you own

One server can run both sides. Set these values in the ignored repo-root `.env`:

```dotenv
PORT25_TRANSPORT=smtp
PORT25_DEMO_PAIR=true
OUR_EMAIL=first-account@gmail.com
OUR_EMAIL_APP_PASSWORD=first-account-app-password
COUNTERPARTY_EMAIL=second-account@gmail.com
COUNTERPARTY_EMAIL_APP_PASSWORD=second-account-app-password
```

Use a separate app password for each inbox. Both accounts use the shared
SMTP/IMAP settings by default. Optional `COUNTERPARTY_SMTP_HOST`,
`COUNTERPARTY_SMTP_PORT`, `COUNTERPARTY_IMAP_HOST`, and `COUNTERPARTY_IMAP_PORT`
override the second account's server settings when it uses another provider.
Save credentials only in `.env`, never in `.env.example`.

From the repository root, check both accounts without sending anything:

```powershell
& .\backend\.venv\Scripts\python.exe .\backend\smoke_smtp.py --pair
```

Then start the server and open http://localhost:8000:

```powershell
cd backend
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

Choose which configured inbox acts as the buyer and which acts as the seller,
then choose their regions and a commodity. Primary aluminium is the default;
copper cathode and hot-rolled steel coil are also available. The same two
accounts can swap roles between runs. Both logins are checked before the first
email is sent.

At the start of a run, Exa searches separately for a recent global benchmark and
for current prices, movement, and premiums in the selected regions. OpenRouter
turns those source excerpts into a structured brief while preserving the quoted
USD or EUR currency. The brief and source URLs appear in the console. Its values
set the buyer's target and ceiling and the seller's floor and opening ask; regional
signals are capped at ±12% when they enter the automated policy. Every offer then
travels through SMTP and is received through IMAP.

This mode uses **deterministic demo pricing rules**, labeled in the console.
Set `PORT25_DEMO_AI=true` and supply `OPENROUTER_API_KEY` in the repo-root `.env`
to enable OpenRouter wording for both agents and classification of supplier
replies. Set `EXA_API_KEY` there for market context. Fixed offer terms and the
six-message cap remain enforced in code. A drafting failure uses a labeled
fallback; a classification failure pauses for review. With `PORT25_DEMO_AI=false`,
the same two-inbox demo needs no model keys. With `PORT25_DEMO_PAIR=false`, the
regular buyer agent is used.

For the integrated dashboard, keep the backend running and start another terminal:

```powershell
cd web/next
npm install
npm run dev
```

Open http://localhost:3000. It shows the live thread, both inboxes, email activity,
model labels, and Exa context. **New negotiation** restarts after closure, and
**Stop both agents** is available during any active run. See [console setup](web/next/README.md).

For the human-supervision beat, lower **Maximum market price** below the seller's
first quote. The buyer parks its next counteroffer for review; approve the draft
to continue. **Stop demo** stops both sides.
Both sides also stop on agreement or after six messages. A failed send stops
the demo without automatically retrying, since the server may have accepted it.
State is in memory; after a server restart, start a new thread. Mail already
sent stays in the two inboxes. Only one active demo runs per server process;
run one worker and use one runner (console or CLI) at a time for these inboxes.

For an unattended check without the console, run from the repository root:

```powershell
& .\backend\.venv\Scripts\python.exe .\backend\smoke_smtp.py --pair --send --timeout 300
```

This sends up to six demo emails across the two accounts. `PASS` means the buyer
received the supplier's agreement. Exit code `3` means the run stopped without
agreement or needed human approval; start a console demo for interactive approval.

### Verify one inbox with a manual reply (Windows / PowerShell)

Create a repo-root `.env` from `.env.example` if it does not exist. Set
`OUR_EMAIL`, `OUR_EMAIL_APP_PASSWORD`, and `COUNTERPARTY_EMAIL` locally.
Use a second inbox you control for `COUNTERPARTY_EMAIL`; reply from that inbox
manually for this first transport check. Only our inbox needs credentials here.
Set `PORT25_DEMO_PAIR=false` to use the console with a manual counterparty.
For Gmail, follow Google's [app password setup](https://support.google.com/accounts/answer/185833)
(requires 2-Step Verification; availability depends on the account).

From the repository root:

```powershell
# Checks both SMTP login and IMAP INBOX access. Sends no email.
& .\backend\.venv\Scripts\python.exe .\backend\smoke_smtp.py

# Sends one test email to COUNTERPARTY_EMAIL and waits up to 180 seconds.
& .\backend\.venv\Scripts\python.exe .\backend\smoke_smtp.py --send
```

The second command prints the unique subject to look for. Reply from the second
inbox, keeping that subject, with `We can offer 12.00 EUR per unit at 21 days lead time.`
`PASS` means a matching, non-empty reply arrived through IMAP. Exit codes:
`0` success, `1` configuration/connection error, `2` reply timeout, `130` cancelled.
Use `--to ADDRESS` to send to a different test inbox or `--timeout 300` to wait longer.
The timeout controls the reply-wait loop; an in-flight network call can take longer
(socket timeout: 15 seconds). The command always tests SMTP, even while the app is
configured to use mock. It does not run the classifier or generate a reply.

After the round trip passes, set `PORT25_TRANSPORT=smtp` in `.env`, then:

```powershell
cd backend
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
# In another PowerShell terminal:
Invoke-RestMethod http://localhost:8000/health
```

Check for `transport: smtp` and `ok: true`, then open http://localhost:8000 and
start a negotiation. It uses the configured inboxes and adds a unique subject
marker. Only replies from the counterparty with that subject enter the agent.
Polling preserves read/unread flags and accepts replies even if you opened them
in Gmail first. Duplicate tracking and queued replies last for the process lifetime;
restart the demo with a new negotiation after restarting the server. Model output
remains stubbed until the brain's API credentials are configured.

Local regression checks (no mailbox credentials needed):

```powershell
cd backend
& .\.venv\Scripts\python.exe -m pytest -q --basetemp=.pytest-tmp
& .\.venv\Scripts\python.exe run_demo.py
```

Install `pytest` into the venv if needed. `--basetemp` keeps test files inside
the workspace on Windows.

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
POST   /negotiation                select roles/market, research it, send opening offer
GET    /negotiation                current state (console polls this)
PATCH  /negotiation/mandate        move the floor — the demo beat
POST   /negotiation/approve        send the parked draft, optionally edited
POST   /negotiation/reject         walk away
```

The start body accepts `buyer_account`, `supplier_account`, `commodity`,
`buyer_region`, and `supplier_region`. `GET /health` returns the safe selectable
options and configured email addresses; credentials never enter the browser.

---

## Things that will bite you

Two polite agents will email each other until the credits run out. `max_turns`
is 6. Do not raise it for the demo.

Email latency kills video. Pre-warm the Exa call and start recording with the
thread already in progress.

The `reason` string from the classifier is not debug output — it appears on
screen and is a large part of what judges read. Write the prompt so it comes
back in plain language.
