"""Per-document analysis: persistence, caching/invalidation, failure handling, ownership, duplicate-click guard."""
import pytest
pytest.importorskip("fastapi"); pytest.importorskip("sqlalchemy")
import json
from datetime import datetime, timezone
from app.database import SessionLocal
from app.models import ApplicationDocument, Bank, MortgageApplication, Reviewer, ReviewAssignment
from app.security import token_for
from tests.test_customer_panel_requirements import client, H, register_and_verify, png_bytes

GOOD = {"scenario": "income_tax", "document_type_guess": "Salary slip", "extracted_facts": ["Gross salary 50,000"], "discrepancies": [], "missing_information": [], "risk_flags": [], "limitations": [], "confidence": "high", "evidence": [{"claim": "Gross", "exact_quote": "Gross Salary: 50,000"}]}

def setup_doc(monkeypatch, name, email):
    from app.config import settings
    monkeypatch.setattr(settings, "nvidia_api_key", "")
    token = register_and_verify(monkeypatch, name, email)
    aid = client.post("/api/v1/applications", headers=H(token), json={"lender_name": "DEMO-BANK"}).json()["id"]
    monkeypatch.setattr("app.routers.documents.extract_text", lambda path: ("Gross Salary: 50,000", "COMPLETED", "ok"))
    up = client.post(f"/api/v1/applications/{aid}/documents", headers=H(token), data={"category": "Income Proof / Salary Slip"}, files={"file": ("slip.png", png_bytes(), "image/png")})
    assert up.status_code == 200, up.text
    return token, aid, up.json()["id"]

def fake_analyze(calls, valid=True):
    async def _a(text, scenario="x", source_evidence=None):
        calls.append(1)
        if not valid:
            return {"provider": "NVIDIA", "model": "m", "analysis": None, "json_valid": False, "validation_errors": ["evidence not verified"], "raw_response": ""}
        return {"provider": "NVIDIA", "model": "m", "analysis": dict(GOOD, evidence=[dict(e) for e in GOOD["evidence"]]), "json_valid": True, "raw_response": ""}
    return _a

def reviewer_for(aid, suffix, assign=True):
    with SessionLocal() as db:
        bank = Bank(name=f"Reanalysis Bank {suffix}", code=f"REANALYSIS_{suffix.upper()}", status="APPROVED", contact_email=f"reanalysis-{suffix}@bank.example")
        db.add(bank); db.flush()
        app = db.get(MortgageApplication, aid); app.bank_id = bank.id; app.lender_name = bank.code
        reviewer = Reviewer(full_name=f"Review {suffix}", email=f"review-{suffix}@example.com", password_hash="unused", bank_code=bank.code, bank_id=bank.id, is_active=True)
        db.add(reviewer); db.flush()
        if assign:
            db.add(ReviewAssignment(application_id=aid, reviewer_id=reviewer.id, assigned_by="test", active=True))
        db.commit(); reviewer_id = reviewer.id
    return H(token_for(f"reviewer:{reviewer_id}"))

def mark_document_stale(did):
    with SessionLocal() as db:
        document = db.get(ApplicationDocument, did)
        document.analysis_status = "ANALYSED"
        document.analysis_result_json = json.dumps({"analysis": GOOD, "model": "previous-model"})
        document.analysis_input_hash = "stale-source-fingerprint"
        db.commit()

def empty_shared_context(*_args):
    async def _context(*_ignored):
        return ({}, [], "NO_POLICY", "not_available", [], [], "NO_DOCUMENT_EVIDENCE", "not_available")
    return _context

