"""Platform Admin Banks page form API validation and normalized uniqueness."""
import pytest
pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")
pytest.importorskip("email_validator")

from fastapi.testclient import TestClient
from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import PlatformAdmin
from app.security import token_for_admin_otp
from sqlalchemy import select

client = TestClient(app)


def admin_headers(email="admin-bank-form@example.com"):
    settings.initial_admin_email = email
    with SessionLocal() as db:
        admin = db.scalar(select(PlatformAdmin).where(PlatformAdmin.email == email))
        if not admin:
            admin = PlatformAdmin(full_name="Bank Form Admin", email=email, password_hash="otp-only", is_active=True)
            db.add(admin); db.commit(); db.refresh(admin)
        return {"Authorization": f"Bearer {token_for_admin_otp(f'admin:{admin.id}')}"}


def bank_payload(**changes):
    values = {"name": "Admin Form Institution", "institution_type": "Public Sector Bank", "contact_email": "  AdminForm@Example.com ",
              "contact_phone": "+91 9876543210", "address": "1 Finance Street, Mumbai, Maharashtra", "ifsc_code": "", "license_number": "RBI-REG-123"}
    values.update(changes)
    return values


def test_admin_bank_form_requires_valid_registration_fields():
    headers = admin_headers()
    assert client.post("/api/v1/admin/banks", headers=headers, json={"name": "Only a name"}).status_code == 422
    assert client.post("/api/v1/admin/banks", headers=headers, json=bank_payload(contact_email="invalid-email")).status_code == 422
    assert client.post("/api/v1/admin/banks", headers=headers, json=bank_payload(contact_phone="12345")).status_code == 422
    assert client.post("/api/v1/admin/banks", headers=headers, json=bank_payload(ifsc_code="BAD-IFSC")).status_code == 422
    assert client.post("/api/v1/admin/banks", headers=headers, json=bank_payload(institution_type="unsupported")).status_code == 422
    assert client.post("/api/v1/admin/banks", headers=headers, json=bank_payload(license_number="")).status_code == 422


def test_admin_bank_form_normalizes_persists_and_prevents_duplicates():
    headers = admin_headers("admin-bank-form-valid@example.com")
    licensed = client.post("/api/v1/admin/banks", headers=headers, json=bank_payload(name="Admin Form Licensed Institution", institution_type="Private Sector Bank", contact_email="licensed-form@example.com", license_number="RBI-REG-9876"))
    assert licensed.status_code == 201 and licensed.json()["institution_type"] == "Private Sector Bank"
    other = bank_payload(name="Admin Form Other Institution", institution_type="Other", contact_email=" Other-Form@Example.com ", contact_phone="022-23456789", license_number="")
    created = client.post("/api/v1/admin/banks", headers=headers, json=other)
    assert created.status_code == 201, created.text
    result = created.json()
    assert result["status"] == "PENDING" and result["institution_type"] == "Other"
    assert result["contact_email"] == "other-form@example.com" and result["code"].startswith("BANK-")
    duplicate_email = client.post("/api/v1/admin/banks", headers=headers, json=bank_payload(name="A Different Institution", contact_email="OTHER-FORM@example.com", license_number="LIC-1234"))
    duplicate_name = client.post("/api/v1/admin/banks", headers=headers, json=bank_payload(name="ADMIN FORM OTHER INSTITUTION", contact_email="new-contact@example.com", institution_type="Other", license_number=""))
    assert duplicate_email.status_code == duplicate_name.status_code == 409
    listed = next(row for row in client.get("/api/v1/admin/banks", headers=headers).json() if row["id"] == result["id"])
    assert listed["contact_phone"] == other["contact_phone"] and listed["address"] == other["address"]
    assert listed["ifsc_code"] == "" and listed["license_number"] == ""
