"""Focused regression tests for customer-panel requirements added to Phase 1."""
import io
import pytest
pytest.importorskip("fastapi"); pytest.importorskip("sqlalchemy"); pytest.importorskip("email_validator")
from fastapi.testclient import TestClient
from app.routers.documents import _structured_fields
from PIL import Image
from app.main import app
from app.config import settings
from app.database import SessionLocal
from app.models import Bank
from sqlalchemy import select

client = TestClient(app)
PW = "Customer-Pass-123"
def H(token): return {"Authorization": f"Bearer {token}"}

def register_and_verify(monkeypatch, name, email, password=PW):
    monkeypatch.setattr("secrets.randbelow", lambda n: 123456)
    r = client.post("/api/v1/auth/register", json={"full_name": name, "email": email, "mobile": "9876543210", "password": password, "confirm_password": password})
    assert r.status_code == 200, r.text
    v = client.post("/api/v1/auth/verify-otp", json={"email": email, "code": "123456"})
    assert v.status_code == 200, v.text
    return v.json()["access_token"]

def app_payload(email="panel@example.com", name="Panel Customer"):
    return {
        "lender_name": "DEMO-BANK", "product_name": "Home Loan", "property_address": "Pune, Maharashtra",
        "property_value": 5000000, "requested_loan": 3500000, "annual_income": 1200000,
        "monthly_debt": 10000, "interest_rate": 8.5, "tenure_years": 20,
        "details": {
            "applicant": {"full_name": name, "date_of_birth": "1995-01-01", "mobile": "9876543210", "email": email, "residential_address": "Pune, Maharashtra"},
            "loan": {"purpose": "Home Improvement"},
            "employment": {"employment_type": "Salaried", "employer_name": "Example Employer", "occupation": "Engineer", "monthly_income": 100000},
            "bank": {}, "property": {"property_type": "Apartment / Flat"},
        },
        "consents": {"truthful_information": True, "privacy_consent": True},
    }

def png_bytes():
    b = io.BytesIO(); Image.new("RGB", (40, 40), "white").save(b, "PNG"); return b.getvalue()

def test_email_password_login_and_duplicate_name_safety(monkeypatch):
    token = register_and_verify(monkeypatch, "Same Customer", "same-a@example.com")
    login = client.post("/api/v1/auth/login", json={"email": "SAME-A@example.com", "password": PW})
    assert login.status_code == 200, login.text
    login_token = login.json()["access_token"]
    me = client.get("/api/v1/auth/me", headers=H(login_token))
    assert me.status_code == 200 and me.json()["email"] == "same-a@example.com"
    invalid = client.post("/api/v1/auth/login", json={"email": "same-a@example.com", "password": "Incorrect-Pass-123"})
    assert invalid.status_code == 401 and invalid.json()["detail"] == "Invalid email address or password."
    missing_email = client.post("/api/v1/auth/login", json={"full_name": "Same Customer", "password": PW})
    assert missing_email.status_code == 422
    register_and_verify(monkeypatch, "Same Customer", "same-b@example.com")
    second_login = client.post("/api/v1/auth/login", json={"email": "same-b@example.com", "password": PW})
    assert second_login.status_code == 200
    assert second_login.json()["customer"]["email"] == "same-b@example.com"
    assert client.get("/api/v1/auth/me", headers=H(token)).status_code == 200

def test_expired_customer_token_is_rejected_by_auth_me(monkeypatch):
    from datetime import datetime, timedelta, timezone
    import jwt
    from app.config import settings
    token = register_and_verify(monkeypatch, "Expired Token Customer", "expired-token@example.com")
    subject = client.get("/api/v1/auth/me", headers=H(token)).json()["id"]
    expired = jwt.encode({"sub": str(subject), "exp": datetime.now(timezone.utc) - timedelta(seconds=5)}, settings.jwt_secret_key, algorithm="HS256")
    response = client.get("/api/v1/auth/me", headers=H(expired))
    assert response.status_code == 401

@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer invalid-token"}])
def test_customer_application_and_notification_endpoints_require_valid_auth(headers):
    assert client.get("/api/v1/applications", headers=headers).status_code == 401
    assert client.get("/api/v1/notifications", headers=headers).status_code == 401

def test_login_preflight_accepts_configured_loopback_host_alias():
    response = client.options("/api/v1/auth/login", headers={
        "Origin": "http://127.0.0.1:5173",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    })
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"

