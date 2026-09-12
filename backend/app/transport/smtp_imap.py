"""
PERSON A — FALLBACK. Only touch this if the 00:50 gate failed.

Two throwaway Gmail accounts with app passwords. This is still genuinely real
email crossing the public internet, so the pitch survives intact — you only
lose the Ambiguous sponsor prize, not the idea.

Poll over IMAP rather than using webhooks. Tunnels fail at the worst moment and
you have no time to debug ngrok at 01:10.

Setup, roughly 10 minutes:
  1. Two Gmail accounts, 2FA on, generate an app password for each.
  2. Put both in .env.
  3. PORT25_TRANSPORT=smtp
"""

from __future__ import annotations

import email
import imaplib
import os
import smtplib
from email.message import EmailMessage

from .base import InboundMessage, Transport


class SmtpImapTransport(Transport):
    name = "smtp"

    def __init__(self) -> None:
        self.address = os.getenv("OUR_EMAIL", "")
        self.password = os.getenv("OUR_EMAIL_APP_PASSWORD", "")
        self.smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "465"))
        self.imap_host = os.getenv("IMAP_HOST", "imap.gmail.com")

    def send(self, to_addr: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"] = self.address
        msg["To"] = to_addr
        msg["Subject"] = subject
        msg.set_content(body)
        with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port) as smtp:
            smtp.login(self.address, self.password)
            smtp.send_message(msg)

    def poll(self) -> list[InboundMessage]:
        out: list[InboundMessage] = []
        with imaplib.IMAP4_SSL(self.imap_host) as imap:
            imap.login(self.address, self.password)
            imap.select("INBOX")
            _, data = imap.search(None, "UNSEEN")
            for num in data[0].split():
                _, raw = imap.fetch(num, "(RFC822)")
                msg = email.message_from_bytes(raw[0][1])
                out.append(
                    InboundMessage(
                        from_addr=msg.get("From", ""),
                        subject=msg.get("Subject", ""),
                        body=_plain_text(msg),
                    )
                )
        return out

    def healthcheck(self) -> tuple[bool, str]:
        if not self.address or not self.password:
            return False, "smtp: OUR_EMAIL or OUR_EMAIL_APP_PASSWORD missing"
        try:
            with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port) as smtp:
                smtp.login(self.address, self.password)
            return True, f"smtp: logged in as {self.address}"
        except Exception as exc:
            return False, f"smtp: {exc}"


def _plain_text(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                return part.get_payload(decode=True).decode(errors="replace")
        return ""
    return msg.get_payload(decode=True).decode(errors="replace")
