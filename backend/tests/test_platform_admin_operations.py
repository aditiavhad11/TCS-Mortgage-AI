from datetime import datetime, timedelta, timezone

import pytest
pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")
pytest.importorskip("email_validator")

from fastapi.testclient import TestClient
from sqlalchemy import select, func

from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import (AdminNotification, AnalysisRun, AuditLog, Bank, BankAdmin,
                        BankInvitation, Customer, MortgageApplication, PlatformAdmin,
                        VerificationCode)
from app.security import clear_failures

client = TestClient(app)
ADMIN_EMAIL = "ops-test-admin@example.com"


@pytest.fixture
def admin_headers(monkeypatch):
    monkeypatch.setattr(settings, "initial_admin_email", ADMIN_EMAIL)
    monkeypatch.setattr(settings, "otp_resend_cooldown_seconds", 0)
    monkeypatch.setattr("app.routers.admin.deliver_otp", lambda *_: "email")
    monkeypatch.setattr("app.routers.admin.secrets.randbelow", lambda _n: 654321)
    clear_failures("admin:" + ADMIN_EMAIL)
    clear_failures("adminotp-lock:" + ADMIN_EMAIL)
    with SessionLocal() as db:
        db.query(VerificationCode).delete()
        db.query(PlatformAdmin).filter(PlatformAdmin.email == ADMIN_EMAIL).delete()
        db.add(PlatformAdmin(full_name="Ops Admin", email=ADMIN_EMAIL, password_hash="otp-only", is_active=True))
        db.commit()
    assert client.post("/api/v1/admin/login", json={"email": ADMIN_EMAIL}).status_code == 200
    auth = client.post("/api/v1/admin/login/verify-otp", json={"email": ADMIN_EMAIL, "code": "654321"})
    assert auth.status_code == 200, auth.text
    yield {"Authorization": f"Bearer {auth.json()['access_token']}"}
    with SessionLocal() as db:
        db.query(VerificationCode).delete()
        db.query(PlatformAdmin).filter(PlatformAdmin.email == ADMIN_EMAIL).delete()
        db.commit()


def test_admin_operations_require_verified_platform_admin(admin_headers):
    assert client.get("/api/v1/admin/monitoring").status_code == 401
    assert client.get("/api/v1/admin/reports", headers=admin_headers).status_code == 200


def test_customer_directory_filters_paginates_and_audits_account_action(admin_headers):
    with SessionLocal() as db:
        customer = Customer(full_name="Directory Example", email="directory@example.com", mobile="9876543210",
                            password_hash="unused", is_verified=True, is_active=True,
                            created_at=datetime.now(timezone.utc))
        db.add(customer); db.commit(); customer_id = customer.id
    res = client.get("/api/v1/admin/customers?q=Directory&verified=verified&limit=10&offset=0", headers=admin_headers)
    assert res.status_code == 200
    assert res.json()["total"] == 1
    assert res.json()["items"][0]["email"] == "d***@example.com"
    assert client.get("/api/v1/admin/customers?q=Directory&status=suspended", headers=admin_headers).json()["total"] == 0
    assert client.get("/api/v1/admin/customers?start=2026-10-25&end=2026-10-01", headers=admin_headers).status_code == 422
    assert client.get("/api/v1/admin/customers?sort=unknown", headers=admin_headers).status_code == 422
    changed = client.patch(f"/api/v1/admin/customers/{customer_id}/status", headers=admin_headers,
                           json={"active": False, "reason": "Verified support request"})
    assert changed.status_code == 200 and changed.json()["active"] is False
    with SessionLocal() as db:
        assert db.scalar(select(AuditLog).where(AuditLog.resource_type == "customer", AuditLog.resource_id == str(customer_id)))


def test_bank_admin_invitation_state_suspend_and_revoke(admin_headers, monkeypatch):
    monkeypatch.setattr("app.routers.admin.send_email", lambda *_: None)
    with SessionLocal() as db:
        bank = Bank(name="Ops Approved Bank", code="OPS-APPROVED", status="APPROVED", contact_email="bank@example.com")
        db.add(bank); db.commit(); bank_id = bank.id
    invitation = client.post("/api/v1/admin/bank-invitations", headers=admin_headers,
                             json={"bank_id": bank_id, "full_name": "Bank Operator", "email": "operator@example.com"})
    assert invitation.status_code == 201
    assert "invitation_token" not in invitation.json() and invitation.json()["delivery"] == "EMAIL_SENT"
    rows = client.get("/api/v1/admin/bank-admins", headers=admin_headers).json()["items"]
    row = next(x for x in rows if x["email"] == "operator@example.com")
    assert row["invitation_status"] == "pending" and "invitation_token" not in row
    revoked = client.post(f"/api/v1/admin/bank-invitations/{row['id']}/revoke", headers=admin_headers,
                          json={"active": False, "reason": "Invitation no longer required"})
    assert revoked.status_code == 200
    assert next(x for x in client.get("/api/v1/admin/bank-admins", headers=admin_headers).json()["items"]
                if x["email"] == "operator@example.com")["invitation_status"] == "revoked"
    with SessionLocal() as db:
        account = BankAdmin(bank_id=bank_id, full_name="Existing Admin", email="existing-ops@example.com", password_hash="unused")
        db.add(account); db.commit(); account_id = account.id
    result = client.patch(f"/api/v1/admin/bank-admins/{account_id}/status", headers=admin_headers,
                          json={"active": False, "reason": "Access review completed"})
    assert result.status_code == 200 and not result.json()["active"]


