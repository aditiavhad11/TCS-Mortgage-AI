"""Bank self-registration (public) and Platform Admin approval/rejection with reason.
A bank stays PENDING until a Platform Admin decides. Approval issues a one-time Bank Admin invitation that is
emailed to the registered contact when SMTP is configured (otherwise the token is shown once to the admin)."""
import hashlib, re, secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, EmailStr, Field, TypeAdapter, ValidationError, field_validator
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.config import settings
from app.database import get_db
from app.models import Bank, BankAdmin, BankDocument, BankInvitation, PlatformAdmin, VerificationCode, AuditLog
from app.routers.admin import audit, current_admin
from app.security import is_locked, note_failure, clear_failures, hash_password, verify_password
from app.services.mailer import OTPDeliveryError, send_email, deliver_otp

router = APIRouter(tags=["Bank registration"])
def _try_email(to, subject, body):
    try: send_email(to, subject, body); return True
    except OTPDeliveryError: return False

class BankRegistrationIn(BaseModel):
    bank_name: str = Field(min_length=3, max_length=180)
    institution_type: str = Field(pattern="^(Public Bank|Private Bank|Cooperative Bank|NBFC|Other)$")
    contact_email: EmailStr
    contact_phone: str = Field(min_length=8, max_length=20)
    address: str = Field(min_length=10, max_length=1000)
    ifsc_code: str = Field(default="", max_length=11)
    license_number: str = Field(default="", max_length=80)

    @field_validator("bank_name", "contact_phone", "address", "ifsc_code", "license_number", mode="before")
    @classmethod
    def trim_values(cls, value):
        return value.strip() if isinstance(value, str) else value

class BankRegistrationOtpIn(BaseModel):
    contact_email: EmailStr
    code: str = Field(pattern=r"^\d{6}$")

class BankRegistrationCompleteIn(BankRegistrationIn):
    registration_token: str = Field(min_length=32, max_length=128)

def _normalized_email(value):
    try: return str(TypeAdapter(EmailStr).validate_python(str(value).strip())).casefold()
    except ValidationError: raise HTTPException(422, "Enter a valid official email address.")

def _registration_match(db, name, email):
    by_email_rows = db.scalars(select(Bank).where(func.lower(Bank.contact_email) == email).limit(2)).all()
    by_name_rows = db.scalars(select(Bank).where(func.lower(Bank.name) == name.casefold()).limit(2)).all()
    if len(by_email_rows) > 1 or len(by_name_rows) > 1:
        raise HTTPException(409, "An institution using this name or email is already registered.")
    by_email = by_email_rows[0] if by_email_rows else None
    by_name = by_name_rows[0] if by_name_rows else None
    if by_email and by_name and by_email.id != by_name.id:
        raise HTTPException(409, "An institution using this name or email is already registered.")
    # A corrected resubmission must prove control of the institution's previously verified
    # email. A matching public name alone is not enough to claim an existing registration.
    if by_name and not by_email:
        raise HTTPException(409, "An institution using this name or email is already registered.")
    existing = by_email
    if existing and existing.status != "REJECTED":
        raise HTTPException(409, "An institution using this name or email is already registered.")
    return existing

def _validate_registration(data, email):
    name = data.bank_name.strip()
    if len(name) < 3: raise HTTPException(422, "Enter the institution name.")
    if not re.fullmatch(r"[+()\-\s\d]{8,20}", data.contact_phone.strip()): raise HTTPException(422, "Enter a valid official contact number.")
    if len(data.address.strip()) < 10: raise HTTPException(422, "Enter the registered office address.")
    if data.ifsc_code and not re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", data.ifsc_code.strip().upper()): raise HTTPException(422, "Enter a valid IFSC code or leave it blank for institution-level registration.")
    if data.institution_type != "Other" and len(data.license_number.strip()) < 4:
        raise HTTPException(422, "RBI registration or license number is required for this institution type.")
    return name, email

