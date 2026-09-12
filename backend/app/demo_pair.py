"""Two owned inboxes negotiating a demo order using explicit pricing rules.

Each side learns the other side's offer only by receiving its email. Optional
OpenRouter drafting and classification supplement the fixed demo pricing rules.
"""

from __future__ import annotations

import os
import re
import threading
from collections import deque

from .state import Negotiation, Position, Status, Tier, Turn, new_negotiation
from .brain.classifier import classify, CLASSIFIER_MODEL
from .brain.context import fetch_market_context
from .brain.demo_drafting import draft_fixed_offer
from .transport import InboundMessage
from .transport.smtp_imap import SmtpImapTransport

ENGINE = "demo rules"
FOOTER = "\n\nPort 25 demo only; no real order is being placed."


def enabled() -> bool:
    return os.getenv("PORT25_DEMO_PAIR", "false").lower() in ("1", "true", "yes")


def from_environment() -> DemoPair:
    buyer = SmtpImapTransport()
    supplier = SmtpImapTransport(counterparty=True)
    # Validate both accounts before either account can send an email.
    buyer.validate_config()
    supplier.validate_config()
    if buyer.address.casefold() == supplier.address.casefold():
        raise ValueError("OUR_EMAIL and COUNTERPARTY_EMAIL must be two different inboxes")
    state = new_negotiation(our_email=buyer.address, counterparty_email=supplier.address)
    state.subject = f"Port 25 demo: component pricing [port25-{state.thread_id}]"
    use_ai = os.getenv("PORT25_DEMO_AI", "false").lower() in ("1", "true", "yes")
    if use_ai and not os.getenv("OPENROUTER_API_KEY", "").strip():
        raise ValueError("PORT25_DEMO_AI requires OPENROUTER_API_KEY")
    return DemoPair(state, buyer, supplier, use_ai=use_ai)


def extract_position(body: str) -> Position:
    # Our agents send plain text. Ignore quoted history if a human joins in.
    text = re.split(r"(?im)^\s*(?:>|On .+wrote:|Am .+schrieb)", body, maxsplit=1)[0]
    price = re.search(r"\b(\d+(?:[.,]\d{1,2})?)\s*EUR\b", text, re.I)
    lead = re.search(r"\b(\d+)\s*days?\b", text, re.I)
    return Position(
        unit_price_eur=float(price.group(1).replace(",", ".")) if price else None,
        lead_time_days=int(lead.group(1)) if lead else None,
    )


def offer_body(price: float, days: int, *, agreed: bool = False, supplier: bool = False) -> str:
    opening = "Agreed" if agreed else ("We can supply" if supplier else "We can offer")
    return f"{opening}: {price:.2f} EUR per unit at {days} days lead time." + FOOTER


