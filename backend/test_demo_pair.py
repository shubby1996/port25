import asyncio
from email import policy
from email.parser import BytesParser
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

import smoke_smtp
from app import demo_pair, main
from app.state import Status, Tier, Position


@pytest.fixture
def email_network(monkeypatch):
    """Real MIME serialization and transport code, with network sockets replaced."""
    for key, value in {
        "OUR_EMAIL": "buyer@example.com", "OUR_EMAIL_APP_PASSWORD": "buyer-password",
        "COUNTERPARTY_EMAIL": "supplier@example.com", "COUNTERPARTY_EMAIL_APP_PASSWORD": "supplier-password",
        "SMTP_PORT": "465", "IMAP_PORT": "993", "PORT25_DEMO_PAIR": "true", "PORT25_DEMO_AI": "false",
    }.items():
        monkeypatch.setenv(key, value)
    for key in ("SMTP_HOST", "SMTP_PORT", "IMAP_HOST", "IMAP_PORT"):
        monkeypatch.delenv("COUNTERPARTY_" + key, raising=False)
    inboxes = {"buyer@example.com": [], "supplier@example.com": []}
    passwords = {"buyer@example.com": "buyer-password", "supplier@example.com": "supplier-password"}
    sent = []
    logins = []
    servers = []

    def connection(kind):
        server = MagicMock()
        server.__enter__.return_value = server
        servers.append(server)
        identity = None
        def login(address, password):
            nonlocal identity
            assert password == passwords[address]
            identity = address
            logins.append((kind, address))
        server.login.side_effect = login
        def send_message(message):
            assert message["From"] == identity
            recipient = str(message["To"])
            wire = message.as_bytes(policy=policy.SMTP)
            inboxes[recipient].append(wire)
            sent.append((identity, recipient, wire))
        server.send_message.side_effect = send_message
        server.select.return_value = ("OK", [b"0"])
        server.response.return_value = ("UIDVALIDITY", [b"1"])
        def uid(command, *args):
            if command == "search":
                return "OK", [b" ".join(str(i).encode() for i in range(1, len(inboxes[identity]) + 1))]
            assert command == "fetch" and args[1] == "(BODY.PEEK[])"
            return "OK", [(b"1 (BODY[])", inboxes[identity][int(args[0]) - 1]), b")"]
        server.uid.side_effect = uid
        return server
    monkeypatch.setattr("app.transport.smtp_imap.smtplib.SMTP_SSL", lambda *a, **k: connection("smtp"))
    monkeypatch.setattr("app.transport.smtp_imap.imaplib.IMAP4_SSL", lambda *a, **k: connection("imap"))
    monkeypatch.setattr(main, "NEGOTIATION", None)
    monkeypatch.setattr(main, "DEMO_PAIR", None)
    transport = MagicMock()
    transport.name = "smtp"
    monkeypatch.setattr(main, "transport", transport)
    return sent, logins, inboxes, servers


def run_until_paused(pair):
    for _ in range(12):
        pair.tick()
        if pair.state.status in (Status.CLOSED, Status.AWAITING_APPROVAL):
            return
    pytest.fail("Demo failed to stop within the expected number of ticks")


def test_both_accounts_exchange_email_and_agree(email_network):
    pair = demo_pair.from_environment()
    assert pair.healthcheck()["ok"]
    assert email_network[0] == []
    assert set(email_network[1]) == {
        (protocol, address) for protocol in ("smtp", "imap")
        for address in ("buyer@example.com", "supplier@example.com")
    }
    pair.start()
    run_until_paused(pair)
    assert pair.outcome == "agreement"
    assert pair.state.status is Status.CLOSED
    assert pair.state.our_position.unit_price_eur == 11
    assert pair.state.their_position.unit_price_eur == 11
    assert [turn.direction for turn in pair.state.turns] == ["out", "in", "out", "in"]
    assert all(turn.model_used == "demo rules" for turn in pair.state.turns)
    assert [item[0] for item in email_network[0]] == ["buyer@example.com", "supplier@example.com"] * 2
    assert len({str(BytesParser(policy=policy.default).parsebytes(item[2])["Subject"]) for item in email_network[0]}) == 1
    for _ in range(5):
        pair.tick()
    assert len(email_network[0]) == 4
    for server in email_network[3]:
        server.store.assert_not_called()