def test_registration_rejects_confirm_password_mismatch():
    response = client.post("/api/v1/auth/register", json={"full_name":"Mismatch User","email":"mismatch@example.com","mobile":"9876543210","password":PW,"confirm_password":"Different-Pass-123"})
    assert response.status_code == 422

def test_customer_draft_validation_structured_correction_and_notifications(monkeypatch):
    token = register_and_verify(monkeypatch, "Panel Customer", "panel@example.com")
    created = client.post("/api/v1/applications", headers=H(token), json={"lender_name":"DEMO-BANK"})
    assert created.status_code == 200, created.text
    aid = created.json()["id"]
    rejected = client.post(f"/api/v1/applications/{aid}/submit", headers=H(token))
    assert rejected.status_code == 422 and "errors" in rejected.json()["detail"]
    saved_incomplete = client.put(f"/api/v1/applications/{aid}", headers=H(token), json={"lender_name":"DEMO-BANK"})
    assert saved_incomplete.status_code == 200, saved_incomplete.text
    assert client.get(f"/api/v1/applications/{aid}", headers=H(token)).json()["status"] == "DRAFT"

    # Use a deterministic OCR fixture for the endpoint contract; production uses the real OCR pipeline.
    monkeypatch.setattr("app.routers.documents.extract_text", lambda path: ("Applicant name: Panel Customer\nAnnual income: 1200000\nProperty value: 5000000", "COMPLETED", "Test OCR extraction"))
    for category, filename in [("KYC", "kyc.png"), ("Bank Statement", "bank.png"), ("Income Proof / Salary Slip", "salary.png")]:
        upload = client.post(f"/api/v1/applications/{aid}/documents", headers=H(token), data={"category":category}, files={"file":(filename, png_bytes(), "image/png")})
        assert upload.status_code == 200, upload.text
    with SessionLocal() as db:
        bank = db.scalar(select(Bank).where(Bank.code == "DEMO-BANK"))
        if bank is None: db.add(Bank(name="Customer Test Bank", code="DEMO-BANK", status="APPROVED"))
        else: bank.status = "APPROVED"
        db.commit()
    # Save full form details and consent; a draft can be updated without submitting.
    optional_blank_payload = app_payload()
    optional_blank_payload["annual_income"] = 0
    updated = client.put(f"/api/v1/applications/{aid}", headers=H(token), json=optional_blank_payload)
    assert updated.status_code == 200, updated.text
    doc = next(d for d in client.get(f"/api/v1/applications/{aid}/documents", headers=H(token)).json() if d["category"] == "Income Proof / Salary Slip")
    assert doc["extracted_fields"]["annual_income"]["value"] == 1200000.0
    correction = client.put(f"/api/v1/applications/{aid}/documents/{doc['id']}/fields", headers=H(token), json={"corrected_fields":{"annual_income":1100000},"reason":"Corrected against source evidence"})
    assert correction.status_code == 200, correction.text
    assert correction.json()["extracted_fields"]["annual_income"]["value"] == 1200000.0
    assert correction.json()["corrected_fields"]["annual_income"]["value"] == 1100000
    assert correction.json()["field_correction_history"][-1]["original_ocr_value"] == 1200000.0
    submit = client.post(f"/api/v1/applications/{aid}/submit", headers=H(token))
    assert submit.status_code == 200, submit.text
    assert submit.json()["status"] in {"SUBMITTED", "PENDING_ASSIGNMENT"}
    dashboard = client.get("/api/v1/customer/dashboard", headers=H(token)).json()
    assert dashboard["total_applications"] == 1
    notifications = client.get("/api/v1/notifications", headers=H(token)).json()
    assert any(n["event_type"] == "APPLICATION_SUBMITTED" for n in notifications)
    unread = next(n for n in notifications if n["event_type"] == "APPLICATION_SUBMITTED")
    assert client.patch(f"/api/v1/notifications/{unread['id']}", headers=H(token), json={"read":True}).status_code == 200
    assert client.get(f"/api/v1/applications/{aid}/activity", headers=H(token)).status_code == 200


