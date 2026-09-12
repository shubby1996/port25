"""
FastAPI service. Person C talks to this; Person A drives the poller.

    uvicorn app.main:app --reload --port 8000

Endpoints are deliberately few. If you are adding a fifth, ask whether the
console really needs it before 02:30.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import loop
from .state import Mandate, Negotiation, Status, new_negotiation
from .transport import get_transport

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
POLL_SECONDS = 3.0


class MandatePatch(BaseModel):
    floor_price_eur: float | None = None
    target_price_eur: float | None = None
    max_lead_time_days: int | None = None


class ApprovePayload(BaseModel):
    edited_body: str = ""


@app.get("/health")
def health() -> dict[str, Any]:
    ok, detail = transport.healthcheck()
    return {"transport": transport.name, "ok": ok, "detail": detail}


@app.post("/negotiation")
def create() -> Negotiation:
    global NEGOTIATION
    NEGOTIATION = loop.start(new_negotiation(), transport)
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
    current = NEGOTIATION.mandate.model_dump()
    current.update({k: v for k, v in patch.model_dump().items() if v is not None})
    NEGOTIATION.mandate = Mandate(**current)
    return NEGOTIATION


@app.post("/negotiation/approve")
def do_approve(payload: ApprovePayload) -> Negotiation:
    if NEGOTIATION is None:
        raise HTTPException(404, "No negotiation yet")
    return loop.approve(NEGOTIATION, transport, payload.edited_body)


@app.post("/negotiation/reject")
def do_reject() -> Negotiation:
    if NEGOTIATION is None:
        raise HTTPException(404, "No negotiation yet")
    return loop.reject(NEGOTIATION)


async def _poller() -> None:
    """Person A: this is where inbound email enters the system."""
    while True:
        await asyncio.sleep(POLL_SECONDS)
        if NEGOTIATION is None or NEGOTIATION.status in (
            Status.AWAITING_APPROVAL,
            Status.CLOSED,
        ):
            continue
        try:
            for message in transport.poll():
                loop.handle_inbound(NEGOTIATION, transport, message.body)
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
