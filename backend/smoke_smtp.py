"""Check SMTP/IMAP credentials, optionally send one email and wait for a reply."""

from __future__ import annotations

import argparse
import os
import time
import uuid

from app.transport.smtp_imap import SmtpImapTransport, validate_address
from app import demo_pair


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--to", help="Send one test email to this inbox and wait for its reply")
    parser.add_argument("--pair", action="store_true", help="Check both inboxes; with --send, run their automatic demo negotiation")
    parser.add_argument(
        "--send", action="store_true",
        help="Send to COUNTERPARTY_EMAIL from .env (or the address supplied with --to)",
    )
    parser.add_argument("--timeout", type=float, default=180, help="Reply wait in seconds (default: 180)")
    parser.add_argument("--interval", type=float, default=3, help="Poll interval in seconds (default: 3)")
    args = parser.parse_args(argv)
    if not 0 < args.timeout < float("inf") or not 0 < args.interval < float("inf"):
        parser.error("--timeout and --interval must be finite, positive numbers")
    if args.pair and args.to is not None:
        parser.error("--pair uses OUR_EMAIL and COUNTERPARTY_EMAIL from .env; omit --to")

    try:
        if args.pair:
            return run_pair(args.send, args.timeout, args.interval)
        transport = SmtpImapTransport()
        recipient = args.to or (os.getenv("COUNTERPARTY_EMAIL", "").strip() if args.send else "")
        if args.send or args.to is not None:
            validate_address(recipient, "--to / COUNTERPARTY_EMAIL")
            if recipient.casefold() == transport.address.casefold():
                raise ValueError("Use a second inbox so the outbound email cannot count as its own reply")
        ok, detail = transport.healthcheck()
        print(detail, flush=True)
        if not ok:
            return 1
        if not recipient:
            print("Check only: no email sent. Use --send or --to ADDRESS to test a round trip.")
            return 0

        subject = f"Port 25 email round trip [port25-{uuid.uuid4().hex[:12]}]"
        body = (
            "This is a Port 25 email transport test.\n\n"
            "Please reply from this inbox, keeping the subject unchanged, with:\n"
            "We can offer 12.00 EUR per unit at 21 days lead time.\n\n"
            "This is a test message, not a purchase order."
        )
        transport.send(recipient, subject, body)
        print(f"Sent one test email to {recipient}.\nSubject: {subject}", flush=True)
        print("Reply from that inbox with the same subject. Waiting for the reply...", flush=True)
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            messages = transport.poll()
            if messages:
                print("PASS: matching reply received; SMTP send and IMAP receive completed.")
                print(f"Decoded plain-text body: {len(messages[0].body)} characters.")
                return 0
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(args.interval, remaining))
        print("TIMEOUT: email was sent, but no matching reply arrived. Check both inboxes and spam folders.")
        return 2
    except ValueError as exc:
        print(f"Configuration error: {exc}")
        return 1
    except KeyboardInterrupt:
        print("Stopped waiting. Any email already sent remains sent.")
        return 130
    except Exception as exc:
        print(f"Transport failed ({type(exc).__name__}). Check credentials and SMTP/IMAP connectivity.")
        return 1


def run_pair(send: bool, timeout: float, interval: float) -> int:
    pair = demo_pair.from_environment()
    health = pair.healthcheck()
    for role, account in health["accounts"].items():
        print(f"{role}: {account['detail']}", flush=True)
    if not health["ok"]:
        return 1
    if not send:
        print("Both inboxes checked. No email sent. Add --send to run the automatic demo.")
        return 0
    pair.start()
    print(f"Started two-inbox demo ({pair.engine}). Subject: {pair.state.subject}", flush=True)
    deadline = time.monotonic() + timeout
    shown = 0
    try:
        while time.monotonic() < deadline:
            pair.tick()
            for turn in pair.state.turns[shown:]:
                print(f"{'Buyer -> Supplier' if turn.direction == 'out' else 'Supplier -> Buyer'}: {turn.body.splitlines()[0]}", flush=True)
            shown = pair.state.turn_count
            if pair.outcome == "agreement":
                print("PASS: both inboxes exchanged real emails and reached a demo agreement.")
                return 0
            if pair.state.status.value == "awaiting":
                print("PAUSED: human approval is required. Use the web console for an interactive demo.")
                return 3
            if pair.state.status.value == "closed":
                print(pair.state.our_position.note)
                return 3
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(interval, remaining))
        print("TIMEOUT: demo stopped; check both inboxes and spam folders for the printed subject.")
        return 2
    finally:
        if pair.state.status.value != "closed":
            pair.stop()


if __name__ == "__main__":
    raise SystemExit(main())
