"""Two owned inboxes negotiating a demo order using explicit pricing rules.

Each side learns the other side's offer only by receiving its email. Optional
OpenRouter drafting and classification supplement the fixed demo pricing rules.
"""

from __future__ import annotations

import os
import re
import threading
from collections import deque
from dataclasses import dataclass

from .state import Negotiation, Position, Status, Tier, Turn, new_negotiation
from .brain.classifier import classify, CLASSIFIER_MODEL
from .brain.context import MarketBrief, research_commodity_market
from .brain.demo_drafting import draft_fixed_offer
from .transport import InboundMessage
from .transport.smtp_imap import SmtpImapTransport

ENGINE = "demo rules"
FOOTER = "\n\nPort 25 demo only; no real order is being placed."
REGIONS = ("Europe", "North America", "East Asia")


@dataclass(frozen=True)
class CommoditySpec:
    id: str
    label: str
    quantity: int
    fallback_benchmark: float


COMMODITIES = {
    spec.id: spec for spec in (
        CommoditySpec("aluminium", "Primary aluminium", 100, 3_400),
        CommoditySpec("copper", "Copper cathode", 50, 10_500),
        CommoditySpec("steel", "Hot-rolled steel coil", 500, 750),
    )
}


def enabled() -> bool:
    return os.getenv("PORT25_DEMO_PAIR", "false").lower() in ("1", "true", "yes")


def setup_options() -> dict:
    primary = SmtpImapTransport()
    secondary = SmtpImapTransport(counterparty=True)
    return {
        "accounts": [
            {"id": "primary", "email": primary.address},
            {"id": "secondary", "email": secondary.address},
        ],
        "commodities": [
            {"id": item.id, "label": item.label, "quantity": item.quantity, "price_unit": "metric tonne"}
            for item in COMMODITIES.values()
        ],
        "regions": list(REGIONS),
        "defaults": {
            "buyer_account": "primary", "supplier_account": "secondary",
            "commodity": "aluminium", "buyer_region": "Europe", "supplier_region": "North America",
        },
    }


def from_environment(
    *,
    buyer_account: str = "primary",
    supplier_account: str = "secondary",
    commodity: str = "aluminium",
    buyer_region: str = "Europe",
    supplier_region: str = "North America",
) -> DemoPair:
    accounts = {
        "primary": SmtpImapTransport(),
        "secondary": SmtpImapTransport(counterparty=True),
    }
    if buyer_account not in accounts or supplier_account not in accounts:
        raise ValueError("Buyer and seller must be selected from the configured inboxes")
    if buyer_account == supplier_account:
        raise ValueError("Buyer and seller must use two different inboxes")
    if commodity not in COMMODITIES:
        raise ValueError("Select a supported commodity")
    if buyer_region not in REGIONS or supplier_region not in REGIONS:
        raise ValueError("Select a supported buyer and seller region")
    buyer = accounts[buyer_account]
    supplier = accounts[supplier_account]
    # Validate both accounts before either account can send an email.
    buyer.validate_config()
    supplier.validate_config()
    if buyer.address.casefold() == supplier.address.casefold():
        raise ValueError("OUR_EMAIL and COUNTERPARTY_EMAIL must be two different inboxes")
    spec = COMMODITIES[commodity]
    state = new_negotiation(
        our_email=buyer.address,
        counterparty_email=supplier.address,
        commodity=spec.label,
        quantity=spec.quantity,
        price_unit="metric tonne",
        buyer_region=buyer_region,
        supplier_region=supplier_region,
    )
    state.subject = f"Port 25: {spec.label} supply negotiation [port25-{state.thread_id}]"
    use_ai = os.getenv("PORT25_DEMO_AI", "false").lower() in ("1", "true", "yes")
    if use_ai and not os.getenv("OPENROUTER_API_KEY", "").strip():
        raise ValueError("PORT25_DEMO_AI requires OPENROUTER_API_KEY")
    return DemoPair(
        state, buyer, supplier, spec=spec, use_ai=use_ai,
        account_options=[{"id": key, "email": transport.address} for key, transport in accounts.items()],
    )


