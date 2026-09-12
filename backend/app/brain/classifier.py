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

from ..state import Negotiation, Position, Tier
from .llm import complete

CLASSIFIER_MODEL = "gpt-4o-mini"

SYSTEM = """You triage inbound negotiation emails for a buyer's autonomous agent.

Return JSON only, with keys: tier, reason, extracted.

tier is one of:
  routine  — the counterparty restated or conceded within familiar terms.
  complex  — they introduced a new argument, condition, or trade-off that needs
             a considered reply.
  escalate — they asked for something structurally new: a contract change, an
             exclusivity or penalty clause, a legal term, or a price the buyer
             cannot accept.

reason: one short plain sentence a busy person can read at a glance.
extracted: any price in EUR per unit and any lead time in days they named,
           or null if they named none.
"""


def classify(negotiation: Negotiation, inbound_body: str) -> tuple[Tier, str, Position]:
    prompt = (
        f"Our mandate floor is {negotiation.mandate.floor_price_eur} EUR per unit "
        f"and max {negotiation.mandate.max_lead_time_days} days lead time.\n"
        f"Our current offer: {negotiation.our_position.model_dump()}\n\n"
        f"Their email:\n{inbound_body}"
    )
    raw = complete(prompt, model=CLASSIFIER_MODEL, system=SYSTEM, json_mode=True)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return Tier.ESCALATE, "Classifier returned unparseable output", Position()

    extracted = data.get("extracted") or {}
    position = Position(
        unit_price_eur=extracted.get("unit_price_eur"),
        lead_time_days=extracted.get("lead_time_days"),
    )

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
        reason = f"{reason} — and it breaches the mandate floor"

    return tier, reason, position
