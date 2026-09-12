"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError, approve, getHealth, getNegotiation, reject, setMandate, startNegotiation,
  type Health, type Negotiation, type StartOptions, type Turn,
} from "../lib/negotiation";

const defaults: StartOptions = { buyer_account: "primary", supplier_account: "secondary", commodity: "aluminium", buyer_region: "Europe", supplier_region: "North America" };
const number = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 });
const money = (value: number | null, unit = "unit", currency = "EUR") => value === null ? "—" : `${currency} ${number.format(value)} / ${unit === "metric tonne" ? "t" : unit}`;
const time = (seconds: number) => new Date(seconds * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const statusLabel = (status: Negotiation["status"]) => ({ idle: "Waiting for email", thinking: "Preparing a reply", awaiting: "Needs your approval", closed: "Closed" })[status];
const errorMessage = (error: unknown) => error instanceof Error ? error.message : "Connection failed. Check the backend.";

function PriceAxis({ state, ceiling }: { state: Negotiation; ceiling: number }) {
  const prices = [state.our_position.unit_price_eur, state.their_position.unit_price_eur, ceiling].filter((v): v is number => v !== null);
  const padding = Math.max(10, Math.max(...prices) * .04);
  const min = Math.max(0, Math.floor((Math.min(...prices) - padding) / 5) * 5);
  const max = Math.ceil((Math.max(...prices) + padding) / 5) * 5;
  const top = (value: number) => `${100 - (value - min) / Math.max(max - min, 1) * 100}%`;
  return <section className={`price-axis ${state.their_position.unit_price_eur !== null && state.their_position.unit_price_eur > ceiling ? "is-breached" : ""}`} aria-label="Negotiated prices">
    <div className="axis-line" />
    {Array.from({ length: 5 }, (_, i) => min + (max - min) * i / 4).map(value => <span className="tick" style={{ top: top(value) }} key={value}>{money(value, state.price_unit, state.currency)}</span>)}
    <div className="floor-line" style={{ top: top(ceiling) }}><span>buyer maximum · {money(ceiling, state.price_unit, state.currency)}</span></div>
    {state.our_position.unit_price_eur !== null && <div className="position ours" style={{ top: top(state.our_position.unit_price_eur) }}><i /><span>buyer offer <b>{money(state.our_position.unit_price_eur, state.price_unit, state.currency)}</b></span></div>}
    {state.their_position.unit_price_eur !== null && <div className="position theirs" style={{ top: top(state.their_position.unit_price_eur) }}><i /><span>seller ask <b>{money(state.their_position.unit_price_eur, state.price_unit, state.currency)}</b></span></div>}
  </section>;
}

function Letter({ turn, state }: { turn: Turn; state: Negotiation }) {
  return <article className={`letter ${turn.direction === "out" ? "outbound" : "inbound"}`}>
    <header><strong>{turn.direction === "out" ? "Buyer → Seller" : "Seller → Buyer"}</strong><time>{time(turn.at)}</time></header>
    <small className="mail-address">{turn.direction === "out" ? state.our_email : state.counterparty_email}</small>
    <p className="email-body">{turn.body}</p>
    <footer>{turn.tier && <span className={`tier ${turn.tier}`}>{turn.tier}</span>}{turn.model_used && <span>{turn.model_used}</span>}{turn.approved_by_human && <span>human approved</span>}{turn.reason && <span className="reason">{turn.reason}</span>}</footer>
  </article>;
}

function Setup({ health, selection, setSelection, disabled, onStart }: {
  health: Health | null; selection: StartOptions; setSelection: (next: StartOptions) => void;
  disabled: boolean; onStart: () => void;
}) {
  const setup = health?.setup;
  const commodity = setup?.commodities.find(item => item.id === selection.commodity);
  const update = (key: keyof StartOptions, value: string) => setSelection({ ...selection, [key]: value });
  const invalid = selection.buyer_account === selection.supplier_account;
  return <section className="setup-card">
    <div className="setup-intro"><p className="eyebrow">New market negotiation</p><h2>Choose who buys and who sells</h2><p>The agents research current regional market signals with Exa, establish their price boundaries, then communicate through the selected inboxes.</p></div>
    <div className="party-grid">
      <fieldset><legend>Buyer</legend><label>Inbox<select aria-label="Buyer inbox" value={selection.buyer_account} disabled={disabled} onChange={event => update("buyer_account", event.target.value)}>{setup?.accounts.map(item => <option value={item.id} key={item.id}>{item.email}</option>)}</select></label><label>Buying region<select aria-label="Buyer region" value={selection.buyer_region} disabled={disabled} onChange={event => update("buyer_region", event.target.value)}>{setup?.regions.map(region => <option key={region}>{region}</option>)}</select></label></fieldset>
      <div className="role-arrow">↔</div>
      <fieldset><legend>Seller</legend><label>Inbox<select aria-label="Seller inbox" value={selection.supplier_account} disabled={disabled} onChange={event => update("supplier_account", event.target.value)}>{setup?.accounts.map(item => <option value={item.id} key={item.id}>{item.email}</option>)}</select></label><label>Selling region<select aria-label="Seller region" value={selection.supplier_region} disabled={disabled} onChange={event => update("supplier_region", event.target.value)}>{setup?.regions.map(region => <option key={region}>{region}</option>)}</select></label></fieldset>
    </div>
    <label className="commodity-picker">Commodity<select aria-label="Commodity" value={selection.commodity} disabled={disabled} onChange={event => update("commodity", event.target.value)}>{setup?.commodities.map(item => <option value={item.id} key={item.id}>{item.label} · {number.format(item.quantity)} metric tonnes</option>)}</select></label>
    <div className="research-preview"><span>EXA MARKET RESEARCH</span><p>Current benchmark, recent price movement, and regional premiums for {commodity?.label ?? "the commodity"} across {selection.buyer_region} and {selection.supplier_region}.</p></div>
    {invalid && <p className="validation" role="alert">Buyer and seller must use different inboxes.</p>}
    <button className="start-market" disabled={disabled || invalid || !setup} onClick={onStart}>Research market & start agents</button>
  </section>;
}

export function NegotiationConsole() {
  const [state, setState] = useState<Negotiation | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [selection, setSelection] = useState<StartOptions>(defaults);
  const [showSetup, setShowSetup] = useState(false);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [connectionError, setConnectionError] = useState("");
  const [ceiling, setCeiling] = useState(12.5);
  const [draft, setDraft] = useState("");
  const initializedSetup = useRef(false);
  const dirty = useRef(false);
  const revision = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refreshHealth = useCallback(async () => {
    try {
      const next = await getHealth();
      setHealth(next);
      if (!initializedSetup.current && next.setup) { setSelection(next.setup.defaults); initializedSetup.current = true; }
    } catch (error) { setHealth(null); setConnectionError(errorMessage(error)); }
  }, []);
  const load = useCallback(async () => {
    const version = revision.current;
    try {
      const next = await getNegotiation();
      if (version !== revision.current || dirty.current) return;
      setState(next); setCeiling(next.mandate.floor_price_eur); setConnectionError("");
    } catch (error) {
      if (version !== revision.current || dirty.current) return;
      if (error instanceof ApiError && error.status === 404) { setState(null); setShowSetup(true); setConnectionError(""); }
      else setConnectionError(errorMessage(error));
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { refreshHealth(); load(); const id = setInterval(() => { if (!dirty.current) load(); }, 2000); return () => { clearInterval(id); if (timer.current) clearTimeout(timer.current); }; }, [load, refreshHealth]);
  useEffect(() => { setDraft(state?.pending_draft ?? ""); }, [state?.thread_id, state?.pending_draft]);

  const mutate = async (operation: () => Promise<Negotiation>) => {
    revision.current += 1; dirty.current = true; setWorking(true); setError("");
    if (timer.current) { clearTimeout(timer.current); timer.current = null; }
    try { const next = await operation(); setState(next); setCeiling(next.mandate.floor_price_eur); setConnectionError(""); return true; }
    catch (error) { setError(errorMessage(error)); return false; }
    finally { revision.current += 1; dirty.current = false; setWorking(false); }
  };
  const begin = async () => { if (await mutate(() => startNegotiation(selection))) setShowSetup(false); };
  const changeCeiling = (value: number) => {
    if (!state || working || state.status === "closed") return;
    const id = state.thread_id; dirty.current = true; setCeiling(value);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => { timer.current = null; mutate(() => setMandate(id, { floor_price_eur: value })); }, 300);
  };
  const active = state !== null && state.status !== "closed";
  const blocked = !health?.ok || working || !!connectionError;
  const needsSetup = showSetup || !state;
  const lastInbound = state?.turns.filter(turn => turn.direction === "in").at(-1);
  const healthError = health && !health.ok ? health.detail || Object.entries(health.accounts ?? {}).filter(([, account]) => !account.ok).map(([role, account]) => `${role}: ${account.detail}`).join("; ") : "";
  const sliderMin = state ? Math.floor(state.mandate.target_price_eur * .9 / 5) * 5 : 1;
  const sliderMax = state ? Math.ceil(Math.max(ceiling * 1.12, state.their_position.unit_price_eur ?? 0) / 5) * 5 : 20;

  return <main className="dashboard">
    <aside className="inbox">
      <div className="wordmark">port<span>25</span><small>agent operations</small></div>
      <button className="new-thread" disabled={active || blocked || loading} onClick={() => { setShowSetup(true); setError(""); }}>{state?.status === "closed" ? "＋ Configure new negotiation" : "＋ Set up negotiation"}</button>
      <p className="inbox-label">Negotiations <b>{state ? 1 : 0}</b></p>
      <nav>{state ? <div className="inbox-thread selected"><i className={state.status} /><span><strong>{state.commodity}</strong><small>{statusLabel(state.status)}</small></span></div> : <p className="sidebar-note">Select both parties and a commodity to begin.</p>}</nav>
      <div className="inbox-footer"><div><b>Two accounts, one market</b><small>Buyer and seller negotiate by email.</small></div></div>
    </aside>

    <section className="workspace">
      <header className="topbar"><div><p className="eyebrow">Live negotiation workspace</p><h1>{needsSetup ? "Configure a commodity negotiation" : state?.subject}</h1>{!needsSetup && state && <span className="thread-id">{state.thread_id}</span>}</div><div className="connection"><i className={state?.status === "awaiting" || !health?.ok ? "amber" : "blue"} />{needsSetup ? health?.ok ? "Inboxes ready" : "Checking inboxes" : state ? statusLabel(state.status) : "Checking"}</div></header>
      {(error || connectionError || healthError) && <p className="error" role="alert">{error || connectionError || healthError}</p>}
      {loading && <p role="status">Loading negotiation setup…</p>}
      {needsSetup && !loading && <Setup health={health} selection={selection} setSelection={setSelection} disabled={blocked} onStart={begin} />}
      {!needsSetup && state && <>
        <section className="overview"><div><p className="eyebrow">{state.commodity} · {number.format(state.quantity)} metric tonnes</p><p className="subhead">Buyer · {state.our_email} · {state.buyer_region}<br />Seller · {state.counterparty_email} · {state.supplier_region}</p></div><div className="stat"><span>delivery ceiling</span><b>{state.mandate.max_lead_time_days} days</b></div><div className="stat"><span>Exa-informed target</span><b>{money(state.mandate.target_price_eur, state.price_unit, state.currency)}</b></div></section>
        {active && <div className="session-actions"><button className="secondary" disabled={working} onClick={() => mutate(() => reject(state.thread_id))}>Stop both agents</button><span>{health?.engine ?? "Waiting for connection details"}</span></div>}
        {state.status === "closed" && <div className="outcome" role="status"><p>{state.our_position.note || "Negotiation closed."}</p><button className="secondary" onClick={() => setShowSetup(true)}>Configure another negotiation</button></div>}
        <PriceAxis state={state} ceiling={ceiling} />
        <section className="mandate"><label htmlFor="ceiling">Maximum market price <strong>{money(ceiling, state.price_unit, state.currency)}</strong></label><input id="ceiling" type="range" min={sliderMin} max={sliderMax} step="5" value={ceiling} disabled={!active || working} onChange={event => changeCeiling(Number(event.target.value))} /><p>{working ? "Saving…" : "Exa informs the anchor. This limit remains enforced in code."}</p></section>
        <section className="thread-heading"><div><p className="eyebrow">Email audit trail</p><h2>Conversation</h2></div><span>{state.turns.length} / {state.max_turns} messages</span></section>
        <section className="thread">{state.turns.map(turn => <Letter key={`${state.thread_id}-${turn.index}`} turn={turn} state={state} />)}</section>
        {state.status === "awaiting" && <aside className="approval"><div><p className="eyebrow">Human decision required</p><h2>Review the buyer’s reply</h2><p>{lastInbound?.reason || "This reply needs your approval."}</p></div><textarea value={draft} onChange={event => setDraft(event.target.value)} aria-label="Edit draft reply" /><div className="actions"><button disabled={working || !draft.trim() || !!connectionError} onClick={() => mutate(() => approve(state.thread_id, draft))}>Approve & send</button><button className="secondary" disabled={working} onClick={() => mutate(() => reject(state.thread_id))}>Walk away</button></div></aside>}
        {state.market_context && <details className="market-context" open><summary>Regional market brief from Exa</summary><p>{state.market_context}</p></details>}
      </>}
    </section>

    <aside className="agent-trace">
      <div className="trace-heading"><div><p className="eyebrow">Agent activity</p><h2>{needsSetup ? "Choose both parties" : state ? statusLabel(state.status) : "Ready"}</h2></div></div>
      <div className="agent-card"><div><strong>{health?.engine ?? "Checking connections…"}</strong><small>{!health ? "Waiting for account status" : health.mode === "demo_pair" ? "Both owned inboxes are automated" : "Buyer agent"}</small></div></div>
      <ol className="activity">{!needsSetup && state?.turns.slice(-4).map(turn => <li key={turn.index} className={turn.tier === "escalate" ? "alert" : "done"}><span>{turn.direction === "in" ? "↓" : "↑"}</span><div><b>{turn.direction === "in" ? "Seller email received" : "Buyer email sent"}</b><p>{turn.reason}</p><time>{time(turn.at)}</time></div></li>)}</ol>
      <div className="trace-note"><b>Connections</b>{Object.entries(health?.accounts ?? {}).map(([role, account]) => <p key={role}>{role}: {account.ok ? "connected" : "needs attention"}</p>)}<p>OpenRouter: {!health ? "checking…" : health.integrations?.openrouter_configured ? "configured" : "not configured"}</p><p>Exa: {!health ? "checking…" : health.integrations?.exa_configured ? "configured" : "not configured"}</p><button className="secondary" onClick={refreshHealth}>Check connections</button></div>
    </aside>
  </main>;
}
