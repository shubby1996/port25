"""
Auth0 gate self-check. Run: python test_auth.py

Confirms the feature-flag behavior in app/auth.py: unconfigured means no-op
(everything that works today keeps working), configured means a missing or
invalid token is rejected. Also confirms provision_coworker fails loudly
instead of guessing a base URL when config is missing.
"""

from __future__ import annotations

import os

from fastapi import HTTPException

from app.auth import require_human
from app.transport.ambiguous import provision_coworker


def test_noop_when_unconfigured() -> None:
    os.environ.pop("AUTH0_DOMAIN", None)
    os.environ.pop("AUTH0_AUDIENCE", None)
    require_human(authorization=None)  # must not raise


def test_rejects_missing_token_when_configured() -> None:
    os.environ["AUTH0_DOMAIN"] = "example.auth0.com"
    os.environ["AUTH0_AUDIENCE"] = "https://port25/api"
    try:
        try:
            require_human(authorization=None)
        except HTTPException as exc:
            assert exc.status_code == 401
        else:
            raise AssertionError("expected HTTPException for missing token")
    finally:
        del os.environ["AUTH0_DOMAIN"]
        del os.environ["AUTH0_AUDIENCE"]


def test_rejects_garbage_token_when_configured() -> None:
    os.environ["AUTH0_DOMAIN"] = "example.auth0.com"
    os.environ["AUTH0_AUDIENCE"] = "https://port25/api"
    try:
        try:
            require_human(authorization="Bearer not-a-real-jwt")
        except HTTPException as exc:
            assert exc.status_code == 401
        else:
            raise AssertionError("expected HTTPException for a garbage token")
    finally:
        del os.environ["AUTH0_DOMAIN"]
        del os.environ["AUTH0_AUDIENCE"]


def test_provision_fails_loudly_without_config() -> None:
    os.environ.pop("AMBIGUOUS_API_KEY", None)
    os.environ.pop("AMBIGUOUS_API_BASE", None)
    try:
        provision_coworker("Test Coworker")
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected RuntimeError without AMBIGUOUS_API_KEY/BASE")


if __name__ == "__main__":
    test_noop_when_unconfigured()
    test_rejects_missing_token_when_configured()
    test_rejects_garbage_token_when_configured()
    test_provision_fails_loudly_without_config()
    print("PASS")