def test_success_is_persisted_cached_and_invalidated(monkeypatch):
    token, aid, did = setup_doc(monkeypatch, "Doc Analysis One", "docan1@example.com")
    calls = []; monkeypatch.setattr("app.routers.ai.analyze", fake_analyze(calls))
    url = f"/api/v1/ai/applications/{aid}/documents/{did}/analyze"
    r = client.post(url, headers=H(token)); assert r.status_code == 200 and r.json()["cached"] is False
    listing = client.get(f"/api/v1/applications/{aid}/documents", headers=H(token)).json()[0]
    assert listing["analysis_status"] == "ANALYSED" and listing["analysis_result"]["analysis"]["document_type_guess"] == "Salary slip" and listing["analysis_duration_ms"] is not None
    assert client.post(url, headers=H(token)).json()["cached"] is True and len(calls) == 1
    assert client.put(f"/api/v1/applications/{aid}/documents/{did}/text", headers=H(token), json={"edited_text": "Gross Salary: 55,000"}).status_code == 200
    assert client.get(f"/api/v1/applications/{aid}/documents", headers=H(token)).json()[0]["analysis_status"] == "NEEDS_REANALYSIS"
    assert client.post(url, headers=H(token)).json()["cached"] is False and len(calls) == 2

def test_dob_label_is_not_duplicated_as_a_generic_document_date():
    from app.routers.documents import _structured_fields
    fields = _structured_fields("Applicant Name: Divya Rathore\nGender: Female\nDate of Birth: 28/11/1980\nAge: 46 years", "KYC")
    assert fields["applicant_name"]["value"] == "Divya Rathore"
    assert fields["gender"]["value"] == "Female"
    assert fields["date_of_birth"]["value"] == "28/11/1980"
    assert fields["age"]["value"] == "46 years"
    assert "document_date" not in fields

def test_previous_prompt_version_is_genuinely_stale_without_source_text_change(monkeypatch):
    import hashlib
    from app.config import settings
    token, aid, did = setup_doc(monkeypatch, "Prompt Version Invalidation", "prompt-version-invalidation@example.com")
    with SessionLocal() as db:
        document = db.get(ApplicationDocument, did)
        previous_hash = hashlib.sha256("\x1f".join([
            "2", settings.nvidia_model, document.category, document.extracted_text or "",
            document.edited_text if document.edited_text is not None else "\x00",
        ]).encode()).hexdigest()
        document.analysis_status = "ANALYSED"
        document.analysis_result_json = json.dumps({"analysis": GOOD})
        document.analysis_input_hash = previous_hash
        db.commit()
    listed = client.get(f"/api/v1/applications/{aid}/documents", headers=H(token)).json()[0]
    assert listed["analysis_status"] == "NEEDS_REANALYSIS"

def test_retrieved_document_evidence_is_passed_to_nemotron(monkeypatch):
    token, aid, did = setup_doc(monkeypatch, "RAG Grounding", "rag-grounding@example.com")
    from app.models import ApplicationDocumentChunk
    from sqlalchemy import select
    with SessionLocal() as db:
        chunks = db.scalars(select(ApplicationDocumentChunk).where(ApplicationDocumentChunk.document_id == did)).all()
        assert chunks and chunks[0].source_filename == "slip.png"
    seen = []
    async def grounded_analyze(text, scenario="x", source_evidence=None):
        seen.append(text)
        return {"provider":"NVIDIA","model":"test","analysis":dict(GOOD,evidence=[dict(e) for e in GOOD["evidence"]]),"json_valid":True,"raw_response":""}
    monkeypatch.setattr("app.routers.ai.analyze", grounded_analyze)
    response = client.post(f"/api/v1/ai/applications/{aid}/documents/{did}/analyze", headers=H(token))
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["document_retrieval_status"] == "RETRIEVED"
    assert result["retrieved_application_evidence"][0]["filename"] == "slip.png"
    assert "retrieved_application_document_evidence_not_verified" in seen[0]
    assert "Gross Salary: 50,000" in seen[0]

def test_failure_is_recorded_and_retry_allowed(monkeypatch):
    token, aid, did = setup_doc(monkeypatch, "Doc Analysis Two", "docan2@example.com")
    calls = []; monkeypatch.setattr("app.routers.ai.analyze", fake_analyze(calls, valid=False))
    url = f"/api/v1/ai/applications/{aid}/documents/{did}/analyze"
    r = client.post(url, headers=H(token)); assert r.status_code == 502 and "structured-output validation" in r.json()["detail"]
    d = client.get(f"/api/v1/applications/{aid}/documents", headers=H(token)).json()[0]
    assert d["analysis_status"] == "FAILED" and d["analysis_result"] is None and d["analysis_error"]
    monkeypatch.setattr("app.routers.ai.analyze", fake_analyze(calls, valid=True))
    assert client.post(url, headers=H(token)).status_code == 200

