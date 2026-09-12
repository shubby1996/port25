"""
PERSON B — Exa.

Cheap version: called once at thread start by loop.start(), result goes into
negotiation.market_context, both agents cite it.

Good version: classifier.classify() calls this again whenever it decides a
turn is COMPLEX, replacing negotiation.market_context with fresh evidence
right as the stakes rise. A failed or empty fetch never overwrites context we
already have — see the guard in classify().
"""

from __future__ import annotations

import os

import httpx

EXA_URL = "https://api.exa.ai/search"


def fetch_market_context(query: str, *, max_results: int = 3) -> str:
    key = os.getenv("EXA_API_KEY", "")
    if not key:
        return ""

    try:
        resp = httpx.post(
            EXA_URL,
            json={
                "query": query,
                "numResults": max_results,
                "contents": {"text": {"maxCharacters": 400}},
            },
            headers={"x-api-key": key},
            timeout=20.0,
        )
        resp.raise_for_status()
    except Exception:
        # Never let grounding break the negotiation. An ungrounded agent still
        # demos; a crashed one does not.
        return ""

    lines = []
    for item in resp.json().get("results", [])[:max_results]:
        title = item.get("title", "").strip()
        text = (item.get("text") or "").strip().replace("\n", " ")[:300]
        if title:
            lines.append(f"- {title}: {text}")
    return "\n".join(lines)