def _registration_otp_key(email):
    return "bankregotp:" + hashlib.sha256(email.encode()).hexdigest()[:32]

def _registration_ticket_key(email):
    return _registration_otp_key(email) + ":verified"

@router.post("/bank-admin/register")
def register_bank(data: BankRegistrationIn, db: Session = Depends(get_db)):
    email = _normalized_email(data.contact_email)
    name, _ = _validate_registration(data, email)
    existing = _registration_match(db, name, email)
    if is_locked("bankreg:" + email): raise HTTPException(429, "Too many registration attempts. Try again later.")
    key = _registration_otp_key(email)
    previous = db.scalar(select(VerificationCode).where(VerificationCode.email == key).order_by(VerificationCode.id.desc()))
    if previous and previous.created_at:
        created = previous.created_at.replace(tzinfo=timezone.utc) if previous.created_at.tzinfo is None else previous.created_at
        remaining = settings.otp_resend_cooldown_seconds - int((datetime.now(timezone.utc) - created).total_seconds())
        if remaining > 0: raise HTTPException(429, f"Please wait {remaining} seconds before requesting another code.")
    code = f"{secrets.randbelow(1000000):06d}"
    for old in db.scalars(select(VerificationCode).where(VerificationCode.email == key, VerificationCode.used == False)).all(): old.used = True
    db.add(VerificationCode(email=key, code_hash=hash_password(code), expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.otp_expiry_minutes)))
    try: delivery = deliver_otp(email, code, "bank registration email verification", settings.otp_expiry_minutes)
    except OTPDeliveryError as exc:
        db.rollback(); raise HTTPException(503, "Unable to send the verification code. Please try again later.") from exc
    db.commit()
    return {"otp_required": True, "email": email, "delivery": delivery, "expires_in_minutes": settings.otp_expiry_minutes,
            "resend_after_seconds": settings.otp_resend_cooldown_seconds}

@router.post("/bank-admin/register/verify-otp")
def verify_bank_registration_email(data: BankRegistrationOtpIn, db: Session = Depends(get_db)):
    email = _normalized_email(data.contact_email)
    lock = "bankreg:" + email
    if is_locked(lock): raise HTTPException(429, "Too many registration attempts. Try again later.")
    key = _registration_otp_key(email)
    row = db.scalar(select(VerificationCode).where(VerificationCode.email == key, VerificationCode.used == False).order_by(VerificationCode.id.desc()))
    if not row: raise HTTPException(401, "Invalid or expired verification code. Request a new code.")
    expires = row.expires_at.replace(tzinfo=timezone.utc) if row.expires_at.tzinfo is None else row.expires_at
    if expires <= datetime.now(timezone.utc) or row.attempts >= 5:
        row.used = True; note_failure(lock); db.commit()
        raise HTTPException(401, "Invalid or expired verification code. Request a new code.")
    if not verify_password(data.code, row.code_hash):
        row.attempts += 1; note_failure(lock); db.commit()
        raise HTTPException(401, "Invalid or expired verification code. Request a new code.")
    row.used = True
    ticket = secrets.token_urlsafe(36)
    ticket_key = _registration_ticket_key(email)
    for old in db.scalars(select(VerificationCode).where(VerificationCode.email == ticket_key, VerificationCode.used == False)).all(): old.used = True
    db.add(VerificationCode(email=ticket_key, code_hash=hash_password(ticket), expires_at=datetime.now(timezone.utc) + timedelta(minutes=15)))
    rejected_rows = db.scalars(select(Bank).where(func.lower(Bank.contact_email) == email, Bank.status == "REJECTED").limit(2)).all()
    rejection_reason = rejected_rows[0].rejection_reason if len(rejected_rows) == 1 else ""
    clear_failures(lock)
    db.commit()
    return {"email": email, "registration_token": ticket, "expires_in_minutes": 15, "previous_rejection_reason": rejection_reason}

