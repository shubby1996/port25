from email.message import EmailMessage
from unittest.mock import MagicMock
import imaplib
import smtplib

import pytest

from app.transport.smtp_imap import SmtpImapTransport, _plain_text


@pytest.fixture
def connections(monkeypatch):
    for key, value in {
        "OUR_EMAIL": "buyer@example.com",
        "OUR_EMAIL_APP_PASSWORD": "test-app-password",
        "SMTP_HOST": "smtp.example.com", "SMTP_PORT": "465",
        "IMAP_HOST": "imap.example.com", "IMAP_PORT": "993",
    }.items():
        monkeypatch.setenv(key, value)
    smtp = MagicMock()
    smtp.__enter__.return_value = smtp
    imap = MagicMock()
    imap.__enter__.return_value = imap
    imap.select.return_value = ("OK", [b"0"])
    imap.response.return_value = ("UIDVALIDITY", [b"1"])
    smtp_factory = MagicMock(return_value=smtp)
    imap_factory = MagicMock(return_value=imap)
    monkeypatch.setattr("app.transport.smtp_imap.smtplib.SMTP_SSL", smtp_factory)
    monkeypatch.setattr("app.transport.smtp_imap.imaplib.IMAP4_SSL", imap_factory)
    return smtp, imap, smtp_factory, imap_factory


def reply(sender="Supplier <supplier@example.com>", subject="Re: Q3 pricing [port25-abcdef]"):
    msg = EmailMessage()
    msg["From"] = sender
    msg["Subject"] = subject
    msg.set_content("12.00 EUR per unit at 21 days lead time.")
    return msg


def mailbox(imap, messages):
    def uid(command, *args):
        if command == "search":
            return "OK", [b" ".join(messages)]
        assert command == "fetch"
        assert args[1] == "(BODY.PEEK[])"
        return "OK", [(b"1 (BODY[])", messages[args[0]].as_bytes()), b")"]
    imap.uid.side_effect = uid


def started_transport():
    transport = SmtpImapTransport()
    transport.send("supplier@example.com", "Q3 pricing [port25-abcdef]", "An opening offer")
    return transport


def test_health_checks_both_protocols_without_sending(connections):
    smtp, imap, smtp_factory, imap_factory = connections
    assert SmtpImapTransport().healthcheck()[0]
    smtp.login.assert_called_once_with("buyer@example.com", "test-app-password")
    imap.login.assert_called_once_with("buyer@example.com", "test-app-password")
    imap.select.assert_called_once_with("INBOX", readonly=True)
    smtp.send_message.assert_not_called()
    for factory, context_arg in [(smtp_factory, "context"), (imap_factory, "ssl_context")]:
        assert factory.call_args.kwargs["timeout"] == 15
        assert factory.call_args.kwargs[context_arg].check_hostname


def test_health_missing_credentials_does_not_connect(connections, monkeypatch):
    monkeypatch.delenv("OUR_EMAIL_APP_PASSWORD")
    ok, detail = SmtpImapTransport().healthcheck()
    assert not ok and "OUR_EMAIL_APP_PASSWORD missing" in detail
    connections[2].assert_not_called()
    connections[3].assert_not_called()


@pytest.mark.parametrize("stage", ["SMTP", "IMAP", "INBOX"])
def test_health_failures_are_reported_without_private_server_text(connections, stage):
    smtp, imap, _, _ = connections
    if stage == "SMTP":
        smtp.login.side_effect = smtplib.SMTPAuthenticationError(535, b"test-app-password")
    elif stage == "IMAP":
        imap.login.side_effect = imaplib.IMAP4.error("test-app-password")
    else:
        imap.select.return_value = ("NO", [b"test-app-password"])
    ok, detail = SmtpImapTransport().healthcheck()
    assert not ok
    assert ("SMTP" if stage == "SMTP" else "IMAP") in detail
    assert "test-app-password" not in detail


def test_smtp_send_has_delivery_headers_and_plain_text(connections):
    transport = started_transport()
    message = connections[0].send_message.call_args.args[0]
    assert message["From"] == transport.address
    assert message["To"] == "supplier@example.com"
    assert message["Date"] and message["Message-ID"]
    assert message.get_content().strip() == "An opening offer"


