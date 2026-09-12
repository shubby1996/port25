"""
PERSON B — the routing table. This is deliberately a dict, not a model decision.

You want the demo to be deterministic. A model choosing its own model is a
second source of variance you cannot debug at 02:20.

The pitch line: we route on consequence, not on complexity. A routine turn gets
a fast cheap model and sends itself. A contentious one escalates to a stronger
model. Anything outside the mandate escalates to a person. The same ladder
decides both which model runs and whether a human gets interrupted.
"""

from __future__ import annotations

from ..state import Tier

# (model id, goes through OpenRouter, why — this string is shown on screen)
ROUTING_TABLE: dict[Tier, tuple[str, bool, str]] = {
    Tier.ROUTINE: (
        "gpt-4o-mini",
        False,
        "Routine restatement of a known position — fast model is enough",
    ),
    Tier.COMPLEX: (
        "anthropic/claude-sonnet-4.5",
        True,
        "Counterparty introduced new terms — routed to a stronger model",
    ),
    Tier.ESCALATE: (
        "anthropic/claude-sonnet-4.5",
        True,
        "Outside mandate — drafted for a human to approve, not sent",
    ),
}


def pick_model(tier: Tier) -> tuple[str, bool, str]:
    return ROUTING_TABLE[tier]
