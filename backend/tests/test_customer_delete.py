import pytest
pytest.importorskip("fastapi"); pytest.importorskip("sqlalchemy")

from sqlalchemy import select
from app.database import SessionLocal
from app.models import ApplicationDocument, AuditLog, Customer, CustomerNotification, MortgageApplication
from tests.test_customer_panel_requirements import client, H, register_and_verify, png_bytes


def test_customer_notification_delete_is_owner_checked_and_persistent(monkeypatch):
    owner = register_and_verify(monkeypatch, "Notice Owner", "notice-owner@example.com")
    other = register_and_verify(monkeypatch, "Notice Other", "notice-other@example.com")
    created = client.post("/api/v1/applications", headers=H(owner), json={"lender_name": "DEMO-BANK"})
    assert created.status_code == 200
    notification = next(n for n in client.get("/api/v1/notifications", headers=H(owner)).json()
                        if n["application_id"] == created.json()["id"])
    unread_before = client.get("/api/v1/customer/dashboard", headers=H(owner)).json()["unread_notifications"]

    denied = client.delete(f"/api/v1/notifications/{notification['id']}", headers=H(other))
    assert denied.status_code == 404
    deleted = client.delete(f"/api/v1/notifications/{notification['id']}", headers=H(owner))
    assert deleted.status_code == 200 and deleted.json()["deleted"] is True
    assert notification["id"] not in [n["id"] for n in client.get("/api/v1/notifications", headers=H(owner)).json()]
    dashboard = client.get("/api/v1/customer/dashboard", headers=H(owner)).json()
    assert dashboard["unread_notifications"] == len([n for n in client.get("/api/v1/notifications", headers=H(owner)).json() if not n["read"]])
    assert dashboard["unread_notifications"] == unread_before - int(not notification["read"])
    assert client.delete(f"/api/v1/notifications/{notification['id']}", headers=H(owner)).status_code == 404


def test_draft_delete_cleans_documents_and_preserves_audit(monkeypatch):
    from app.config import settings
    owner = register_and_verify(monkeypatch, "Delete Draft", "delete-draft@example.com")
    other = register_and_verify(monkeypatch, "Other Draft", "other-draft@example.com")
    aid = client.post("/api/v1/applications", headers=H(owner), json={"lender_name": "DEMO-BANK"}).json()["id"]
    monkeypatch.setattr("app.routers.documents.extract_text", lambda path: ("Applicant name: Delete Draft", "COMPLETED", "test"))
    uploaded = client.post(f"/api/v1/applications/{aid}/documents", headers=H(owner), data={"category": "KYC"}, files={"file": ("id.png", png_bytes(), "image/png")})
    assert uploaded.status_code == 200, uploaded.text
    from pathlib import Path
    with SessionLocal() as db:
        stored_name = db.scalar(select(ApplicationDocument.stored_filename).where(ApplicationDocument.id == uploaded.json()["id"]))
    stored = Path(settings.uploads_dir).resolve() / stored_name
    assert stored.is_file()

    assert client.delete(f"/api/v1/applications/{aid}", headers=H(other)).status_code == 404
    deleted = client.delete(f"/api/v1/applications/{aid}", headers=H(owner))
    assert deleted.status_code == 200 and deleted.json()["deleted"] is True
    assert client.get(f"/api/v1/applications/{aid}", headers=H(owner)).status_code == 404
    assert aid not in [row["id"] for row in client.get("/api/v1/applications", headers=H(owner)).json()]
    assert client.get("/api/v1/customer/dashboard", headers=H(owner)).json()["total_applications"] == 0
    assert not stored.exists()
    with SessionLocal() as db:
        audit = db.scalar(select(AuditLog).where(AuditLog.action == "APPLICATION_DRAFT_DELETED", AuditLog.resource_id == str(aid)))
        assert audit is not None
        customer_id = db.scalar(select(Customer.id).where(Customer.email == "delete-draft@example.com"))
        related_notice = db.scalar(select(CustomerNotification).where(CustomerNotification.customer_id == customer_id))
        assert related_notice is not None and related_notice.application_id is None
        assert db.scalar(select(MortgageApplication).where(MortgageApplication.id == aid)) is None


def test_non_draft_application_delete_is_rejected(monkeypatch):
    token = register_and_verify(monkeypatch, "Submitted Draft", "submitted-delete@example.com")
    aid = client.post("/api/v1/applications", headers=H(token), json={"lender_name": "DEMO-BANK"}).json()["id"]
    with SessionLocal() as db:
        row = db.get(MortgageApplication, aid)
        row.status = "SUBMITTED"
        db.commit()
    response = client.delete(f"/api/v1/applications/{aid}", headers=H(token))
    assert response.status_code == 409
    assert client.get(f"/api/v1/applications/{aid}", headers=H(token)).status_code == 200
