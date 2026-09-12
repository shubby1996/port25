"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { approve, getNegotiation, reject, setFloor, startNegotiation, type Negotiation, type Turn } from "../lib/negotiation";
import { CopilotProgress } from "./copilot-progress";

const money = (value: number | null) => value === null ? "—" : `€${value.toFixed(2)}`;
const clock = (seconds: number) => new Intl.DateTimeFormat("en", { hour: "2-digit", minute: "2-digit" }).format(new Date(seconds * 1000));
const demo: Negotiation = { thread_id: "P25-0842", subject: "Q3 coupling assemblies — pricing", our_email: "maya@port25.ai", counterparty_email: "jonas@nordwerk.de", status: "awaiting", mandate: { floor_price_eur: 138, target_price_eur: 132, max_lead_time_days: 21 }, our_position: { unit_price_eur: 136, lead_time_days: 18 }, their_position: { unit_price_eur: 145, lead_time_days: 16 }, pending_draft: "We can proceed at €138 per unit for a twelve-month commitment, with payment terms unchanged. Please let us know if that works on your side.", turns: [
  { index: 1, direction: "out", subject: "", body: "We can confirm 2,000 coupling assemblies at €132 per unit, with delivery inside 18 days.", at: 1789214400, tier: "routine", reason: "Confirmed volume within the approved range.", model_used: "gpt-4.1-mini", approved_by_human: false },
  { index: 2, direction: "in", subject: "", body: "We can make the 16-day window work, but our position is €145 per unit at that volume. Would you consider a longer commitment?", at: 1789214640, tier: "complex", reason: "Introduced a price and delivery trade-off.", model_used: "claude-3.5-sonnet", approved_by_human: false },
  { index: 3, direction: "out", subject: "", body: "We can consider a twelve-month commitment if you can move to €136 per unit while holding the 16-day delivery window.", at: 1789214760, tier: "complex", reason: "Countered on price while preserving delivery.", model_used: "claude-3.5-sonnet", approved_by_human: false },
  { index: 4, direction: "in", subject: "", body: "I can hold 16 days, but €145 is our firm position without a change to payment terms.", at: 1789214940, tier: "escalate", reason: "Their ask exceeds your €138 walk-away floor.", model_used: "policy check", approved_by_human: false }
] };
const mockThreads: Record<string, Negotiation> = {
  "P25-0842": demo,
  "P25-0817": { ...demo, thread_id: "P25-0817", subject: "Aerospace valve housings — annual volume", counterparty_email: "sam@arcfield.io", status: "thinking", mandate: { floor_price_eur: 86, target_price_eur: 82, max_lead_time_days: 28 }, our_position: { unit_price_eur: 82, lead_time_days: 25 }, their_position: { unit_price_eur: 88, lead_time_days: 22 }, pending_draft: "", turns: [
    { index: 1, direction: "out", subject: "", body: "We are planning annual volume of 4,000 valve housings and can begin at €82 per unit.", at: 1789211500, tier: "routine", reason: "Opening position is inside the mandate.", model_used: "gpt-4.1-mini", approved_by_human: false },
    { index: 2, direction: "in", subject: "", body: "At 4,000 units, we can offer €88 with a 22-day lead time. A yearly forecast would help us improve the price.", at: 1789211740, tier: "complex", reason: "They introduced a volume-for-price trade-off.", model_used: "claude-3.5-sonnet", approved_by_human: false },
    { index: 3, direction: "out", subject: "", body: "Maya is researching the annual forecast trade-off before sending a counteroffer.", at: 1789211820, tier: "complex", reason: "Agent is gathering evidence for a new trade-off.", model_used: "claude-3.5-sonnet", approved_by_human: false }
  ] },
  "P25-0803": { ...demo, thread_id: "P25-0803", subject: "Precision bearings — supply renewal", counterparty_email: "lina@kinoprecision.com", status: "closed", mandate: { floor_price_eur: 47, target_price_eur: 44, max_lead_time_days: 14 }, our_position: { unit_price_eur: 45, lead_time_days: 12 }, their_position: { unit_price_eur: 45, lead_time_days: 12 }, pending_draft: "", turns: [
    { index: 1, direction: "in", subject: "", body: "We can renew at €46 per bearing with delivery in 12 days.", at: 1789208000, tier: "routine", reason: "Offer is within price and delivery authority.", model_used: "gpt-4.1-mini", approved_by_human: false },
    { index: 2, direction: "out", subject: "", body: "Confirmed. We accept €45 per bearing, delivery in 12 days, for the renewal volume.", at: 1789208240, tier: "routine", reason: "Accepted a compliant counterparty concession.", model_used: "gpt-4.1-mini", approved_by_human: false },
    { index: 3, direction: "in", subject: "", body: "Confirmed — we will issue the revised confirmation today.", at: 1789208420, tier: "routine", reason: "Deal is agreed within the mandate.", model_used: "gpt-4.1-mini", approved_by_human: false }
  ] },
  "P25-0798": { ...demo, thread_id: "P25-0798", subject: "Motor control boards — lead time", counterparty_email: "eve@rothensupply.com", status: "awaiting", mandate: { floor_price_eur: 63, target_price_eur: 59, max_lead_time_days: 20 }, our_position: { unit_price_eur: 60, lead_time_days: 18 }, their_position: { unit_price_eur: 62, lead_time_days: 27 }, pending_draft: "We can proceed at €62 per board if the delivery date returns to 20 days or fewer. Please confirm your earliest workable slot.", turns: [
    { index: 1, direction: "out", subject: "", body: "We need 1,500 motor control boards at €60 per unit with delivery in 18 days.", at: 1789204000, tier: "routine", reason: "Opening offer is within mandate.", model_used: "gpt-4.1-mini", approved_by_human: false },
    { index: 2, direction: "in", subject: "", body: "We can meet €62 per unit, but the earliest delivery date is 27 days.", at: 1789204300, tier: "escalate", reason: "Their 27-day delivery exceeds your 20-day ceiling.", model_used: "policy check", approved_by_human: false }
  ] }
};

