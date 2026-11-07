"""Nemotron advisory document-category checks and server-enforced mismatch resolution."""
from types import SimpleNamespace
import pytest

from app.config import settings
from app.database import SessionLocal
from app.models import ApplicationDocument, ApplicationDocumentChunk
from app.services.nvidia import classify_document_category
from tests.test_customer_panel_requirements import client, H, register_and_verify, png_bytes


def _setup(monkeypatch, name, email, classification, extracted_text=None, extraction_status="COMPLETED"):
    monkeypatch.setattr(settings, "nvidia_api_key", "")
    token = register_and_verify(monkeypatch, name, email)
    aid = client.post("/api/v1/applications", headers=H(token), json={"lender_name": "DEMO-BANK"}).json()["id"]
    text = extracted_text if extracted_text is not None else ("Aadhaar identity proof document. " * 6)
    monkeypatch.setattr("app.routers.documents.extract_text", lambda _path: (text, extraction_status, "OCR finished"))
    async def classify(*_args): return classification
    monkeypatch.setattr("app.routers.documents.classify_document_category", classify)
    return token, aid


def _result(status, detected="KYC", confidence=0.96, selected="Mortgage Application"):
    return {"status": status, "selected_category": selected, "detected_category": detected,
            "matches_selected_category": detected == selected, "confidence": confidence,
            "reason": "Identity document markers are present."}


def _upload(token, aid):
    return client.post(f"/api/v1/applications/{aid}/documents", headers=H(token),
                       data={"category": "Mortgage Application"},
                       files={"file": ("evidence.png", png_bytes(), "image/png")})


def test_upload_reports_correct_category_match(monkeypatch):
    token, aid = _setup(monkeypatch, "Category Match", "category-match@example.com", _result("MATCH", detected="Mortgage Application"))
    response = _upload(token, aid)
    assert response.status_code == 200, response.text
    assert response.json()["category_check"]["status"] == "MATCH"
    assert response.json()["category_check"]["matches_selected_category"] is True


def test_mismatch_blocks_single_and_bulk_analysis_until_explicit_category_confirmation(monkeypatch):
    token, aid = _setup(monkeypatch, "Category Mismatch", "category-mismatch@example.com", _result("MISMATCH_PENDING"))
    response = _upload(token, aid)
    assert response.status_code == 200, response.text
    document = response.json()
    assert document["category_match_status"] == "MISMATCH_PENDING"
    with SessionLocal() as db:
        assert db.query(ApplicationDocumentChunk).filter_by(document_id=document["id"]).count() == 0
    single = client.post(f"/api/v1/ai/applications/{aid}/documents/{document['id']}/analyze", headers=H(token))
    bulk = client.post(f"/api/v1/ai/applications/{aid}/analyze", headers=H(token))
    assert single.status_code == 409 and "mismatch" in single.json()["detail"].lower()
    assert bulk.status_code == 409 and "mismatch" in bulk.json()["detail"].lower()
    wrong = client.put(f"/api/v1/applications/{aid}/documents/{document['id']}/category", headers=H(token), json={"category": "KYC", "confirm": True})
    assert wrong.status_code == 200, wrong.text
    assert wrong.json()["category"] == "KYC" and wrong.json()["category_match_status"] == "CONFIRMED_BY_CUSTOMER"
    assert wrong.json()["category_check"]["selected_category"] == "Mortgage Application"
    assert wrong.json()["category_check"]["detected_category"] == "KYC"
    assert wrong.json()["category_check"]["matches_selected_category"] is None
    with SessionLocal() as db:
        chunks = db.query(ApplicationDocumentChunk).filter_by(document_id=document["id"]).all()
        assert chunks and all(chunk.source_category == "KYC" for chunk in chunks)