class DemoPair:
    def __init__(self, state: Negotiation, buyer, supplier, *, use_ai: bool = False) -> None:
        self.state = state
        self.buyer = buyer
        self.supplier = supplier
        self.use_ai = use_ai
        self.engine = "OpenRouter drafting + bounded demo policy" if use_ai else ENGINE
        self._supplier_model = ENGINE
        self.lock = threading.RLock()
        self.phase = "supplier"
        self.supplier_floor = 11.00
        self.supplier_ask = 12.00
        self.supplier_days = 21
        self.outcome = ""
        self._started = False
        self._pending = {"buyer": deque(), "supplier": deque()}

    def healthcheck(self) -> dict:
        accounts = {}
        for role, transport in (("buyer", self.buyer), ("supplier", self.supplier)):
            ok, detail = transport.healthcheck()
            accounts[role] = {"email": transport.address, "ok": ok, "detail": detail}
        return {
            "transport": "smtp", "mode": "demo_pair", "engine": self.engine,
            "ok": all(account["ok"] for account in accounts.values()),
            "accounts": accounts,
            "integrations": {
                "openrouter_configured": bool(os.getenv("OPENROUTER_API_KEY", "").strip()),
                "exa_configured": bool(os.getenv("EXA_API_KEY", "").strip()),
            },
        }

    def start(self) -> Negotiation:
        with self.lock:
            if self._started:
                raise ValueError("This demo has already started")
            self._started = True
            if self.use_ai:
                self.state.market_context = fetch_market_context("electronic component manufacturing unit pricing Europe", max_results=2)
            self.buyer.watch_thread(self.state.counterparty_email, self.state.subject)
            self.supplier.watch_thread(self.state.our_email, self.state.subject)
            position = self.state.our_position
            self._send_buyer(
                offer_body(position.unit_price_eur, position.lead_time_days),
                reason="Buyer opens at its target price", tier=None,
            )
            return self.state

    def tick(self) -> None:
        """Poll the expected receiver and handle at most one email per tick."""
        with self.lock:
            if not self._started or self.state.status is not Status.IDLE:
                return
            phase = self.phase
            transport = self.supplier if phase == "supplier" else self.buyer
            needs_poll = not self._pending[phase]
        # Release the state lock while waiting for IMAP, so Stop stays available.
        messages = transport.poll() if needs_poll else []
        with self.lock:
            if self.phase != phase:
                return
            self._pending[phase].extend(messages)
            if self.state.status is not Status.IDLE or not self._pending[phase]:
                return
            message = self._pending[phase].popleft()
            if phase == "supplier":
                self._supplier_reply(message)
            else:
                self._buyer_reply(message)

    def _supplier_reply(self, message: InboundMessage) -> None:
        if self.state.turn_count >= self.state.max_turns:
            self._close("turn_limit", "Demo stopped at the six-message limit.")
            return
        position = extract_position(message.body)
        acceptable = (
            position.unit_price_eur is not None
            and position.unit_price_eur >= self.supplier_floor
            and position.lead_time_days is not None
            and position.lead_time_days >= self.supplier_days
        )
        if acceptable:
            price, days = position.unit_price_eur, position.lead_time_days
        else:
            price, days = self.supplier_ask, self.supplier_days
            self.supplier_ask = max(self.supplier_floor, round(self.supplier_ask - 0.50, 2))
        body = offer_body(price, days, agreed=acceptable, supplier=True)
        if self.use_ai:
            body, self._supplier_model = draft_fixed_offer(body, role="supplier", tier=Tier.ROUTINE, context=self.state.market_context)
        try:
            self.supplier.send(self.state.our_email, self.state.subject, body)
        except Exception:
            self._close("send_error", "Supplier send failed; stopped to avoid duplicate emails.")
            raise
        self.phase = "buyer"

    def _buyer_reply(self, message: InboundMessage) -> None:
        state = self.state
        position = extract_position(message.body)
        state.their_position = position
        inbound = Turn(
            index=state.turn_count, direction="in", subject=message.subject,
            body=message.body, tier=Tier.ROUTINE, model_used=ENGINE,
            reason="Supplier replied through its email inbox",
        )
        state.turns.append(inbound)
        tier = Tier.ROUTINE
        if self.use_ai:
            try:
                tier, reason, _ = classify(state, message.body)
                inbound.tier = tier
                inbound.reason = reason
                inbound.model_used = f"{CLASSIFIER_MODEL} · supplier: {self._supplier_model}"
            except Exception:
                tier = Tier.ESCALATE
                inbound.tier = tier
                inbound.reason = "AI classification failed; review this reply before sending"
                inbound.model_used = "classification unavailable"
        known = position.unit_price_eur is not None and position.lead_time_days is not None
        within = known and state.is_within_mandate(position)
        if within and tier is not Tier.ESCALATE and message.body.startswith("Agreed:"):
            inbound.reason = "Supplier accepted the buyer's offer within the mandate"
            state.our_position = position.model_copy()
            self._close("agreement", f"Demo agreement: {position.unit_price_eur:.2f} EUR per unit at {position.lead_time_days} days.")
            return
        if state.turn_count >= state.max_turns:
            self._close("turn_limit", "Demo stopped at the six-message limit.")
            return

        previous = state.our_position.unit_price_eur or state.mandate.target_price_eur
        ask = position.unit_price_eur if known else previous
        price = round(min(state.mandate.floor_price_eur, (previous + ask) / 2), 2)
        days = min(position.lead_time_days or 21, state.mandate.max_lead_time_days)
        body = offer_body(price, days)
        if not within or tier is Tier.ESCALATE:
            inbound.tier = Tier.ESCALATE
            if not within:
                inbound.reason = "Offer exceeds your price or lead-time limit" if known else "Reply did not include a clear price and lead time"
            state.pending_draft = body
            state.status = Status.AWAITING_APPROVAL
            return
        inbound.reason = "Offer is within the mandate; buyer proposes a midpoint price"
        self._send_buyer(body, reason="Buyer counteroffer within the current mandate", tier=tier)

    def _send_buyer(self, body: str, *, reason: str, tier=Tier.ROUTINE, approved=False) -> None:
        state = self.state
        if state.turn_count >= state.max_turns:
            self._close("turn_limit", "Demo stopped at the six-message limit.")
            return
        model = ENGINE
        if self.use_ai and not approved:
            body, model = draft_fixed_offer(body, role="buyer", tier=tier or Tier.ROUTINE, context=state.market_context)
        try:
            self.buyer.send(state.counterparty_email, state.subject, body)
        except Exception:
            self._close("send_error", "Buyer send failed; stopped to avoid duplicate emails.")
            raise
        state.turns.append(Turn(
            index=state.turn_count, direction="out", subject=state.subject, body=body,
            tier=tier, reason=reason, model_used=model, approved_by_human=approved,
        ))
        state.our_position = extract_position(body)
        state.pending_draft = ""
        state.status = Status.IDLE
        self.phase = "supplier"

    def approve(self, edited: str = "") -> Negotiation:
        with self.lock:
            if self.state.status is Status.AWAITING_APPROVAL:
                body = edited.strip() or self.state.pending_draft
                self._send_buyer(body, reason="Buyer reply approved by a person", tier=Tier.ESCALATE, approved=True)
            return self.state

    def stop(self) -> Negotiation:
        with self.lock:
            self._close("stopped", "Demo stopped by you.")
            return self.state

    def _close(self, outcome: str, note: str) -> None:
        self.outcome = outcome
        self.state.status = Status.CLOSED
        self.state.pending_draft = ""
        self.state.our_position.note = note
