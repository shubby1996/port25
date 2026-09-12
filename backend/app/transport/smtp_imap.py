"""SMTP/IMAP fallback for a single live negotiation thread.

Only replies from the last recipient with the matching subject enter the loop.
Polling leaves mailbox flags unchanged; delivered UIDs are tracked in memory.
"""

from __future__ import annotations

import email
import imaplib
import os
import re
import smtplib
import ssl
from email import policy
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from html.parser import HTMLParser

from .base import InboundMessage, Transport


class SmtpImapTransport(Transport):
    name = "smtp"

    def __init__(self, *, counterparty: bool = False) -> None:
        self._email_key = "COUNTERPARTY_EMAIL" if counterparty else "OUR_EMAIL"
        self._password_key = self._email_key + "_APP_PASSWORD"
        self.address = os.getenv(self._email_key, "").strip()
        self.password = os.getenv(self._password_key, "").strip()
        def setting(key, default):
            shared = os.getenv(key, default)
            return (os.getenv("COUNTERPARTY_" + key, "") or shared) if counterparty else shared
        self.smtp_host = setting("SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = int(setting("SMTP_PORT", "465"))
        self.imap_host = setting("IMAP_HOST", "imap.gmail.com")
        self.imap_port = int(setting("IMAP_PORT", "993"))
        self.timeout = 15.0
        self._tls = ssl.create_default_context()
        self._thread: tuple[str, str] | None = None
        self._seen: set[bytes] = set()
        self._uidvalidity = None

    def validate_config(self) -> None:
        if not self.address or not self.password:
            raise ValueError(f"{self._email_key} or {self._password_key} missing in the repo-root .env")
        validate_address(self.address, self._email_key)
        if self.smtp_port not in (465, 587):
            raise ValueError("SMTP_PORT must be 465 (TLS) or 587 (STARTTLS)")
        if not 1 <= self.imap_port <= 65535:
            raise ValueError("IMAP_PORT must be between 1 and 65535")

    def _smtp(self):
        if self.smtp_port == 465:
            return smtplib.SMTP_SSL(
                self.smtp_host, self.smtp_port, timeout=self.timeout, context=self._tls
            )
        return smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=self.timeout)

    def _smtp_login(self, smtp) -> None:
        if self.smtp_port == 587:
            smtp.ehlo()
            smtp.starttls(context=self._tls)
            smtp.ehlo()
        smtp.login(self.address, self.password)

    def _imap(self):
        return imaplib.IMAP4_SSL(
            self.imap_host, self.imap_port,
            ssl_context=self._tls, timeout=self.timeout,
        )

    def send(self, to_addr: str, subject: str, body: str) -> None:
        self.validate_config()
        validate_address(to_addr, "recipient")
        msg = EmailMessage()
        msg["From"] = self.address
        msg["To"] = to_addr
        msg["Subject"] = subject
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain=self.address.split("@", 1)[1])
        msg.set_content(body)
        with self._smtp() as smtp:
            self._smtp_login(smtp)
            smtp.send_message(msg)

        self.watch_thread(to_addr, subject)

    def watch_thread(self, from_addr: str, subject: str) -> None:
        """Receive an opening email without having to send first."""
        validate_address(from_addr, "counterparty")
        thread = (from_addr.casefold(), normalize_subject(subject))
        if thread != self._thread:
            self._thread = thread
            self._seen.clear()
            self._uidvalidity = None

    def poll(self) -> list[InboundMessage]:
        if self._thread is None:
            return []
        self.validate_config()
        sender, subject = self._thread
        out: list[InboundMessage] = []
        examined: set[bytes] = set()
        with self._imap() as imap:
            imap.login(self.address, self.password)
            _require_ok(imap.select("INBOX", readonly=True), "select INBOX")
            _, validity = imap.response("UIDVALIDITY")
            if validity != self._uidvalidity:
                self._seen.clear()
                self._uidvalidity = validity
            # Search read and unread mail: opening the reply in Gmail must not
            # cause the agent to miss it. Exact sender/subject checks follow.
            criteria = ["FROM", _imap_quote(sender)]
            marker = re.search(r"\[port25-[a-f0-9]+\]", subject)
            if marker:
                criteria.extend(["SUBJECT", _imap_quote(marker.group())])
            data = _require_ok(imap.uid("search", None, *criteria), "search INBOX")
            for uid in (data[0] or b"").split():
                if uid in self._seen:
                    continue
                raw = _require_ok(imap.uid("fetch", uid, "(BODY.PEEK[])"), "fetch email")
                payload = next(
                    (part[1] for part in raw if isinstance(part, tuple) and isinstance(part[1], bytes)),
                    None,
                )
                if payload is None:
                    # It may have been deleted between SEARCH and FETCH.
                    continue
                msg = email.message_from_bytes(payload, policy=policy.default)
                from_addr = parseaddr(str(msg.get("From", "")))[1]
                decoded_subject = str(msg.get("Subject", ""))
                if (
                    from_addr.casefold() == sender
                    and normalize_subject(decoded_subject) == subject
                ):
                    body = _plain_text(msg)
                    if body.strip():
                        out.append(InboundMessage(
                            from_addr=from_addr, subject=decoded_subject, body=body,
                        ))
                examined.add(uid)
        # Commit only after the whole batch succeeds so a later FETCH error
        # does not silently consume earlier messages that were never returned.
        self._seen.update(examined)
        return out

    def healthcheck(self) -> tuple[bool, str]:
        try:
            self.validate_config()
        except ValueError as exc:
            return False, f"smtp: {exc}"
        stage = "SMTP"
        try:
            with self._smtp() as smtp:
                self._smtp_login(smtp)
            stage = "IMAP"
            with self._imap() as imap:
                imap.login(self.address, self.password)
                _require_ok(imap.select("INBOX", readonly=True), "select INBOX")
            return True, "smtp: SMTP and IMAP login succeeded; INBOX is readable"
        except Exception as exc:
            # Server responses can contain credentials or private mailbox data.
            return False, f"smtp: {stage} failed ({type(exc).__name__}); check credentials, host and port"


def validate_address(value: str, label: str) -> None:
    """Require one bare ASCII mailbox address for configuration and SMTP."""
    if (
        not value.isascii()
        or any(char.isspace() for char in value)
        or parseaddr(value)[1] != value
        or value.count("@") != 1
        or not all(value.split("@"))
    ):
        raise ValueError(f"{label} must be a single email address")


def normalize_subject(subject: str) -> str:
    return re.sub(r"^(?:(?:re|aw|sv):\s*)+", "", subject.strip(), flags=re.I).casefold()


def _imap_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _require_ok(response, operation: str):
    status, data = response
    if status != "OK":
        raise imaplib.IMAP4.error(f"Could not {operation}")
    return data


def _plain_text(msg: EmailMessage) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    try:
        text = part.get_content()
    except (LookupError, UnicodeError):
        text = (part.get_payload(decode=True) or b"").decode("utf-8", errors="replace")
    if part.get_content_type() == "text/html":
        parser = _HTMLText()
        parser.feed(text)
        return "".join(parser.parts).strip()
    return text.strip()


class _HTMLText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self.hidden += 1
        if tag in ("br", "p", "div", "li", "tr") and not self.hidden:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head"):
            self.hidden = max(0, self.hidden - 1)
        if tag in ("p", "div", "li", "tr") and not self.hidden:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)
