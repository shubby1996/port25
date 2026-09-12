"""
Smoke test. Runs a whole negotiation against the mock transport, no keys needed.

    python run_demo.py

If this prints a full thread, the loop is sound and any failure you hit later is
in transport, routing credentials, or the console — not in the core.
"""

from __future__ import annotations

from app import loop
from app.state import Status, new_negotiation
from app.transport.mock import MockTransport


def main() -> None:
    transport = MockTransport()
    negotiation = loop.start(new_negotiation(), transport)

    for _ in range(negotiation.max_turns):
        inbound = transport.poll()
        if not inbound:
            break
        loop.handle_inbound(negotiation, transport, inbound[0].body)
        if negotiation.status is Status.AWAITING_APPROVAL:
            break

    for turn in negotiation.turns:
        arrow = "->" if turn.direction == "out" else "<-"
        tag = f"[{turn.tier.value}]" if turn.tier else ""
        print(f"{arrow} {tag} {turn.body[:110]}")
        if turn.reason:
            print(f"     why: {turn.reason}")

    print(f"\nstatus: {negotiation.status.value}")
    if negotiation.pending_draft:
        print(f"awaiting approval:\n{negotiation.pending_draft[:200]}")


if __name__ == "__main__":
    main()
