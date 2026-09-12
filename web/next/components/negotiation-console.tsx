"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, approve, getHealth, getNegotiation, reject, setMandate, startNegotiation, type Health, type Negotiation, type Turn } from "../lib/negotiation";

const money = (value: number | null) => value === null ? "—" : `€${value.toFixed(2)}`;
const time = (seconds: number) => new Date(seconds * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const statusLabel = (status: Negotiation["status"]) => ({ idle: "Waiting for email", thinking: "Preparing a reply", awaiting: "Needs your approval", closed: "Closed" })[status];
const errorMessage = (error: unknown) => error instanceof Error ? error.message : "Connection failed. Check the backend.";

function PriceAxis({ state, ceiling }: { state: Negotiation; ceiling: number }) {
  const prices = [state.our_position.unit_price_eur, state.their_position.unit_price_eur, ceiling].filter((v): v is number => v !== null);
  const min = Math.max(0, Math.floor(Math.min(...prices) - 1));
  const max = Math.ceil(Math.max(...prices) + 1);
  const top = (value: number) => `${100 - (value - min) / Math.max(max - min, 1) * 100}%`;
  return <section className={`price-axis ${state.their_position.unit_price_eur !== null && state.their_position.unit_price_eur > ceiling ? "is-breached" : ""}`} aria-label="Negotiated prices">
    <div className="axis-line" />
    {Array.from({ length: 5 }, (_, i) => min + (max - min) * i / 4).map(value => <span className="tick" style={{ top: top(value) }} key={value}>{money(value)}</span>)}
    <div className="floor-line" style={{ top: top(ceiling) }}><span>maximum unit price · {money(ceiling)}</span></div>
    {state.our_position.unit_price_eur !== null && <div className="position ours" style={{ top: top(state.our_position.unit_price_eur) }}><i /><span>buyer offer <b>{money(state.our_position.unit_price_eur)}</b></span></div>}
    {state.their_position.unit_price_eur !== null && <div className="position theirs" style={{ top: top(state.their_position.unit_price_eur) }}><i /><span>supplier ask <b>{money(state.their_position.unit_price_eur)}</b></span></div>}
  </section>;
}

function Letter({ turn, state }: { turn: Turn; state: Negotiation }) {
  return <article className={`letter ${turn.direction === "out" ? "outbound" : "inbound"}`}>
    <header><strong>{turn.direction === "out" ? "Buyer → Supplier" : "Supplier → Buyer"}</strong><time>{time(turn.at)}</time></header>
    <small className="mail-address">{turn.direction === "out" ? state.our_email : state.counterparty_email}</small>
    <p className="email-body">{turn.body}</p>
    <footer>{turn.tier && <span className={`tier ${turn.tier}`}>{turn.tier}</span>}{turn.model_used && <span>{turn.model_used}</span>}{turn.approved_by_human && <span>human approved</span>}{turn.reason && <span className="reason">{turn.reason}</span>}</footer>
  </article>;
}

export function NegotiationConsole() {
  const [state, setState] = useState<Negotiation | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [connectionError, setConnectionError] = useState("");
  const [ceiling, setCeiling] = useState(12.5);
  const [draft, setDraft] = useState("");
  const dirty = useRef(false);
  const revision = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refreshHealth = useCallback(async () => {
    try { setHealth(await getHealth()); }
    catch (error) { setHealth(null); setConnectionError(errorMessage(error)); }
  }, []);
  const load = useCallback(async () => {
    const version = revision.current;
    try {
      const next = await getNegotiation();
      if (version !== revision.current || dirty.current) return;
      setState(next); setCeiling(next.mandate.floor_price_eur); setConnectionError("");
    } catch (error) {
      if (version !== revision.current || dirty.current) return;
      if (error instanceof ApiError && error.status === 404) { setState(null); setConnectionError(""); }
      else setConnectionError(errorMessage(error));
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { refreshHealth(); load(); const id = setInterval(() => { if (!dirty.current) load(); }, 2000); return () => { clearInterval(id); if (timer.current) clearTimeout(timer.current); }; }, [load, refreshHealth]);
  useEffect(() => { setDraft(state?.pending_draft ?? ""); }, [state?.thread_id, state?.pending_draft]);

  const mutate = async (operation: () => Promise<Negotiation>) => {
    revision.current += 1;
    dirty.current = true;
    setWorking(true); setError("");
    if (timer.current) { clearTimeout(timer.current); timer.current = null; }
    try { const next = await operation(); setState(next); setCeiling(next.mandate.floor_price_eur); setConnectionError(""); }
    catch (error) { setError(errorMessage(error)); }
    finally { revision.current += 1; dirty.current = false; setWorking(false); }
  };
  const changeCeiling = (value: number) => {
    if (!state || working || state.status === "closed") return;
    const id = state.thread_id;
    dirty.current = true; setCeiling(value);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => { timer.current = null; mutate(() => setMandate(id, { floor_price_eur: value })); }, 300);
  };
  const active = state !== null && state.status !== "closed";
  const blocked = !health?.ok || working || !!connectionError;
  const lastInbound = state?.turns.filter(turn => turn.direction === "in").at(-1);
  const healthError = health && !health.ok ? health.detail || Object.entries(health.accounts ?? {}).filter(([, account]) => !account.ok).map(([role, account]) => `${role}: ${account.detail}`).join("; ") : "";

  return <main className="dashboard">
    <aside className="inbox">
      <div className="wordmark">port<span>25</span><small>agent operations</small></div>
      <button className="new-thread" disabled={active || blocked || loading} onClick={() => mutate(startNegotiation)}>{working ? "Please wait…" : state?.status === "closed" ? "＋ New negotiation" : "＋ Start two-inbox demo"}</button>
      <p className="inbox-label">Negotiations <b>{state ? 1 : 0}</b></p>
      <nav>{state ? <div className="inbox-thread selected"><i className={state.status} /><span><strong>{state.counterparty_email}</strong><small>{statusLabel(state.status)}</small></span></div> : <p className="sidebar-note">Your live conversation will appear here.</p>}</nav>
      <div className="inbox-footer"><div><b>Two accounts, one conversation</b><small>Buyer and supplier reply by email.</small></div></div>
    </aside>

    <section className="workspace">
      <header className="topbar"><div><p className="eyebrow">Live negotiation workspace</p><h1>{state?.subject ?? "Your agents, connected by email"}</h1>{state && <span className="thread-id">{state.thread_id}</span>}</div><div className="connection"><i className={state?.status === "awaiting" || !health?.ok ? "amber" : "blue"} />{state ? statusLabel(state.status) : health?.ok ? "Inboxes ready" : "Checking inboxes"}</div></header>
      {(error || connectionError || healthError) && <p className="error" role="alert">{error || connectionError || healthError}</p>}
      {loading && <p role="status">Loading current negotiation…</p>}
      {!state && !loading && <section className="empty-state"><h2>Start a real email exchange</h2><p>The buyer opens an offer, the supplier counters, and both work toward agreement. You can change the buyer’s limit or stop the exchange.</p><p>The run stops on agreement or at six messages.</p></section>}
      {state && <>
        <section className="overview"><div><p className="eyebrow">Buyer · {state.our_email}</p><p className="subhead">Supplier · {state.counterparty_email}</p></div><div className="stat"><span>delivery ceiling</span><b>{state.mandate.max_lead_time_days} days</b></div><div className="stat"><span>target price</span><b>{money(state.mandate.target_price_eur)}</b></div></section>
        {active && <div className="session-actions"><button className="secondary" disabled={working} onClick={() => mutate(() => reject(state.thread_id))}>Stop both agents</button><span>{health?.engine ?? "Waiting for connection details"}</span></div>}
        {state.status === "closed" && <p className="outcome" role="status">{state.our_position.note || "Negotiation closed."}</p>}
        <PriceAxis state={state} ceiling={ceiling} />
        <section className="mandate"><label htmlFor="ceiling">Maximum unit price <strong>{money(ceiling)}</strong></label><input id="ceiling" type="range" min="1" max={Math.ceil(Math.max(20, ceiling + 1, state.their_position.unit_price_eur ?? 0))} step="0.1" value={ceiling} disabled={!active || working} onChange={event => changeCeiling(Number(event.target.value))} /><p>{working ? "Saving…" : "Limits are enforced in code. Review a parked reply before sending it."}</p></section>
        <section className="thread-heading"><div><p className="eyebrow">Email audit trail</p><h2>Conversation</h2></div><span>{state.turns.length} / {state.max_turns} messages</span></section>
        <section className="thread">{state.turns.map(turn => <Letter key={`${state.thread_id}-${turn.index}`} turn={turn} state={state} />)}</section>
        {state.status === "awaiting" && <aside className="approval"><div><p className="eyebrow">Human decision required</p><h2>Review the buyer’s reply</h2><p>{lastInbound?.reason || "This reply needs your approval."}</p></div><textarea value={draft} onChange={event => setDraft(event.target.value)} aria-label="Edit draft reply" /><div className="actions"><button disabled={working || !draft.trim() || !!connectionError} onClick={() => mutate(() => approve(state.thread_id, draft))}>Approve & send</button><button className="secondary" disabled={working} onClick={() => mutate(() => reject(state.thread_id))}>Walk away</button></div></aside>}
        {state.market_context && <details className="market-context"><summary>Market context from Exa</summary><p>{state.market_context}</p></details>}
      </>}
    </section>

    <aside className="agent-trace">
      <div className="trace-heading"><div><p className="eyebrow">Agent activity</p><h2>{state ? statusLabel(state.status) : "Ready for a new thread"}</h2></div></div>
      <div className="agent-card"><div><strong>{health?.engine ?? "Checking connections…"}</strong><small>{!health ? "Waiting for account status" : health.mode === "demo_pair" ? "Both owned inboxes are automated" : "Buyer agent"}</small></div></div>
      <ol className="activity">{state?.turns.slice(-4).map(turn => <li key={turn.index} className={turn.tier === "escalate" ? "alert" : "done"}><span>{turn.direction === "in" ? "↓" : "↑"}</span><div><b>{turn.direction === "in" ? "Supplier email received" : "Buyer email sent"}</b><p>{turn.reason}</p><time>{time(turn.at)}</time></div></li>)}</ol>
      <div className="trace-note"><b>Connections</b>{Object.entries(health?.accounts ?? {}).map(([role, account]) => <p key={role}>{role}: {account.ok ? "connected" : "needs attention"}</p>)}<p>OpenRouter: {!health ? "checking…" : health.integrations?.openrouter_configured ? "configured" : "not configured"}</p><p>Exa: {!health ? "checking…" : health.integrations?.exa_configured ? "configured" : "not configured"}</p><button className="secondary" onClick={refreshHealth}>Check connections</button></div>
    </aside>
  </main>;
}