def test_low_confidence_and_invalid_classification_are_unverified(monkeypatch):
    token, aid = _setup(monkeypatch, "Category Low Confidence", "category-low@example.com", _result("UNVERIFIED", confidence=0.61))
    response = _upload(token, aid)
    assert response.status_code == 200 and response.json()["category_match_status"] == "UNVERIFIED"
    token2, aid2 = _setup(monkeypatch, "Category Invalid Result", "category-invalid@example.com", None)
    response2 = _upload(token2, aid2)
    assert response2.status_code == 200 and response2.json()["category_match_status"] == "UNVERIFIED"
    assert client.post(f"/api/v1/ai/applications/{aid2}/documents/{response2.json()['id']}/analyze", headers=H(token2)).status_code != 409


def test_empty_or_failed_ocr_is_unverified_and_can_be_explicitly_confirmed(monkeypatch):
    token, aid = _setup(monkeypatch, "Category OCR Failure", "category-ocr-failure@example.com", None, extracted_text="", extraction_status="NEEDS_REVIEW")
    response = _upload(token, aid)
    assert response.status_code == 200
    doc = response.json()
    assert doc["category_match_status"] == "UNVERIFIED" and "not enough readable text" in doc["category_match_reason"].lower()
    assert client.put(f"/api/v1/applications/{aid}/documents/{doc['id']}/category", headers=H(token), json={"category": "Mortgage Application", "confirm": True}).status_code == 200


def test_category_confirmation_requires_owner_auth_and_explicit_confirmation(monkeypatch):
    token, aid = _setup(monkeypatch, "Category Owner", "category-owner@example.com", _result("MISMATCH_PENDING"))
    doc = _upload(token, aid).json()
    path = f"/api/v1/applications/{aid}/documents/{doc['id']}/category"
    assert client.put(path, json={"category": "KYC", "confirm": True}).status_code == 401
    assert client.put(path, headers=H(token), json={"category": "KYC", "confirm": False}).status_code == 422
    other = register_and_verify(monkeypatch, "Other Category Owner", "category-other@example.com")
    assert client.put(path, headers=H(other), json={"category": "KYC", "confirm": True}).status_code == 404


@pytest.mark.asyncio
async def test_nemotron_classifier_validates_schema_allowed_categories_and_confidence(monkeypatch):
    class Response:
        def __init__(self, content):
            self.choices = [SimpleNamespace(message=SimpleNamespace(content=content))]
    async def completion(*_args, **_kwargs):
        return Response('{"selected_category":"Mortgage Application","detected_category":"KYC","matches_selected_category":false,"confidence":0.96,"reason":"Identity markers found."}')
    monkeypatch.setattr("app.services.nvidia._client", lambda: object())
    monkeypatch.setattr("app.services.nvidia._guarded_chat_completion", completion)
    mismatch = await classify_document_category("Aadhaar identity proof. " * 8, "Mortgage Application", ["Mortgage Application", "KYC"])
    assert mismatch["status"] == "MISMATCH_PENDING"
    async def matching(*_args, **_kwargs):
        return Response('{"selected_category":"Mortgage Application","detected_category":"Mortgage Application","matches_selected_category":true,"confidence":0.96,"reason":"Mortgage application fields found."}')
    monkeypatch.setattr("app.services.nvidia._guarded_chat_completion", matching)
    assert (await classify_document_category("Mortgage application form. " * 8, "Mortgage Application", ["Mortgage Application", "KYC"]))["status"] == "MATCH"
    async def low(*_args, **_kwargs):
        return Response('{"selected_category":"Mortgage Application","detected_category":"KYC","matches_selected_category":false,"confidence":0.55,"reason":"Weak clues."}')
    monkeypatch.setattr("app.services.nvidia._guarded_chat_completion", low)
    uncertain = await classify_document_category("Aadhaar identity proof. " * 8, "Mortgage Application", ["Mortgage Application", "KYC"])
    assert uncertain["status"] == "UNVERIFIED"
    async def invalid(*_args, **_kwargs):
        return Response('{"selected_category":"Mortgage Application","detected_category":"unsupported","matches_selected_category":false,"confidence":0.99,"reason":"Unknown."}')
    monkeypatch.setattr("app.services.nvidia._guarded_chat_completion", invalid)
    assert await classify_document_category("Aadhaar identity proof. " * 8, "Mortgage Application", ["Mortgage Application", "KYC"]) is None
