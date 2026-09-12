import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app import main
from app.state import Status, new_negotiation
from app.transport import InboundMessage


@pytest.mark.parametrize("action", ["mandate", "approve", "reject"])
def test_stale_displayed_thread_cannot_mutate_current_thread(service, monkeypatch, action):
    state = new_negotiation()
    monkeypatch.setattr(main, "NEGOTIATION", state)
    with pytest.raises(HTTPException) as error:
        if action == "mandate":
            main.patch_mandate(main.MandatePatch(thread_id="old-thread", floor_price_eur=50))
        elif action == "approve":
            main.do_approve(main.ApprovePayload(thread_id="old-thread", edited_body="Stale draft"))
        else:
            main.do_reject(main.ThreadPayload(thread_id="old-thread"))
    assert error.value.status_code == 409
    assert state.status is not Status.CLOSED
    assert state.mandate.floor_price_eur == 12.5
    service.send.assert_not_called()


@pytest.fixture
def service(monkeypatch):
    fake = MagicMock()
    fake.name = "smtp"
    monkeypatch.setattr(main, "transport", fake)
    monkeypatch.setattr(main, "NEGOTIATION", None)
    monkeypatch.setattr(main, "DEMO_PAIR", None)
    monkeypatch.setenv("PORT25_DEMO_PAIR", "false")
    monkeypatch.setenv("OUR_EMAIL", "buyer@example.com")
    monkeypatch.setenv("COUNTERPARTY_EMAIL", "supplier@example.com")
    monkeypatch.setattr(main.loop, "fetch_market_context", lambda _: "")
    return fake


def test_smtp_start_uses_configured_addresses_and_unique_subject(service):
    first = main.create()
    second = main.create()
    assert first.our_email == "buyer@example.com"
    assert first.counterparty_email == "supplier@example.com"
    assert f"[port25-{first.thread_id}]" in first.subject
    assert first.subject != second.subject
    assert service.send.call_args.args[:2] == (second.counterparty_email, second.subject)


def test_missing_counterparty_does_not_send_to_demo_address(service, monkeypatch):
    monkeypatch.delenv("COUNTERPARTY_EMAIL")
    with pytest.raises(HTTPException) as error:
        main.create()
    assert error.value.status_code == 503
    assert "COUNTERPARTY_EMAIL" in error.value.detail
    service.send.assert_not_called()


def test_mock_start_keeps_demo_defaults(service):
    service.name = "mock"
    negotiation = main.create()
    assert negotiation.counterparty_email == "supplier@port25.demo"
    assert "[port25-" not in negotiation.subject


def test_create_passes_selected_parties_and_market(service, monkeypatch):
    monkeypatch.setenv("PORT25_DEMO_PAIR", "true")
    service.name = "smtp"
    pair = MagicMock()
    pair.state = new_negotiation()
    pair.state.status = Status.CLOSED
    pair.healthcheck.return_value = {"ok": True, "accounts": {}}
    pair.start.return_value = pair.state
    factory = MagicMock(return_value=pair)
    monkeypatch.setattr(main.demo_pair, "from_environment", factory)
    main.create(main.StartPayload(
        buyer_account="secondary", supplier_account="primary", commodity="steel",
        buyer_region="East Asia", supplier_region="Europe",
    ))
    factory.assert_called_once_with(
        buyer_account="secondary", supplier_account="primary", commodity="steel",
        buyer_region="East Asia", supplier_region="Europe",
    )


@pytest.mark.parametrize("resume", [True, False])
def test_poller_preserves_batch_while_awaiting_approval(service, monkeypatch, resume):
    negotiation = new_negotiation()
    monkeypatch.setattr(main, "NEGOTIATION", negotiation)
    service.poll.return_value = [
        InboundMessage(from_addr="supplier@example.com", subject="Test", body=body)
        for body in ("first", "second")
    ]
    handled = []
    def handle(state, transport, body):
        handled.append(body)
        state.status = Status.AWAITING_APPROVAL
    monkeypatch.setattr(main.loop, "handle_inbound", handle)
    ticks = 0
    async def tick(_):
        nonlocal ticks
        ticks += 1
        if ticks == 3:
            assert handled == ["first"]
            negotiation.status = Status.IDLE if resume else Status.CLOSED
        if ticks == 4:
            raise asyncio.CancelledError
    monkeypatch.setattr(main.asyncio, "sleep", tick)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(main._poller())
    assert handled == (["first", "second"] if resume else ["first"])
    service.poll.assert_called_once()


def test_poller_discards_old_batch_when_negotiation_changes(service, monkeypatch):
    old = new_negotiation()
    monkeypatch.setattr(main, "NEGOTIATION", old)
    def poll():
        main.NEGOTIATION = new_negotiation()
        return [InboundMessage(from_addr="supplier@example.com", subject="Old", body="Old reply")]
    service.poll.side_effect = poll
    handle = MagicMock()
    monkeypatch.setattr(main.loop, "handle_inbound", handle)
    ticks = 0
    async def tick(_):
        nonlocal ticks
        ticks += 1
        if ticks == 2:
            raise asyncio.CancelledError
    monkeypatch.setattr(main.asyncio, "sleep", tick)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(main._poller())
    handle.assert_not_called()
