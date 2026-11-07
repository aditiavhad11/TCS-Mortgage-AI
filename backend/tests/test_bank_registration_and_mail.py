"""SMTP transport and bank registration OTP -> admin decision -> invitation workflow."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.config import settings
from app.database import SessionLocal
from app.models import PlatformAdmin
from app.security import hash_password, token_for_admin_otp
from app.services import mailer

client = TestClient(app)
PW = "BankAdmin-Test-Password-2026!"
CODE = "112233"

@pytest.fixture(autouse=True)
def reset_mailer_backoff():
    mailer._limit_failures = 0
    mailer._limit_blocked_until = 0.0
    yield
    mailer._limit_failures = 0
    mailer._limit_blocked_until = 0.0

def H(token): return {"Authorization": f"Bearer {token}"}

def fields(n):
    return {"bank_name": f"OTP Registration Bank {n}", "institution_type": "NBFC", "contact_email": f"reg{n}@bank.example",
            "contact_phone": "9876543210", "address": "1 MG Road, Pune, Maharashtra", "license_number": "NBFC-12345", "ifsc_code": ""}

def admin_token():
    email = "reg-platform-admin@example.com"
    settings.initial_admin_email = email
    with SessionLocal() as db:
        admin = db.scalar(select(PlatformAdmin).where(PlatformAdmin.email == email))
        if not admin:
            admin = PlatformAdmin(full_name="Reg Admin", email=email, password_hash="otp-only", is_active=True)
            db.add(admin); db.commit(); db.refresh(admin)
        return token_for_admin_otp(f"admin:{admin.id}")

def complete_registration(monkeypatch, data):
    monkeypatch.setattr(settings, "otp_resend_cooldown_seconds", 0)
    monkeypatch.setattr("app.routers.bank_registration.secrets.randbelow", lambda _n: int(CODE))
    monkeypatch.setattr("app.routers.bank_registration.deliver_otp", lambda *_args: "email")
    start = client.post("/api/v1/bank-admin/register", json=data)
    assert start.status_code == 200, start.text
    verified = client.post("/api/v1/bank-admin/register/verify-otp", json={"contact_email": data["contact_email"], "code": CODE})
    assert verified.status_code == 200, verified.text
    return client.post("/api/v1/bank-admin/register/complete", json={**data, "registration_token": verified.json()["registration_token"]})


class FakeSMTP:
    sent = []
    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def starttls(self, **k): pass
    def login(self, u, p): FakeSMTP.login_args = (u, p)
    def send_message(self, m): FakeSMTP.sent.append(m)

def test_otp_goes_to_email_when_smtp_configured(monkeypatch):
    FakeSMTP.sent = []
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com"); monkeypatch.setattr(settings, "smtp_username", "me@example.com")
    monkeypatch.setattr(settings, "smtp_password", "abcd efgh ijkl mnop"); monkeypatch.setattr(settings, "smtp_from", "me@example.com")
    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    assert mailer.deliver_otp("cust@example.com", "123456", "email verification", 10) == "email"
    assert FakeSMTP.sent[0]["To"] == "cust@example.com" and "123456" in FakeSMTP.sent[0].get_content()
    assert FakeSMTP.sent[0]["From"] == "me@example.com"
    assert FakeSMTP.login_args[1] == "abcdefghijklmnop"

def test_smtp_user_alias_and_sender_fallback(monkeypatch):
    from app.config import Settings

    monkeypatch.delenv("SMTP_USERNAME", raising=False)
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "465")
    monkeypatch.setenv("SMTP_USER", "verified@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "app-password")
    monkeypatch.setenv("SMTP_FROM", "")
    monkeypatch.setenv("SMTP_USE_SSL", "true")
    configured = Settings(
        _env_file=None,
    )
    assert configured.smtp_username == "verified@example.com"
    assert configured.smtp_port == 465 and configured.smtp_use_ssl is True
    assert configured.smtp_password == "app-password"

    FakeSMTP.sent = []
    monkeypatch.setattr(settings, "smtp_host", configured.smtp_host)
    monkeypatch.setattr(settings, "smtp_port", configured.smtp_port)
    monkeypatch.setattr(settings, "smtp_use_ssl", configured.smtp_use_ssl)
    monkeypatch.setattr(settings, "smtp_username", configured.smtp_username)
    monkeypatch.setattr(settings, "smtp_password", configured.smtp_password)
    monkeypatch.setattr(settings, "smtp_from", "")
    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", FakeSMTP)

    assert mailer.deliver_otp("customer@example.com", "123456", "verification", 10) == "email"
    assert FakeSMTP.sent[0]["From"] == "verified@example.com"
    assert FakeSMTP.login_args == ("verified@example.com", "app-password")

def test_smtp_failure_is_reported_not_faked(monkeypatch):
    class Boom(FakeSMTP):
        def __init__(self, *a, **k): raise OSError("down")
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com"); monkeypatch.setattr(settings, "smtp_from", "me@example.com"); monkeypatch.setattr(mailer.smtplib, "SMTP", Boom)
    with pytest.raises(mailer.OTPDeliveryError): mailer.deliver_otp("a@b.com", "111111", "x", 10)

def test_smtp_content_rejection_exposes_only_response_code(monkeypatch, caplog):
    class RejectingSMTP(FakeSMTP):
        def send_message(self, _message):
            raise mailer.smtplib.SMTPDataError(550, b"Daily user sending limit exceeded. private server diagnostic")

    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_from", "me@example.com")
    monkeypatch.setattr(settings, "smtp_use_ssl", True)
    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", RejectingSMTP)

    with pytest.raises(mailer.OTPDeliveryError, match="sending limit reached") as error:
        mailer.deliver_otp("a@b.com", "111111", "x", 10)

    assert "private server diagnostic" not in str(error.value)
    assert "response code 550" in caplog.text
    assert "Daily user sending limit exceeded. private server diagnostic" in caplog.text

def test_smtp_policy_rejection_does_not_expose_provider_response(monkeypatch):
    class RejectingSMTP(FakeSMTP):
        def send_message(self, _message):
            raise mailer.smtplib.SMTPDataError(550, b"private recipient policy diagnostic")

    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_from", "me@example.com")
    monkeypatch.setattr(settings, "smtp_use_ssl", True)
    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", RejectingSMTP)

    with pytest.raises(mailer.OTPDeliveryError, match="rejected the message") as error:
        mailer.deliver_otp("a@b.com", "111111", "x", 10)

    assert "private recipient policy diagnostic" not in str(error.value)

def test_smtp_diagnostic_redacts_addresses_codes_and_newlines():
    diagnostic = mailer._safe_smtp_diagnostic(
        b"550 denied for admin@example.com; code 123456\r\nsecond line"
    )
    assert diagnostic == "550 denied for <email>; code <code> second line"

@pytest.mark.parametrize(("diagnostic", "message"), [
    (b"550 5.4.5 Daily user sending limit exceeded", "sending limit reached"),
    (b"550 5.7.1 The recipient is receiving email at a rate that prevents delivery", "rate limiting the recipient"),
    (b"550 recipient rate limit exceeded", "rate limiting the recipient"),
    (b"550 rate limit exceeded", "rejected the message"),
    (b"550 quota exceeded", "rejected the message"),
    (b"550 5.7.1 Recipient domain policy prohibits this message", "rejected the message"),
    (b"550 5.7.1 Your account sending rate limit exceeded", "sending limit reached"),
    (b"550 5.7.1 Sender address is not a verified sender", "rejected the sender or sender policy"),
    (b"550 5.1.1 The recipient account does not exist", "rejected the message"),
])
def test_smtp_550_reasons_are_classified_from_diagnostic(monkeypatch, diagnostic, message):
    class RejectingSMTP(FakeSMTP):
        def send_message(self, _message):
            raise mailer.smtplib.SMTPDataError(550, diagnostic)

    mailer._limit_failures = 0
    mailer._limit_blocked_until = 0.0
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_from", "me@example.com")
    monkeypatch.setattr(settings, "smtp_use_ssl", True)
    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", RejectingSMTP)
    with pytest.raises(mailer.OTPDeliveryError, match=message) as error:
        mailer.send_email("private@example.com", "subject", "body")
    assert "private@example.com" not in str(error.value)
    assert "5.7.1" not in str(error.value)

def test_sending_limit_rejection_applies_bounded_backoff(monkeypatch):
    now = [1000.0]
    calls = []
    class RejectingSMTP(FakeSMTP):
        def send_message(self, _message):
            calls.append("send")
            raise mailer.smtplib.SMTPDataError(550, b"Daily user sending limit exceeded")

    mailer._limit_failures = 0
    mailer._limit_blocked_until = 0.0
    monkeypatch.setattr(mailer.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_from", "me@example.com")
    monkeypatch.setattr(settings, "smtp_use_ssl", True)
    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", RejectingSMTP)
    with pytest.raises(mailer.OTPDeliveryError, match="sending limit reached"):
        mailer.send_email("private@example.com", "subject", "body")
    with pytest.raises(mailer.OTPDeliveryError, match="SMTP sending is paused"):
        mailer.send_email("private@example.com", "subject", "body")
    assert calls == ["send"]
    now[0] += mailer._LIMIT_BACKOFF_BASE_SECONDS
    with pytest.raises(mailer.OTPDeliveryError, match="sending limit reached"):
        mailer.send_email("private@example.com", "subject", "body")
    assert calls == ["send", "send"]

def test_register_reject_resubmit_then_approve_and_invite(monkeypatch):
    sent = []; monkeypatch.setattr("app.routers.bank_registration.send_email", lambda to, subject, body: sent.append((to, subject, body)))
    first = complete_registration(monkeypatch, fields(1)); assert first.status_code == 201, first.text
    bank_id = first.json()["id"]
    assert "id" not in client.post("/api/v1/bank-admin/register", json=fields(1)).json()
    assert client.post("/api/v1/bank-admin/register", json=fields(1)).status_code == 409
    token = admin_token()
    assert client.get("/api/v1/admin/banks", headers={}).status_code in (401, 403)
    detail = client.get(f"/api/v1/admin/banks/{bank_id}", headers=H(token)).json()
    assert detail["status"] == "PENDING" and detail["institution_type"] == "NBFC"
    reject_path = f"/api/v1/admin/banks/{bank_id}/decision"
    assert client.post(reject_path, headers=H(token), json={"decision": "REJECTED", "reason": "no"}).status_code == 422
    rejected = client.post(reject_path, headers=H(token), json={"decision": "REJECTED", "reason": "Please correct the RBI license details."})
    assert rejected.status_code == 200 and rejected.json()["status"] == "REJECTED"
    assert "RBI license" in sent[-1][2]
    corrected = fields(1); corrected["license_number"] = "NBFC-CORRECTED"
    start = client.post("/api/v1/bank-admin/register", json=corrected)
    assert start.status_code == 200
    assert "previous_rejection_reason" not in start.json()
    otp_check = client.post("/api/v1/bank-admin/register/verify-otp", json={"contact_email": corrected["contact_email"], "code": CODE})
    assert "RBI license" in otp_check.json()["previous_rejection_reason"]
    resubmitted = client.post("/api/v1/bank-admin/register/complete", json={**corrected, "registration_token": otp_check.json()["registration_token"]})
    assert resubmitted.status_code == 201 and resubmitted.json()["id"] == bank_id and resubmitted.json()["status"] == "PENDING"
    # A second institution follows the same verified email workflow, then receives the existing invitation.
    second = complete_registration(monkeypatch, fields(3)); assert second.status_code == 201
    approved = client.post(f"/api/v1/admin/banks/{second.json()['id']}/decision", headers=H(token), json={"decision": "APPROVED"}).json()
    assert approved["status"] == "APPROVED" and approved["notification_emailed"] and approved["invitation_token"] is None
    invite_token = sent[-1][2].split("invite=")[1].split()[0]
    assert client.post("/api/v1/bank-admin/accept-invitation", json={"token": invite_token, "password": PW}).status_code == 200
    assert client.post("/api/v1/bank-admin/login", json={"email": "reg3@bank.example", "password": PW}).status_code == 200

def test_approval_without_email_never_returns_invitation_token(monkeypatch):
    from app.services.mailer import OTPDeliveryError
    def fail(*args): raise OTPDeliveryError("no smtp")
    monkeypatch.setattr("app.routers.bank_registration.send_email", fail)
    bank = complete_registration(monkeypatch, fields(4)); assert bank.status_code == 201
    result = client.post(f"/api/v1/admin/banks/{bank.json()['id']}/decision", headers=H(admin_token()), json={"decision": "APPROVED"}).json()
    assert result["notification_emailed"] is False and result["invitation_token"] is None
