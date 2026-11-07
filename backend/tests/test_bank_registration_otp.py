"""Registration and approval tests for institution-level bank onboarding."""
import pytest
from datetime import datetime, timedelta, timezone
pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")
pytest.importorskip("email_validator")

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import Bank, BankAdmin, PlatformAdmin, VerificationCode
from app.security import hash_password, token_for_admin_otp, token_for

client = TestClient(app)
CODE = "246810"
PW = "Bank-Test-Password-2026!"


@pytest.fixture(autouse=True)
def onboarding_settings(monkeypatch):
    monkeypatch.setattr(settings, "otp_resend_cooldown_seconds", 0)
    monkeypatch.setattr(settings, "otp_expiry_minutes", 10)
    monkeypatch.setattr(settings, "environment", "development")


def payload(name="Example Institution", email="official@example.com", **changes):
    result = {
        "bank_name": name,
        "institution_type": "Private Bank",
        "contact_email": email,
        "contact_phone": "+91 9876543210",
        "address": "12 Finance Road, Mumbai, Maharashtra",
        "ifsc_code": "ABCD0123456",
        "license_number": "RBI-LIC-2026",
    }
    result.update(changes)
    return result


def request_code(monkeypatch, data):
    sent = []
    monkeypatch.setattr("app.routers.bank_registration.secrets.randbelow", lambda _n: int(CODE))
    monkeypatch.setattr("app.routers.bank_registration.deliver_otp", lambda email, code, *_args: sent.append((email, code)) or "email")
    response = client.post("/api/v1/bank-admin/register", json=data)
    return response, sent


def admin_headers(monkeypatch, email):
    monkeypatch.setattr(settings, "initial_admin_email", email)
    with SessionLocal() as db:
        admin = db.scalar(select(PlatformAdmin).where(PlatformAdmin.email == email))
        if not admin:
            admin = PlatformAdmin(full_name="Registration Admin", email=email, password_hash="otp-only", is_active=True)
            db.add(admin); db.commit(); db.refresh(admin)
        return {"Authorization": f"Bearer {token_for_admin_otp(f'admin:{admin.id}')}"}


def test_invalid_registration_fields_are_rejected(monkeypatch):
    invalid = payload("Invalid Institution", "invalid-fields@example.com", institution_type="Unknown", ifsc_code="NOT-IFSC")
    response = client.post("/api/v1/bank-admin/register", json=invalid)
    assert response.status_code == 422
    missing_license = payload("Missing License Institution", "missing-license@example.com", license_number="")
    assert client.post("/api/v1/bank-admin/register", json=missing_license).status_code == 422
    other, _ = request_code(monkeypatch, payload("Other Institution", "other-type@example.com", institution_type="Other", license_number=""))
    assert other.status_code == 200


def test_registration_verifies_official_email_before_saving_pending_bank(monkeypatch):
    data = payload("OTP Verified Bank", "otp-verified@example.com")
    response, sent = request_code(monkeypatch, data)
    assert response.status_code == 200 and response.json()["otp_required"] is True
    assert sent == [(data["contact_email"], CODE)]
    assert "id" not in response.json()  # no registration row is persisted before verification
    wrong = client.post("/api/v1/bank-admin/register/verify-otp", json={**data, "code": "000000"})
    assert wrong.status_code == 401
    verified = client.post("/api/v1/bank-admin/register/verify-otp", json={"contact_email": " OTP-VERIFIED@example.com ", "code": CODE})
    assert verified.status_code == 200 and verified.json()["email"] == "otp-verified@example.com"
    saved = client.post("/api/v1/bank-admin/register/complete", json={**data, "contact_email": " OTP-VERIFIED@example.com ", "registration_token": verified.json()["registration_token"]})
    assert saved.status_code == 201 and saved.json()["status"] == "PENDING"
    with SessionLocal() as db:
        bank = db.get(Bank, saved.json()["id"])
        assert bank and bank.institution_type == "Private Bank" and bank.ifsc_code == "ABCD0123456"
        assert bank.contact_email == data["contact_email"] and bank.status == "PENDING"


def test_expired_registration_otp_cannot_create_bank(monkeypatch):
    data = payload("Expired OTP Bank", "expired-otp@example.com")
    response, _ = request_code(monkeypatch, data)
    assert response.status_code == 200
    with SessionLocal() as db:
        row = db.scalar(select(VerificationCode).where(VerificationCode.email.like("bankregotp:%"), VerificationCode.used.is_(False)).order_by(VerificationCode.id.desc()))
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    expired = client.post("/api/v1/bank-admin/register/verify-otp", json={"contact_email": data["contact_email"], "code": CODE})
    assert expired.status_code == 401
    with SessionLocal() as db:
        assert db.scalar(select(Bank.id).where(Bank.contact_email == data["contact_email"])) is None