function Inbox({ selected, onSelect }: { selected: string; onSelect: (id: string) => void }) {
  const threads = [
    ["P25-0842", "Nordwerk Components", "€145 ask needs review", "awaiting"],
    ["P25-0817", "Arcfield Systems", "Agent sent counteroffer", "active"],
    ["P25-0803", "Kino Precision", "Terms agreed", "closed"],
    ["P25-0798", "Rothen Supply", "Lead-time question", "active"]
  ];
  return <aside className="inbox"><div className="wordmark">port<span>25</span><small>agent operations</small></div><button className="new-thread">＋ New negotiation</button><p className="inbox-label">Negotiations <b>4</b></p><nav>{threads.map(([id, name, note, status]) => <button onClick={() => onSelect(id)} className={`inbox-thread ${selected === id ? "selected" : ""}`} key={id}><i className={status} /><span><strong>{name}</strong><small>{note}</small></span>{status === "awaiting" && <em>1</em>}</button>)}</nav><div className="inbox-footer"><span className="avatar">MS</span><div><b>Maya Shah</b><small>Procurement lead</small></div><button>•••</button></div></aside>;
}

function HumanInputCard({ negotiation, onAnswer }: { negotiation: Negotiation; onAnswer: (answer: string) => void }) {
  const [answer, setAnswer] = useState("");
  if (negotiation.status !== "awaiting") return null;
  const question = negotiation.thread_id === "P25-0798" ? "Can we relax the delivery ceiling to 27 days?" : "Can I offer a 12-month commitment while keeping payment terms unchanged?";
  return <section className="human-input"><div className="human-input-head"><span>✦ Agent needs your input</span><small>Generated decision UI</small></div><h3>{question}</h3><p>The agent cannot infer this authority. Choose a policy and it will shape the next email.</p><div className="choice-row"><button className={answer === "hold" ? "selected" : ""} onClick={() => { setAnswer("hold"); onAnswer("Hold the current mandate"); }}>Hold current mandate</button><button className={answer === "allow" ? "selected" : ""} onClick={() => { setAnswer("allow"); onAnswer("Allow this exception once"); }}>Allow one exception</button></div>{answer && <div className="answer-result"><b>{answer === "hold" ? "Agent will keep the hard boundary." : "Agent will draft with the temporary exception."}</b><span>Next action preview updated</span></div>}</section>;
}

function AgentTrace({ negotiation }: { negotiation: Negotiation }) {
  const newest = negotiation.turns.at(-1);
  return <aside className="agent-trace"><div className="trace-heading"><div><p className="eyebrow">Agent trace</p><h2>What the AI did</h2></div><span className="live-pill"><i /> live</span></div><div className="agent-card"><div className="agent-avatar">M</div><div><strong>Maya, buyer agent</strong><small>Operating inside your mandate</small></div></div><ol className="activity"><li className="done"><span>✓</span><div><b>Read inbound email</b><p>Nordwerk introduced a firm price.</p><time>09:48:12</time></div></li><li className="done"><span>✓</span><div><b>Checked mandate in code</b><p>{newest?.reason}</p><time>09:48:13</time></div></li><li className="alert"><span>!</span><div><b>Paused for human review</b><p>Draft is ready. No email has been sent.</p><time>09:48:14</time></div></li></ol><div className="trace-note"><b>Why this matters</b><p>The classifier can raise risk, but it cannot lower the walk-away floor.</p></div></aside>;
}

