import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.database import SessionLocal
from app.models import Bank, BankAdmin, Reviewer, ReviewerInvitation, Customer, MortgageApplication, ReviewAssignment
from app.security import hash_password, token_for

client = TestClient(app)


def create_admin_pair():
    suffix = uuid.uuid4().hex[:12]
    with SessionLocal() as db:
        bank = Bank(name=f"Reviewer Flow Bank {suffix}", code=f"RFB{suffix.upper()}", status="APPROVED", contact_email=f"bank-{suffix}@example.com")
        db.add(bank); db.flush()
        admin = BankAdmin(bank_id=bank.id, full_name="Reviewer Flow Admin", email=f"admin-{suffix}@example.com", password_hash=hash_password("Bank-Admin-Password-2026!"))
        db.add(admin); db.commit()
        bank_id, admin_id = bank.id, admin.id
    return bank_id, admin_id, {"Authorization": f"Bearer {token_for(f'bankadmin:{admin_id}')}"}


def invite_reviewer(headers, monkeypatch, suffix=None):
    suffix = suffix or uuid.uuid4().hex[:12]
    messages = []
    monkeypatch.setattr("app.routers.bank_admin.send_email", lambda to, subject, body: messages.append((to, subject, body)))
    response = client.post("/api/v1/bank-admin/reviewers", headers=headers, json={"full_name": "New Reviewer", "email": f"reviewer-{suffix}@example.com", "specialisation": "GENERAL_MORTGAGE_REVIEW", "max_active_assignments": 3})
    return response, messages


def token_from_message(messages):
    assert messages
    match = re.search(r"/reviewer\?activate=([^\s]+)", messages[-1][2])
    assert match
    return match.group(1)


def test_invitation_creates_inactive_account_without_password_or_returning_token(monkeypatch):
    _, _, headers = create_admin_pair()
    response, messages = invite_reviewer(headers, monkeypatch)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["account_status"] == "INVITATION_PENDING"
    assert body["delivery"] == "EMAIL_SENT"
    assert "token" not in body and "password" not in body
    assert messages[0][0] == body["email"]
    token = token_from_message(messages)
    with SessionLocal() as db:
        row = db.get(Reviewer, body["id"])
        invitation = db.scalar(select(ReviewerInvitation).where(ReviewerInvitation.reviewer_id == row.id))
        assert row.is_active is False
        assert row.password_hash and token not in row.password_hash and token not in invitation.token_hash
        assert invitation.token_hash != token
    assert client.post("/api/v1/reviewer/login", json={"email": body["email"], "password": "Any-Password-2026!"}).status_code == 401


def test_invitation_rejects_duplicate_email_and_bank_admin_password_submission(monkeypatch):
    _, _, headers = create_admin_pair()
    response, _ = invite_reviewer(headers, monkeypatch, "duplicate-flow")
    assert response.status_code == 201
    duplicate = client.post("/api/v1/bank-admin/reviewers", headers=headers, json={"full_name": "Duplicate Reviewer", "email": "REVIEWER-DUPLICATE-FLOW@example.com"})
    assert duplicate.status_code == 409
    password = client.post("/api/v1/bank-admin/reviewers", headers=headers, json={"full_name": "Unsafe Password", "email": f"unsafe-{uuid.uuid4().hex[:8]}@example.com", "password": "Reviewer-Password-2026!"})
    assert password.status_code == 422


def test_activation_is_single_use_and_enables_reviewer_signin(monkeypatch):
    _, _, headers = create_admin_pair()
    response, messages = invite_reviewer(headers, monkeypatch)
    token = token_from_message(messages)
    email = response.json()["email"]
    activated = client.post("/api/v1/reviewer/accept-invitation", json={"token": token, "password": "Reviewer-Password-2026!"})
    assert activated.status_code == 200, activated.text
    assert activated.json()["email"] == email
    assert client.post("/api/v1/reviewer/accept-invitation", json={"token": token, "password": "Another-Password-2026!"}).status_code == 400
    login = client.post("/api/v1/reviewer/login", json={"email": email.upper(), "password": "Reviewer-Password-2026!"})
    assert login.status_code == 200, login.text
    assert client.get("/api/v1/reviewer/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"}).status_code == 200


def test_expired_invitation_cannot_activate(monkeypatch):
    response, messages = invite_reviewer(create_admin_pair()[2], monkeypatch)
    token = token_from_message(messages)
    with SessionLocal() as db:
        invitation = db.scalar(select(ReviewerInvitation).where(ReviewerInvitation.reviewer_id == response.json()["id"]))
        invitation.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    activated = client.post("/api/v1/reviewer/accept-invitation", json={"token": token, "password": "Reviewer-Password-2026!"})
    assert activated.status_code == 400
    with SessionLocal() as db:
        assert db.get(Reviewer, response.json()["id"]).is_active is False


def test_revoked_invitation_cannot_activate(monkeypatch):
    _, _, headers = create_admin_pair()
    response, messages = invite_reviewer(headers, monkeypatch)
    token = token_from_message(messages)
    revoked = client.post(f"/api/v1/bank-admin/reviewers/{response.json()['id']}/revoke-invitation", headers=headers)
    assert revoked.status_code == 200
    assert client.post("/api/v1/reviewer/accept-invitation", json={"token": token, "password": "Reviewer-Password-2026!"}).status_code == 400


