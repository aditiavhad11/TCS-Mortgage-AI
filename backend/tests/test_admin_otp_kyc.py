"""PBKDF2 hashing + legacy upgrade, 8-character passwords, Platform Admin OTP login, and KYC verification.
Requires fastapi, SQLAlchemy, email-validator. Run: pytest tests/test_admin_otp_kyc.py -v
Tesseract is NOT required: uploads of blank images are accepted with OCR status NEEDS_REVIEW.
"""
import base64, hashlib, io, os
import pytest
pytest.importorskip("fastapi"); pytest.importorskip("sqlalchemy"); pytest.importorskip("email_validator")
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from app.main import app
from app.config import settings, Settings, validate_runtime, MIN_PASSWORD_LENGTH
from app.database import SessionLocal
from app.models import Customer, PlatformAdmin, Bank
from sqlalchemy import select
from app.security import hash_password, verify_password, needs_rehash

client = TestClient(app)
PW = "Str0ng-Passw0rd!"
def H(tok): return {"Authorization": f"Bearer {tok}"}

def make_admin(email):
    with SessionLocal() as db:
        db.add(PlatformAdmin(full_name="OTP Admin", email=email, password_hash=hash_password(PW), is_active=True)); db.commit()

def tiny_png():
    b = io.BytesIO(); Image.new("RGB", (40, 40), "white").save(b, "PNG"); return b.getvalue()

# ---------------- PBKDF2 / password policy ----------------
def test_new_hashes_are_pbkdf2_and_legacy_scrypt_still_verifies():
    h = hash_password("Abcdefg1")
    assert h.startswith("pbkdf2_sha256$") and verify_password("Abcdefg1", h) and not verify_password("abcdefg1", h)
    salt = os.urandom(16); dk = hashlib.scrypt(b"Legacy-Pass-1", salt=salt, n=2**14, r=8, p=1, dklen=32)
    legacy = "scrypt$%d$%d$%d$%s$%s" % (2**14, 8, 1, base64.b64encode(salt).decode(), base64.b64encode(dk).decode())
    assert verify_password("Legacy-Pass-1", legacy) and needs_rehash(legacy) and not needs_rehash(h)

