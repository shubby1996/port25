"""
In-memory transport. No credentials, no network, no excuses.

This exists so Person B and Person C are never blocked on Person A. It plays a
scripted counterparty so the whole loop runs end to end from minute one.

Do not delete it when the real transport lands — it is also your demo fallback
if the venue wifi dies during recording.
"""

from __future__ import annotations

from .base import InboundMessage, Transport

# A counterparty that concedes slowly, then asks for something out of mandate.
# The last reply is the one that must trigger tier 3.
SCRIPTED_REPLIES = [
    "Thanks for the enquiry. We can do 15.80 EUR per unit at 28 days lead time. "
    "That is our standard rate for this volume.",

    "We have some room on price. 14.20 EUR at 28 days is achievable if the order "
    "is confirmed this quarter. Lead time is hard to move, our line is full.",

    "13.40 EUR is the best we can do at 28 days. If you need it faster we can "
    "look at 25 days but that carries an expedite charge.",

    "We can agree 12.90 EUR only if you commit to a 24 month exclusive supply "
    "agreement and waive the late delivery penalty clause. Otherwise 13.40 stands.",
]


class MockTransport(Transport):
    name = "mock"

    def __init__(self) -> None:
        self._sent: list[tuple[str, str, str]] = []
        self._reply_index = 0
        self._pending: list[InboundMessage] = []

    def send(self, to_addr: str, subject: str, body: str) -> None:
        self._sent.append((to_addr, subject, body))
        if self._reply_index < len(SCRIPTED_REPLIES):
            self._pending.append(
                InboundMessage(
                    from_addr=to_addr,
                    subject=f"Re: {subject}",
                    body=SCRIPTED_REPLIES[self._reply_index],
                )
            )
            self._reply_index += 1

    def poll(self) -> list[InboundMessage]:
        out, self._pending = self._pending, []
        return out

    def healthcheck(self) -> tuple[bool, str]:
        return True, "mock: always healthy, sends nothing"

    @property
    def sent(self) -> list[tuple[str, str, str]]:
        return list(self._sent)
