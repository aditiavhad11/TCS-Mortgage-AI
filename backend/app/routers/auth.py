import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select, func, update
from app.database import get_db
from app.config import settings
from app.models import BankAdmin, Customer, PasswordResetToken, Reviewer, VerificationCode
from app.schemas import LoginIn, OTPIn, PasswordResetCompleteIn, PasswordResetRequestIn, ProfileUpdateIn, RegisterIn, ResendOTPIn
from app.security import hash_password, verify_password, token_for, is_locked, note_failure, clear_failures, needs_rehash
from app.dependencies import current_customer
from app.services.audit import record
from app.services.mailer import deliver_otp, send_email, smtp_configured, OTPDeliveryError

router = APIRouter(prefix="/auth", tags=["Authentication"])
PASSWORD_RESET_MESSAGE = "If an eligible account exists, the recovery request is processed through its registered email address."
PASSWORD_RESET_UNAVAILABLE = "Password recovery email is temporarily unavailable. Please try again later or contact support."
RESET_PATHS = {"CUSTOMER": "/", "REVIEWER": "/reviewer", "BANK_ADMIN": "/bank-admin"}

def _customer_json(u):
    return {"id": u.id, "full_name": u.full_name, "email": u.email, "mobile": u.mobile, "is_verified": u.is_verified, "is_active": u.is_active}

def _issue_otp(db: Session, email: str, purpose: str = "email verification") -> str:
    code = f"{secrets.randbelow(1000000):06d}"
    delivery = deliver_otp(email, code, purpose, settings.otp_expiry_minutes)
    for old in db.scalars(select(VerificationCode).where(VerificationCode.email == email, VerificationCode.used == False)).all():
        old.used = True
    db.add(VerificationCode(email=email, code_hash=hash_password(code), expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.otp_expiry_minutes), created_at=datetime.now(timezone.utc)))
    return delivery

def _reset_account(db: Session, account_type: str, email: str):
    model={"CUSTOMER":Customer,"REVIEWER":Reviewer,"BANK_ADMIN":BankAdmin}[account_type]
    account=db.scalar(select(model).where(func.lower(model.email)==email))
    if not account or not account.is_active:
        return None
    if account_type=="CUSTOMER" and not account.is_verified:
        return None
    return account

@router.post("/password-reset/request")
def request_password_reset(data: PasswordResetRequestIn, db: Session = Depends(get_db)):
    if not smtp_configured():
        raise HTTPException(503, PASSWORD_RESET_UNAVAILABLE)
    email=str(data.email).strip().lower()
    account=_reset_account(db,data.account_type,email)
    if not account:
        return {"message":PASSWORD_RESET_MESSAGE}

    now=datetime.now(timezone.utc)
    latest=db.scalar(select(PasswordResetToken).where(
        PasswordResetToken.account_type==data.account_type,
        PasswordResetToken.account_id==account.id,
    ).order_by(PasswordResetToken.created_at.desc()))
    if latest:
        created=latest.created_at.replace(tzinfo=timezone.utc) if latest.created_at.tzinfo is None else latest.created_at
        if (now-created).total_seconds()<settings.otp_resend_cooldown_seconds:
            return {"message":PASSWORD_RESET_MESSAGE}

    token=secrets.token_urlsafe(48)
    token_hash=hashlib.sha256(token.encode()).hexdigest()
    db.query(PasswordResetToken).filter(
        PasswordResetToken.account_type==data.account_type,
        PasswordResetToken.account_id==account.id,
        PasswordResetToken.used_at.is_(None),
    ).update({"used_at":now},synchronize_session=False)
    row=PasswordResetToken(
        account_type=data.account_type,
        account_id=account.id,
        token_hash=token_hash,
        expires_at=now+timedelta(minutes=settings.password_reset_expiry_minutes),
        created_at=now,
    )
    db.add(row)
    query=urlencode({"reset_token":token})
    reset_url=f"{settings.frontend_base_url.rstrip('/')}{RESET_PATHS[data.account_type]}?{query}"
    try:
        send_email(
            account.email,
            f"Reset your {settings.app_name} password",
            f"A password reset was requested for your account. Use the secure link below within {settings.password_reset_expiry_minutes} minutes. The link can only be used once.\n\n{reset_url}\n\nIf you did not request a reset, you can ignore this email.",
        )
    except OTPDeliveryError:
        db.rollback()
        logging.getLogger("auth").warning("Password reset email delivery failed for account type %s", data.account_type)
        return {"message":PASSWORD_RESET_MESSAGE}
    record(db,email,data.account_type,"PASSWORD_RESET_REQUESTED","password_reset",account.id)
    db.commit()
    return {"message":PASSWORD_RESET_MESSAGE}