function GeneratedProgressCard({ negotiation }: { negotiation: Negotiation }) {
  const paused = negotiation.status === "awaiting";
  return <section className="genui-card"><div className="genui-head"><span>✦ Generated by Maya</span><small>CopilotKit component</small></div><div className="genui-body"><div className="mini-steps"><span className="complete">Email received</span><span className="complete">Terms extracted</span><span className="complete">Mandate checked</span><span className={paused ? "warning" : "complete"}>{paused ? "Human review" : negotiation.status === "closed" ? "Deal confirmed" : "Drafting reply"}</span></div><div className="genui-copy"><b>{paused ? "Counterparty’s ask needs a decision" : negotiation.status === "closed" ? "Negotiation completed inside the mandate" : "Agent is building a counteroffer"}</b><p>{paused ? `€${negotiation.their_position.unit_price_eur?.toFixed(2)} / unit exceeds your €${negotiation.mandate.floor_price_eur.toFixed(2)} rule. The agent prepared a reply but did not send it.` : "The visual changes with each selected thread, using the current agent state and extracted terms."}</p></div><div className="term"><span>{negotiation.their_position.lead_time_days ?? "—"}</span><small>day lead time</small></div><div className={`term ${paused ? "alert" : ""}`}><span>{money(negotiation.their_position.unit_price_eur)}</span><small>their ask</small></div></div></section>;
}

function PriceAxis({ negotiation, previewFloor }: { negotiation: Negotiation; previewFloor: number }) {
  const values = [negotiation.our_position.unit_price_eur, negotiation.their_position.unit_price_eur, previewFloor].filter((v): v is number => v !== null);
  const min = Math.floor((Math.min(...values) - 1) * 2) / 2;
  const max = Math.ceil((Math.max(...values) + 1) * 2) / 2;
  const range = Math.max(max - min, 1);
  const top = (value: number) => `${100 - ((value - min) / range) * 100}%`;
  const asksTooMuch = negotiation.their_position.unit_price_eur !== null && negotiation.their_position.unit_price_eur > previewFloor;
  const ticks = Array.from({ length: 5 }, (_, i) => min + (range / 4) * i).reverse();
  return <section className={`price-axis ${asksTooMuch ? "is-breached" : ""}`} aria-label="Price position">
    <div className="axis-line" />
    {ticks.map(value => <span className="tick" style={{ top: top(value) }} key={value}>{money(value)}</span>)}
    <div className="floor-line" style={{ top: top(previewFloor) }}><span>walk-away floor · {money(previewFloor)}</span></div>
    {negotiation.our_position.unit_price_eur !== null && <div className="position ours" style={{ top: top(negotiation.our_position.unit_price_eur) }}><i /><span>our offer <b>{money(negotiation.our_position.unit_price_eur)}</b></span></div>}
    {negotiation.their_position.unit_price_eur !== null && <div className="position theirs" style={{ top: top(negotiation.their_position.unit_price_eur) }}><i /><span>their ask <b>{money(negotiation.their_position.unit_price_eur)}</b></span></div>}
  </section>;
}

function Letter({ turn }: { turn: Turn }) {
  const inbound = turn.direction === "in";
  return <article className={`letter ${inbound ? "inbound" : "outbound"}`}>
    <div className="letter-top"><span>{inbound ? "Received" : "Sent"} · {clock(turn.at)}</span>{turn.tier && <span className={`tier ${turn.tier}`}>{turn.tier}</span>}</div>
    <p>{turn.body}</p>
    {(turn.reason || turn.model_used || turn.approved_by_human) && <footer>
      {turn.model_used && <span>{turn.model_used}</span>}
      {turn.approved_by_human && <span>human approved</span>}
      {turn.reason && <span className="reason">{turn.reason}</span>}
    </footer>}
  </article>;
}

