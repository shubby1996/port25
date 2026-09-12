"""PERSON B — turns state into an email a human would plausibly have written."""

from __future__ import annotations

from ..state import Negotiation, Tier
from .llm import complete
from .router import pick_model

SYSTEM = """You are a procurement agent writing a short business email.

Rules:
- Four sentences maximum. Real buyers do not write essays.
- Name a specific number. Never say "competitive pricing".
- If market evidence is supplied, cite it once, naturally.
- Never accept worse than the mandate floor. If their offer is worse, counter.
- Plain sign-off. No pleasantries beyond one line.
"""


def draft_reply(negotiation: Negotiation, inbound_body: str, tier: Tier) -> tuple[str, str]:
    """Returns (body, model_used)."""
    model, via_openrouter, _ = pick_model(tier)

    context_block = (
        f"\nMarket evidence you may cite:\n{negotiation.market_context}\n"
        if negotiation.market_context
        else ""
    )

    prompt = (
        f"Mandate: floor {negotiation.mandate.floor_price_eur} EUR/unit, "
        f"target {negotiation.mandate.target_price_eur} EUR/unit, "
        f"max {negotiation.mandate.max_lead_time_days} days.\n"
        f"Our last position: {negotiation.our_position.model_dump()}\n"
        f"Their last position: {negotiation.their_position.model_dump()}\n"
        f"{context_block}\n"
        f"Their email:\n{inbound_body}\n\n"
        f"Write our reply."
    )

    body = complete(prompt, model=model, system=SYSTEM, via_openrouter=via_openrouter)
    return body.strip(), model
