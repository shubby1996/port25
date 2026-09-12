"""
FastAPI service. Person C talks to this; Person A drives the poller.

    uvicorn app.main:app --reload --port 8000

Endpoints are deliberately few. If you are adding a fifth, ask whether the
console really needs it before 02:30.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import threading
from collections import deque
from typing import Any

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import demo_pair, loop
from .auth import require_human
from .state import Mandate, Negotiation, Status, new_negotiation
from .transport import get_transport
from .transport.ambiguous import provision_coworker
from .transport.smtp_imap import validate_address

app = FastAPI(title="Port 25")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

transport = get_transport()

# One thread at a time. Multi-thread support is not a hackathon problem.
NEGOTIATION: Negotiation | None = None
DEMO_PAIR: demo_pair.DemoPair | None = None
CREATE_LOCK = threading.Lock()
POLL_SECONDS = 3.0


class ThreadPayload(BaseModel):
    thread_id: str | None = None


class MandatePatch(ThreadPayload):
    floor_price_eur: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    target_price_eur: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    max_lead_time_days: int | None = Field(default=None, gt=0)


class ApprovePayload(ThreadPayload):
    edited_body: str = ""


class ProvisionPayload(BaseModel):
    display_name: str
    role: str = "member"


@app.get("/health")
def health() -> dict[str, Any]:
    if demo_pair.enabled():
        if transport.name != "smtp":
            return {"transport": transport.name, "ok": False, "mode": "demo_pair", "detail": "Two-inbox demo requires PORT25_TRANSPORT=smtp"}
        try:
            return demo_pair.from_environment().healthcheck()
        except ValueError as exc:
            return {"transport": "smtp", "ok": False, "mode": "demo_pair", "detail": str(exc)}
    ok, detail = transport.healthcheck()
    return {"transport": transport.name, "ok": ok, "detail": detail}


@app.post("/negotiation")
def create() -> Negotiation:
    with CREATE_LOCK:
        return _create()


def _create() -> Negotiation:
    global NEGOTIATION, DEMO_PAIR
    if DEMO_PAIR is not None and DEMO_PAIR.state.status is not Status.CLOSED:
        raise HTTPException(409, "Stop the current two-inbox demo before starting another")
    if demo_pair.enabled():
        if transport.name != "smtp":
            raise HTTPException(503, "Two-inbox demo requires PORT25_TRANSPORT=smtp")
        try:
            pair = demo_pair.from_environment()
        except ValueError as exc:
            raise HTTPException(503, str(exc)) from exc
        health = pair.healthcheck()
        if not health["ok"]:
            failed = [f"{role}: {info['detail']}" for role, info in health["accounts"].items() if not info["ok"]]
            raise HTTPException(503, "; ".join(failed))
        try:
            pair.start()
        except Exception as exc:
            raise HTTPException(502, "Opening email failed; check the buyer inbox before starting again") from exc
        NEGOTIATION = pair.state
        DEMO_PAIR = pair
        return NEGOTIATION
    DEMO_PAIR = None
    negotiation = new_negotiation()
    if transport.name == "smtp":
        our_email = os.getenv("OUR_EMAIL", "").strip()
        counterparty_email = os.getenv("COUNTERPARTY_EMAIL", "").strip()
        try:
            validate_address(our_email, "OUR_EMAIL")
            validate_address(counterparty_email, "COUNTERPARTY_EMAIL")
            if our_email.casefold() == counterparty_email.casefold():
                raise ValueError("COUNTERPARTY_EMAIL must be a second inbox")
        except ValueError as exc:
            raise HTTPException(503, str(exc)) from exc
        negotiation.our_email = our_email
        negotiation.counterparty_email = counterparty_email
        # A new run must not consume replies to an earlier negotiation.
        negotiation.subject += f" [port25-{negotiation.thread_id}]"
    NEGOTIATION = loop.start(negotiation, transport)
    return NEGOTIATION


@app.get("/negotiation")
def read() -> Negotiation:
    if NEGOTIATION is None:
        raise HTTPException(404, "No negotiation yet — POST /negotiation first")
    return NEGOTIATION


@app.patch("/negotiation/mandate")
def patch_mandate(patch: MandatePatch) -> Negotiation:
    """The slider. This is the demo beat — keep it fast and never 500."""
    if NEGOTIATION is None:
        raise HTTPException(404, "No negotiation yet")
    _check_thread(patch.thread_id)
    guard = DEMO_PAIR.lock if DEMO_PAIR is not None else contextlib.nullcontext()
    with guard:
        current = NEGOTIATION.mandate.model_dump()
        current.update({k: v for k, v in patch.model_dump(exclude={"thread_id"}).items() if v is not None})
        NEGOTIATION.mandate = Mandate(**current)
    return NEGOTIATION


@app.post("/negotiation/approve")
def do_approve(payload: ApprovePayload) -> Negotiation:
    if NEGOTIATION is None:
        raise HTTPException(404, "No negotiation yet")
    _check_thread(payload.thread_id)
    if DEMO_PAIR is not None:
        return DEMO_PAIR.approve(payload.edited_body)
    return loop.approve(NEGOTIATION, transport, payload.edited_body)


@app.post("/negotiation/reject")
def do_reject(payload: ThreadPayload | None = None) -> Negotiation:
    if NEGOTIATION is None:
        raise HTTPException(404, "No negotiation yet")
    _check_thread(payload.thread_id if payload else None)
    if DEMO_PAIR is not None:
        return DEMO_PAIR.stop()
    return loop.reject(NEGOTIATION)


@app.post("/coworkers", dependencies=[Depends(require_human)])
def provision(payload: ProvisionPayload) -> dict:
    """Auth0-gated: only an authenticated human may mint a new Ambiguous
    coworker identity. A no-op auth check (see auth.py) until AUTH0_DOMAIN
    and AUTH0_AUDIENCE are both set, so this can't affect anything today.
    """
    try:
        return provision_coworker(payload.display_name, role=payload.role)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Ambiguous provisioning failed: {exc}") from exc


def _check_thread(thread_id: str | None) -> None:
    if thread_id is not None and (NEGOTIATION is None or thread_id != NEGOTIATION.thread_id):
        raise HTTPException(409, "The displayed thread is no longer current. Refresh before making changes.")


async def _poller() -> None:
    """Person A: this is where inbound email enters the system."""
    pending = deque()
    active = None
    while True:
        await asyncio.sleep(POLL_SECONDS)
        if DEMO_PAIR is not None:
            try:
                await asyncio.to_thread(DEMO_PAIR.tick)
            except Exception as exc:
                print(f"[two-inbox demo] {type(exc).__name__}: check mailbox connectivity")
            continue
        negotiation = NEGOTIATION
        if negotiation is not active:
            pending.clear()
            active = negotiation
        if negotiation is None or negotiation.status is not Status.IDLE:
            continue
        try:
            if not pending:
                messages = await asyncio.to_thread(transport.poll)
                if NEGOTIATION is not negotiation:
                    continue
                pending.extend(messages)
            # Keep the remaining batch queued if a turn needs human approval.
            if pending and negotiation.status is Status.IDLE:
                message = pending.popleft()
                loop.handle_inbound(negotiation, transport, message.body)
        except Exception as exc:  # noqa: BLE001 — never kill the poller
            print(f"[poller] {exc}")


@app.on_event("startup")
async def _startup() -> None:
    app.state.poller = asyncio.create_task(_poller())


@app.on_event("shutdown")
async def _shutdown() -> None:
    app.state.poller.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await app.state.poller


with contextlib.suppress(RuntimeError):
    app.mount("/", StaticFiles(directory="../web", html=True), name="console")