def extract_position(body: str) -> Position:
    # Our agents send plain text. Ignore quoted history if a human joins in.
    text = re.split(r"(?im)^\s*(?:>|On .+wrote:|Am .+schrieb)", body, maxsplit=1)[0]
    price = re.search(r"\b(\d+(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:,\d{1,2})?)\s*(?:EUR|USD)\b", text, re.I)
    lead = re.search(r"\b(\d+)\s*days?\b", text, re.I)
    return Position(
        unit_price_eur=_parse_price(price.group(1)) if price else None,
        lead_time_days=int(lead.group(1)) if lead else None,
    )


def offer_body(
    price: float,
    days: int,
    *,
    agreed: bool = False,
    supplier: bool = False,
    commodity: str = "components",
    quantity: int = 1,
    price_unit: str = "unit",
    currency: str = "EUR",
    market_note: str = "",
) -> str:
    opening = "Agreed" if agreed else ("We can supply" if supplier else "We can offer")
    volume = f" for {quantity:,} metric tonnes of {commodity}" if price_unit == "metric tonne" else ""
    evidence = f"\nMarket reference: {market_note}" if market_note else ""
    return f"{opening}: {price:.2f} {currency} per {price_unit}{volume} at {days} days lead time.{evidence}" + FOOTER


class DemoPair:
    def __init__(
        self,
        state: Negotiation,
        buyer,
        supplier,
        *,
        spec: CommoditySpec | None = None,
        use_ai: bool = False,
        account_options: list[dict] | None = None,
    ) -> None:
        self.state = state
        self.buyer = buyer
        self.supplier = supplier
        self.use_ai = use_ai
        self.spec = spec or CommoditySpec("components", "Electronic components", 1, 10)
        self.account_options = account_options or [
            {"id": "primary", "email": buyer.address},
            {"id": "secondary", "email": supplier.address},
        ]
        self.engine = "OpenRouter drafting + bounded demo policy" if use_ai else ENGINE
        self._supplier_model = ENGINE
        self.lock = threading.RLock()
        self.phase = "supplier"
        self.market_brief = MarketBrief(
            benchmark_price_per_metric_tonne=self.spec.fallback_benchmark,
            currency="USD",
            change_pct_30d=0,
            change_period="not researched",
            buyer_region_change_pct=0,
            supplier_region_change_pct=0,
            buyer_region_adjustment_pct=0,
            supplier_region_adjustment_pct=2,
            summary="Demo benchmark before market research.",
            used_fallback=True,
        )
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
            "setup": {
                "accounts": self.account_options,
                "commodities": [
                    {"id": item.id, "label": item.label, "quantity": item.quantity, "price_unit": "metric tonne"}
                    for item in COMMODITIES.values()
                ],
                "regions": list(REGIONS),
                "defaults": {
                    "buyer_account": "primary", "supplier_account": "secondary",
                    "commodity": "aluminium", "buyer_region": "Europe", "supplier_region": "North America",
                },
            },
        }

    def start(self) -> Negotiation:
        with self.lock:
            if self._started:
                raise ValueError("This demo has already started")
            self._started = True
            if self.use_ai:
                self.market_brief = research_commodity_market(
                    self.spec.label,
                    self.state.buyer_region,
                    self.state.supplier_region,
                    fallback_benchmark=self.spec.fallback_benchmark,
                )
            self._apply_market_brief()
            self.buyer.watch_thread(self.state.counterparty_email, self.state.subject)
            self.supplier.watch_thread(self.state.our_email, self.state.subject)
            position = self.state.our_position
            self._send_buyer(
                self._offer(position.unit_price_eur, position.lead_time_days),
                reason=f"Buyer opens from the Exa benchmark for {self.state.buyer_region}", tier=None,
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
            self.supplier_ask = _round_market(max(self.supplier_floor, (self.supplier_ask + self.supplier_floor) / 2))
        body = self._offer(price, days, agreed=acceptable, supplier=True)
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
            self._close(
                "agreement",
                f"Demo agreement: {position.unit_price_eur:,.2f} {state.currency} per {state.price_unit} "
                f"for {state.quantity:,} metric tonnes at {position.lead_time_days} days.",
            )
            return
        if state.turn_count >= state.max_turns:
            self._close("turn_limit", "Demo stopped at the six-message limit.")
            return

        previous = state.our_position.unit_price_eur or state.mandate.target_price_eur
        ask = position.unit_price_eur if known else previous
        # Public regional evidence gives the seller's market more weight than a
        # simple midpoint, while the code-enforced ceiling remains absolute.
        price = _round_market(min(state.mandate.floor_price_eur, previous + (ask - previous) * 0.65))
        days = min(position.lead_time_days or 21, state.mandate.max_lead_time_days)
        body = self._offer(price, days)
        if not within or tier is Tier.ESCALATE:
            inbound.tier = Tier.ESCALATE
            if not within:
                inbound.reason = "Offer exceeds your price or lead-time limit" if known else "Reply did not include a clear price and lead time"
            state.pending_draft = body
            state.status = Status.AWAITING_APPROVAL
            return
        inbound.reason = "Offer is within the mandate; buyer weights the seller's regional market signal"
        self._send_buyer(body, reason="Buyer counteroffer uses the Exa regional price gap", tier=tier)

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

    def _apply_market_brief(self) -> None:
        """Translate public evidence into bounded, overlapping demo mandates."""
        brief = self.market_brief
        buyer_adjustment = max(-8, min(12, brief.buyer_region_adjustment_pct))
        supplier_adjustment = max(-8, min(12, brief.supplier_region_adjustment_pct))
        benchmark = brief.benchmark_price_per_metric_tonne
        target = _round_market(benchmark * (1 + buyer_adjustment / 100))
        self.supplier_floor = _round_market(benchmark * (1 + supplier_adjustment / 100))
        regional_movement = max(abs(brief.change_pct_30d), abs(brief.buyer_region_change_pct), abs(brief.supplier_region_change_pct))
        volatility = max(0.05, min(0.10, (regional_movement + 3) / 100))
        ceiling = _round_market(max(target * (1 + volatility), self.supplier_floor * 1.07))
        ask_margin = max(0.03, min(0.06, (max(0, brief.supplier_region_change_pct, brief.change_pct_30d) + 3) / 100))
        self.supplier_ask = _round_market(self.supplier_floor * (1 + ask_margin))
        self.state.mandate.floor_price_eur = ceiling
        self.state.mandate.target_price_eur = target
        self.state.currency = brief.currency
        self.state.our_position = Position(unit_price_eur=target, lead_time_days=21, note="Exa-informed opening target")
        self.state.market_context = brief.display(
            commodity=self.spec.label,
            buyer_region=self.state.buyer_region,
            supplier_region=self.state.supplier_region,
        )

    def _offer(self, price: float, days: int, *, agreed: bool = False, supplier: bool = False) -> str:
        brief = self.market_brief
        note = (
            f"Exa benchmark {brief.currency} {brief.benchmark_price_per_metric_tonne:,.0f}/t, "
            f"{self.state.buyer_region} move {brief.buyer_region_change_pct:+.1f}% / adjustment {brief.buyer_region_adjustment_pct:+.1f}%; "
            f"{self.state.supplier_region} move {brief.supplier_region_change_pct:+.1f}% / adjustment {brief.supplier_region_adjustment_pct:+.1f}%"
        )
        return offer_body(
            price, days, agreed=agreed, supplier=supplier,
            commodity=self.state.commodity, quantity=self.state.quantity,
            price_unit=self.state.price_unit, currency=self.state.currency, market_note=note,
        )


def _round_market(value: float) -> float:
    return round(value / 5) * 5.0


def _parse_price(value: str) -> float:
    if "," in value and "." not in value and len(value.rsplit(",", 1)[1]) <= 2:
        return float(value.replace(",", "."))
    return float(value.replace(",", ""))