def test_supplier_waits_for_delivery_in_its_own_inbox(email_network):
    pair = demo_pair.from_environment()
    pair.start()
    supplier_inbox = email_network[2]["supplier@example.com"]
    in_transit = supplier_inbox.pop()
    pair.tick()
    assert len(email_network[0]) == 1
    supplier_inbox.append(in_transit)
    pair.tick()
    assert len(email_network[0]) == 2


def test_pause_approve_and_resume_both_accounts(email_network):
    state = main.create()
    main.patch_mandate(main.MandatePatch(floor_price_eur=11.00))
    pair = main.DEMO_PAIR
    run_until_paused(pair)
    assert state.status is Status.AWAITING_APPROVAL
    assert state.turns[-1].tier.value == "escalate"
    assert "11.00 EUR" in state.pending_draft
    for _ in range(5):
        pair.tick()
    assert len(email_network[0]) == 2
    main.do_approve(main.ApprovePayload())
    run_until_paused(pair)
    assert pair.outcome == "agreement"
    assert state.turns[2].approved_by_human
    assert len(email_network[0]) == 4


def test_stop_prevents_supplier_from_replying(email_network):
    main.create()
    pair = main.DEMO_PAIR
    main.do_reject()
    for _ in range(5):
        pair.tick()
    assert pair.outcome == "stopped"
    assert len(email_network[0]) == 1


def test_old_emails_do_not_restart_new_demo(email_network):
    first = demo_pair.from_environment()
    first.start()
    run_until_paused(first)
    second = demo_pair.from_environment()
    second.start()
    run_until_paused(second)
    assert first.state.subject != second.state.subject
    assert second.outcome == "agreement"
    assert len(email_network[0]) == 8


def test_non_agreeing_supplier_hits_six_message_limit(email_network):
    pair = demo_pair.from_environment()
    pair.supplier_floor = 12.4
    pair.supplier_ask = 12.4
    pair.start()
    run_until_paused(pair)
    assert pair.outcome == "turn_limit"
    assert pair.state.turn_count == 6
    assert len(email_network[0]) == 6


def test_lead_time_outside_mandate_requires_approval(email_network):
    pair = demo_pair.from_environment()
    pair.supplier_days = 40
    pair.start()
    run_until_paused(pair)
    assert pair.state.status is Status.AWAITING_APPROVAL
    assert len(email_network[0]) == 2
    assert "30 days" in pair.state.pending_draft


def test_failed_supplier_send_stops_without_resending(email_network, monkeypatch):
    pair = demo_pair.from_environment()
    pair.start()
    send = MagicMock(side_effect=OSError("Temporary disconnect"))
    monkeypatch.setattr(pair.supplier, "send", send)
    with pytest.raises(OSError):
        pair.tick()
    pair.tick()
    assert pair.outcome == "send_error"
    send.assert_called_once()


def test_missing_second_password_fails_before_network(email_network, monkeypatch):
    monkeypatch.delenv("COUNTERPARTY_EMAIL_APP_PASSWORD")
    with pytest.raises(ValueError, match="COUNTERPARTY_EMAIL_APP_PASSWORD"):
        demo_pair.from_environment()
    assert not email_network[0] and not email_network[1]
    health = main.health()
    assert not health["ok"] and "COUNTERPARTY_EMAIL_APP_PASSWORD" in health["detail"]


def test_same_account_is_rejected_before_network(email_network, monkeypatch):
    monkeypatch.setenv("COUNTERPARTY_EMAIL", "buyer@example.com")
    with pytest.raises(ValueError, match="two different inboxes"):
        demo_pair.from_environment()
    assert not email_network[1]


