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

import httpx

from .base import InboundMessage, Transport

PROVISION_PATH = "/api/admin/users/provision-agent"


def provision_coworker(
    display_name: str, *, role: str = "member", focus_areas: list[str] | None = None
) -> dict:
    """Create a real Ambiguous AI coworker with its own workspace email identity.

    Endpoint and auth format confirmed against ambiguous.ai/agents:
        POST {AMBIGUOUS_API_BASE}/api/admin/users/provision-agent
        Authorization: Bearer <AMBIGUOUS_API_KEY>

    AMBIGUOUS_API_BASE is not published anywhere public — get it from your
    Ambiguous workspace's API settings rather than guessing it here. Fails
    loudly (RuntimeError) if config is missing, rather than silently hitting
    a made-up domain.
    """
    api_key = os.getenv("AMBIGUOUS_API_KEY", "")
    base = os.getenv("AMBIGUOUS_API_BASE", "")
    if not api_key or not base:
        raise RuntimeError(
            "Set AMBIGUOUS_API_KEY and AMBIGUOUS_API_BASE to provision a coworker"
        )

    resp = httpx.post(
        f"{base.rstrip('/')}{PROVISION_PATH}",
        json={"display_name": display_name, "role": role, "focus_areas": focus_areas or []},
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=20.0,
    )
    resp.raise_for_status()
    return resp.json()


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