@router.post("/bank-admin/register/complete", status_code=201)
def complete_bank_registration(data: BankRegistrationCompleteIn, db: Session = Depends(get_db)):
    email = _normalized_email(data.contact_email)
    name, _ = _validate_registration(data, email)
    lock = "bankreg:" + email
    if is_locked(lock): raise HTTPException(429, "Too many registration attempts. Try again later.")
    ticket_key = _registration_ticket_key(email)
    row = db.scalar(select(VerificationCode).where(VerificationCode.email == ticket_key, VerificationCode.used == False).order_by(VerificationCode.id.desc()))
    if not row: raise HTTPException(401, "Email verification has expired. Verify the official email again.")
    expires = row.expires_at.replace(tzinfo=timezone.utc) if row.expires_at.tzinfo is None else row.expires_at
    if expires <= datetime.now(timezone.utc) or row.attempts >= 5:
        row.used = True; note_failure(lock); db.commit()
        raise HTTPException(401, "Email verification has expired. Verify the official email again.")
    if not verify_password(data.registration_token, row.code_hash):
        row.attempts += 1; note_failure(lock); db.commit()
        raise HTTPException(401, "Email verification has expired. Verify the official email again.")
    existing = _registration_match(db, name, email)
    now = datetime.now(timezone.utc)
    if existing:
        bank = existing
        bank.name = name
        bank.institution_type = data.institution_type
        bank.contact_email = email
        bank.contact_phone = data.contact_phone.strip()
        bank.address = data.address.strip()
        bank.ifsc_code = data.ifsc_code.strip().upper()
        bank.license_number = data.license_number.strip()
        bank.status = "PENDING"
        bank.rejection_reason = ""
        bank.decided_by = None
        bank.decided_at = None
        action = "BANK_REGISTRATION_RESUBMITTED"
    else:
        code = "BANK-" + secrets.token_hex(5).upper()
        bank = Bank(name=name, code=code, institution_type=data.institution_type, contact_email=email, contact_phone=data.contact_phone.strip(),
                    address=data.address.strip(), ifsc_code=data.ifsc_code.strip().upper(), license_number=data.license_number.strip(), status="PENDING")
        db.add(bank); action = "BANK_SELF_REGISTERED"
    row.used = True
    db.flush()
    db.add(AuditLog(actor_email=email, actor_role="BANK_APPLICANT", action=action, resource_type="bank", resource_id=str(bank.id), detail=f"type={data.institution_type}"))
    clear_failures(lock)
    try: db.commit(); db.refresh(bank)
    except IntegrityError:
        db.rollback(); raise HTTPException(409, "An institution using this name or official email is already registered.")
    emailed = _try_email(email, f"{settings.app_name}: bank registration received", f"We received the registration of {name}. It is pending Platform Admin approval. You will receive an email with the decision.\n")
    return {"id": bank.id, "status": bank.status, "message": "Registration submitted and awaiting Platform Admin approval.", "confirmation_emailed": emailed}

def _bank_detail(db, b):
    docs = db.scalars(select(BankDocument).where(BankDocument.bank_id == b.id).order_by(BankDocument.id)).all()
    return {"id": b.id, "name": b.name, "code": b.code, "status": b.status, "institution_type": b.institution_type, "contact_email": b.contact_email, "contact_person": b.contact_person, "contact_phone": b.contact_phone, "address": b.address, "ifsc_code": b.ifsc_code, "license_number": b.license_number, "rejection_reason": b.rejection_reason, "decided_by": b.decided_by, "decided_at": b.decided_at.isoformat() if b.decided_at else None, "created_at": b.created_at.isoformat(), "documents": [{"id": d.id, "filename": d.original_filename, "size_bytes": d.size_bytes, "content_type": d.content_type} for d in docs]}

