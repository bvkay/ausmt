"""Config-driven plain-text mail sender for the self-serve key path (K3). stdlib smtplib ONLY — no
new dependency, no third-party mail client. The gateway house style is stdlib-lean and fail-closed;
this module keeps that: a send is best-effort, every failure is logged WITHOUT the key, and the
caller (the request-key endpoint) still returns the neutral 202 whatever happens here.

Transport is chosen by PORT, the conventional SMTP mapping:
  * 465          -> implicit TLS from the first byte (smtplib.SMTP_SSL);
  * 587 / 25 / * -> plaintext connect then STARTTLS upgrade (smtplib.SMTP + starttls()).
STARTTLS is REQUIRED on the non-465 path (a mailbox provider like VentraIP offers it): if the server
does not advertise it, the send fails closed rather than falling back to cleartext auth.

SECURITY: the key is a bearer secret. It appears ONLY in the message body handed to the SMTP server;
it is NEVER written to a log line here (a failure logs the recipient + the error, never the key), and
smtp_pass never leaves this module except into the authenticated session.
"""
from __future__ import annotations

import logging
import re
import smtplib
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

logger = logging.getLogger("ausmt.gateway.mailer")

# Syntactic email check (K1). Deliberately conservative and stdlib-only: one @, no whitespace, a dot
# in the domain. This is a FORMAT gate, not a deliverability or existence check (the endpoint never
# reveals whether an address exists — that is the whole anti-enumeration point). It only needs to
# reject obvious junk before an address reaches the rate-limit store and the mailer.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# An RFC 5321 path caps at 254 chars; anything longer is not a real address.
_EMAIL_MAX_LEN = 254


def is_syntactic_email(email: str) -> bool:
    """True for a syntactically plausible single email address (one @, no spaces, a dotted domain,
    <= 254 chars). Not a deliverability check — see the module note on why existence is never probed."""
    email = (email or "").strip()
    return 0 < len(email) <= _EMAIL_MAX_LEN and _EMAIL_RE.fullmatch(email) is not None


def _build_message(cfg, *, to_email: str, key: str, expires_utc: str, allowance: int) -> EmailMessage:
    """The plain-text issued-key email (K3): what the key is, its expiry and allowance, the submit
    page link, a one-line what-happens-next, and Reply-To set to the From address. No em dashes in any
    user-facing string (house rule). Kept as a pure builder so a test can assert the body without a
    live SMTP server."""
    msg = EmailMessage()
    msg["From"] = cfg.mail_from
    msg["To"] = to_email
    msg["Reply-To"] = cfg.mail_from
    msg["Subject"] = "Your AusMT submission key"
    msg["Date"] = formatdate(localtime=False)
    # A Message-ID from the From-address domain (falls back to a generated domain if parsing fails).
    domain = cfg.mail_from.split("@")[-1].strip(">") if "@" in cfg.mail_from else "ausmt.local"
    msg["Message-ID"] = make_msgid(domain=domain)

    link_line = (
        f"Submit your data package here: {cfg.submit_page_url}\n"
        if cfg.submit_page_url.strip() else ""
    )
    body = (
        "Hello,\n\n"
        "You (or someone using this email address) requested an AusMT submission key.\n\n"
        "Your submission key is:\n\n"
        f"    {key}\n\n"
        "Use it by sending it in the X-AusMT-Submit-Key header when you upload, and submit\n"
        "with THIS email address as the submitter email (the key is bound to it).\n\n"
        f"This key expires on {expires_utc} and allows up to {allowance} submission(s).\n\n"
        f"{link_line}"
        "What happens next: after you upload, a curator reviews your package before it is published.\n\n"
        "If you did not request this key, you can ignore this message and the key will go unused.\n\n"
        f"Reply to {cfg.mail_from} if you need help.\n"
    )
    msg.set_content(body)
    return msg


def send_key_email(cfg, *, to_email: str, key: str, expires_utc: str, allowance: int) -> bool:
    """Send the issued-key email. Returns True on a successful hand-off to the SMTP server, False on
    ANY failure (logged without the key). Never raises: the caller's 202 must not depend on mail.

    Fail-closed on an unconfigured mailer: if mail is not configured the caller should not reach here,
    but this guards anyway (returns False, logs disabled)."""
    if not cfg.mail_configured:
        logger.info("mailer: SMTP not configured — issuance disabled, no mail sent")
        return False
    msg = _build_message(cfg, to_email=to_email, key=key, expires_utc=expires_utc, allowance=allowance)
    try:
        if int(cfg.smtp_port) == 465:
            with smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, timeout=30) as smtp:
                _auth_and_send(smtp, cfg, msg)
        else:
            with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
                _auth_and_send(smtp, cfg, msg)
    except Exception as exc:  # noqa: BLE001 -- a mail failure must never break the 202; log sans key
        logger.warning("mailer: send to %s failed (%s: %s) — key NOT logged",
                       to_email, type(exc).__name__, exc)
        return False
    return True


def _auth_and_send(smtp: smtplib.SMTP, cfg, msg: EmailMessage) -> None:
    """Authenticate (only when a user is configured — an open relay / localhost port needs none) and
    send. smtp_pass is used here and never logged."""
    if cfg.smtp_user:
        smtp.login(cfg.smtp_user, cfg.smtp_pass)
    smtp.send_message(msg)
