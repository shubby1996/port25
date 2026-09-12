"""
The negotiation turn. This is the integration seam — Person A and Person B both
land here at 01:40.

One inbound email produces exactly one of:
  - an outbound email sent autonomously (tier 1 or 2), or
  - a pending draft parked for a human (tier 3).

Nothing else. Resist adding branches.
"""

from __future__ import annotations

from .brain import classify, draft_reply, fetch_market_context
from .brain.router import pick_model
from .state import Negotiation, Position, Status, Tier, Turn
from .transport import Transport


def start(negotiation: Negotiation, transport: Transport) -> Negotiation:
    """Send the opening offer and seed market context."""
    negotiation.market_context = fetch_market_context(
        "electronic component contract manufacturing unit pricing Europe 2026"
    )

    body = (
        f"Hello,\n\nWe are sourcing for a Q3 order and can work to "
        f"{negotiation.our_position.unit_price_eur:.2f} EUR per unit at "
        f"{negotiation.our_position.lead_time_days} days. "
        f"Can you meet that?\n\nBest regards"
    )
    _send(negotiation, transport, body, tier=None, model="", reason="opening offer")
    negotiation.status = Status.IDLE
    return negotiation


def handle_inbound(negotiation: Negotiation, transport: Transport, body: str) -> Negotiation:
    """The whole product, in one function."""
    negotiation.turns.append(
        Turn(
            index=negotiation.turn_count,
            direction="in",
            subject=f"Re: {negotiation.subject}",
            body=body,
        )
    )
    negotiation.status = Status.THINKING

    tier, reason, their_position = classify(negotiation, body)
    _merge_position(negotiation.their_position, their_position)

    inbound = negotiation.turns[-1]
    inbound.tier = tier
    inbound.reason = reason

    draft, model_used = draft_reply(negotiation, body, tier)
    inbound.model_used = model_used

    if negotiation.turn_count >= negotiation.max_turns:
        negotiation.status = Status.CLOSED
        return negotiation

    if tier is Tier.ESCALATE:
        negotiation.pending_draft = draft
        negotiation.status = Status.AWAITING_APPROVAL
        return negotiation

    _send(negotiation, transport, draft, tier=tier, model=model_used, reason=reason)
    negotiation.status = Status.IDLE
    return negotiation


def approve(negotiation: Negotiation, transport: Transport, edited: str = "") -> Negotiation:
    """Person C's approve button lands here."""
    if negotiation.status is not Status.AWAITING_APPROVAL:
        return negotiation
    body = edited.strip() or negotiation.pending_draft
    _, _, why = pick_model(Tier.ESCALATE)
    _send(negotiation, transport, body, tier=Tier.ESCALATE, model="", reason=why, approved=True)
    negotiation.pending_draft = ""
    negotiation.status = Status.IDLE
    return negotiation


def reject(negotiation: Negotiation) -> Negotiation:
    negotiation.pending_draft = ""
    negotiation.status = Status.CLOSED
    return negotiation


def _send(
    negotiation: Negotiation,
    transport: Transport,
    body: str,
    *,
    tier: Tier | None,
    model: str,
    reason: str,
    approved: bool = False,
) -> None:
    transport.send(negotiation.counterparty_email, negotiation.subject, body)
    negotiation.turns.append(
        Turn(
            index=negotiation.turn_count,
            direction="out",
            subject=negotiation.subject,
            body=body,
            tier=tier,
            reason=reason,
            model_used=model,
            approved_by_human=approved,
        )
    )


def _merge_position(target: Position, incoming: Position) -> None:
    if incoming.unit_price_eur is not None:
        target.unit_price_eur = incoming.unit_price_eur
    if incoming.lead_time_days is not None:
        target.lead_time_days = incoming.lead_time_days
