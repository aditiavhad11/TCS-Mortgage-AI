"""Authenticated bank policy PDF extraction, persistence, and retrieval tests."""
from io import BytesIO
import shutil
from datetime import datetime, timedelta, timezone

import fitz
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.database import SessionLocal
from app.models import Bank, BankAdmin, PolicyChunk, PolicyDocument
from app.security import hash_password, token_for
from app.config import settings

client = TestClient(app)


def _bank_admin(code):
    with SessionLocal() as db:
        bank = Bank(name=f"{code} Bank", code=code, status="APPROVED", contact_email=f"{code.lower()}@example.test")
        db.add(bank); db.flush()
        admin = BankAdmin(bank_id=bank.id, full_name="Policy Admin", email=f"admin-{code.lower()}@example.test", password_hash=hash_password("Test-Policy-Password-2026!"))
        db.add(admin); db.commit()
        return bank.id, token_for(f"bankadmin:{admin.id}")


def _pdf(text="The mortgage policy requires customer identity verification before loan disbursement."):
    document = fitz.open(); page = document.new_page(); page.insert_text((72, 72), text)
    return document.tobytes()


def _upload(data, filename="policy.pdf", content_type="application/pdf"):
    return {"file": (filename, data, content_type)}


def _policy_data(title, version, extracted):
    return {"title": title, "policy_version": version, "category": "Mortgage", "content": extracted,
            "active": "true", "customer_visible": "true", "customer_summary": "Customers must verify identity before loan disbursement."}


def test_policy_pdf_extract_save_directory_and_secure_download(monkeypatch, tmp_path):
    bank_id, token = _bank_admin("PDF_SAVE")
    monkeypatch.setattr(settings, "uploads_dir", str(tmp_path))
    headers = {"Authorization": f"Bearer {token}"}
    pdf = _pdf()
    extracted = client.post("/api/v1/bank-admin/policies/extract", headers=headers, files=_upload(pdf))
    assert extracted.status_code == 200, extracted.text
    result = extracted.json()
    assert result["extraction_status"] == "COMPLETED"
    assert "[PAGE 1]" in result["extracted_text"] and "identity verification" in result["extracted_text"]
    assert result["page_count"] == 1
    saved = client.post("/api/v1/bank-admin/policies/from-pdf", headers=headers,
                        data={**_policy_data("Uploaded Policy", "1", result["extracted_text"]), "extraction_digest": result["extraction_digest"]}, files=_upload(pdf))
    assert saved.status_code == 201, saved.text
    policy_id = saved.json()["id"]
    listing = client.get("/api/v1/bank-admin/policies", headers=headers)
    assert listing.status_code == 200 and listing.json()[0]["has_source_pdf"]
    assert listing.json()[0]["source_filename"] == "policy.pdf"
    assert listing.json()[0]["text_status"] == "TEXT_SAVED"
    assert listing.json()[0]["indexing_status"] == "COMPLETED"
    assert listing.json()[0]["customer_availability"] == "AVAILABLE"
    assert listing.json()[0]["text_status"] == "TEXT_SAVED"
    assert listing.json()[0]["indexing_status"] == "COMPLETED"
    assert listing.json()[0]["customer_availability"] == "AVAILABLE"
    download = client.get(f"/api/v1/bank-admin/policies/{policy_id}/file", headers=headers)
    assert download.status_code == 200 and download.content == pdf
    foreign_bank_id, foreign_token = _bank_admin("PDF_FOREIGN")
    assert client.get(f"/api/v1/bank-admin/policies/{policy_id}/file", headers={"Authorization": f"Bearer {foreign_token}"}).status_code == 404
    with SessionLocal() as db:
        policy = db.get(PolicyDocument, policy_id)
        assert policy.bank_id == bank_id and policy.content == result["extracted_text"] and policy.source_filename == "policy.pdf"
        chunks = db.scalars(select(PolicyChunk).where(PolicyChunk.policy_id == policy_id)).all()
        assert any(chunk.audience == "INTERNAL" and "identity verification" in chunk.text for chunk in chunks)
        assert any(chunk.audience == "CUSTOMER" and "Customers must verify identity" in chunk.text for chunk in chunks)
        assert all("mortgage policy requires" not in chunk.text for chunk in chunks if chunk.audience == "CUSTOMER")
        from app.services.policy_rag import retrieve_policy_chunks
        customer_rows = retrieve_policy_chunks(db, "identity verification", bank_id=bank_id, customer_visible_only=True)
        assert customer_rows and all(row["audience"] == "CUSTOMER" and "Customers must verify identity" in row["text"] for row in customer_rows)
    assert client.post("/api/v1/bank-admin/policies/extract", files=_upload(pdf)).status_code in (401, 403)


def test_policy_pdf_validation_rejects_empty_invalid_oversized_and_encrypted(monkeypatch):
    _, token = _bank_admin("PDF_VALIDATE")
    headers = {"Authorization": f"Bearer {token}"}
    assert client.post("/api/v1/bank-admin/policies/extract", headers=headers, files=_upload(b"", "empty.pdf")).status_code == 400
    assert client.post("/api/v1/bank-admin/policies/extract", headers=headers, files=_upload(b"%PDF not actually readable", "broken.pdf")).status_code == 422
    monkeypatch.setattr(settings, "max_upload_size_mb", 1)
    assert client.post("/api/v1/bank-admin/policies/extract", headers=headers, files=_upload(b"%PDF" + b"x" * (1024 * 1024), "large.pdf")).status_code == 413
    document = fitz.open(); document.new_page()
    encrypted = document.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="secret")
    assert client.post("/api/v1/bank-admin/policies/extract", headers=headers, files=_upload(encrypted, "encrypted.pdf")).status_code == 422