def test_duplicate_institution_name_or_normalized_email_is_rejected(monkeypatch):
    with SessionLocal() as db:
        db.add(Bank(name="Duplicate Bank", code="BANK-DUPLICATE", contact_email="Duplicate@Example.com", status="PENDING")); db.commit()
    same_email = client.post("/api/v1/bank-admin/register", json=payload("Different Name", " duplicate@example.com "))
    same_name = client.post("/api/v1/bank-admin/register", json=payload("DUPLICATE BANK", "different@example.com"))
    assert same_email.status_code == same_name.status_code == 409


def test_platform_admin_approval_rejection_and_resubmission(monkeypatch):
    data = payload("Resubmitting Bank", "resubmit@example.com")
    issued, _ = request_code(monkeypatch, data)
    assert "previous_rejection_reason" not in issued.json()
    verification = client.post("/api/v1/bank-admin/register/verify-otp", json={"contact_email": data["contact_email"], "code": CODE}).json()
    bank_id = client.post("/api/v1/bank-admin/register/complete", json={**data, "registration_token": verification["registration_token"]}).json()["id"]
    reject_path = f"/api/v1/admin/banks/{bank_id}/decision"
    assert client.post(reject_path, json={"decision": "REJECTED", "reason": "Incorrect paperwork"}).status_code == 401
    headers = admin_headers(monkeypatch, "platform-registration-admin@example.com")
    short_reason = client.post(reject_path, headers=headers, json={"decision": "REJECTED", "reason": "No"})
    assert short_reason.status_code == 422
    rejected = client.post(reject_path, headers=headers, json={"decision": "REJECTED", "reason": "Please provide the current RBI license."})
    assert rejected.status_code == 200 and rejected.json()["status"] == "REJECTED"
    row = next(bank for bank in client.get("/api/v1/admin/banks", headers=headers).json() if bank["id"] == bank_id)
    assert row["institution_type"] == "Private Bank" and row["contact_email"] == data["contact_email"]
    assert row["contact_phone"] == data["contact_phone"] and row["ifsc_code"] == data["ifsc_code"]
    detail = client.get(f"/api/v1/admin/banks/{bank_id}", headers=headers).json()
    assert detail["address"] == data["address"] and detail["license_number"] == data["license_number"]
    updated = payload("Resubmitting Bank Corrected", "resubmit@example.com", license_number="RBI-LIC-CORRECTED")
    next_code, _ = request_code(monkeypatch, updated)
    assert next_code.status_code == 200
    corrected_email = client.post("/api/v1/bank-admin/register/verify-otp", json={"contact_email": updated["contact_email"], "code": CODE})
    assert corrected_email.json()["previous_rejection_reason"] == "Please provide the current RBI license."
    resubmitted = client.post("/api/v1/bank-admin/register/complete", json={**updated, "registration_token": corrected_email.json()["registration_token"]})
    assert resubmitted.status_code == 201 and resubmitted.json()["id"] == bank_id and resubmitted.json()["status"] == "PENDING"
    approved = client.post(reject_path, headers=headers, json={"decision": "APPROVED"})
    assert approved.status_code == 200 and approved.json()["status"] == "APPROVED"


def test_bank_admin_access_is_blocked_until_approved_then_existing_login_works(monkeypatch):
    with SessionLocal() as db:
        pending = Bank(name="Pending Access Bank", code="BANK-PENDING-ACCESS", contact_email="pending-access@example.com", status="PENDING")
        rejected = Bank(name="Rejected Access Bank", code="BANK-REJECTED-ACCESS", contact_email="rejected-access@example.com", status="REJECTED")
        approved = Bank(name="Approved Access Bank", code="BANK-APPROVED-ACCESS", contact_email="approved-access@example.com", status="APPROVED")
        db.add_all([pending, rejected, approved]); db.flush()
        pending_admin = BankAdmin(bank_id=pending.id, full_name="Pending User", email="pending-user@example.com", password_hash=hash_password(PW), is_active=True)
        rejected_admin = BankAdmin(bank_id=rejected.id, full_name="Rejected User", email="rejected-user@example.com", password_hash=hash_password(PW), is_active=True)
        approved_admin = BankAdmin(bank_id=approved.id, full_name="Approved User", email="approved-user@example.com", password_hash=hash_password(PW), is_active=True)
        db.add_all([pending_admin, rejected_admin, approved_admin]); db.commit()
        pending_id, rejected_id, approved_bank_id = pending_admin.id, rejected_admin.id, approved.id
    blocked_login = client.post("/api/v1/bank-admin/login", json={"email": "pending-user@example.com", "password": PW})
    assert blocked_login.status_code == 403
    blocked_api = client.get("/api/v1/bank-admin/me", headers={"Authorization": f"Bearer {token_for(f'bankadmin:{pending_id}')}"})
    assert blocked_api.status_code == 403
    assert client.post("/api/v1/bank-admin/login", json={"email": "rejected-user@example.com", "password": PW}).status_code == 403
    assert client.get("/api/v1/bank-admin/me", headers={"Authorization": f"Bearer {token_for(f'bankadmin:{rejected_id}')}"}).status_code == 403
    login = client.post("/api/v1/bank-admin/login", json={"email": "approved-user@example.com", "password": PW})
    assert login.status_code == 200 and login.json()["bank_admin"]["bank"]["id"] == approved_bank_id
