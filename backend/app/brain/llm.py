"""
One place where model calls happen. Person B owns this package.

Both providers speak the OpenAI chat-completions shape, so a single function
covers them: pass a base_url and a model id and it works for either.

If no key is present the call returns a canned string instead of raising. That
keeps Person C unblocked before any credentials exist.
"""

from __future__ import annotations

import json
import os

import httpx

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def complete(
    prompt: str,
    *,
    model: str,
    system: str = "",
    via_openrouter: bool = False,
    json_mode: bool = False,
    timeout: float = 30.0,
) -> str:
    key = os.getenv("OPENROUTER_API_KEY" if via_openrouter else "OPENAI_API_KEY", "")
    if not key:
        return _stub(prompt, json_mode=json_mode)

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload: dict = {"model": model, "messages": messages, "temperature": 0.3}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    url = OPENROUTER_URL if via_openrouter else OPENAI_URL
    headers = {"Authorization": f"Bearer {key}"}
    if via_openrouter:
        headers["HTTP-Referer"] = "https://github.com/port25"
        headers["X-Title"] = "Port 25"

    resp = httpx.post(url, json=payload, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _stub(prompt: str, *, json_mode: bool) -> str:
    if json_mode:
        return json.dumps(
            {"tier": "routine", "reason": "stub mode — no API key set", "confidence": 0.0}
        )
    return "[stub mode — no API key set] " + prompt[:120]
