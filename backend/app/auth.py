"""
Auth0 gate for endpoints that trigger a real, consequential external action.

Feature-flagged like the rest of this codebase (llm.py, context.py): if
AUTH0_DOMAIN or AUTH0_AUDIENCE is unset, require_human() is a no-op, so
nothing that already works changes behavior. Set both to actually require a
valid Auth0-issued access token.
"""

from __future__ import annotations

import os

import jwt
from fastapi import Header, HTTPException

_jwks_client: jwt.PyJWKClient | None = None


def _client(domain: str) -> jwt.PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = jwt.PyJWKClient(f"https://{domain}/.well-known/jwks.json")
    return _jwks_client


def require_human(authorization: str | None = Header(default=None)) -> None:
    """FastAPI dependency: 401s unless a valid Auth0 access token is present."""
    domain = os.getenv("AUTH0_DOMAIN", "")
    audience = os.getenv("AUTH0_AUDIENCE", "")
    if not domain or not audience:
        return

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing bearer token")
    token = authorization.removeprefix("Bearer ")

    try:
        signing_key = _client(domain).get_signing_key_from_jwt(token)
        jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=audience,
            issuer=f"https://{domain}/",
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(401, f"Invalid token: {exc}") from exc