def test_port_587_upgrades_tls_before_login(connections, monkeypatch):
    smtp = connections[0]
    monkeypatch.setenv("SMTP_PORT", "587")
    factory = MagicMock(return_value=smtp)
    monkeypatch.setattr("app.transport.smtp_imap.smtplib.SMTP", factory)
    started_transport()
    calls = [call[0] for call in smtp.method_calls]
    assert calls[:5] == ["ehlo", "starttls", "ehlo", "login", "send_message"]
    connections[2].assert_not_called()


@pytest.mark.parametrize("recipient", ["", "supplier", "a@example.com,b@example.com", "a@example.com\nBcc:b@example.com"])
def test_invalid_recipient_does_not_connect(connections, recipient):
    with pytest.raises(ValueError, match="recipient"):
        SmtpImapTransport().send(recipient, "Test", "Body")
    connections[2].assert_not_called()


def test_poll_before_send_does_not_read_mailbox(connections):
    assert SmtpImapTransport().poll() == []
    connections[3].assert_not_called()


def test_poll_filters_and_deduplicates_without_changing_flags(connections):
    imap = connections[1]
    mailbox(imap, {
        b"1": reply(sender="stranger@example.com"),
        b"2": reply(subject="Re: Old negotiation [port25-123456]"),
        b"3": reply(),
    })
    transport = started_transport()
    received = transport.poll()
    assert len(received) == 1
    assert received[0].from_addr == "supplier@example.com"
    assert "12.00 EUR" in received[0].body
    assert transport.poll() == []
    imap.select.assert_called_with("INBOX", readonly=True)
    imap.store.assert_not_called()
    searches = [call.args for call in imap.uid.call_args_list if call.args[0] == "search"]
    assert all("UNSEEN" not in call for call in searches)
    assert searches[0][-2:] == ("SUBJECT", '"[port25-abcdef]"')
    assert sum(call.args[0] == "fetch" for call in imap.uid.call_args_list) == 3


def test_uidvalidity_change_allows_reused_uids(connections):
    imap = connections[1]
    mailbox(imap, {b"1": reply()})
    transport = started_transport()
    assert len(transport.poll()) == 1
    imap.response.return_value = ("UIDVALIDITY", [b"2"])
    assert len(transport.poll()) == 1


def test_failed_fetch_does_not_lose_earlier_messages(connections):
    imap = connections[1]
    mailbox(imap, {b"1": reply(), b"2": reply()})
    normal_uid = imap.uid.side_effect
    def broken_uid(command, *args):
        if command == "fetch" and args[0] == b"2":
            return "NO", [b"Temporary failure"]
        return normal_uid(command, *args)
    imap.uid.side_effect = broken_uid
    transport = started_transport()
    with pytest.raises(imaplib.IMAP4.error, match="fetch"):
        transport.poll()
    imap.uid.side_effect = normal_uid
    assert len(transport.poll()) == 2


def test_imap_search_failure_is_not_reported_as_empty_mailbox(connections):
    connections[1].uid.return_value = ("NO", [b"Search failed"])
    with pytest.raises(imaplib.IMAP4.error, match="search"):
        started_transport().poll()


def test_encoded_headers_and_charset_are_decoded(connections):
    msg = reply(subject="Re: Q3 — café [port25-abcdef]")
    msg.set_content("Prix proposé: 12.00 EUR, délai 21 jours.", charset="iso-8859-1")
    mailbox(connections[1], {b"1": msg})
    transport = SmtpImapTransport()
    transport.send("supplier@example.com", "Q3 — café [port25-abcdef]", "Offer")
    received = transport.poll()[0]
    assert received.subject == "Re: Q3 — café [port25-abcdef]"
    assert "proposé" in received.body and "délai" in received.body


def test_plain_text_is_preferred_and_attachments_are_ignored():
    msg = reply()
    msg.add_alternative("<p>Do not prefer HTML</p>", subtype="html")
    msg.add_attachment("Do not use the attachment", subtype="plain", filename="notes.txt")
    assert _plain_text(msg) == "12.00 EUR per unit at 21 days lead time."


def test_html_only_reply_becomes_readable_text():
    msg = EmailMessage()
    msg.set_content("<html><head><style>hidden</style></head><body><p>12.00 EUR &amp; tax</p><p>21 days</p><script>hidden</script></body></html>", subtype="html")
    body = _plain_text(msg)
    assert "12.00 EUR & tax" in body and "\n21 days" in body
    assert "<" not in body and "hidden" not in body


def test_attachment_only_message_has_no_body():
    msg = EmailMessage()
    msg.add_attachment(b"binary", maintype="application", subtype="octet-stream", filename="quote.bin")
    assert _plain_text(msg) == ""