export function NegotiationConsole() {
  const [negotiation, setNegotiation] = useState<Negotiation | null>(null);
  const [floor, setFloorValue] = useState(12.5);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [selectedThread, setSelectedThread] = useState("P25-0842");
  const [humanNote, setHumanNote] = useState("");
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);
  const dirty = useRef(false);

  const load = useCallback(async () => {
    try { const data = await getNegotiation(); setNegotiation(data); if (!dirty.current) setFloorValue(data.mandate.floor_price_eur); setError(""); }
    catch { setNegotiation(null); if (!dirty.current) setFloorValue(demo.mandate.floor_price_eur); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); const interval = setInterval(() => { if (!dirty.current) load(); }, 2000); return () => clearInterval(interval); }, [load]);
  useEffect(() => { if (negotiation?.status === "awaiting") setDraft(negotiation.pending_draft); }, [negotiation?.pending_draft, negotiation?.status]);
  useEffect(() => () => { if (debounce.current) clearTimeout(debounce.current); }, []);

  const sliderBounds = useMemo(() => {
    const source = selectedThread === "P25-0842" && negotiation ? negotiation : mockThreads[selectedThread] ?? demo;
    const points = [source.our_position.unit_price_eur, source.their_position.unit_price_eur, source.mandate.floor_price_eur].filter((x): x is number => x !== null);
    return { min: Math.floor(Math.min(...points) - 3), max: Math.ceil(Math.max(...points) + 3) };
  }, [negotiation, selectedThread]);
  const changeFloor = (value: number) => {
    setFloorValue(value); dirty.current = true;
    if (debounce.current) clearTimeout(debounce.current);
    debounce.current = setTimeout(async () => {
      try { setNegotiation(await setFloor(value)); setError(""); } catch { setError("The mandate change could not be saved. Is the API running?"); }
      finally { dirty.current = false; }
    }, 220);
  };
  const act = async (action: "approve" | "reject") => {
    setWorking(true); try { setNegotiation(action === "approve" ? await approve(draft) : await reject()); } catch { setError("Action could not be sent. Please try again."); } finally { setWorking(false); }
  };
  const start = async () => { setWorking(true); try { setNegotiation(await startNegotiation()); setError(""); } catch { setError("Could not open a negotiation. Start the FastAPI server on port 8000."); } finally { setWorking(false); } };

  if (loading) return <main className="shell"><div className="loading">Opening Port 25…</div></main>;
  const active = selectedThread === "P25-0842" && negotiation ? negotiation : mockThreads[selectedThread] ?? demo;
  const selectThread = (id: string) => {
    setSelectedThread(id); setFloorValue((mockThreads[id] ?? demo).mandate.floor_price_eur); setDraft(""); setHumanNote("");
  };

  return <main className="dashboard">
    <Inbox selected={selectedThread} onSelect={selectThread} />
    <section className="workspace">
    <header className="topbar"><div><p className="eyebrow">Negotiation workspace</p><div className="title-row"><h1>{active.subject}</h1><span className="thread-id">{active.thread_id}</span></div></div><div className="connection"><i className={active.status === "awaiting" ? "amber" : "blue"} />{active.status.replace("_", " ")}</div></header>
    {!negotiation && <div className="demo-banner"><span>✦</span><p><b>Interactive demo data</b> — connect the FastAPI backend to replace this with live inbox activity.</p><button onClick={start} disabled={working}>{working ? "Opening…" : "Start live loop"}</button></div>}
    <section className="overview"><div><p className="eyebrow">Live mandate · {active.counterparty_email || "Counterparty"}</p><p className="subhead">Your buyer agent negotiates by email. It acts on routine messages and pauses only when a hard mandate rule is crossed.</p></div><div className="stat"><span>delivery ceiling</span><b>{active.mandate.max_lead_time_days} days</b></div><div className="stat"><span>target price</span><b>{money(active.mandate.target_price_eur)}</b></div></section>
    <PriceAxis negotiation={active} previewFloor={floor} />
    <section className="mandate"><label htmlFor="floor">Walk-away floor <strong>{money(floor)}</strong></label><input id="floor" type="range" min={sliderBounds.min} max={sliderBounds.max} step="0.1" value={floor} onChange={e => changeFloor(Number(e.target.value))} /><p>Changing this immediately constrains the next agent reply.</p></section>
    <GeneratedProgressCard negotiation={active} />
    <HumanInputCard negotiation={active} onAnswer={setHumanNote} />
    {humanNote && <div className="human-note">✓ <b>Human instruction saved:</b> {humanNote}. The agent’s next draft will use it.</div>}
    {error && <p className="error">{error}</p>}
    <section className="thread-heading"><div><p className="eyebrow">Email audit trail</p><h2>Conversation</h2></div><span>{active.turns.length} messages</span></section>
    <section className="thread">{active.turns.map(turn => <Letter key={turn.index} turn={turn} />)}</section>
    {active.status === "awaiting" && <aside className="approval"><div><p className="eyebrow">Human decision required</p><h2>Your agent stopped before sending</h2><p>{active.turns.filter(t => t.direction === "in").at(-1)?.reason || "This response needs your approval."}</p></div><textarea value={draft || active.pending_draft} onChange={e => setDraft(e.target.value)} aria-label="Edit draft reply" /><div className="actions"><button onClick={() => act("approve")} disabled={working}>{working ? "Sending…" : "Approve & send"}</button><button className="secondary" onClick={() => act("reject")} disabled={working}>Walk away</button></div></aside>}
    <section className="copilot-panel"><p className="eyebrow">CopilotKit generative UI</p><CopilotProgress /></section>
    </section><AgentTrace negotiation={active} /></main>;
}