def test_counterparty_can_use_other_servers_without_changing_buyer(email_network, monkeypatch):
    monkeypatch.setenv("COUNTERPARTY_SMTP_HOST", "smtp.second.example")
    monkeypatch.setenv("COUNTERPARTY_IMAP_HOST", "imap.second.example")
    monkeypatch.setenv("COUNTERPARTY_SMTP_PORT", "587")
    pair = demo_pair.from_environment()
    assert pair.supplier.smtp_host == "smtp.second.example"
    assert pair.supplier.imap_host == "imap.second.example"
    assert pair.supplier.smtp_port == 587
    assert pair.buyer.smtp_port == 465
    assert pair.buyer.address != pair.supplier.address
    assert pair.buyer.password != pair.supplier.password


def test_starting_another_active_demo_is_rejected(email_network):
    main.create()
    with pytest.raises(HTTPException) as error:
        main.create()
    assert error.value.status_code == 409
    assert len(email_network[0]) == 1


def test_bad_second_login_prevents_opening_email(email_network, monkeypatch):
    monkeypatch.setattr(demo_pair.SmtpImapTransport, "healthcheck", lambda self: (self.address.startswith("buyer"), "Login check"))
    with pytest.raises(HTTPException) as error:
        main.create()
    assert error.value.status_code == 503
    assert not email_network[0]


def test_background_poller_drives_both_inboxes(email_network, monkeypatch):
    main.create()
    pair = main.DEMO_PAIR
    ticks = 0
    async def tick(_):
        nonlocal ticks
        ticks += 1
        if ticks == 5:
            raise asyncio.CancelledError
    monkeypatch.setattr(main.asyncio, "sleep", tick)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(main._poller())
    assert pair.outcome == "agreement"
    assert len(email_network[0]) == 4


def test_cli_pair_check_does_not_send(email_network):
    assert smoke_smtp.main(["--pair"]) == 0
    assert len(email_network[1]) == 4
    assert not email_network[0]


def test_cli_pair_sends_automatic_round_trip(email_network, capsys, monkeypatch):
    monkeypatch.setattr(smoke_smtp.time, "sleep", lambda _: None)
    assert smoke_smtp.main(["--pair", "--send"]) == 0
    assert len(email_network[0]) == 4
    assert "PASS" in capsys.readouterr().out


def test_ai_pair_uses_both_roles_and_market_context(email_network, monkeypatch):
    monkeypatch.setenv("PORT25_DEMO_AI", "true")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    draft = MagicMock(side_effect=lambda body, **kwargs: (body, "openai/gpt-4o-mini"))
    classify = MagicMock(return_value=(Tier.ROUTINE, "Familiar terms", Position()))
    monkeypatch.setattr(demo_pair, "draft_fixed_offer", draft)
    monkeypatch.setattr(demo_pair, "classify", classify)
    monkeypatch.setattr(demo_pair, "fetch_market_context", lambda *a, **k: "Verified market context")
    pair = demo_pair.from_environment()
    pair.start()
    run_until_paused(pair)
    assert pair.outcome == "agreement"
    assert pair.state.our_position.unit_price_eur == 11
    assert [call.kwargs["role"] for call in draft.call_args_list] == ["buyer", "supplier", "buyer", "supplier"]
    assert all(call.kwargs["context"] == "Verified market context" for call in draft.call_args_list)
    assert classify.call_count == 2
    assert all("openai/gpt-4o-mini" in turn.model_used for turn in pair.state.turns)
    assert len(email_network[0]) == 4


def test_ai_classification_failure_pauses_before_next_send(email_network, monkeypatch):
    pair = demo_pair.from_environment()
    pair.use_ai = True
    monkeypatch.setattr(demo_pair, "draft_fixed_offer", lambda body, **kwargs: (body, "test-model"))
    monkeypatch.setattr(demo_pair, "fetch_market_context", lambda *a, **k: "")
    monkeypatch.setattr(demo_pair, "classify", MagicMock(side_effect=TimeoutError))
    pair.start()
    run_until_paused(pair)
    assert pair.state.status is Status.AWAITING_APPROVAL
    assert "classification failed" in pair.state.turns[-1].reason
    assert len(email_network[0]) == 2