@router.get("/admin/banks/{bank_id}")
def bank_detail(bank_id: int, db: Session = Depends(get_db), a: PlatformAdmin = Depends(current_admin)):
    b = db.get(Bank, bank_id)
    if not b: raise HTTPException(404, "Bank not found.")
    return _bank_detail(db, b)

@router.get("/admin/banks/{bank_id}/documents/{doc_id}/file")
def bank_document(bank_id: int, doc_id: int, db: Session = Depends(get_db), a: PlatformAdmin = Depends(current_admin)):
    d = db.scalar(select(BankDocument).where(BankDocument.id == doc_id, BankDocument.bank_id == bank_id))
    if not d: raise HTTPException(404, "Document not found.")
    folder = (Path(settings.uploads_dir).resolve() / "bank_registration"); p = (folder / d.stored_filename).resolve()
    if folder not in p.parents or not p.is_file(): raise HTTPException(404, "Stored file is unavailable.")
    return FileResponse(p, media_type=d.content_type, filename=d.original_filename, headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store", "Content-Security-Policy": "default-src 'none'"})

class DecisionIn(BaseModel):
    decision: str = Field(pattern="^(APPROVED|REJECTED)$")
    reason: str = Field(default="", max_length=1000)

@router.post("/admin/banks/{bank_id}/decision")
def decide(bank_id: int, data: DecisionIn, db: Session = Depends(get_db), a: PlatformAdmin = Depends(current_admin)):
    b = db.get(Bank, bank_id)
    if not b: raise HTTPException(404, "Bank not found.")
    if b.status != "PENDING": raise HTTPException(409, f"Only PENDING registrations can be decided (current status: {b.status}).")
    reason = data.reason.strip()
    if data.decision == "REJECTED" and len(reason) < 10: raise HTTPException(422, "A rejection reason of at least 10 characters is required.")
    now = datetime.now(timezone.utc)
    b.status = data.decision; b.rejection_reason = reason if data.decision == "REJECTED" else ""; b.decided_by = a.email; b.decided_at = now
    result = {"id": b.id, "status": b.status, "reason": b.rejection_reason, "notification_emailed": False, "invitation_token": None}
    if data.decision == "REJECTED":
        audit(db, a, "BANK_REJECTED", "bank", b.id, f"reason={reason[:300]}"); db.commit()
        result["notification_emailed"] = _try_email(b.contact_email, f"{settings.app_name}: bank registration not approved", f"Dear {b.contact_person or 'Sir/Madam'},\n\nThe registration of {b.name} was not approved.\nReason: {reason}\n\nYou may register again after correcting the issues.\n")
        return result
    if db.scalar(select(BankAdmin).where(BankAdmin.email == b.contact_email)): raise HTTPException(409, "A Bank Admin account already exists for the contact email.")
    raw = secrets.token_urlsafe(36)
    inv = BankInvitation(bank_id=b.id, email=b.contact_email, full_name=b.contact_person or b.name, token_hash=hashlib.sha256(raw.encode()).hexdigest(), expires_at=now + timedelta(hours=48), created_by=a.email)
    db.add(inv); db.flush(); audit(db, a, "BANK_APPROVED", "bank", b.id, f"invitation={inv.id}"); db.commit()
    link = f"{settings.frontend_base_url.rstrip('/')}/bank-admin?invite={raw}"
    emailed = _try_email(b.contact_email, f"{settings.app_name}: bank approved - activate your Bank Admin access", f"Dear {b.contact_person or 'Sir/Madam'},\n\n{b.name} has been approved. Activate your Bank Admin account (valid for 48 hours, single use):\n{link}\n")
    result["notification_emailed"] = emailed
    if not emailed:
        inv.used_at = datetime.now(timezone.utc)
        audit(db, a, "BANK_ADMIN_INVITATION_DELIVERY_FAILED", "bank_invitation", inv.id, "SMTP delivery failed; invitation invalidated")
        db.commit()
    return result