@router.post("/password-reset/complete")
def complete_password_reset(data: PasswordResetCompleteIn, db: Session = Depends(get_db)):
    now=datetime.now(timezone.utc)
    token_hash=hashlib.sha256(data.token.encode()).hexdigest()
    reset=db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash==token_hash))
    if not reset or reset.used_at is not None:
        raise HTTPException(400,"This password reset link is invalid or has already been used.")
    expires=reset.expires_at.replace(tzinfo=timezone.utc) if reset.expires_at.tzinfo is None else reset.expires_at
    if expires<=now:
        reset.used_at=now
        db.commit()
        raise HTTPException(400,"This password reset link has expired. Request a new one.")

    model={"CUSTOMER":Customer,"REVIEWER":Reviewer,"BANK_ADMIN":BankAdmin}.get(reset.account_type)
    account=db.get(model,reset.account_id) if model else None
    if not account or not account.is_active or (reset.account_type=="CUSTOMER" and not account.is_verified):
        reset.used_at=now
        db.commit()
        raise HTTPException(400,"This password reset link is invalid or has expired.")

    claimed=db.execute(update(PasswordResetToken).where(
        PasswordResetToken.id==reset.id,
        PasswordResetToken.used_at.is_(None),
        PasswordResetToken.expires_at>now,
    ).values(used_at=now).execution_options(synchronize_session=False))
    if claimed.rowcount!=1:
        db.rollback()
        raise HTTPException(400,"This password reset link is invalid or has already been used.")

    account.password_hash=hash_password(data.password)
    db.query(PasswordResetToken).filter(
        PasswordResetToken.account_type==reset.account_type,
        PasswordResetToken.account_id==reset.account_id,
        PasswordResetToken.used_at.is_(None),
    ).update({"used_at":now},synchronize_session=False)
    record(db,account.email,reset.account_type,"PASSWORD_RESET_COMPLETED","password_reset",account.id)
    db.commit()
    return {"message":"Your password has been reset. Sign in using your new password."}

@router.post("/register")
def register(data: RegisterIn, db: Session = Depends(get_db)):
    email = str(data.email).lower()
    existing = db.scalar(select(Customer).where(Customer.email == email))
    if existing and existing.is_verified:
        raise HTTPException(409, "An account with this email already exists.")
    if existing:
        existing.full_name = data.full_name.strip()
        existing.mobile = data.mobile.strip()
        existing.password_hash = hash_password(data.password)
    else:
        db.add(Customer(full_name=data.full_name.strip(), email=email, mobile=data.mobile.strip(), password_hash=hash_password(data.password)))
        db.flush()
    try:
        delivery = _issue_otp(db, email)
    except OTPDeliveryError as exc:
        db.rollback()
        raise HTTPException(503, str(exc)) from exc
    record(db, email, "CUSTOMER", "CUSTOMER_REGISTERED", "customer", email, f"otp_delivery={delivery}")
    db.commit()
    return {"message": "Verification code generated and delivered.", "delivery": delivery, "expires_in_minutes": settings.otp_expiry_minutes, "resend_after_seconds": settings.otp_resend_cooldown_seconds}

