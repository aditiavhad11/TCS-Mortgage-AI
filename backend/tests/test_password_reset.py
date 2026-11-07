import hashlib
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")
pytest.importorskip("email_validator")

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import Bank, BankAdmin, Customer, PasswordResetToken, Reviewer
from app.security import hash_password, verify_password
from app.services.mailer import OTPDeliveryError

client=TestClient(app)
OLD_PASSWORD="Old-Password123!"
NEW_PASSWORD="New-Password123!"
ACCOUNTS={
    "CUSTOMER":"reset-customer@example.com",
    "REVIEWER":"reset-reviewer@example.com",
    "BANK_ADMIN":"reset-bank-admin@example.com",
}


@pytest.fixture(autouse=True)
def reset_accounts(monkeypatch):
    monkeypatch.setattr(settings,"otp_resend_cooldown_seconds",0)
    monkeypatch.setattr(settings,"password_reset_expiry_minutes",30)
    monkeypatch.setattr(settings,"frontend_base_url","http://localhost:5173")
    monkeypatch.setattr("app.routers.auth.smtp_configured",lambda:True)
    sent=[]
    monkeypatch.setattr("app.routers.auth.send_email",lambda recipient,subject,body:sent.append((recipient,subject,body)))
    created_bank_id=None
    with SessionLocal() as db:
        for account_type,model in (("CUSTOMER",Customer),("REVIEWER",Reviewer),("BANK_ADMIN",BankAdmin)):
            account_ids=select(model.id).where(model.email.in_(list(ACCOUNTS.values())))
            db.query(PasswordResetToken).filter(
                PasswordResetToken.account_type==account_type,
                PasswordResetToken.account_id.in_(account_ids),
            ).delete(synchronize_session=False)
        db.query(Customer).filter(Customer.email.in_(list(ACCOUNTS.values()))).delete(synchronize_session=False)
        db.query(Reviewer).filter(Reviewer.email.in_(list(ACCOUNTS.values()))).delete(synchronize_session=False)
        db.query(BankAdmin).filter(BankAdmin.email.in_(list(ACCOUNTS.values()))).delete(synchronize_session=False)
        bank=db.scalar(select(Bank).where(Bank.code=="RESET-TEST-BANK"))
        if not bank:
            bank=Bank(name="Reset Test Bank",code="RESET-TEST-BANK",status="APPROVED")
            db.add(bank)
            db.flush()
            created_bank_id=bank.id
        else:
            bank.status="APPROVED"
        db.add_all([
            Customer(full_name="Reset Customer",email=ACCOUNTS["CUSTOMER"],mobile="9999999999",password_hash=hash_password(OLD_PASSWORD),is_verified=True,is_active=True),
            Reviewer(full_name="Reset Reviewer",email=ACCOUNTS["REVIEWER"],password_hash=hash_password(OLD_PASSWORD),bank_code=bank.code,is_active=True),
            BankAdmin(bank_id=bank.id,full_name="Reset Bank Admin",email=ACCOUNTS["BANK_ADMIN"],password_hash=hash_password(OLD_PASSWORD),is_active=True),
        ])
        db.commit()
    yield sent
    with SessionLocal() as db:
        for account_type,model in (("CUSTOMER",Customer),("REVIEWER",Reviewer),("BANK_ADMIN",BankAdmin)):
            account_ids=select(model.id).where(model.email.in_(list(ACCOUNTS.values())))
            db.query(PasswordResetToken).filter(
                PasswordResetToken.account_type==account_type,
                PasswordResetToken.account_id.in_(account_ids),
            ).delete(synchronize_session=False)
        for model in (Customer,Reviewer,BankAdmin):
            db.query(model).filter(model.email.in_(list(ACCOUNTS.values()))).delete(synchronize_session=False)
        if created_bank_id is not None:
            db.query(Bank).filter(Bank.id==created_bank_id).delete(synchronize_session=False)
        db.commit()


