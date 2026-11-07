"""End-to-end API workflow: customer -> admin -> reviewer, isolation, audit, scenarios, policy RAG (no NVIDIA key => no network).
Requires fastapi, SQLAlchemy, Tesseract (for the OCR step). Run: pytest tests/test_api_workflow.py -v
"""
import io
import json
from datetime import datetime, timezone
import pytest
pytest.importorskip("fastapi"); pytest.importorskip("sqlalchemy"); pytest.importorskip("email_validator")
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont
from app.main import app
from app.database import SessionLocal
from app.config import settings
from app.models import PlatformAdmin, Bank
from sqlalchemy import select
from app.security import hash_password

client = TestClient(app)
PW = "Str0ng-Passw0rd!"

def H(tok): return {"Authorization": f"Bearer {tok}"}

def register_customer(monkeypatch, email):
    monkeypatch.setattr("secrets.randbelow", lambda n: 123456)
    assert client.post("/api/v1/auth/register", json={"full_name": "Test Customer", "email": email, "mobile": "9999999999", "password": PW}).status_code == 200
    r = client.post("/api/v1/auth/verify-otp", json={"email": email, "code": "123456"}); assert r.status_code == 200, r.text
    return r.json()["access_token"]

def png_bytes(text):
    img = Image.new("RGB", (1400, 260), "white"); ImageDraw.Draw(img).text((30, 90), text, fill="black", font=ImageFont.load_default(size=44))
    b = io.BytesIO(); img.save(b, "PNG"); return b.getvalue()