@router.post("/resend-otp")
def resend_otp(data: ResendOTPIn, db: Session = Depends(get_db)):
    email = str(data.email).lower()
    user = db.scalar(select(Customer).where(Customer.email == email))
    if not user or user.is_verified:
        raise HTTPException(400, "An active unverified registration was not found for this email.")
    latest = db.scalar(select(VerificationCode).where(VerificationCode.email == email).order_by(VerificationCode.id.desc()))
    now = datetime.now(timezone.utc)
    if latest and latest.created_at:
        created = latest.created_at.replace(tzinfo=timezone.utc) if latest.created_at.tzinfo is None else latest.created_at
        remaining = settings.otp_resend_cooldown_seconds - int((now - created).total_seconds())
        if remaining > 0:
            raise HTTPException(429, f"Please wait {remaining} seconds before requesting another code.")
    try:
        delivery = _issue_otp(db, email, "email verification")
    except OTPDeliveryError as exc:
        db.rollback()
        raise HTTPException(503, str(exc)) from exc
    record(db, email, "CUSTOMER", "CUSTOMER_OTP_RESENT", "customer", user.id, f"delivery={delivery}")
    db.commit()
    return {"message": "A new verification code was issued.", "delivery": delivery, "expires_in_minutes": settings.otp_expiry_minutes, "resend_after_seconds": settings.otp_resend_cooldown_seconds}

@router.post("/verify-otp")
def verify(data: OTPIn, db: Session = Depends(get_db)):
    email = str(data.email).lower()
    row = db.scalar(select(VerificationCode).where(VerificationCode.email == email, VerificationCode.used == False).order_by(VerificationCode.id.desc()))
    if not row:
        raise HTTPException(400, "No active OTP. Request a new verification code.")
    if row.attempts >= 5:
        row.used = True
        db.commit()
        raise HTTPException(429, "Too many incorrect OTP attempts. Request a new code.")
    exp = row.expires_at.replace(tzinfo=timezone.utc) if row.expires_at.tzinfo is None else row.expires_at
    if exp < datetime.now(timezone.utc):
        row.used = True
        db.commit()
        raise HTTPException(400, "The verification code has expired. Request a new code.")
    if not verify_password(data.code, row.code_hash):
        row.attempts += 1
        db.commit()
        raise HTTPException(400, "Incorrect verification code.")
    user = db.scalar(select(Customer).where(Customer.email == email))
    if not user:
        raise HTTPException(404, "Customer not found.")
    row.used = True
    user.is_verified = True
    record(db, email, "CUSTOMER", "CUSTOMER_VERIFIED", "customer", user.id)
    db.commit()
    return {"access_token": token_for(user.id), "token_type": "bearer", "customer": _customer_json(user)}

@router.post("/login")
def login(data: LoginIn, db: Session = Depends(get_db)):
    identifier = str(data.email).strip().lower()
    key = "customer:" + identifier
    if is_locked(key):
        raise HTTPException(429, "Too many failed sign-in attempts. Try again later.")
    candidates = db.scalars(select(Customer).where(func.lower(Customer.email) == identifier)).all()
    matches = [u for u in candidates if verify_password(data.password, u.password_hash)]
    if not matches:
        note_failure(key)
        record(db, identifier, "CUSTOMER", "LOGIN_FAILED", "customer", identifier)
        db.commit()
        raise HTTPException(401, "Invalid email address or password.")
    if len(matches) > 1:
        note_failure(key)
        record(db, identifier, "CUSTOMER", "LOGIN_AMBIGUOUS", "customer", identifier)
        db.commit()
        raise HTTPException(409, "Multiple accounts match these credentials. Contact support to resolve the duplicate account identity.")
    user = matches[0]
    if not user.is_verified:
        raise HTTPException(403, "Verify your email before signing in.")
    if not user.is_active:
        raise HTTPException(403, "This customer account is inactive. Contact support.")
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(data.password)
    clear_failures(key)
    record(db, user.email, "CUSTOMER", "LOGIN_SUCCESS", "customer", user.id)
    db.commit()
    return {"access_token": token_for(user.id), "token_type": "bearer", "customer": _customer_json(user)}

@router.get("/me")
def me(user: Customer = Depends(current_customer)):
    return _customer_json(user)

@router.patch("/me")
def update_me(data: ProfileUpdateIn, db: Session = Depends(get_db), user: Customer = Depends(current_customer)):
    user.mobile = data.mobile.strip()
    record(db, user.email, "CUSTOMER", "PROFILE_UPDATED", "customer", user.id, "mobile updated")
    db.commit(); db.refresh(user)
    return _customer_json(user)