@pytest.mark.parametrize(("account_type","endpoint","email"),[
    ("CUSTOMER","/api/v1/auth/login",ACCOUNTS["CUSTOMER"]),
    ("REVIEWER","/api/v1/reviewer/login",ACCOUNTS["REVIEWER"]),
    ("BANK_ADMIN","/api/v1/bank-admin/login",ACCOUNTS["BANK_ADMIN"]),
])
def test_reset_flow_for_password_based_roles(account_type,endpoint,email,reset_accounts):
    requested=client.post("/api/v1/auth/password-reset/request",json={"email":email,"account_type":account_type})
    assert requested.status_code==200
    assert requested.json()["message"]=="If an eligible account exists, the recovery request is processed through its registered email address."
    assert len(reset_accounts)==1
    link=reset_accounts[0][2].splitlines()[2]
    query=parse_qs(urlparse(link).query)
    reset_token=query["reset_token"][0]
    assert urlparse(link).path=={"CUSTOMER":"/","REVIEWER":"/reviewer","BANK_ADMIN":"/bank-admin"}[account_type]
    assert reset_token not in requested.text
    assert account_type!="PLATFORM_ADMIN"
    with SessionLocal() as db:
        token_hash=hashlib.sha256(reset_token.encode()).hexdigest()
        row=db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash==token_hash))
        assert row is not None and row.account_type==account_type

    completed=client.post("/api/v1/auth/password-reset/complete",json={
        "token":reset_token,"password":NEW_PASSWORD,"confirm_password":NEW_PASSWORD,
    })
    assert completed.status_code==200,completed.text
    assert client.post(endpoint,json={"email":email,"password":NEW_PASSWORD}).status_code==200
    assert client.post(endpoint,json={"email":email,"password":OLD_PASSWORD}).status_code!=200
    replay=client.post("/api/v1/auth/password-reset/complete",json={
        "token":reset_token,"password":NEW_PASSWORD,"confirm_password":NEW_PASSWORD,
    })
    assert replay.status_code==400
    with SessionLocal() as db:
        if account_type=="CUSTOMER":
            account=db.scalar(select(Customer).where(Customer.email==email))
        elif account_type=="REVIEWER":
            account=db.scalar(select(Reviewer).where(Reviewer.email==email))
        else:
            account=db.scalar(select(BankAdmin).where(BankAdmin.email==email))
        assert verify_password(NEW_PASSWORD,account.password_hash)


def test_unknown_account_gets_same_request_response_without_email(reset_accounts):
    known=client.post("/api/v1/auth/password-reset/request",json={"email":ACCOUNTS["CUSTOMER"],"account_type":"CUSTOMER"})
    reset_accounts.clear()
    missing=client.post("/api/v1/auth/password-reset/request",json={"email":"missing-reset@example.com","account_type":"CUSTOMER"})
    assert known.status_code==missing.status_code==200
    assert known.json()==missing.json()
    assert reset_accounts==[]


def test_platform_admin_is_not_added_to_password_recovery(reset_accounts):
    response=client.post("/api/v1/auth/password-reset/request",json={
        "email":"admin@example.com","account_type":"PLATFORM_ADMIN",
    })
    assert response.status_code==422


def test_failed_delivery_does_not_reveal_account_existence(monkeypatch,reset_accounts):
    def fail_delivery(*_args,**_kwargs):
        raise OTPDeliveryError("delivery failed")
    monkeypatch.setattr("app.routers.auth.send_email",fail_delivery)
    known=client.post("/api/v1/auth/password-reset/request",json={"email":ACCOUNTS["CUSTOMER"],"account_type":"CUSTOMER"})
    missing=client.post("/api/v1/auth/password-reset/request",json={"email":"missing-reset@example.com","account_type":"CUSTOMER"})
    assert known.status_code==missing.status_code==200
    assert known.json()==missing.json()


def test_reset_link_expires_and_is_consumed(reset_accounts):
    email=ACCOUNTS["CUSTOMER"]
    assert client.post("/api/v1/auth/password-reset/request",json={"email":email,"account_type":"CUSTOMER"}).status_code==200
    token=parse_qs(urlparse(reset_accounts[0][2].splitlines()[2]).query)["reset_token"][0]
    with SessionLocal() as db:
        row=db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash.is_not(None)))
        row.expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)
        db.commit()
    response=client.post("/api/v1/auth/password-reset/complete",json={"token":token,"password":NEW_PASSWORD,"confirm_password":NEW_PASSWORD})
    assert response.status_code==400
    assert "expired" in response.json()["detail"].lower()
