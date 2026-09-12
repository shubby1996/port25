"""
THE CONTRACT.

Everyone reads this file before writing anything else. If you need to change a
field, say so out loud first — all three workstreams touch this object and a
silent rename at 01:40 costs more than it saves.

Person A (transport) writes:  their_position, turns[].direction == "in"
Person B (brain) writes:      tier, reason, model_used, pending_draft, our_position
Person C (console) writes:    mandate, and flips status via approve/reject
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Tier(str, Enum):
    """What the classifier decided about this inbound message."""

    ROUTINE = "routine"          # tier 1 — fast model, send without asking
    COMPLEX = "complex"          # tier 2 — stronger model via OpenRouter, still autonomous
    ESCALATE = "escalate"        # tier 3 — outside mandate, a human decides


class Status(str, Enum):
    IDLE = "idle"                        # waiting for the counterparty
    THINKING = "thinking"                # classifier / drafting in flight
    AWAITING_APPROVAL = "awaiting"       # tier 3 — console shows approve / reject
    CLOSED = "closed"                    # deal agreed, walked away, or turn cap hit


class Position(BaseModel):
    """Whatever is actually being negotiated. Keep it to two or three numbers.

    The demo scenario is a supplier quoting on a component order, because it
    needs no domain knowledge to follow. Swap the fields if you swap scenario,
    but swap them before 00:20.
    """

    unit_price_eur: float | None = None
    lead_time_days: int | None = None
    note: str = ""


class Mandate(BaseModel):
    """The authority the agent is operating under. The console edits this live.

    floor is the walk-away. The agent may never send a reply that accepts worse
    than floor — that is what makes tier 3 fire.
    """

    floor_price_eur: float
    target_price_eur: float
    max_lead_time_days: int


class Turn(BaseModel):
    """One email, in or out. This list is the audit trail and the console feed."""

    index: int
    direction: Literal["in", "out"]
    subject: str
    body: str
    at: float = Field(default_factory=time.time)

    # Populated by Person B for inbound turns only.
    tier: Tier | None = None
    reason: str = ""
    model_used: str = ""
    approved_by_human: bool = False


class Negotiation(BaseModel):
    """The whole world. One instance per email thread."""

    thread_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    subject: str = "Q3 component order — pricing"

    counterparty_email: str = ""
    our_email: str = ""

    # Scenario metadata. The legacy numeric field names are retained so the
    # transport and classifier contract stays stable while the visible price
    # basis can represent a commodity tonne instead of a manufactured unit.
    commodity: str = "Electronic components"
    quantity: int = 1
    price_unit: str = "unit"
    currency: str = "EUR"
    buyer_region: str = "Europe"
    supplier_region: str = "Europe"

    mandate: Mandate
    our_position: Position = Field(default_factory=Position)
    their_position: Position = Field(default_factory=Position)

    # Set once at thread start by Person B from Exa. Both agents cite it.
    market_context: str = ""

    turns: list[Turn] = Field(default_factory=list)
    status: Status = Status.IDLE

    # The reply the agent wants to send but hasn't. Non-empty only when
    # status is AWAITING_APPROVAL.
    pending_draft: str = ""

    # Hard stop. Two polite agents will exchange emails until the credits run
    # out. Do not raise this for the demo.
    max_turns: int = 6

    @property
    def turn_count(self) -> int:
        return len(self.turns)

    @property
    def last_inbound(self) -> Turn | None:
        for turn in reversed(self.turns):
            if turn.direction == "in":
                return turn
        return None

    def is_within_mandate(self, position: Position) -> bool:
        """The one rule that cannot be delegated to a model.

        Person B's classifier proposes a tier; this function overrides it. A
        model may not talk itself into exceeding the mandate.
        """
        if position.unit_price_eur is not None and position.unit_price_eur > self.mandate.floor_price_eur:
            return False
        if (
            position.lead_time_days is not None
            and position.lead_time_days > self.mandate.max_lead_time_days
        ):
            return False
        return True


def new_negotiation(**overrides) -> Negotiation:
    """Demo defaults. Person A calls this when a thread starts."""
    defaults = dict(
        mandate=Mandate(
            floor_price_eur=12.50,
            target_price_eur=10.00,
            max_lead_time_days=30,
        ),
        our_position=Position(
            unit_price_eur=10.00,
            lead_time_days=21,
            note="opening offer",
        ),
        our_email="buyer@port25.demo",
        counterparty_email="supplier@port25.demo",
    )
    defaults.update(overrides)
    return Negotiation(**defaults)