def test_full_workflow(monkeypatch):
    # --- customers A and B
    a = register_customer(monkeypatch, "a@example.com"); b = register_customer(monkeypatch, "b@example.com")
    assert client.post("/api/v1/auth/login", json={"email": "a@example.com", "password": "wrong-password"}).status_code == 401
    with SessionLocal() as db:
        bank = db.scalar(select(Bank).where(Bank.code == "BANK-DEMO"))
        if bank is None: db.add(Bank(name="Workflow Demo Bank", code="BANK-DEMO", status="APPROVED"))
        else: bank.status = "APPROVED"
        db.commit()
    app_payload = {"lender_name": "BANK-DEMO", "product_name": "Home Loan", "property_address": "Pune, Maharashtra", "property_value": 5000000, "requested_loan": 4000000, "annual_income": 1200000, "monthly_debt": 0, "interest_rate": 9.0, "tenure_years": 20,
        "details": {"applicant": {"full_name": "Divya Rathore", "date_of_birth": "1990-01-01", "mobile": "8888888888", "email": "divya.applicant@example.com", "residential_address": "Pune, Maharashtra"}, "loan": {"purpose": "Home Improvement"}, "employment": {"employment_type": "Salaried", "employer_name": "TCS", "occupation": "Engineer", "monthly_income": 100000}, "bank": {"bank_name": "Test Bank", "account_holder_name": "Test Customer"}, "property": {"property_type": "Apartment / Flat"}},
        "consents": {"truthful_information": True, "privacy_consent": True}}
    app_row = client.post("/api/v1/applications", headers=H(a), json=app_payload).json()
    aid = app_row["id"]
    assert app_row["details"]["applicant"] == app_payload["details"]["applicant"]
    edited_payload = {**app_payload, "details": {**app_payload["details"], "applicant": {**app_payload["details"]["applicant"], "full_name": "Divya Rathore (corrected)"}}}
    assert client.put(f"/api/v1/applications/{aid}", headers=H(a), json=edited_payload).status_code == 200
    reloaded = client.get(f"/api/v1/applications/{aid}", headers=H(a)).json()
    assert reloaded["details"]["applicant"]["full_name"] == "Divya Rathore (corrected)"
    assert reloaded["details"]["applicant"]["email"] == "divya.applicant@example.com"
    assert reloaded["details"]["applicant"]["mobile"] == "8888888888"
    est = client.get(f"/api/v1/applications/{aid}/estimates", headers=H(a)).json()
    assert est["loan_to_value_percent"] == 80.0 and abs(est["estimated_monthly_emi_inr"] - 35989.04) < 0.01

    # --- upload + deterministic OCR fixture + original/edited separation
    monkeypatch.setattr("app.routers.documents.extract_text", lambda path: ("Test Customer mortgage supporting document. Applicant and financial details are legible.", "COMPLETED", "Deterministic OCR fixture"))
    up = client.post(f"/api/v1/applications/{aid}/documents", headers=H(a), data={"category": "Property Valuation"}, files={"file": ("val.png", png_bytes("Valuation INR 4300000"), "image/png")})
    assert up.status_code == 200, up.text
    doc = up.json(); did = doc["id"]; original = doc["extracted_text"]
    ed = client.put(f"/api/v1/applications/{aid}/documents/{did}/text", headers=H(a), json={"edited_text": "Valuation INR 4300000 (corrected)"})
    assert ed.status_code == 200 and ed.json()["extracted_text"] == original and ed.json()["edited_text"].endswith("(corrected)")
    assert client.post(f"/api/v1/applications/{aid}/documents", headers=H(a), data={"category": "Nope"}, files={"file": ("v.png", png_bytes("x"), "image/png")}).status_code == 422
    assert client.post(f"/api/v1/applications/{aid}/documents", headers=H(a), data={"category": "KYC"}, files={"file": ("v.pdf", b"not a pdf", "application/pdf")}).status_code == 415

    # --- customer isolation
    assert client.get(f"/api/v1/applications/{aid}", headers=H(b)).status_code == 404
    assert client.get(f"/api/v1/applications/{aid}/documents", headers=H(b)).status_code == 404
    assert client.get(f"/api/v1/applications/{aid}/documents/{did}/file", headers=H(b)).status_code == 404
    assert client.post(f"/api/v1/ai/applications/{aid}/scenarios/valuation_ltv", headers=H(b), json={}).status_code == 404
    assert client.get("/api/v1/applications").status_code == 401
    assert client.get(f"/api/v1/applications/{aid}/documents/{did}/file", headers=H(a)).status_code == 200
    for category, name in [("KYC", "kyc.png"), ("Bank Statement", "bank.png"), ("Income Proof / Salary Slip", "salary.png")]:
        response = client.post(f"/api/v1/applications/{aid}/documents", headers=H(a), data={"category": category}, files={"file": (name, png_bytes("Applicant name: Test Customer"), "image/png")})
        assert response.status_code == 200, response.text

    # --- submit; documents become read-only; still viewable
    submitted = client.post(f"/api/v1/applications/{aid}/submit", headers=H(a))
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "PENDING_ASSIGNMENT"
    assert client.get(f"/api/v1/applications/{aid}/documents", headers=H(a)).status_code == 200
    assert client.put(f"/api/v1/applications/{aid}/documents/{did}/text", headers=H(a), json={"edited_text": "x"}).status_code == 409

    # --- admin (provisioned directly in DB, as scripts/provision_admin.py does)
    monkeypatch.setattr(settings,"initial_admin_email","admin@example.com")
    monkeypatch.setattr("secrets.randbelow",lambda n:123456)
    monkeypatch.setattr("app.routers.admin.deliver_otp",lambda *_args:"email")
    with SessionLocal() as db:
        db.add(PlatformAdmin(full_name="Admin", email="admin@example.com", password_hash=hash_password(PW), is_active=True)); db.commit()
    assert client.post("/api/v1/admin/login",json={"email":"admin@example.com"}).status_code==200
    adm = client.post("/api/v1/admin/login/verify-otp",json={"email":"admin@example.com","code":"123456"}).json()["access_token"]
    assert client.get("/api/v1/admin/dashboard", headers=H(a)).status_code in (401, 403)           # customer token rejected
    r1 = client.post("/api/v1/admin/reviewers", headers=H(adm), json={"full_name": "Rev One", "email": "rev1@example.com", "password": PW + "xx", "bank_code": "BANK-DEMO"}).json()
    r2 = client.post("/api/v1/admin/reviewers", headers=H(adm), json={"full_name": "Rev Two", "email": "rev2@example.com", "password": PW + "xx", "bank_code": "BANK-DEMO"}).json()
    assert client.post("/api/v1/admin/assignments", headers=H(adm), json={"application_id": aid, "reviewer_id": r1["id"]}).status_code == 403
    assert client.get(f"/api/v1/applications/{aid}", headers=H(a)).json()["status"] == "ASSIGNED"

    # --- reviewer assignment isolation + workflow
    t1 = client.post("/api/v1/reviewer/login", json={"email": "rev1@example.com", "password": PW + "xx"}).json()["access_token"]
    t2 = client.post("/api/v1/reviewer/login", json={"email": "rev2@example.com", "password": PW + "xx"}).json()["access_token"]
    queue = client.get("/api/v1/reviewer/applications", headers=H(t1)).json()
    assert [x["id"] for x in queue] == [aid]
    queue_item = queue[0]
    assert queue_item["assigned_at"] and queue_item["submitted_at"]
    assert queue_item["customer"]["full_name"] == "Divya Rathore (corrected)"
    assert any(document["filename"] == "val.png" and document["extraction_status"] == "COMPLETED" for document in queue_item["documents"])
    assert "details" not in queue_item and "extracted_text" not in queue_item["documents"][0]
    assert client.get("/api/v1/reviewer/applications", headers=H(t2)).json() == []
    assert client.get(f"/api/v1/reviewer/applications/{aid}", headers=H(t2)).status_code == 404
    assert client.get(f"/api/v1/reviewer/applications/{aid}/documents/{did}/file", headers=H(t2)).status_code == 404
    assert client.get("/api/v1/reviewer/applications", headers=H(a)).status_code == 401              # customer token on reviewer API
    assert client.get("/api/v1/applications", headers=H(t1)).status_code == 401                     # reviewer token on customer API
    from app.models import ApplicationDocument
    with SessionLocal() as db:
        reviewed_doc=db.get(ApplicationDocument,did)
        reviewed_doc.extracted_fields_json=json.dumps({"property_value":{"value":4300000,"evidence":"Valuation INR 4300000","page_number":1}})
        reviewed_doc.corrected_fields_json=json.dumps({"property_value":{"value":4200000,"evidence":"Reviewer correction","page_number":1}})
        reviewed_doc.field_correction_history_json=json.dumps([{"field":"property_value","original_value":4300000,"corrected_value":4200000,"reason":"Checked against source"}])
        reviewed_doc.analysis_status="ANALYSED"
        reviewed_doc.analysis_result_json=json.dumps({"analysis":{"document_type_guess":"Property valuation","risk_flags":["Value needs confirmation"],"evidence":[{"claim":"Reported value","exact_quote":"Valuation INR 4300000","source_reference":{"filename":"val.png","page_number":1,"source_kind":"ORIGINAL_OCR"}}]},"deterministic_checks":[{"field":"property_value","label":"Declared property value","declared_value":5000000,"document_value":4300000,"difference_percent":14.0,"within_configured_tolerance":False,"tolerance_percent":2.0}],"provider":"NVIDIA","model":"test-fixture","warning":"Assistive draft only."})
        from app.routers.ai import _input_hash
        reviewed_doc.analysis_input_hash=_input_hash(reviewed_doc)
        reviewed_doc.analysis_completed_at=datetime.now(timezone.utc)
        db.commit()
    detail_response=client.get(f"/api/v1/reviewer/applications/{aid}", headers=H(t1))
    assert detail_response.status_code==200,detail_response.text
    detail=detail_response.json()
    reviewed_document=next(document for document in detail["documents"] if document["id"]==did)
    assert detail["assigned_at"] and reviewed_document["extracted_fields"]["property_value"]["page_number"]==1
    correction=client.patch(
        f"/api/v1/reviewer/applications/{aid}/documents/{did}/fields",
        headers=H(t1),
        json={"corrected_fields":{"property_value":4100000},"reason":"Checked against the signed valuation page."},
    )
    assert correction.status_code==200,correction.text
    assert correction.json()["corrected_fields"]["property_value"]["value"]==4100000
    assert correction.json()["field_correction_history"][-1]["original_value"]==4300000
    assert correction.json()["field_correction_history"][-1]["reason"]=="Checked against the signed valuation page."
    assert client.patch(
        f"/api/v1/reviewer/applications/{aid}/documents/{did}/fields",
        headers=H(t2),
        json={"corrected_fields":{"property_value":4200000},"reason":"Unauthorized correction"},
    ).status_code==404
    corrected_detail=client.get(f"/api/v1/reviewer/applications/{aid}",headers=H(t1)).json()
    corrected_document=next(document for document in corrected_detail["documents"] if document["id"]==did)
    assert corrected_document["extracted_fields"]["property_value"]["value"]==4300000
    assert corrected_document["corrected_fields"]["property_value"]["value"]==4100000
    assert corrected_document["field_correction_history"][-1]["reason"]=="Checked against the signed valuation page."
    assert reviewed_document["corrected_fields"]["property_value"]["value"]==4200000
    assert reviewed_document["field_correction_history"][0]["reason"]=="Checked against source"
    assert reviewed_document["analysis_status"]=="ANALYSED"
    assert reviewed_document["analysis_result"]["analysis"]["evidence"][0]["source_reference"]["page_number"]==1
    with SessionLocal() as db:
        reviewed_doc=db.get(ApplicationDocument,did)
        reviewed_doc.analysis_status="FAILED"
        reviewed_doc.analysis_error="NVIDIA_API_KEY is not configured."
        db.commit()
    failed_response=client.get(f"/api/v1/reviewer/applications/{aid}",headers=H(t1)).json()
    failed_detail=next(document for document in failed_response["documents"] if document["id"]==did)
    assert failed_detail["analysis_status"]=="FAILED" and failed_detail["analysis_error"] and failed_detail["analysis_result"] is None
    detail=client.get(f"/api/v1/reviewer/applications/{aid}", headers=H(t1)).json()
    d0 = next(d for d in detail["documents"] if d["id"] == did); assert d0["original_text"] == original and d0["extracted_text"].endswith("(corrected)")
    assert client.get(f"/api/v1/reviewer/applications/{aid}/documents/{did}/file", headers=H(t1)).status_code == 200
    verified = client.patch(f"/api/v1/reviewer/applications/{aid}/documents/{did}/verification", headers=H(t1), json={"status":"VERIFIED","note":"Original evidence reviewed."})
    assert verified.status_code == 200 and verified.json()["verification_status"] == "VERIFIED"
    receipt = client.get(f"/api/v1/applications/{aid}/receipt.pdf", headers=H(a))
    assert receipt.status_code == 200 and receipt.headers["content-type"] == "application/pdf" and receipt.content.startswith(b"%PDF")
    act = lambda action, note="": client.post(f"/api/v1/reviewer/applications/{aid}/actions", headers=H(t1), json={"action": action, "note": note})
    assert act("complete").status_code == 409                                                       # cannot complete without recommendation
    assert act("recommend_approve").status_code == 422                                              # note required
    assert act("recommend_decline").status_code == 422                                             # rejection rationale required
    assert act("start_review").json()["status"] == "IN_REVIEW"
    assert act("request_documents", "Please add ITR").json()["status"] == "DOCUMENTS_REQUESTED"
    assert client.post(f"/api/v1/applications/{aid}/documents", headers=H(a), data={"category": "ITR"}, files={"file": ("itr.png", png_bytes("Total income INR 1200000"), "image/png")}).status_code == 200  # customer may now add documents
    kyc_did = next(d["id"] for d in client.get(f"/api/v1/applications/{aid}/documents", headers=H(a)).json() if d["category"] == "KYC")
    assert client.post(f"/api/v1/applications/{aid}/submit", headers=H(a)).json()["status"] == "ASSIGNED"
    # --- KYC gate: approval cannot be recommended until KYC documents and the KYC outcome are verified
    assert act("recommend_approve", "Evidence reviewed").status_code == 409
    kyc = lambda status, note="": client.post(f"/api/v1/reviewer/applications/{aid}/kyc", headers=H(t1), json={"status": status, "note": note})
    assert kyc("VERIFIED").status_code == 409                                                       # KYC document not yet verified
    assert kyc("REJECTED").status_code == 422                                                       # reason required
    assert client.patch(f"/api/v1/reviewer/applications/{aid}/documents/{kyc_did}/verification", headers=H(t1), json={"status": "VERIFIED", "note": ""}).status_code == 200
    kv = kyc("VERIFIED", "Identity matches application."); assert kv.status_code == 200 and kv.json()["status"] == "VERIFIED" and kv.json()["kyc_documents_verified"] == 1
    assert client.post(f"/api/v1/reviewer/applications/{aid}/kyc", headers=H(t2), json={"status": "VERIFIED"}).status_code == 404   # other reviewers cannot touch it
    assert client.get(f"/api/v1/applications/{aid}", headers=H(a)).json()["kyc_status"] == "VERIFIED"
    assert act("start_review").json()["status"] == "IN_REVIEW"                                     # resume after customer resubmission
    assert act("recommend_approve", "Evidence reviewed").json()["status"] == "RECOMMEND_APPROVE"
    assert act("recommend_decline", "Change recommendation").status_code == 409
    assert act("recommend_approve", "Submit again").status_code == 409
    assert act("complete").json()["status"] == "COMPLETED"
    assert act("complete", "Assessment completed").status_code == 409                             # duplicate final submission is blocked
    assert client.patch(
        f"/api/v1/reviewer/applications/{aid}/documents/{did}/fields",
        headers=H(t1),
        json={"corrected_fields":{"property_value":4000000},"reason":"Attempt after completion"},
    ).status_code==409

    # --- scenarios (deterministic)
    body = {"valuation_amount": 4300000, "max_ltv_percent": 80}
    s = client.post(f"/api/v1/reviewer/applications/{aid}/scenarios/valuation_ltv", headers=H(t1), json=body).json()
    assert s["metrics"]["ltv_percent"] == round(4000000 / 4300000 * 100, 2) and any(f["code"] == "VALUE_DISCREPANCY" for f in s["findings"])
    inc = {"income_years": [{"year": "FY2021-22", "itr_total_income": 1000000}, {"year": "FY2022-23", "itr_total_income": 1100000}, {"year": "FY2023-24", "itr_total_income": 1200000}]}
    assert client.post(f"/api/v1/ai/applications/{aid}/scenarios/income_tax", headers=H(a), json=inc).json()["metrics"]["years_analyzed"] == 3
    assert client.post(f"/api/v1/ai/applications/{aid}/scenarios/terms_conditions", headers=H(a), json={"terms_text": "Loan amount Rs. 40,00,000"}).status_code == 200
    assert client.post(f"/api/v1/ai/applications/{aid}/scenarios/bogus", headers=H(a), json={}).status_code == 422

    # --- policies: versioning + lexical retrieval; NVIDIA absent => honest 503, never a fabricated answer
    pol = lambda v, txt: client.post("/api/v1/admin/policies", headers=H(adm), json={"title": "LTV Policy", "policy_version": v, "category": "Credit", "content": txt})
    assert pol("1.0", "The maximum loan to value ratio for salaried borrowers is 75 percent of property value.").status_code == 201
    r = pol("2.0", "The maximum loan to value ratio for salaried borrowers is 80 percent of property value."); assert r.status_code == 201 and r.json()["superseded_versions"] == ["1.0"]
    assert pol("2.0", "Duplicate version should be refused by the API for the same title.").status_code == 409
    scenario = client.post(f"/api/v1/reviewer/applications/{aid}/scenarios/valuation_ltv", headers=H(t1), json=body)
    assert scenario.status_code == 200
    assert scenario.json()["policy_retrieval_status"] == "RETRIEVED"
    assert any(row["policy_version"] == "2.0" for row in scenario.json()["policy_evidence"])
    qa = client.post("/api/v1/reviewer/policy-qa", headers=H(t1), json={"question": "maximum loan to value ratio for salaried borrowers"})
    assert qa.status_code == 503 and "NVIDIA_API_KEY" in qa.text
    assert client.post("/api/v1/ai/test", headers=H(a), json={"text": "hello"}).status_code == 503

    # --- audit trail (admin only)
    logs = client.get("/api/v1/admin/audit-logs?limit=250", headers=H(adm)).json()["items"]
    actions = {l["action"] for l in logs}
    assert {"DOCUMENT_UPLOADED", "DOCUMENT_TEXT_EDITED", "DOCUMENT_DOWNLOADED", "APPLICATION_SUBMITTED", "REVIEWER_CREATED", "APPLICATION_AUTO_ASSIGNED", "REVIEW_START_REVIEW", "REVIEWER_DOCUMENT_FIELDS_CORRECTED", "SCENARIO_RUN", "POLICY_SUPERSEDED", "LOGIN_FAILED"} <= actions
    assert client.get("/api/v1/admin/audit-logs", headers=H(t1)).status_code in (401, 403)
    assert all("Valuation INR" not in l["detail"] for l in logs)                                      # no document content in audit rows
