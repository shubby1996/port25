"""
PERSON B — Exa. Cheap version first, good version only if you are ahead.

Cheap version (about 15 minutes, do this one):
    Called once at thread start. Result goes into negotiation.market_context
    and both agents cite it. No per-turn latency, no per-turn cost.

Good version (only after 02:10):
    Call this again when the classifier returns COMPLEX, so the agent reaches
    for fresh evidence exactly when the stakes rise. That wires Exa into the
    router and is a much better line in the video.
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