def test_truncated_model_response_is_recorded_as_failure_without_partial_analysis(monkeypatch):
    token, aid, did = setup_doc(monkeypatch, "Truncated Analysis", "truncated-analysis@example.com")
    async def truncated(_text, scenario="x", source_evidence=None):
        return {
            "provider": "NVIDIA",
            "model": "nvidia/nemotron-3.5-lightning-30b-a3b",
            "analysis": None,
            "json_valid": False,
            "validation_errors": ["model output was truncated (finish_reason=length) after the bounded 8,192-token recovery attempt"],
            "raw_response": "",
        }
    monkeypatch.setattr("app.routers.ai.analyze", truncated)
    response = client.post(f"/api/v1/ai/applications/{aid}/documents/{did}/analyze", headers=H(token))
    assert response.status_code == 502
    assert "structured-output validation" in response.json()["detail"]
    document = client.get(f"/api/v1/applications/{aid}/documents", headers=H(token)).json()[0]
    assert document["analysis_status"] == "FAILED"
    assert document["analysis_result"] is None
    assert "finish_reason=length" in document["analysis_error"]

def test_guardrails_configuration_failure_is_safe_and_actionable(monkeypatch):
    from app.services.nvidia import NVIDIAConfigurationError
    token, aid, did = setup_doc(monkeypatch, "Guardrails Configuration Failure", "guardrails-config-failure@example.com")

    async def broken_guardrails(*_args, **_kwargs):
        raise NVIDIAConfigurationError("NeMo Guardrails input check failed (RailTypeNotConfiguredError); inference was stopped.")

    monkeypatch.setattr("app.routers.ai.analyze", broken_guardrails)
    response = client.post(f"/api/v1/ai/applications/{aid}/documents/{did}/analyze", headers=H(token))

    assert response.status_code == 503
    assert "safety checks" in response.json()["detail"]
    assert "RailTypeNotConfiguredError" not in response.json()["detail"]
    document = client.get(f"/api/v1/applications/{aid}/documents", headers=H(token)).json()[0]
    assert document["analysis_status"] == "FAILED"
    assert "retry later or contact support" in document["analysis_error"]
    assert "RailTypeNotConfiguredError" not in document["analysis_error"]

def test_other_customer_cannot_analyse_and_duplicate_click_is_rejected(monkeypatch):
    token, aid, did = setup_doc(monkeypatch, "Doc Analysis Three", "docan3@example.com")
    other = register_and_verify(monkeypatch, "Doc Analysis Four", "docan4@example.com")
    monkeypatch.setattr("app.routers.ai.analyze", fake_analyze([]))
    url = f"/api/v1/ai/applications/{aid}/documents/{did}/analyze"
    assert client.post(url, headers=H(other)).status_code == 404
    with SessionLocal() as db:
        d = db.get(ApplicationDocument, did); d.analysis_status = "ANALYSING"; d.analysis_started_at = datetime.now(timezone.utc); db.commit()
    assert client.post(url, headers=H(token)).status_code == 409