def test_structured_ocr_extracts_next_line_pairs_and_keeps_distinct_values_separate():
    text = """[PAGE 1]
Full Name
Divya Rathore
Gender
Female
Date of Birth
28/11/1980
Age
46 years
Loan Amount
3,500,000
[PAGE 2]
Loan Amount
4,000,000
Purchase Price
5,000,000
Valuation Amount
5,200,000
"""
    fields = _structured_fields(text, "KYC")

    assert fields["applicant_name"]["value"] == "Divya Rathore"
    assert fields["gender"]["value"] == "Female"
    assert fields["date_of_birth"]["value"] == "28/11/1980"
    assert fields["age"]["value"] == "46 years"
    assert fields["loan_amount"]["value"] == 3500000.0
    assert fields["loan_amount"]["page_number"] == 1
    assert fields["loan_amount"]["alternates"] == [{"value": 4000000.0, "evidence": "Loan Amount\n4,000,000", "page_number": 2}]
    assert fields["purchase_price"]["value"] == 5000000.0
    assert fields["valuation_amount"]["value"] == 5200000.0
    assert "annual_income" not in fields

def test_nvidia_failure_is_persisted_without_mock_result(monkeypatch):
    token = register_and_verify(monkeypatch, "AI Failure User", "ai-failure@example.com")
    app_row = client.post("/api/v1/applications", headers=H(token), json={"lender_name":"DEMO-BANK"}).json()
    aid = app_row["id"]
    monkeypatch.setattr(settings, "nvidia_api_key", "")
    monkeypatch.setattr("app.routers.documents.extract_text", lambda path: ("Applicant name: AI Failure User", "COMPLETED", "Test OCR extraction"))
    upload = client.post(f"/api/v1/applications/{aid}/documents", headers=H(token), data={"category":"KYC"}, files={"file":("kyc.png", png_bytes(), "image/png")})
    assert upload.status_code == 200
    result = client.post(f"/api/v1/ai/applications/{aid}/analyze", headers=H(token))
    assert result.status_code == 503
    history = client.get(f"/api/v1/ai/applications/{aid}/analysis-history", headers=H(token)).json()
    assert history and history[0]["status"] == "FAILED"
    assert history[0]["result"]["results"][0]["failure_type"] == "configuration"

def test_otp_delivery_failure_does_not_claim_success_or_keep_pending_account(monkeypatch):
    from sqlalchemy import select
    from app.models import Customer
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "smtp_host", "")
    response = client.post("/api/v1/auth/register", json={"full_name":"No Mail Customer","email":"no-mail-customer@example.com","mobile":"9876543210","password":PW,"confirm_password":PW})
    assert response.status_code == 503
    with SessionLocal() as db:
        assert db.scalar(select(Customer).where(Customer.email == "no-mail-customer@example.com")) is None

def test_profile_mobile_update_and_full_blank_draft_persistence(monkeypatch):
    token = register_and_verify(monkeypatch, "Draft Persistence", "draft-persistence@example.com")
    blank = {
        "lender_name":"", "product_name":"", "property_address":"", "property_value":0, "requested_loan":0,
        "annual_income":0, "monthly_debt":0, "interest_rate":8.5, "tenure_years":20, "customer_notes":"",
        "details":{"applicant":{"full_name":"Draft Persistence","date_of_birth":"","mobile":"9876543210","email":"draft-persistence@example.com","residential_address":"","current_address":""},
                   "loan":{"purpose":"","income_category":"","down_payment":"","co_applicant_required":False,"repayment_preference":""},
                   "employment":{"employment_type":"","employer_name":"","occupation":"","business_duration":"","monthly_income":"","annual_income":"","other_income":"","income_source":""},
                   "bank":{"account_holder_name":"","bank_name":"","ifsc":"","account_type":""},
                   "property":{"property_type":"","location":"","property_status":"","estimated_market_value":"","seller_builder":"","registration_details":"","ownership_relationship":""},
                   "co_applicant":{"full_name":"","relationship":"","mobile":"","email":"","annual_income":"","employment_type":""}},
        "consents":{"truthful_information":False,"privacy_consent":False}}
    created = client.post("/api/v1/applications", headers=H(token), json=blank)
    assert created.status_code == 200, created.text
    aid = created.json()["id"]
    changed = blank.copy(); changed["details"] = {**blank["details"], "applicant": {**blank["details"]["applicant"], "residential_address":"Pune, Maharashtra"}}
    saved = client.put(f"/api/v1/applications/{aid}", headers=H(token), json=changed)
    assert saved.status_code == 200
    fetched = client.get(f"/api/v1/applications/{aid}", headers=H(token)).json()
    assert fetched["status"] == "DRAFT" and fetched["details"]["applicant"]["residential_address"] == "Pune, Maharashtra"
    profile = client.patch("/api/v1/auth/me", headers=H(token), json={"mobile":"9123456789"})
    assert profile.status_code == 200 and profile.json()["mobile"] == "9123456789"