def test_monitoring_reports_notifications_and_csv_are_real_and_persistent(admin_headers):
    with SessionLocal() as db:
        bank = Bank(name="Attention Bank", code="OPS-PENDING", status="PENDING", contact_email="pending@example.com")
        db.add(bank)
        customer = Customer(full_name="Report Person", email="report@example.com", mobile="9999999999", password_hash="unused")
        db.add(customer); db.flush()
        app_row = MortgageApplication(reference="OPS-REPORT-1", customer_id=customer.id, status="SUBMITTED")
        db.add(app_row); db.flush()
        db.add(AnalysisRun(application_id=app_row.id, customer_id=customer.id, status="FAILED", error_message="private detail"))
        db.commit()
    monitor = client.get("/api/v1/admin/monitoring", headers=admin_headers)
    assert monitor.status_code == 200
    status_by_name = {x["name"]: x["status"] for x in monitor.json()["services"]}
    assert status_by_name["Database"] == "Healthy"
    assert status_by_name["RAG / retrieval"] == "Unknown"
    assert status_by_name["NeMo Guardrails"] == "Unknown"
    first = client.get("/api/v1/admin/notifications?category=AI", headers=admin_headers).json()
    second = client.get("/api/v1/admin/notifications?category=AI", headers=admin_headers).json()
    assert first["total"] == second["total"] == 1
    report = client.get("/api/v1/admin/reports", headers=admin_headers).json()
    assert report["analysis_by_status"].get("FAILED") == 1
    csv_response = client.get("/api/v1/admin/reports.csv", headers=admin_headers)
    assert csv_response.status_code == 200 and "FAILED" in csv_response.text
    assert "private detail" not in csv_response.text


def test_notification_delete_is_persistent_deduplicated_and_keeps_audit(admin_headers):
    suffix = "Delete Flow Sentinel"
    with SessionLocal() as db:
        bank = Bank(name=suffix, code="OPS-DELETE", status="PENDING", contact_email="delete-alert@example.com")
        db.add(bank); db.commit(); bank_id = bank.id
    first = client.get(f"/api/v1/admin/notifications?q={suffix}", headers=admin_headers).json()
    again = client.get(f"/api/v1/admin/notifications?q={suffix}", headers=admin_headers).json()
    assert first["total"] == again["total"] == 1
    filtered = client.get(f"/api/v1/admin/notifications?q={suffix}&category=BANK&severity=MEDIUM&read_status=unread", headers=admin_headers).json()
    assert filtered["total"] == 1 and filtered["unread_count"] >= 1
    notification = first["items"][0]
    assert notification["category"] == "BANK" and notification["read"] is False
    read = client.patch(f"/api/v1/admin/notifications/{notification['id']}/read", headers=admin_headers,
                        json={"read": True})
    assert read.status_code == 200 and read.json()["unread_count"] >= 0
    assert client.get(f"/api/v1/admin/notifications?q={suffix}&read_status=unread", headers=admin_headers).json()["total"] == 0
    deleted = client.delete(f"/api/v1/admin/notifications/{notification['id']}", headers=admin_headers)
    assert deleted.status_code == 200 and deleted.json()["deleted"] is True
    assert client.get(f"/api/v1/admin/notifications?q={suffix}", headers=admin_headers).json()["total"] == 0
    with SessionLocal() as db:
        assert db.scalar(select(AdminNotification).where(AdminNotification.id == notification["id"])).deleted_at
        assert db.scalar(select(AuditLog).where(AuditLog.action == "ADMIN_NOTIFICATION_DELETED",
                                                AuditLog.resource_id == str(notification["id"])))
        assert db.get(Bank, bank_id).status == "PENDING"  # notification deletion leaves the source record intact