def test_assigned_reviewer_can_reanalyse_stale_document_and_refresh_sees_persisted_result(monkeypatch):
    token, aid, did = setup_doc(monkeypatch, "Reviewer Reanalysis Success", "reviewer-reanalyse-success@example.com")
    reviewer_headers = reviewer_for(aid, "success")
    mark_document_stale(did)
    calls = []; monkeypatch.setattr("app.routers.ai.analyze", fake_analyze(calls))
    monkeypatch.setattr("app.routers.ai._shared_context", empty_shared_context())
    response = client.post(f"/api/v1/reviewer/applications/{aid}/documents/{did}/reanalyze", headers=reviewer_headers)
    assert response.status_code == 200, response.text
    assert response.json()["analysis_status"] == "ANALYSED" and response.json()["cached"] is False
    refreshed = client.get(f"/api/v1/reviewer/applications/{aid}", headers=reviewer_headers)
    document = next(row for row in refreshed.json()["documents"] if row["id"] == did)
    assert document["analysis_status"] == "ANALYSED"
    assert document["analysis_result"]["analysis"]["document_type_guess"] == "Salary slip"
    assert len(calls) == 1
    with SessionLocal() as db:
        saved = db.get(ApplicationDocument, did)
        from app.routers.ai import _input_hash
        assert saved.analysis_input_hash == _input_hash(saved)

def test_reanalysis_requires_assigned_reviewer_access(monkeypatch):
    _customer_token, aid, did = setup_doc(monkeypatch, "Reviewer Reanalysis Unauthorized", "reviewer-reanalyse-unauth@example.com")
    unauthorized_headers = reviewer_for(aid, "unauthorized", assign=False)
    mark_document_stale(did)
    response = client.post(f"/api/v1/reviewer/applications/{aid}/documents/{did}/reanalyze", headers=unauthorized_headers)
    assert response.status_code == 404

def test_reanalysis_cors_preflight_and_post_keep_reviewer_authorization(monkeypatch):
    token, aid, did = setup_doc(monkeypatch, "Reviewer Reanalysis CORS", "reviewer-reanalyse-cors@example.com")
    reviewer_headers = reviewer_for(aid, "cors")
    mark_document_stale(did)
    url = f"/api/v1/reviewer/applications/{aid}/documents/{did}/reanalyze"
    origin = "http://localhost:5173"
    preflight = client.options(url, headers={
        "Origin": origin,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type",
    })
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == origin
    assert preflight.headers["access-control-allow-credentials"] == "true"
    assert "POST" in preflight.headers["access-control-allow-methods"]
    assert "authorization" in preflight.headers["access-control-allow-headers"].lower()

    calls = []
    monkeypatch.setattr("app.routers.ai.analyze", fake_analyze(calls))
    monkeypatch.setattr("app.routers.ai._shared_context", empty_shared_context())
    authorized = client.post(url, headers={**reviewer_headers, "Origin": origin})
    assert authorized.status_code == 200, authorized.text
    assert authorized.headers["access-control-allow-origin"] == origin
    assert authorized.json()["analysis_status"] == "ANALYSED"

    unauthenticated = client.post(url, headers={"Origin": origin})
    assert unauthenticated.status_code == 401
    assert unauthenticated.headers["access-control-allow-origin"] == origin

    loopback_origin = "http://127.0.0.1:5173"
    loopback = client.options(url, headers={"Origin": loopback_origin, "Access-Control-Request-Method": "POST"})
    assert loopback.status_code == 200
    assert loopback.headers["access-control-allow-origin"] == loopback_origin

def test_cors_headers_are_attached_to_unhandled_backend_errors():
    from fastapi.testclient import TestClient
    from app.main import app as cors_app

    async def unexpected_failure():
        raise RuntimeError("private test diagnostic")

    cors_app.app.add_api_route("/_test/unhandled-cors-error", unexpected_failure, methods=["GET"])
    with TestClient(cors_app, raise_server_exceptions=False) as cors_client:
        response = cors_client.get("/_test/unhandled-cors-error", headers={"Origin": "http://localhost:5173"})
    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "private test diagnostic" not in response.text

