"""
PERSON B — start here at 00:20. You need no transport and no console to build
this: run it against backend/fixtures/inbound_emails.json.

Contract: inbound email text in, strict JSON out.

    {"tier": "routine" | "complex" | "escalate",
     "reason": "one short sentence, shown verbatim in the console",
     "extracted": {"unit_price_eur": float|null, "lead_time_days": int|null}}

The reason string is not debug output. It appears on screen next to the model
name and it is a large part of what the judges read. Write the prompt so it
comes back in plain language, not model-speak.
"""

from __future__ import annotations

import json

from pydantic import ValidationError

from ..state import Negotiation, Position, Tier
from .context import fetch_market_context
from .llm import complete

CLASSIFIER_MODEL = "openai/gpt-4o-mini"

SYSTEM = """You triage inbound negotiation emails for a buyer's autonomous agent.

Return JSON only, with keys: tier, reason, extracted.

tier is one of:
  routine  — the counterparty restated or conceded within familiar terms.
  complex  — they introduced a new argument, condition, or trade-off that needs
             a considered reply.
  escalate — they asked for something structurally new: a contract change, an
             exclusivity or penalty clause, a change to payment terms or
             liability/legal terms, or a price the buyer cannot accept. This
             applies even if they also moved price or lead time in the same
             email — a legal or structural change escalates regardless of
             what else is in the message.

reason: one short plain sentence a busy person can read at a glance.
extracted: the offered numeric price in the negotiation currency and any lead time in days they named,
           or null if they named none.
"""


def classify(negotiation: Negotiation, inbound_body: str) -> tuple[Tier, str, Position]:
    prompt = (
        f"We are buying {negotiation.quantity} metric tonnes of {negotiation.commodity}. "
        f"Our maximum purchase price is {negotiation.mandate.floor_price_eur} {negotiation.currency} per {negotiation.price_unit} "
        f"and max {negotiation.mandate.max_lead_time_days} days lead time.\n"
        f"Buyer region: {negotiation.buyer_region}; supplier region: {negotiation.supplier_region}.\n"
        f"Our current offer: {negotiation.our_position.model_dump()}\n\n"
        f"Their email:\n{inbound_body}"
    )
    raw = complete(
        prompt, model=CLASSIFIER_MODEL, system=SYSTEM, json_mode=True, via_openrouter=True
    )

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return Tier.ESCALATE, "Classifier returned unparseable output", Position()

    if not isinstance(data, dict) or not isinstance(data.get("extracted") or {}, dict):
        return Tier.ESCALATE, "Classifier returned an invalid result; review the reply", Position()
    extracted = data.get("extracted") or {}
    try:
        position = Position(
            unit_price_eur=extracted.get("unit_price_eur"),
            lead_time_days=extracted.get("lead_time_days"),
        )
    except ValidationError:
        return Tier.ESCALATE, "Classifier could not read the offer terms; review the reply", Position()

    try:
        tier = Tier(data.get("tier", "escalate"))
    except ValueError:
        tier = Tier.ESCALATE

    reason = str(data.get("reason", "")).strip() or "No reason given"

    # The mandate check is code, not a model decision. A model may not talk
    # itself into exceeding the mandate, so this override is one-directional:
    # it can raise the tier to ESCALATE, never lower it.
    if not negotiation.is_within_mandate(position):
        tier = Tier.ESCALATE
        reason = f"{reason} — and it exceeds your price or lead-time limit"

    # Good version of Exa grounding: refresh market evidence exactly when the
    # stakes rise, not on every turn. A failed/empty fetch never clobbers
    # context we already have (fetch_market_context swallows its own errors
    # and returns "").
    if tier is Tier.COMPLEX:
        fresh_context = fetch_market_context(
            f"{negotiation.subject} — market pricing benchmark for a unit price "
            f"near {position.unit_price_eur} {negotiation.currency}" if position.unit_price_eur
            else f"{negotiation.subject} — market pricing benchmark"
        )
        if fresh_context:
            negotiation.market_context = fresh_context

    return tier, reason, position
