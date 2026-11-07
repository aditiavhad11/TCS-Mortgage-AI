"""Email delivery. Real email goes out only when SMTP is configured; nothing is faked.

- SMTP_HOST set          -> send by email (STARTTLS on 587, implicit TLS on 465 / SMTP_USE_SSL=true)
- development, no SMTP   -> OTPs are printed to the backend console (never in other environments)
- otherwise              -> OTPDeliveryError (the caller must fail closed)
"""
import logging, smtplib, ssl, re, threading, time
from email.message import EmailMessage
from app.config import settings

logger = logging.getLogger(__name__)
_backoff_lock = threading.Lock()
_limit_failures = 0
_limit_blocked_until = 0.0
_LIMIT_BACKOFF_BASE_SECONDS = 15 * 60
_LIMIT_BACKOFF_MAX_SECONDS = 24 * 60 * 60

def _safe_smtp_diagnostic(value: bytes | str) -> str:
    """Keep provider context in backend logs without recording addresses or OTPs."""
    text = value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)
    text = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "<email>", text)
    text = re.sub(r"(?<!\d)\d{6}(?!\d)", "<code>", text)
    # SMTP diagnostics are untrusted input; keep them single-line and bounded.
    return " ".join(text.split())[:1000]

def _is_sending_limit(response: str) -> bool:
    text = response.casefold()
    if any(term in text for term in (
        "daily user sending limit", "daily smtp relay", "sending quota",
        "sending limit exceeded", "limit for sending",
        "smtp relay limit exceeded", "daily sending limit",
    )):
        # A recipient's mailbox or receiving-rate quota is not our sender quota.
        if any(term in text for term in (
            "recipient quota", "recipient rate", "receiving email at a rate",
            "user you are trying to contact", "recipient's inbox",
        )):
            return False
        return True
    # Generic rate-limit text is only a sender limit when the diagnostic identifies
    # outbound sending or the authenticated account as the limited party.
    rate_limited = "rate limit exceeded" in text or "has been rate limited" in text
    sending_subject = any(term in text for term in (
        "sender", "sending", "outbound", "smtp relay", "your account", "your user",
    ))
    return rate_limited and sending_subject and not _is_recipient_rate_limit(text)

def _is_recipient_rate_limit(response: str) -> bool:
    text = response.casefold()
    return ("receiving email at a rate" in text or "recipient rate limit" in text
            or "recipient rate limit exceeded" in text
            or "recipient has been rate limited" in text
            or "user you are trying to contact" in text)

def _is_sender_policy_rejection(response: str) -> bool:
    text = response.casefold()
    return any(term in text for term in (
        "sender address", "sender domain", "unauthorized sender", "unauthorised sender",
        "sender not verified", "not a verified sender", "mail from address",
        "from address is not", "sending domain policy",
    ))

def _check_limit_backoff() -> None:
    remaining = _limit_blocked_until - time.monotonic()
    if remaining > 0:
        raise OTPDeliveryError(
            f"SMTP sending is paused after a provider sending-limit response. Try again in about {max(1, int(remaining / 60))} minutes."
        )

def _record_send_result(*, limit_rejected: bool = False) -> None:
    global _limit_failures, _limit_blocked_until
    with _backoff_lock:
        if not limit_rejected:
            _limit_failures = 0
            _limit_blocked_until = 0.0
            return
        _limit_failures += 1
        seconds = min(_LIMIT_BACKOFF_BASE_SECONDS * (2 ** (_limit_failures - 1)), _LIMIT_BACKOFF_MAX_SECONDS)
        _limit_blocked_until = time.monotonic() + seconds

class OTPDeliveryError(Exception):
    """Delivery failed or no channel is configured. The message never contains the code."""

def smtp_configured() -> bool:
    return bool(settings.smtp_host.strip())

def send_email(to_email: str, subject: str, body: str) -> None:
    """Send one plain-text email through the configured SMTP server. Raises OTPDeliveryError on any failure."""
    if not smtp_configured():
        raise OTPDeliveryError("SMTP is not configured (set SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM).")
    sender = (settings.smtp_from or settings.smtp_username).strip()
    if not sender:
        raise OTPDeliveryError("SMTP_FROM (or SMTP_USERNAME) must be set.")
    _check_limit_backoff()
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_email
    msg.set_content(body)
    host, port = settings.smtp_host.strip(), int(settings.smtp_port)
    use_ssl = settings.smtp_use_ssl or port == 465
    password = settings.smtp_password.replace(" ", "")  # Gmail app passwords are shown with spaces
    try:
        ctx = ssl.create_default_context()
        smtp = smtplib.SMTP_SSL(host, port, timeout=15, context=ctx) if use_ssl else smtplib.SMTP(host, port, timeout=15)
        with smtp as s:
            if not use_ssl:
                s.starttls(context=ctx)
            if settings.smtp_username:
                s.login(settings.smtp_username.strip(), password)
            s.send_message(msg)
        _record_send_result()
    except smtplib.SMTPAuthenticationError as e:
        logger.error("SMTP authentication rejected (response code %s): %s", e.smtp_code, _safe_smtp_diagnostic(e.smtp_error))
        raise OTPDeliveryError("SMTP authentication was rejected. Check the configured account and SMTP credentials.") from e
    except smtplib.SMTPRecipientsRefused as e:
        diagnostics = "; ".join(_safe_smtp_diagnostic(value[1]) for value in e.recipients.values())
        logger.error("SMTP recipient rejected: %s", diagnostics[:1000])
        raise OTPDeliveryError("The SMTP provider rejected the recipient address. Check that address or the recipient's mail policy.") from e
    except smtplib.SMTPResponseException as e:
        response = e.smtp_error.decode("utf-8", "replace") if isinstance(e.smtp_error, bytes) else str(e.smtp_error)
        diagnostic = _safe_smtp_diagnostic(e.smtp_error)
        logger.error("SMTP provider rejected message (response code %s): %s", e.smtp_code, diagnostic)
        if _is_recipient_rate_limit(response):
            raise OTPDeliveryError(f"SMTP provider is rate limiting the recipient (response code {e.smtp_code}). Wait before requesting another code.") from e
        if _is_sending_limit(response):
            _record_send_result(limit_rejected=True)
            raise OTPDeliveryError(f"SMTP provider sending limit reached (response code {e.smtp_code}). Delivery is paused temporarily; check the provider's quota and retry after its reset window.") from e
        if _is_sender_policy_rejection(response):
            raise OTPDeliveryError(f"SMTP provider rejected the sender or sender policy (response code {e.smtp_code}). Verify the sender identity and account policy.") from e
        raise OTPDeliveryError(f"SMTP provider rejected the message (response code {e.smtp_code}). Check the redacted backend diagnostic for the specific reason.") from e
    except Exception as e:
        raise OTPDeliveryError(f"SMTP delivery failed ({type(e).__name__}). Check SMTP_HOST / SMTP_PORT and network access.") from e

def deliver_otp(to_email: str, code: str, purpose: str, minutes: int) -> str:
    """Returns the channel used: 'email' or 'console'."""
    if smtp_configured():
        send_email(to_email, f"Your {settings.app_name} verification code",
                   f"Your one-time code for {purpose} is {code}.\n\nIt expires in {minutes} minutes and can be used only once. Never share this code with anyone.\n\nIf you did not request this code, you can ignore this email.")
        return "email"
    if settings.environment.lower() == "development":
        print(f"[DEV OTP] purpose={purpose} email={to_email} code={code} expires_minutes={minutes}")
        return "console"
    raise OTPDeliveryError("No OTP delivery channel is configured (set SMTP_HOST).")