def test_failed_reanalysis_keeps_stale_status_and_last_good_result(monkeypatch):
    token, aid, did = setup_doc(monkeypatch, "Reviewer Reanalysis Failure", "reviewer-reanalyse-fail@example.com")
    reviewer_headers = reviewer_for(aid, "failure")
    mark_document_stale(did)
    async def invalid_output(*_args, **_kwargs):
        return {"provider":"NVIDIA","model":"test","analysis":{},"json_valid":True,"validation_errors":[],"raw_response":"{}"}
    monkeypatch.setattr("app.routers.ai.analyze", invalid_output)
    monkeypatch.setattr("app.routers.ai._shared_context", empty_shared_context())
    response = client.post(f"/api/v1/reviewer/applications/{aid}/documents/{did}/reanalyze", headers=reviewer_headers)
    assert response.status_code == 502
    summary = client.get(f"/api/v1/reviewer/applications/{aid}", headers=reviewer_headers).json()
    reviewer_document = next(row for row in summary["documents"] if row["id"] == did)
    assert reviewer_document["analysis_status"] == "NEEDS_REANALYSIS"
    assert "structured-output validation" in reviewer_document["analysis_error"]
    with SessionLocal() as db:
        saved = db.get(ApplicationDocument, did)
        assert saved.analysis_status == "NEEDS_REANALYSIS"
        assert saved.analysis_input_hash == "stale-source-fingerprint"
        assert json.loads(saved.analysis_result_json)["analysis"] == GOOD

def test_reanalysis_rejects_current_or_inflight_document(monkeypatch):
    _customer_token, aid, did = setup_doc(monkeypatch, "Reviewer Reanalysis Claim", "reviewer-reanalyse-claim@example.com")
    reviewer_headers = reviewer_for(aid, "claim")
    from app.routers.ai import _input_hash
    with SessionLocal() as db:
        document = db.get(ApplicationDocument, did)
        document.analysis_status = "ANALYSED"; document.analysis_input_hash = _input_hash(document)
        db.commit()
    url = f"/api/v1/reviewer/applications/{aid}/documents/{did}/reanalyze"
    assert client.post(url, headers=reviewer_headers).status_code == 409
    with SessionLocal() as db:
        document = db.get(ApplicationDocument, did)
        document.analysis_status = "ANALYSING"; document.analysis_started_at = datetime.now(timezone.utc)
        db.commit()
    assert client.post(url, headers=reviewer_headers).status_code == 409

def test_fast_mode_parameter_falls_back_once_if_rejected(monkeypatch):
    import asyncio, types
    from app.services import nvidia as n
    from app.config import settings
    monkeypatch.setattr(settings, "nvidia_api_key", "x")
    class AllowedRails:
        config = types.SimpleNamespace(rails=types.SimpleNamespace(
            input=types.SimpleNamespace(flows=["self check input"]),
            output=types.SimpleNamespace(flows=["self check output"]),
        ))
        async def generate_async(self, messages, options):
            if options["rails"]["input"]:
                content = ""
            else:
                content = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "assistant"), "")
            return types.SimpleNamespace(response=[{"role": "assistant", "content": content}])
    monkeypatch.setattr(n, "_GUARDRAILS_ENGINE", AllowedRails())
    body = '{"scenario":"s","document_type_guess":"d","extracted_facts":[],"discrepancies":[],"missing_information":[],"risk_flags":[],"limitations":[],"evidence":[],"confidence":"low"}'
    class Bad(Exception): status_code = 400
    seen = []
    class C:
        def __init__(s): s.chat = types.SimpleNamespace(completions=s)
        async def create(s, **k):
            seen.append("extra_body" in k)
            if "extra_body" in k: raise Bad()
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=body), finish_reason="stop")])
    monkeypatch.setattr(n, "_client", lambda: C())
    r = asyncio.run(n.analyze("text", "valuation_ltv", source_evidence="text"))
    assert r["json_valid"] and seen == [True, False]

def test_customer_can_remove_draft_document_and_file(monkeypatch):
    from app.routers.documents import stored_path
    token, aid, did = setup_doc(monkeypatch, "Removable Upload", "remove-upload@example.com")
    with SessionLocal() as db:
        document = db.get(ApplicationDocument, did)
        path = stored_path(document)
    response = client.delete(f"/api/v1/applications/{aid}/documents/{did}", headers=H(token))
    assert response.status_code == 200 and response.json() == {"id": did, "deleted": True}
    assert client.get(f"/api/v1/applications/{aid}/documents", headers=H(token)).json() == []
    assert not path.exists()