def test_legacy_hash_is_upgraded_to_pbkdf2_on_customer_login():
    salt = os.urandom(16); dk = hashlib.scrypt(b"Legacy-Pass-1", salt=salt, n=2**14, r=8, p=1, dklen=32)
    legacy = "scrypt$%d$%d$%d$%s$%s" % (2**14, 8, 1, base64.b64encode(salt).decode(), base64.b64encode(dk).decode())
    with SessionLocal() as db:
        db.add(Customer(full_name="Legacy User", email="legacy-user@example.com", mobile="9999999999", password_hash=legacy, is_verified=True)); db.commit()
    assert client.post("/api/v1/auth/login", json={"email": "legacy-user@example.com", "password": "wrong-password"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": "legacy-user@example.com", "password": "Legacy-Pass-1"}).status_code == 200
    with SessionLocal() as db:
        stored = db.scalar(select(Customer.password_hash).where(Customer.email == "legacy-user@example.com"))
    assert stored.startswith("pbkdf2_sha256$")
    assert client.post("/api/v1/auth/login", json={"email": "legacy-user@example.com", "password": "Legacy-Pass-1"}).status_code == 200  # still works after upgrade

def test_password_minimum_is_eight_characters():
    assert MIN_PASSWORD_LENGTH == 8
    reg = lambda pw: client.post("/api/v1/auth/register", json={"full_name": "Short Pw", "email": f"pw{len(pw)}@example.com", "mobile": "9999999999", "password": pw})
    assert reg("a" * 7).status_code == 422
    assert reg("a" * 8).status_code == 200
    assert reg("a" * 129).status_code == 422                                                         # upper bound unchanged

def test_production_requires_otp_channel_and_strong_iterations():
    base = dict(environment="production", jwt_secret_key="x" * 40)
    with pytest.raises(RuntimeError): validate_runtime(Settings(**base, pbkdf2_iterations=1000, admin_otp_required=False))
    with pytest.raises(RuntimeError): validate_runtime(Settings(**base, pbkdf2_iterations=600_000, admin_otp_required=True, smtp_host=""))
    validate_runtime(Settings(**base, pbkdf2_iterations=600_000, admin_otp_required=True, smtp_host="smtp.example.com"))
    validate_runtime(Settings(**base, pbkdf2_iterations=600_000, admin_otp_required=False, smtp_host="smtp.example.com"))

# Platform Admin email OTP cases are covered in test_platform_admin_email_otp.py.

# ---------------- KYC ----------------
def test_kyc_workflow_and_resets(monkeypatch):
    monkeypatch.setattr("secrets.randbelow", lambda n: 123456)
    monkeypatch.setattr("app.routers.documents.extract_text", lambda path: ("KYC review fixture evidence", "COMPLETED", "Deterministic OCR fixture"))
    assert client.post("/api/v1/auth/register", json={"full_name": "Kyc Customer", "email": "kyc-customer@example.com", "mobile": "9999999999", "password": PW}).status_code == 200
    cust = client.post("/api/v1/auth/verify-otp", json={"email": "kyc-customer@example.com", "code": "123456"}).json()["access_token"]
    with SessionLocal() as db:
        bank = db.scalar(select(Bank).where(Bank.code == "KYC-DEMO"))
        if bank is None: db.add(Bank(name="KYC Demo Bank", code="KYC-DEMO", status="APPROVED"))
        else: bank.status = "APPROVED"
        db.commit()
    app_payload = {"lender_name": "KYC-DEMO", "product_name": "Home Loan", "property_address": "Pune, Maharashtra", "property_value": 5000000, "requested_loan": 4000000, "annual_income": 1200000, "monthly_debt": 0, "interest_rate": 9.0, "tenure_years": 20,
        "details": {"applicant": {"full_name": "Kyc Customer", "date_of_birth": "1990-01-01", "mobile": "9999999999", "email": "kyc-customer@example.com", "residential_address": "Pune, Maharashtra"}, "loan": {"purpose": "Home Improvement"}, "employment": {"employment_type": "Salaried", "employer_name": "TCS", "occupation": "Engineer", "monthly_income": 100000}, "bank": {}, "property": {"property_type": "Apartment / Flat"}},
        "consents": {"truthful_information": True, "privacy_consent": True}}
    aid = client.post("/api/v1/applications", headers=H(cust), json=app_payload).json()["id"]
    up = lambda: client.post(f"/api/v1/applications/{aid}/documents", headers=H(cust), data={"category": "KYC"}, files={"file": ("kyc.png", tiny_png(), "image/png")})
    first = up(); assert first.status_code == 200; d1 = first.json()["id"]
    for category, name in [("Bank Statement", "bank.png"), ("Income Proof / Salary Slip", "salary.png")]:
        response = client.post(f"/api/v1/applications/{aid}/documents", headers=H(cust), data={"category": category}, files={"file": (name, tiny_png(), "image/png")})
        assert response.status_code == 200, response.text
    assert client.get(f"/api/v1/applications/{aid}", headers=H(cust)).json()["kyc_status"] == "PENDING"
    assert client.post(f"/api/v1/applications/{aid}/submit", headers=H(cust)).json()["status"] == "PENDING_ASSIGNMENT"

    admin_email = "kyc-admin@example.com"
    monkeypatch.setattr(settings, "initial_admin_email", admin_email)
    monkeypatch.setattr("app.routers.admin.deliver_otp", lambda *_args: "email")
    make_admin(admin_email)
    issued = client.post("/api/v1/admin/login", json={"email": admin_email})
    assert issued.status_code == 200 and "access_token" not in issued.json()
    adm = client.post("/api/v1/admin/login/verify-otp", json={"email": admin_email, "code": "123456"}).json()["access_token"]
    rid = client.post("/api/v1/admin/reviewers", headers=H(adm), json={"full_name": "Kyc Reviewer", "email": "kyc-rev@example.com", "password": "12345678", "bank_code": "KYC-DEMO"}).json()["id"]  # exactly 8 chars is accepted
    assert client.post("/api/v1/admin/assignments", headers=H(adm), json={"application_id": aid, "reviewer_id": rid}).status_code == 403
    assert client.get(f"/api/v1/applications/{aid}", headers=H(cust)).json()["status"] == "ASSIGNED"
    rev = client.post("/api/v1/reviewer/login", json={"email": "kyc-rev@example.com", "password": "12345678"}).json()["access_token"]
    kyc = lambda status, note="": client.post(f"/api/v1/reviewer/applications/{aid}/kyc", headers=H(rev), json={"status": status, "note": note})
    act = lambda action, note="": client.post(f"/api/v1/reviewer/applications/{aid}/actions", headers=H(rev), json={"action": action, "note": note})
    vdoc = lambda did, status="VERIFIED", note="": client.patch(f"/api/v1/reviewer/applications/{aid}/documents/{did}/verification", headers=H(rev), json={"status": status, "note": note})

    detail = client.get(f"/api/v1/reviewer/applications/{aid}", headers=H(rev)).json()["kyc"]
    assert detail["status"] == "PENDING" and detail["kyc_documents"] == 1 and detail["kyc_documents_verified"] == 0 and "no external" in detail["attestation"].lower()
    assert kyc("VERIFIED").status_code == 409                                                          # KYC document not verified yet
    assert kyc("REJECTED").status_code == 422 and kyc("NEEDS_REVIEW").status_code == 422               # reason required
    assert kyc("BOGUS").status_code == 422
    assert kyc("NEEDS_REVIEW", "Photo is blurry").json()["status"] == "NEEDS_REVIEW"
    assert act("recommend_approve", "Looks fine").status_code == 409                                   # recommendation requires an active review
    assert act("recommend_decline", "Cannot proceed").status_code == 409
    assert act("start_review").json()["status"] == "IN_REVIEW"
    assert act("recommend_approve", "Looks fine").status_code == 409                                   # gate: KYC not verified

    assert vdoc(d1).status_code == 200
    ok = kyc("VERIFIED", "Identity confirmed"); assert ok.status_code == 200 and ok.json()["status"] == "VERIFIED" and ok.json()["verified_by"] == "kyc-rev@example.com"
    assert client.get(f"/api/v1/applications/{aid}", headers=H(cust)).json()["kyc_status"] == "VERIFIED"

    # resets: new KYC evidence / edited verified text invalidates the attestation
    assert act("request_documents", "Please re-upload a clearer ID").json()["status"] == "DOCUMENTS_REQUESTED"
    second = up(); assert second.status_code == 200; d2 = second.json()["id"]
    assert client.get(f"/api/v1/applications/{aid}", headers=H(cust)).json()["kyc_status"] == "PENDING"
    assert kyc("VERIFIED").status_code == 409                                                          # d2 unverified
    assert vdoc(d2).status_code == 200 and kyc("VERIFIED", "Both documents verified").status_code == 200
    assert client.put(f"/api/v1/applications/{aid}/documents/{d2}/text", headers=H(cust), json={"edited_text": "Corrected ID number ABCDE1234F"}).status_code == 200
    assert client.get(f"/api/v1/applications/{aid}", headers=H(cust)).json()["kyc_status"] == "PENDING"
    assert client.get(f"/api/v1/applications/{aid}/documents", headers=H(cust)).json()[1]["verification_status"] == "PENDING"

    # re-verify, resubmit, and approval can now be recommended
    assert vdoc(d2).status_code == 200 and kyc("VERIFIED", "Re-verified after correction").status_code == 200
    assert client.post(f"/api/v1/applications/{aid}/submit", headers=H(cust)).json()["status"] == "ASSIGNED"
    assert act("start_review").json()["status"] == "IN_REVIEW"
    assert act("recommend_approve", "KYC verified; evidence reviewed").json()["status"] == "RECOMMEND_APPROVE"
    assert act("complete").json()["status"] == "COMPLETED"
    assert kyc("REJECTED", "Too late").status_code == 409                                              # frozen after completion
    actions = {l["action"] for l in client.get("/api/v1/admin/audit-logs?limit=250", headers=H(adm)).json()["items"]}
    assert {"KYC_VERIFIED", "KYC_NEEDS_REVIEW"} <= actions

# Public UI bootstrap was removed; the backend provisions only the configured address.
def test_platform_admin_bootstrap_endpoints_are_removed():
    assert client.get("/api/v1/admin/bootstrap/status").status_code == 404
    assert client.post("/api/v1/admin/bootstrap", json={}).status_code == 404