def test_audit_filters_labels_csv_privacy_and_immutability(admin_headers):
    with SessionLocal() as db:
        event = AuditLog(actor_email="audited-user@example.com", actor_role="PLATFORM_ADMIN",
                         action="LOGIN_FAILED", resource_type="admin", resource_id="redacted-target",
                         detail="unnecessary-private-detail")
        db.add(event); db.commit(); event_id = event.id
    rows = client.get("/api/v1/admin/audit-logs?outcome=failure&action=LOGIN_FAILED", headers=admin_headers)
    assert rows.status_code == 200
    event_row = next(row for row in rows.json()["items"] if row["id"] == event_id)
    assert event_row["action_label"] == "Failed sign-in" and event_row["outcome"] == "Failure"
    assert client.get("/api/v1/admin/audit-logs?severity=high&category=security&action=LOGIN_FAILED", headers=admin_headers).status_code == 200
    exported = client.get("/api/v1/admin/audit-logs.csv?outcome=failure&action=LOGIN_FAILED", headers=admin_headers)
    assert exported.status_code == 200 and "LOGIN_FAILED" in exported.text
    assert "unnecessary-private-detail" not in exported.text
    assert client.patch(f"/api/v1/admin/audit-logs/{event_id}", headers=admin_headers, json={"detail": "changed"}).status_code in {404, 405}
    assert client.get("/api/v1/admin/audit-logs?start=2026-10-25&end=2026-10-01", headers=admin_headers).status_code == 422


def test_report_period_filter_and_settings_redact_secrets(admin_headers, monkeypatch):
    old_day = datetime.now(timezone.utc) - timedelta(days=20)
    with SessionLocal() as db:
        db.add(Bank(name="Old Period Sentinel", code="OPS-OLD-PERIOD", status="PERIOD_TEST", contact_email="old-period@example.com", created_at=old_day))
        db.commit()
    all_time = client.get("/api/v1/admin/reports", headers=admin_headers)
    period = client.get(f"/api/v1/admin/reports?start={datetime.now(timezone.utc).date().isoformat()}", headers=admin_headers)
    assert all_time.status_code == period.status_code == 200
    assert all_time.json()["banks_by_status"].get("PERIOD_TEST") == 1
    assert "PERIOD_TEST" not in period.json()["banks_by_status"]
    assert client.get("/api/v1/admin/reports.csv?start=2026-10-25&end=2026-10-01", headers=admin_headers).status_code == 422
    monkeypatch.setattr(settings, "nvidia_api_key", "DO_NOT_EXPOSE_NVIDIA_SENTINEL")
    monkeypatch.setattr(settings, "smtp_password", "DO_NOT_EXPOSE_SMTP_SENTINEL")
    result = client.get("/api/v1/admin/configuration", headers=admin_headers)
    assert result.status_code == 200
    assert "DO_NOT_EXPOSE_NVIDIA_SENTINEL" not in result.text
    assert "DO_NOT_EXPOSE_SMTP_SENTINEL" not in result.text
    assert result.json()["authentication"]["platform_admin"] == "Email and OTP"
    assert "documents" in result.json() and "database_status" in result.json()


def test_bank_invitation_edit_resend_revoke_delete_preserves_audit(admin_headers, monkeypatch):
    delivered=[]
    monkeypatch.setattr("app.routers.admin.send_email",lambda email,*_:delivered.append(email))
    with SessionLocal() as db:
        bank=Bank(name="Inv Manage Bank",code="OPS-INV-MGMT",status="APPROVED",contact_email="inv-mgmt-bank@example.com")
        bank2=Bank(name="Inv Manage Bank Two",code="OPS-INV-MGMT2",status="APPROVED",contact_email="inv-mgmt-bank2@example.com")
        db.add_all([bank,bank2]);db.commit();bank_id=bank.id;bank2_id=bank2.id
    first=client.post("/api/v1/admin/bank-invitations",headers=admin_headers,json={"bank_id":bank_id,"full_name":"Invite Operator","email":"old-typo@example.com"})
    second=client.post("/api/v1/admin/bank-invitations",headers=admin_headers,json={"bank_id":bank2_id,"full_name":"Other Operator","email":"other-operator@example.com"})
    assert first.status_code==second.status_code==201
    first_id=first.json()["invitation_id"];second_id=second.json()["invitation_id"]
    with SessionLocal() as db: old_hash=db.get(BankInvitation,first_id).token_hash
    edited=client.patch(f"/api/v1/admin/bank-invitations/{first_id}",headers=admin_headers,json={"bank_id":bank_id,"full_name":"Corrected Operator","email":"corrected-operator@example.com","reason":"Corrected recipient address"})
    assert edited.status_code==200 and edited.json()["delivery"]=="EMAIL_SENT" and delivered[-1]=="corrected-operator@example.com"
    with SessionLocal() as db:
        current=db.get(BankInvitation,first_id);assert current.token_hash!=old_hash and current.email=="corrected-operator@example.com"
    duplicate=client.patch(f"/api/v1/admin/bank-invitations/{second_id}",headers=admin_headers,json={"bank_id":bank_id,"full_name":"Duplicate Operator","email":"CORRECTED-OPERATOR@example.com","reason":"Corrected recipient address"})
    assert duplicate.status_code==409
    assert client.post(f"/api/v1/admin/bank-invitations/{first_id}/resend",headers=admin_headers,json={"reason":"Recipient requested resend"}).status_code==200
    assert delivered[-1]=="corrected-operator@example.com"
    assert client.post(f"/api/v1/admin/bank-invitations/{first_id}/revoke",headers=admin_headers,json={"active":False,"reason":"Invitation no longer needed"}).status_code==200
    deleted=client.request("DELETE",f"/api/v1/admin/bank-invitations/{first_id}",headers=admin_headers,json={"reason":"Remove obsolete invitation"})
    assert deleted.status_code==200
    with SessionLocal() as db:
        assert db.get(BankInvitation,first_id) is None
        assert db.scalar(select(AuditLog).where(AuditLog.action=="BANK_ADMIN_INVITATION_DELETED",AuditLog.resource_id==str(first_id)))