def test_resend_rotates_invitation_and_resend_is_rate_limited(monkeypatch):
    _, _, headers = create_admin_pair()
    response, messages = invite_reviewer(headers, monkeypatch)
    old_token = token_from_message(messages)
    with SessionLocal() as db:
        invitation = db.scalar(select(ReviewerInvitation).where(ReviewerInvitation.reviewer_id == response.json()["id"]))
        invitation.created_at = datetime.now(timezone.utc) - timedelta(seconds=61)
        db.commit()
    resent = client.post(f"/api/v1/bank-admin/reviewers/{response.json()['id']}/resend-invitation", headers=headers)
    assert resent.status_code == 200, resent.text
    new_token = token_from_message(messages)
    assert new_token != old_token
    assert client.post("/api/v1/reviewer/accept-invitation", json={"token": old_token, "password": "Reviewer-Password-2026!"}).status_code == 400
    assert client.post(f"/api/v1/bank-admin/reviewers/{response.json()['id']}/resend-invitation", headers=headers).status_code == 429
    assert client.post("/api/v1/reviewer/accept-invitation", json={"token": new_token, "password": "Reviewer-Password-2026!"}).status_code == 200


def test_wrong_invitation_token_is_rate_limited(monkeypatch):
    token = secrets.token_urlsafe(36)
    statuses = [client.post("/api/v1/reviewer/accept-invitation", json={"token": token, "password": "Reviewer-Password-2026!"}).status_code for _ in range(6)]
    assert statuses[:5] == [400] * 5
    assert statuses[5] == 429


def test_reviewer_routes_and_profile_are_bank_scoped(monkeypatch):
    _, _, headers = create_admin_pair()
    _, _, other_headers = create_admin_pair()
    response, messages = invite_reviewer(headers, monkeypatch)
    reviewer_id = response.json()["id"]
    own = client.get(f"/api/v1/bank-admin/reviewers/{reviewer_id}", headers=headers)
    assert own.status_code == 200 and own.json()["profile"]["account_status"] == "INVITATION_PENDING"
    assert own.json()["workload"]["active_assignments"] == 0
    assert client.get(f"/api/v1/bank-admin/reviewers/{reviewer_id}", headers=other_headers).status_code == 404
    assert client.post(f"/api/v1/bank-admin/reviewers/{reviewer_id}/revoke-invitation", headers=other_headers).status_code == 404
    summary = client.get("/api/v1/bank-admin/reviewers/summary", headers=headers)
    assert summary.status_code == 200 and summary.json()["pending_invitations"] == 1
    assert summary.json()["total_reviewers"] == 0


def test_email_delivery_failure_is_reported_and_does_not_create_reviewer(monkeypatch):
    _, _, headers = create_admin_pair()
    monkeypatch.setattr("app.routers.bank_admin.send_email", lambda *_: (_ for _ in ()).throw(RuntimeError("mail unavailable")))
    email = f"failed-{uuid.uuid4().hex[:8]}@example.com"
    response = client.post("/api/v1/bank-admin/reviewers", headers=headers, json={"full_name": "No Delivery", "email": email})
    assert response.status_code == 503
    with SessionLocal() as db:
        assert db.scalar(select(Reviewer.id).where(Reviewer.email == email)) is None


def test_reviewer_cannot_open_cross_bank_application_even_if_assignment_is_inconsistent():
    suffix=uuid.uuid4().hex[:12]
    with SessionLocal() as db:
        bank_a=Bank(name=f"Review Scope A {suffix}",code=f"RSA{suffix.upper()}",status="APPROVED",contact_email=f"a-{suffix}@example.com")
        bank_b=Bank(name=f"Review Scope B {suffix}",code=f"RSB{suffix.upper()}",status="APPROVED",contact_email=f"b-{suffix}@example.com")
        db.add_all([bank_a,bank_b]);db.flush()
        reviewer=Reviewer(bank_id=bank_a.id,bank_code=bank_a.code,full_name="Scoped Reviewer",email=f"scoped-{suffix}@example.com",password_hash=hash_password("Reviewer-Password-2026!"))
        customer=Customer(full_name="Scope Customer",email=f"customer-{suffix}@example.com",mobile="9999999999",password_hash=hash_password("Customer-Password-2026!"))
        db.add_all([reviewer,customer]);db.flush()
        application=MortgageApplication(reference=f"RS{suffix.upper()[:20]}",customer_id=customer.id,bank_id=bank_b.id,lender_name=bank_b.code,status="ASSIGNED",requested_loan=1000000,property_value=2000000)
        db.add(application);db.flush()
        db.add(ReviewAssignment(application_id=application.id,reviewer_id=reviewer.id,assigned_by="test",active=True))
        reviewer_id,application_id=reviewer.id,application.id
        db.commit()
    reviewer_token=token_for(f"reviewer:{reviewer_id}")
    headers={"Authorization":f"Bearer {reviewer_token}"}
    assert client.get("/api/v1/reviewer/applications",headers=headers).json()==[]
    denied=client.get(f"/api/v1/reviewer/applications/{application_id}",headers=headers)
    assert denied.status_code==404
