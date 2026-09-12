"""
PERSON A — PRIMARY TARGET. Timebox: 00:20 to 00:50.

Goal for the gate: one email travels buyer -> supplier -> buyer with real
Ambiguous coworker identities. If that has not happened by 00:50, stop, set
PORT25_TRANSPORT=smtp in .env, and move on. Do not keep debugging past the gate.

Docs: https://www.ambiguous.ai  (agents provision via one API call, then MCP/CLI)

What you need to fill in:
  1. Provision two coworkers with their own email identities.
  2. send()  -> post an outbound email as our coworker.
  3. poll()  -> read anything new in our coworker's inbox since last call.

Keep poll() non-blocking and idempotent. main.py calls it on a timer.
"""

from __future__ import annotations

import os

from .base import InboundMessage, Transport


class AmbiguousTransport(Transport):
    name = "ambiguous"

    def __init__(self) -> None:
        self.api_key = os.getenv("AMBIGUOUS_API_KEY", "")
        self.our_agent_id = os.getenv("AMBIGUOUS_OUR_AGENT_ID", "")
        self.their_agent_id = os.getenv("AMBIGUOUS_THEIR_AGENT_ID", "")
        self._seen: set[str] = set()

    def send(self, to_addr: str, subject: str, body: str) -> None:
        raise NotImplementedError("Person A: wire Ambiguous send here")

    def poll(self) -> list[InboundMessage]:
        raise NotImplementedError("Person A: wire Ambiguous inbox read here")

    def healthcheck(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "ambiguous: AMBIGUOUS_API_KEY is not set"
        return False, "ambiguous: not implemented yet"