def test_bank_admin_edit_is_platform_admin_only_unique_and_bank_owned(admin_headers):
    with SessionLocal() as db:
        bank=Bank(name="Account Edit Bank",code="OPS-ACCT-EDIT",status="APPROVED",contact_email="account-edit-bank@example.com")
        other=Bank(name="Account Edit Bank Two",code="OPS-ACCT-EDIT2",status="APPROVED",contact_email="account-edit-bank2@example.com")
        db.add_all([bank,other]);db.flush()
        account=BankAdmin(bank_id=bank.id,full_name="Account Edit User",email="account-edit@example.com",password_hash="unused")
        existing=BankAdmin(bank_id=other.id,full_name="Other User",email="already-used@example.com",password_hash="unused")
        db.add_all([account,existing]);db.commit();account_id=account.id;bank_id=bank.id
    payload={"full_name":"Corrected Account User","email":" Corrected-Account@example.com ","reason":"Corrected name and email"}
    assert client.patch(f"/api/v1/admin/bank-admins/{account_id}",json=payload).status_code==401
    conflict=client.patch(f"/api/v1/admin/bank-admins/{account_id}",headers=admin_headers,json={**payload,"email":"already-used@example.com"})
    assert conflict.status_code==409
    edited=client.patch(f"/api/v1/admin/bank-admins/{account_id}",headers=admin_headers,json=payload)
    assert edited.status_code==200 and edited.json()["email"]=="corrected-account@example.com"
    with SessionLocal() as db:
        row=db.get(BankAdmin,account_id);assert row.bank_id==bank_id and row.full_name=="Corrected Account User"


def test_dashboard_metrics_and_activity_use_persisted_records(admin_headers,monkeypatch):
    from app.services import nvidia as nv
    monkeypatch.setattr(settings,"nvidia_api_key","")
    monkeypatch.setattr(nv,"LAST_VERIFICATION",None)
    with SessionLocal() as db:
        bank=Bank(name="Dashboard Source Bank",code="OPS-DASH-SOURCE",status="PENDING",contact_email="dash-source@example.com")
        customer=Customer(full_name="Dashboard Source Customer",email="dash-source-customer@example.com",mobile="9999999911",password_hash="unused")
        db.add_all([bank,customer]);db.flush()
        application=MortgageApplication(reference="OPS-DASH-SOURCE",customer_id=customer.id,status="SUBMITTED")
        db.add(application)
        event=AuditLog(actor_email="private-actor@example.com",actor_role="PLATFORM_ADMIN",action="BANK_ADMIN_INVITED",resource_type="bank_invitation",resource_id="987",detail="safe test detail")
        db.add(event);db.commit()
        submitted_count=db.scalar(select(func.count()).select_from(MortgageApplication).where(MortgageApplication.status=="SUBMITTED"))
    data=client.get("/api/v1/admin/dashboard",headers=admin_headers)
    assert data.status_code==200
    result=data.json()
    assert result["statuses"]["SUBMITTED"]==submitted_count
    assert result["generated_at"] and result["ai"]["configured"] is False and result["ai"]["status"]=="Unavailable"
    activity=next(x for x in result["recent_actions"] if x["action"]=="BANK_ADMIN_INVITED")
    assert activity["action_label"]=="Bank Admin invitation created" and activity["outcome"]=="Recorded"
    assert activity["actor"]!="private-actor@example.com" and activity["resource_type"]=="bank_invitation"

