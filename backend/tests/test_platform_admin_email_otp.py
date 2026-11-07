"""Focused coverage for the Platform Admin email-only OTP sign-in."""
from datetime import datetime, timedelta, timezone

import pytest
pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")
pytest.importorskip("email_validator")

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import PlatformAdmin, VerificationCode
from app.security import clear_failures

client = TestClient(app)
EMAIL = "configured-admin@example.com"


@pytest.fixture(autouse=True)
def configured_admin(monkeypatch):
    monkeypatch.setattr(settings, "initial_admin_email", EMAIL)
    monkeypatch.setattr(settings, "admin_otp_required", False)  # legacy switch cannot disable OTP
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "otp_resend_cooldown_seconds", 0)
    with SessionLocal() as db:
        db.query(VerificationCode).delete()
        db.query(PlatformAdmin).filter(PlatformAdmin.email == EMAIL).delete()
        db.add(PlatformAdmin(full_name="Configured Admin", email=EMAIL, password_hash="otp-only", is_active=True))
        db.commit()
    clear_failures("admin:" + EMAIL)
    clear_failures("adminotp-lock:" + EMAIL)
    yield
    with SessionLocal() as db:
        db.query(VerificationCode).delete()
        db.query(PlatformAdmin).filter(PlatformAdmin.email == EMAIL).delete()
        db.commit()


def issue_code(monkeypatch, code="123456"):
    monkeypatch.setattr("app.routers.admin.secrets.randbelow", lambda _limit: int(code))
    monkeypatch.setattr("app.routers.admin.deliver_otp", lambda *_args: "email")
    return client.post("/api/v1/admin/login", json={"email": f"  {EMAIL.upper()}  "})


def test_authorized_email_is_normalized_and_gets_otp_without_password(monkeypatch):
    response = issue_code(monkeypatch)
    assert response.status_code == 200
    assert response.json()["otp_required"] is True
    assert response.json()["email"] == EMAIL
    assert "access_token" not in response.json()
    assert "123456" not in response.text
    assert "password" not in response.text.lower()


def test_unauthorized_email_is_rejected_without_account_disclosure(monkeypatch):
    monkeypatch.setattr("app.routers.admin.deliver_otp", lambda *_args: pytest.fail("unauthorized address received OTP"))
    a = client.post("/api/v1/admin/login", json={"email": "other@example.com"})
    b = client.post("/api/v1/admin/login", json={"email": "missing@example.com"})
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()

def test_otp_delivery_failure_does_not_issue_a_login_code(monkeypatch):
    from app.services.mailer import OTPDeliveryError

    def fail_delivery(*_args):
        raise OTPDeliveryError("SMTP unavailable")

    monkeypatch.setattr("app.routers.admin.deliver_otp", fail_delivery)
    response = client.post("/api/v1/admin/login", json={"email": EMAIL})

    assert response.status_code == 503
    assert "access_token" not in response.json()
    with SessionLocal() as db:
        assert db.scalar(select(VerificationCode).where(VerificationCode.email.like("adminotp:%"))) is None

def test_expired_otp_is_rejected(monkeypatch):
    assert issue_code(monkeypatch).status_code == 200
    with SessionLocal() as db:
        row = db.scalar(select(VerificationCode).where(VerificationCode.used.is_(False)))
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    response = client.post("/api/v1/admin/login/verify-otp", json={"email": EMAIL, "code": "123456"})
    assert response.status_code == 401
    assert "access_token" not in response.text


def test_incorrect_otp_is_rejected_and_counted(monkeypatch):
    assert issue_code(monkeypatch).status_code == 200
    response = client.post("/api/v1/admin/login/verify-otp", json={"email": EMAIL, "code": "000000"})
    assert response.status_code == 401
    with SessionLocal() as db:
        row = db.scalar(select(VerificationCode).where(VerificationCode.used.is_(False)))
        assert row.attempts == 1


def test_otp_resend_cooldown_is_enforced(monkeypatch):
    monkeypatch.setattr(settings, "otp_resend_cooldown_seconds", 60)
    assert issue_code(monkeypatch).status_code == 200
    response = client.post("/api/v1/admin/login", json={"email": EMAIL})
    assert response.status_code == 429


def test_failed_attempt_rate_limit_blocks_further_otp_verification(monkeypatch):
    assert issue_code(monkeypatch).status_code == 200
    for _ in range(settings.login_max_failures):
        assert client.post("/api/v1/admin/login/verify-otp", json={"email": EMAIL, "code": "000000"}).status_code == 401
    assert client.post("/api/v1/admin/login/verify-otp", json={"email": EMAIL, "code": "123456"}).status_code == 429


def test_successful_otp_only_login_opens_admin_api(monkeypatch):
    assert issue_code(monkeypatch).status_code == 200
    result = client.post("/api/v1/admin/login/verify-otp", json={"email": EMAIL, "code": "123456"})
    assert result.status_code == 200
    token = result.json()["access_token"]
    assert client.get("/api/v1/admin/dashboard", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert client.get("/api/v1/admin/dashboard", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_non_otp_admin_token_cannot_access_platform_apis(monkeypatch):
    from app.security import token_for
    with SessionLocal() as db:
        admin = db.scalar(select(PlatformAdmin).where(PlatformAdmin.email == EMAIL))
        admin_id = admin.id
    response = client.get("/api/v1/admin/dashboard", headers={"Authorization": f"Bearer {token_for(f'admin:{admin_id}') }"})
    assert response.status_code == 401
