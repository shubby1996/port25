"""
Person A owns this package.

One interface, three implementations. You switch between them with the
PORT25_TRANSPORT env var and nothing else in the codebase changes. That switch
is the whole point — at 00:50 you may need to abandon Ambiguous and you should
be able to do it by editing .env, not by editing the agent.

    mock       always works, no credentials, no network. Use this until 00:50.
    ambiguous  primary. Real coworker identities with real inboxes.
    smtp       fallback. Two throwaway Gmail accounts. Still real email.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod

from pydantic import BaseModel


class InboundMessage(BaseModel):
    from_addr: str
    subject: str
    body: str


class Transport(ABC):
    """Send an email, and collect anything that has arrived since last asked."""

    name: str = "base"

    @abstractmethod
    def send(self, to_addr: str, subject: str, body: str) -> None: ...

    @abstractmethod
    def poll(self) -> list[InboundMessage]:
        """Non-blocking. Returns [] when nothing new has arrived."""

    def healthcheck(self) -> tuple[bool, str]:
        """Called by /health. Person A: make this actually prove credentials work.

        A transport that reports healthy but cannot send is worse than one that
        reports broken, because you will find out at 02:30 instead of 00:35.
        """
        return True, f"{self.name}: no healthcheck implemented"


def get_transport() -> Transport:
    choice = os.getenv("PORT25_TRANSPORT", "mock").lower()

    if choice == "ambiguous":
        from .ambiguous import AmbiguousTransport

        return AmbiguousTransport()
    if choice == "smtp":
        from .smtp_imap import SmtpImapTransport

        return SmtpImapTransport()

    from .mock import MockTransport

    return MockTransport()