def test_scanned_policy_pdf_uses_shared_tesseract_pipeline():
    if not shutil.which("tesseract"):
        pytest.skip("Tesseract is not installed")
    from PIL import Image, ImageDraw, ImageFont
    _, token = _bank_admin("PDF_SCAN")
    image = Image.new("RGB", (1400, 260), "white")
    ImageDraw.Draw(image).text((30, 90), "Mortgage policy valuation INR 5200000", fill="black", font=ImageFont.load_default(size=44))
    image_data = BytesIO(); image.save(image_data, format="PNG")
    document = fitz.open(); page = document.new_page(width=700, height=130)
    page.insert_image(page.rect, stream=image_data.getvalue()); pdf = document.tobytes()
    response = client.post("/api/v1/bank-admin/policies/extract", headers={"Authorization": f"Bearer {token}"}, files=_upload(pdf))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["extraction_status"] == "COMPLETED" and "5200000" in result["extracted_text"].replace(" ", "")
    assert "Tesseract" in result["extraction_message"] and "[PAGE 1]" in result["extracted_text"]


@pytest.mark.asyncio
async def test_new_active_policy_version_removes_old_retrieval_chunks(monkeypatch, tmp_path):
    bank_id, token = _bank_admin("PDF_VERSION")
    monkeypatch.setattr(settings, "uploads_dir", str(tmp_path))
    headers = {"Authorization": f"Bearer {token}"}
    for version, text in (("1", "Version one policy content sets the initial mortgage valuation threshold."), ("2", "Version two policy content sets the revised mortgage valuation threshold.")):
        pdf = _pdf(text)
        extracted = client.post("/api/v1/bank-admin/policies/extract", headers=headers, files=_upload(pdf)).json()
        response = client.post("/api/v1/bank-admin/policies/from-pdf", headers=headers,
                               data={**_policy_data("Versioned Policy", version, extracted["extracted_text"]), "extraction_digest": extracted["extraction_digest"]}, files=_upload(pdf))
        assert response.status_code == 201, response.text
    with SessionLocal() as db:
        rows = db.scalars(select(PolicyDocument).where(PolicyDocument.bank_id == bank_id, PolicyDocument.title == "Versioned Policy")).all()
        assert len(rows) == 2
        old = next(row for row in rows if row.policy_version == "1")
        new = next(row for row in rows if row.policy_version == "2")
        assert old.active is False and new.active is True
        assert db.scalars(select(PolicyChunk).where(PolicyChunk.policy_id == old.id)).all() == []
        assert db.scalars(select(PolicyChunk).where(PolicyChunk.policy_id == new.id)).all()


def test_inactive_policy_is_not_indexed_until_authorized_activation():
    _, token = _bank_admin("PDF_ACTIVE")
    headers = {"Authorization": f"Bearer {token}"}
    response = client.post("/api/v1/bank-admin/policies", headers=headers, json={
        "title": "Inactive policy", "policy_version": "1", "category": "Mortgage",
        "content": "This inactive policy content is retained but must not enter retrieval until activated.", "active": False,
        "customer_visible": False, "customer_summary": ""
    })
    assert response.status_code == 201, response.text
    policy_id = response.json()["id"]
    with SessionLocal() as db:
        assert db.scalars(select(PolicyChunk).where(PolicyChunk.policy_id == policy_id)).all() == []
    activated = client.patch(f"/api/v1/bank-admin/policies/{policy_id}/active?active=true", headers=headers)
    assert activated.status_code == 200, activated.text
    with SessionLocal() as db:
        assert db.scalars(select(PolicyChunk).where(PolicyChunk.policy_id == policy_id, PolicyChunk.audience == "INTERNAL")).all()


def test_bank_admin_can_retry_policy_indexing_only_for_own_active_policy(monkeypatch):
    _, token = _bank_admin("PDF_REINDEX")
    _, other_token = _bank_admin("PDF_REINDEX_OTHER")
    monkeypatch.setattr(settings, "nvidia_api_key", "")
    headers = {"Authorization": f"Bearer {token}"}
    saved = client.post("/api/v1/bank-admin/policies", headers=headers, json={
        "title":"Reindex Test Policy", "policy_version":"1", "category":"Mortgage",
        "content":"[Page 1]\nApplicants should provide current proof of income for mortgage review.",
        "active":True, "customer_visible":False, "customer_summary":"",
    })
    assert saved.status_code == 201, saved.text
    policy_id = saved.json()["id"]
    with SessionLocal() as db:
        for chunk in db.scalars(select(PolicyChunk).where(PolicyChunk.policy_id == policy_id)).all():
            chunk.page_number = None
        db.commit()
    listing = client.get("/api/v1/bank-admin/policies", headers=headers)
    assert listing.status_code == 200 and listing.json()[0]["indexing_status"] == "INCOMPLETE"
    assert client.post(f"/api/v1/bank-admin/policies/{policy_id}/reindex").status_code == 401
    assert client.post(f"/api/v1/bank-admin/policies/{policy_id}/reindex", headers={"Authorization": f"Bearer {other_token}"}).status_code == 404
    retried = client.post(f"/api/v1/bank-admin/policies/{policy_id}/reindex", headers=headers)
    assert retried.status_code == 200, retried.text
    assert retried.json()["indexing"]["chunks"] > 0
    with SessionLocal() as db:
        assert any(chunk.page_number == 1 for chunk in db.scalars(select(PolicyChunk).where(PolicyChunk.policy_id == policy_id, PolicyChunk.audience == "INTERNAL")).all())
    refreshed = client.get("/api/v1/bank-admin/policies", headers=headers)
    assert refreshed.json()[0]["indexing_status"] == "COMPLETED"
