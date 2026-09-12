from unittest.mock import MagicMock

import pytest

import smoke_smtp
from app.transport import InboundMessage


@pytest.fixture
def transport(monkeypatch):
    fake = MagicMock(address="buyer@example.com")
    fake.healthcheck.return_value = (True, "Both protocols connected")
    monkeypatch.setattr(smoke_smtp, "SmtpImapTransport", lambda: fake)
    monkeypatch.setenv("COUNTERPARTY_EMAIL", "supplier@example.com")
    return fake


def test_default_checks_credentials_without_sending(transport):
    assert smoke_smtp.main([]) == 0
    transport.send.assert_not_called()
    transport.poll.assert_not_called()


def test_failed_health_never_sends(transport):
    transport.healthcheck.return_value = (False, "IMAP failed")
    assert smoke_smtp.main(["--send"]) == 1
    transport.send.assert_not_called()


@pytest.mark.parametrize("args", [["--send"], ["--to", "supplier@example.com"]])
def test_round_trip_sends_exactly_once(transport, args, capsys):
    transport.poll.return_value = [InboundMessage(
        from_addr="supplier@example.com", subject="Re: test", body="Private reply text",
    )]
    assert smoke_smtp.main(args) == 0
    transport.send.assert_called_once()
    recipient, subject, body = transport.send.call_args.args
    assert recipient == "supplier@example.com"
    assert "[port25-" in subject and "12.00 EUR" in body
    output = capsys.readouterr().out
    assert "PASS" in output and "Private reply text" not in output


def test_timeout_reports_failure_without_resending(transport, monkeypatch, capsys):
    transport.poll.return_value = []
    times = iter([0, 0, 1, 2])
    monkeypatch.setattr(smoke_smtp.time, "monotonic", lambda: next(times))
    assert smoke_smtp.main(["--send", "--timeout", "1"]) == 2
    transport.send.assert_called_once()
    assert "TIMEOUT" in capsys.readouterr().out


def test_same_inbox_cannot_produce_a_false_round_trip(transport):
    assert smoke_smtp.main(["--to", "buyer@example.com"]) == 1
    transport.send.assert_not_called()


@pytest.mark.parametrize("timeout", ["0", "-1", "nan", "inf"])
def test_invalid_timeout_is_rejected(transport, timeout):
    with pytest.raises(SystemExit) as error:
        smoke_smtp.main(["--timeout", timeout])
    assert error.value.code == 2
    transport.send.assert_not_called()
