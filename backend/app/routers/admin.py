from datetime import datetime, timedelta, timezone
import json, os, hashlib, secrets, re
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field, EmailStr, TypeAdapter, ValidationError, field_validator, model_validator
from sqlalchemy import select, func, or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import PlatformAdmin, Customer, Reviewer, MortgageApplication, ApplicationDocument, ReviewAssignment, ReviewEvent, AuditLog, PolicyDocument, VerificationCode
from app.security import token_for_admin_otp, token_claims, hash_password, verify_password
from app.config import settings, MIN_PASSWORD_LENGTH
from app.services.mailer import deliver_otp, OTPDeliveryError, send_email
from app.security import is_locked,note_failure,clear_failures
from app.services import nvidia as nv
from app.services.policy_rag import index_policy
from app.services.assignment import retry_pending_assignments, release_reviewer_assignments, reviewer_load
from app.models import AssignmentEvent
from app.models import PolicyChunk, Bank, BankAdmin, BankInvitation, AdminNotification, AnalysisRun
from datetime import date
import csv, io
import shutil, sys

router=APIRouter(prefix="/admin",tags=["Platform administration"])
bearer=HTTPBearer(auto_error=False)
class LoginIn(BaseModel): email: str = Field(min_length=3, max_length=254)
class OTPVerifyIn(BaseModel): email: EmailStr; code: str = Field(pattern=r"^\d{6}$")
class ReviewerCreate(BaseModel): full_name:str=Field(min_length=2,max_length=160); email:EmailStr; password:str=Field(min_length=MIN_PASSWORD_LENGTH,max_length=128); bank_code:str=Field(min_length=2,max_length=80); specialisation:str=Field(default="GENERAL_MORTGAGE_REVIEW", pattern="^(GENERAL_MORTGAGE_REVIEW|INCOME_TAX|PROPERTY_VALUATION|TERMS_CONDITIONS)$"); max_active_assignments:int=Field(default=10,ge=1,le=100)
class AssignmentIn(BaseModel): application_id:int=Field(gt=0); reviewer_id:int=Field(gt=0)
class PolicyIn(BaseModel): title:str=Field(min_length=3,max_length=200); policy_version:str=Field(min_length=1,max_length=80); category:str=Field(min_length=2,max_length=100); content:str=Field(min_length=20,max_length=100000); active:bool=True; bank_id:int|None=None
class ConfigIn(BaseModel): frontend_origin:str|None=None; uploads_dir:str|None=None; max_upload_mb:int|None=Field(default=None,ge=1,le=50)
class BankCreate(BaseModel):
    name:str=Field(min_length=3,max_length=180)
    institution_type:str=Field(pattern="^(Public Sector Bank|Private Sector Bank|Cooperative Bank|NBFC|Other)$")
    contact_email:EmailStr
    contact_phone:str=Field(min_length=8,max_length=20)
    address:str=Field(min_length=10,max_length=1000)
    ifsc_code:str=Field(default="",max_length=11)
    license_number:str=Field(default="",max_length=80)
    code:str|None=Field(default=None,min_length=2,max_length=40,pattern=r"^[A-Za-z0-9_-]+$")

    @field_validator("name","contact_phone","address","ifsc_code","license_number","code",mode="before")
    @classmethod
    def trim_bank_fields(cls,value): return value.strip() if isinstance(value,str) else value

    @field_validator("contact_email")
    @classmethod
    def normalize_bank_email(cls,value): return str(value).strip().casefold()

    @model_validator(mode="after")
    def validate_bank_registration(self):
        if not re.fullmatch(r"(?:\+91[\s-]?)?(?:[6-9]\d{9}|0\d{2,4}[\s-]?\d{6,8}|[2-9]\d{1,3}[\s-]?\d{6,8})",self.contact_phone):
            raise ValueError("Enter a valid Indian mobile or official landline number.")
        if self.ifsc_code and not re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}",self.ifsc_code.upper()):
            raise ValueError("Enter a valid 11-character IFSC code or leave it blank for institution-level registration.")
        if self.institution_type!="Other" and len(self.license_number.strip())<4:
            raise ValueError("RBI registration or license number is required for this institution type.")
        return self
class BankAdminInviteIn(BaseModel): bank_id:int=Field(gt=0); full_name:str=Field(min_length=2,max_length=160); email:EmailStr
class BankAdminEditIn(BaseModel):
    full_name:str=Field(min_length=2,max_length=160)
    email:EmailStr
    reason:str=Field(min_length=8,max_length=1000)
    @field_validator("full_name")
    @classmethod
    def clean_name(cls,value): return value.strip()
    @field_validator("email")
    @classmethod
    def clean_email(cls,value): return str(value).strip().casefold()
class InvitationEditIn(BankAdminEditIn): bank_id:int=Field(gt=0)
class ReasonIn(BaseModel): reason:str=Field(min_length=8,max_length=1000)

def current_admin(credentials:HTTPAuthorizationCredentials|None=Depends(bearer),db:Session=Depends(get_db)):
    if not credentials: raise HTTPException(401,"Admin authentication required.")
    claims=token_claims(credentials.credentials)
    sub=claims.get("sub") if claims else None
    if not claims or "email_otp" not in claims.get("amr", []): raise HTTPException(401,"Admin authentication required.")
    if not sub or not sub.startswith("admin:"): raise HTTPException(403,"Platform admin role required.")
    try: aid=int(sub.split(":",1)[1])
    except ValueError: raise HTTPException(401,"Invalid admin token.")
    a=db.get(PlatformAdmin,aid)
    configured_email=settings.initial_admin_email.strip().casefold()
    if not configured_email or not a or not a.is_active or a.email.strip().casefold()!=configured_email: raise HTTPException(401,"Admin account is inactive or unavailable.")
    return a
def audit(db,admin,action,resource_type,resource_id="",detail=""):
    db.add(AuditLog(actor_email=admin.email,actor_role="PLATFORM_ADMIN",action=action,resource_type=resource_type,resource_id=str(resource_id),detail=detail[:4000]))

def _outcome(action:str)->str:
    value=action.upper()
    if any(part in value for part in ("FAILED","DENIED","REJECTED","ERROR")): return "Failure"
    if any(part in value for part in ("SUCCESS","APPROVED","CREATED","ACTIVATED","REACTIVATED","UPDATED","RESENT","REVOKED","DELETED")): return "Success"
    return "Recorded"

def _action_label(action:str)->str:
    labels={"LOGIN_SUCCESS":"Successful sign-in","LOGIN_FAILED":"Failed sign-in","ADMIN_OTP_ISSUED":"Administrator verification code requested","BANK_APPROVED":"Bank registration approved","BANK_REJECTED":"Bank registration rejected","CUSTOMER_SUSPENDED":"Customer account suspended","CUSTOMER_REACTIVATED":"Customer account reactivated","BANK_ADMIN_INVITED":"Bank Admin invitation created","BANK_ADMIN_INVITATION_UPDATED":"Bank Admin invitation updated","BANK_ADMIN_INVITATION_RESENT":"Bank Admin invitation resent","BANK_ADMIN_INVITATION_REVOKED":"Bank Admin invitation revoked","BANK_ADMIN_INVITATION_DELETED":"Bank Admin invitation deleted","BANK_ADMIN_DETAILS_UPDATED":"Bank Admin details updated","BANK_ADMIN_INVITATION_DELIVERY_FAILED":"Bank Admin invitation delivery failed"}
    return labels.get(action.upper(),action.replace("_"," ").strip().capitalize() or "Administrative event")

def _check_period(start:date|None,end:date|None):
    if start and end and start>end: raise HTTPException(422,"Start date must be on or before end date.")
def app_row(db,a):
    c=db.get(Customer,a.customer_id); ass=db.scalar(select(ReviewAssignment).where(ReviewAssignment.application_id==a.id,ReviewAssignment.active==True)); rev=db.get(Reviewer,ass.reviewer_id) if ass else None
    return {"id":a.id,"reference":a.reference,"status":a.status,"lender_name":a.lender_name,"product_name":a.product_name,"requested_loan":a.requested_loan,"property_value":a.property_value,"customer_name":c.full_name if c else "Unavailable","customer_email":c.email if c else "Unavailable","reviewer_id":rev.id if rev else None,"reviewer_email":rev.email if rev else None,"created_at":a.created_at.isoformat() if a.created_at else None}
@router.post("/login")
def login(data:LoginIn,db:Session=Depends(get_db)):
    try: email=str(TypeAdapter(EmailStr).validate_python(data.email.strip())).casefold()
    except ValidationError: email=""
    configured_email=settings.initial_admin_email.strip().casefold()
    key="admin:"+(email or "invalid")
    if is_locked(key): raise HTTPException(429,"Too many failed sign-in attempts. Try again later.")
    # Same response for unknown and unauthorized addresses; never disclose account existence.
    a=db.scalar(select(PlatformAdmin).where(func.lower(PlatformAdmin.email)==email)) if email else None
    if not email or not configured_email or email!=configured_email or not a or not a.is_active:
        note_failure(key)
        raise HTTPException(401,"Unable to send a verification code. Check the address or try again later.")
    okey=_otp_key(email)
    previous=db.scalar(select(VerificationCode).where(VerificationCode.email==okey).order_by(VerificationCode.id.desc()))
    if previous and previous.created_at:
        created=previous.created_at.replace(tzinfo=timezone.utc) if previous.created_at.tzinfo is None else previous.created_at
        remaining=settings.otp_resend_cooldown_seconds-int((datetime.now(timezone.utc)-created).total_seconds())
        if remaining>0: raise HTTPException(429,f"Please wait {remaining} seconds before requesting another code.")
    code=f"{secrets.randbelow(1000000):06d}"
    for old in db.scalars(select(VerificationCode).where(VerificationCode.email==okey,VerificationCode.used==False)).all(): old.used=True
    db.add(VerificationCode(email=okey,code_hash=hash_password(code),expires_at=datetime.now(timezone.utc)+timedelta(minutes=settings.otp_expiry_minutes)))
    try: channel=deliver_otp(email,code,"Platform Admin sign-in",settings.otp_expiry_minutes)
    except OTPDeliveryError as e:
        db.rollback();raise HTTPException(503,f"Could not deliver the sign-in code. {e}")
    db.add(AuditLog(actor_email=email[:255],actor_role="PLATFORM_ADMIN",action="ADMIN_OTP_ISSUED",resource_type="admin",resource_id=str(a.id),detail=f"channel={channel}"));db.commit()
    return {"otp_required":True,"email":email,"expires_in_minutes":settings.otp_expiry_minutes,"resend_after_seconds":settings.otp_resend_cooldown_seconds,"delivery":channel}
def _otp_key(email:str)->str:
    return "adminotp:"+hashlib.sha256(email.encode()).hexdigest()[:32]  # fixed-length key; never stores the raw email in the code table
def _admin_session(a):
    return {"access_token":token_for_admin_otp(f"admin:{a.id}"),"token_type":"bearer","admin":{"id":a.id,"full_name":a.full_name,"email":a.email,"role":"PLATFORM_ADMIN"}}
@router.post("/login/verify-otp")
def verify_login_otp(data:OTPVerifyIn,db:Session=Depends(get_db)):
    email=data.email.strip().casefold();lock="adminotp-lock:"+email;okey=_otp_key(email)
    configured_email=settings.initial_admin_email.strip().casefold()
    if not configured_email or email!=configured_email: raise HTTPException(401,"Invalid or expired code. Sign in again to receive a new one.")
    if is_locked(lock): raise HTTPException(429,"Too many incorrect codes. Try again later.")
    a=db.scalar(select(PlatformAdmin).where(func.lower(PlatformAdmin.email)==email))
    row=db.scalar(select(VerificationCode).where(VerificationCode.email==okey,VerificationCode.used==False).order_by(VerificationCode.id.desc()))
    if not a or not a.is_active or not row:
        # No live code exists, so nothing can be guessed: do not count it toward the lockout (otherwise anyone who knows
        # the admin's email could lock the real admin out of the OTP step with bogus requests).
        raise HTTPException(401,"Invalid or expired code. Sign in again to receive a new one.")
    exp=row.expires_at.replace(tzinfo=timezone.utc) if row.expires_at.tzinfo is None else row.expires_at
    if exp<datetime.now(timezone.utc) or row.attempts>=5:
        row.used=True;note_failure(lock);db.commit();raise HTTPException(401,"Invalid or expired code. Sign in again to receive a new one.")
    if not verify_password(data.code,row.code_hash):
        row.attempts+=1;note_failure(lock);db.add(AuditLog(actor_email=email[:255],actor_role="PLATFORM_ADMIN",action="LOGIN_FAILED",resource_type="admin",resource_id=str(a.id),detail="incorrect OTP"));db.commit()
        raise HTTPException(401,"Invalid or expired code. Sign in again to receive a new one.")
    row.used=True;clear_failures(lock);clear_failures("admin:"+email)
    db.add(AuditLog(actor_email=email[:255],actor_role="PLATFORM_ADMIN",action="LOGIN_SUCCESS",resource_type="admin",resource_id=str(a.id),detail="email_otp"));db.commit()
    return _admin_session(a)
@router.get("/me")
def me(a:PlatformAdmin=Depends(current_admin)): return {"id":a.id,"full_name":a.full_name,"email":a.email,"role":"PLATFORM_ADMIN"}
@router.get("/dashboard")
def dashboard(db:Session=Depends(get_db),a:PlatformAdmin=Depends(current_admin)):
    _sync_notifications(db)
    count=lambda model: db.scalar(select(func.count()).select_from(model)) or 0
    statuses={s:(db.scalar(select(func.count()).select_from(MortgageApplication).where(MortgageApplication.status==s)) or 0) for s in ["DRAFT","SUBMITTED","IN_REVIEW","DOCUMENTS_REQUESTED","ESCALATED","RECOMMEND_APPROVE","RECOMMEND_DECLINE","COMPLETED"]}
    verification=nv.LAST_VERIFICATION or {}; checked=verification.get("checked_at"); checked_at=None
    try: checked_at=datetime.fromisoformat(checked.replace("Z","+00:00")) if checked else None
    except (ValueError,AttributeError): checked_at=None
    ai_status="Unavailable" if not settings.nvidia_api_key.strip() else ("Not Verified" if not checked_at else ("Not Verified" if datetime.now(timezone.utc)-checked_at>timedelta(minutes=30) else ("Healthy" if verification.get("inference_ok") and verification.get("embedding_ok") else "Degraded")))
    recent_logs=db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(5)).all()
    return {"generated_at":datetime.now(timezone.utc).isoformat(),"customers":count(Customer),"active_customers":db.scalar(select(func.count()).select_from(Customer).where(Customer.is_active==True)) or 0,"suspended_customers":db.scalar(select(func.count()).select_from(Customer).where(Customer.is_active==False)) or 0,"banks":count(Bank),"pending_banks":db.scalar(select(func.count()).select_from(Bank).where(Bank.status=="PENDING")) or 0,"approved_banks":db.scalar(select(func.count()).select_from(Bank).where(Bank.status=="APPROVED")) or 0,"reviewers":count(Reviewer),"applications":count(MortgageApplication),"documents":count(ApplicationDocument),"active_policies":db.scalar(select(func.count()).select_from(PolicyDocument).where(PolicyDocument.active==True)) or 0,"unassigned":db.scalar(select(func.count()).select_from(MortgageApplication).where(MortgageApplication.status!="DRAFT",~MortgageApplication.id.in_(select(ReviewAssignment.application_id).where(ReviewAssignment.active==True)))) or 0,"statuses":statuses,"ai":{"provider":"NVIDIA","configured":bool(settings.nvidia_api_key.strip()),"model":settings.nvidia_model,"status":ai_status,"last_verified":checked},"analysis":{"total":count(AnalysisRun),"succeeded":db.scalar(select(func.count()).select_from(AnalysisRun).where(func.upper(AnalysisRun.status).in_(["SUCCEEDED","SUCCESS","COMPLETED"]))) or 0,"failed":db.scalar(select(func.count()).select_from(AnalysisRun).where(func.upper(AnalysisRun.status).in_(["FAILED","ERROR"]))) or 0},"critical_alerts":db.scalar(select(func.count()).select_from(AdminNotification).where(AdminNotification.severity.in_(["CRITICAL","HIGH"]),AdminNotification.read_at.is_(None))) or 0,"recent_banks":[{"id":b.id,"name":b.name,"status":b.status,"created_at":b.created_at.isoformat()} for b in db.scalars(select(Bank).order_by(Bank.created_at.desc()).limit(5)).all()],"recent_actions":[{"id":x.id,"action":x.action,"action_label":_action_label(x.action),"actor_role":x.actor_role,"actor":(x.actor_email[:1]+"***"+x.actor_email[x.actor_email.find("@"):]) if x.actor_email and "@" in x.actor_email else (x.actor_role or "System"),"resource_type":x.resource_type,"resource_id":x.resource_id,"detail":x.detail,"outcome":_outcome(x.action),"created_at":x.created_at.isoformat()} for x in recent_logs]}
@router.get("/applications")
def applications(status:str|None=None,db:Session=Depends(get_db),a:PlatformAdmin=Depends(current_admin)):
    q=select(MortgageApplication).order_by(MortgageApplication.created_at.desc())
    if status: q=q.where(MortgageApplication.status==status)
    return [app_row(db,x) for x in db.scalars(q).all()]
@router.get("/reviewers")
def reviewers(db:Session=Depends(get_db),a:PlatformAdmin=Depends(current_admin)):
    rows=db.scalars(select(Reviewer).order_by(Reviewer.bank_code,Reviewer.full_name)).all()
    return [{"id":r.id,"full_name":r.full_name,"email":r.email,"bank_code":r.bank_code,"is_active":r.is_active,"assigned_count":reviewer_load(db,r.id),"is_available":r.is_available is not False,"specialisation":r.specialisation,"max_active_assignments":r.max_active_assignments} for r in rows]
@router.post("/reviewers",status_code=201)
def create_reviewer(data:ReviewerCreate,db:Session=Depends(get_db),a:PlatformAdmin=Depends(current_admin)):
    email=data.email.lower().strip()
    if db.scalar(select(Reviewer).where(Reviewer.email==email)): raise HTTPException(409,"Reviewer email already exists.")
    bank=db.scalar(select(Bank).where(Bank.code==data.bank_code.strip().upper()))
    if bank and bank.status!="APPROVED": raise HTTPException(409,"Reviewer accounts can only be created for approved banks.")
    r=Reviewer(full_name=data.full_name.strip(),email=email,password_hash=hash_password(data.password),bank_code=data.bank_code.strip().upper(),bank_id=bank.id if bank else None,is_active=True,specialisation=data.specialisation,max_active_assignments=data.max_active_assignments); db.add(r); db.flush(); retry_pending_assignments(db,bank_code=r.bank_code,bank_id=r.bank_id); audit(db,a,"REVIEWER_CREATED","reviewer",r.id,email); db.commit(); return {"id":r.id,"email":r.email,"bank_code":r.bank_code,"is_active":r.is_active,"specialisation":r.specialisation,"max_active_assignments":r.max_active_assignments}
@router.patch("/reviewers/{rid}/active")
def toggle_reviewer(rid:int,active:bool,db:Session=Depends(get_db),a:PlatformAdmin=Depends(current_admin)):
    r=db.get(Reviewer,rid)
    if not r: raise HTTPException(404,"Reviewer not found.")
    r.is_active=active
    db.flush()
    if active:
        retry_pending_assignments(db,bank_code=r.bank_code,bank_id=r.bank_id)
    else:
        release_reviewer_assignments(db,r,"Previous reviewer was deactivated; automatic reassignment initiated.")
        retry_pending_assignments(db,bank_code=r.bank_code,bank_id=r.bank_id)
    audit(db,a,"REVIEWER_ACTIVATED" if active else "REVIEWER_SUSPENDED","reviewer",rid); db.commit(); return {"id":rid,"is_active":r.is_active}
@router.post("/assignments")
def assign(data:AssignmentIn,db:Session=Depends(get_db),a:PlatformAdmin=Depends(current_admin)):
    raise HTTPException(403,"Manual reviewer assignment is disabled. The backend assignment engine assigns eligible reviewers automatically.")
@router.get("/policies")
def policies(db:Session=Depends(get_db),a:PlatformAdmin=Depends(current_admin)):
    return [{"id":p.id,"bank_id":p.bank_id,"title":p.title,"policy_version":p.policy_version,"category":p.category,"content":p.content,"active":p.active,"created_by":p.created_by,"created_at":p.created_at.isoformat()} for p in db.scalars(select(PolicyDocument).order_by(PolicyDocument.created_at.desc())).all()]
@router.post("/policies",status_code=201)
async def add_policy(data:PolicyIn,db:Session=Depends(get_db),a:PlatformAdmin=Depends(current_admin)):
    if data.bank_id is not None:
        bank=db.get(Bank,data.bank_id)
        if not bank or bank.status!="APPROVED": raise HTTPException(422,"Select an approved bank or leave bank_id empty for a global policy.")
    if db.scalar(select(PolicyDocument).where(PolicyDocument.title==data.title,PolicyDocument.policy_version==data.policy_version,PolicyDocument.bank_id==data.bank_id)): raise HTTPException(409,"This policy title already has that version in this scope; use a new version number.")
    superseded=[]
    if data.active:  # a new active version supersedes older active versions of the same policy so RAG never mixes versions
        for old in db.scalars(select(PolicyDocument).where(PolicyDocument.title==data.title,PolicyDocument.bank_id==data.bank_id,PolicyDocument.active==True)).all(): old.active=False;superseded.append(old.policy_version);audit(db,a,"POLICY_SUPERSEDED","policy",old.id,f"{old.title} v{old.policy_version} replaced by v{data.policy_version}")
    p=PolicyDocument(title=data.title,policy_version=data.policy_version,category=data.category,content=data.content,active=data.active,created_by=a.email,bank_id=data.bank_id); db.add(p); db.flush(); audit(db,a,"POLICY_CREATED","policy",p.id,f"{p.title} v{p.policy_version}"); db.commit()
    idx=await index_policy(db,p)
    return {"id":p.id,"title":p.title,"policy_version":p.policy_version,"active":p.active,"superseded_versions":superseded,"indexing":idx}
@router.post("/policies/reindex")
async def reindex(db:Session=Depends(get_db),a:PlatformAdmin=Depends(current_admin)):
    res=[await index_policy(db,p) for p in db.scalars(select(PolicyDocument).where(PolicyDocument.active==True)).all()]
    audit(db,a,"POLICIES_REINDEXED","policy","*",f"policies={len(res)}");db.commit();return res
@router.post("/ai/verify")
async def ai_verify(db:Session=Depends(get_db),a:PlatformAdmin=Depends(current_admin)):
    try: res=await nv.verify_connectivity()
    except nv.NVIDIAConfigurationError as e: raise HTTPException(503,str(e))
    audit(db,a,"AI_VERIFY","ai","nvidia",f"inference_ok={res['inference_ok']} model_listed={res['model_listed']} embedding_ok={res['embedding_ok']}");db.commit();return res
@router.patch("/policies/{pid}/active")
def policy_active(pid:int,active:bool,db:Session=Depends(get_db),a:PlatformAdmin=Depends(current_admin)):
    p=db.get(PolicyDocument,pid)
    if not p: raise HTTPException(404,"Policy not found.")
    p.active=active; audit(db,a,"POLICY_ACTIVATED" if active else "POLICY_ARCHIVED","policy",pid); db.commit(); return {"id":pid,"active":p.active}
@router.get("/audit-logs")
def audit_logs(limit:int=100,offset:int=0,actor:str|None=None,action:str|None=None,resource_type:str|None=None,outcome:str|None=None,severity:str|None=None,category:str|None=None,start:date|None=None,end:date|None=None,db:Session=Depends(get_db),a:PlatformAdmin=Depends(current_admin)):
    _check_period(start,end)
    q=select(AuditLog)
    if actor: q=q.where(func.lower(AuditLog.actor_email).contains(actor.strip().casefold()))
    if action: q=q.where(func.lower(AuditLog.action).contains(action.strip().casefold()))
    if resource_type: q=q.where(func.lower(AuditLog.resource_type)==resource_type.strip().casefold())
    if severity:
        level=severity.strip().upper()
        if level not in {"HIGH","INFO"}: raise HTTPException(422,"Severity must be High or Info.")
        failures=or_(AuditLog.action.ilike("%FAILED%"),AuditLog.action.ilike("%DENIED%"),AuditLog.action.ilike("%REJECTED%"),AuditLog.action.ilike("%ERROR%"))
        q=q.where(failures if level=="HIGH" else ~failures)
    if category:
        kind=category.strip().casefold()
        if kind not in {"security","administration"}: raise HTTPException(422,"Category must be Security or Administration.")
        security=or_(AuditLog.action.ilike("%LOGIN%"),AuditLog.action.ilike("%OTP%"),AuditLog.action.ilike("%DENIED%"))
        q=q.where(security if kind=="security" else ~security)
    if outcome:
        val=outcome.strip().casefold()
        if val not in {"success","failure","recorded"}: raise HTTPException(422,"Outcome must be Success, Failure, or Recorded.")
        if val=="failure": q=q.where(or_(AuditLog.action.ilike("%FAILED%"),AuditLog.action.ilike("%DENIED%"),AuditLog.action.ilike("%REJECTED%"),AuditLog.action.ilike("%ERROR%")))
        elif val=="success": q=q.where(or_(AuditLog.action.ilike("%SUCCESS%"),AuditLog.action.ilike("%APPROVED%"),AuditLog.action.ilike("%CREATED%"),AuditLog.action.ilike("%ACTIVATED%"),AuditLog.action.ilike("%REACTIVATED%")))
        else: q=q.where(~or_(AuditLog.action.ilike("%FAILED%"),AuditLog.action.ilike("%DENIED%"),AuditLog.action.ilike("%REJECTED%"),AuditLog.action.ilike("%ERROR%"),AuditLog.action.ilike("%SUCCESS%"),AuditLog.action.ilike("%APPROVED%"),AuditLog.action.ilike("%CREATED%"),AuditLog.action.ilike("%ACTIVATED%"),AuditLog.action.ilike("%REACTIVATED%")))
    if start: q=q.where(AuditLog.created_at>=datetime.combine(start,datetime.min.time(),tzinfo=timezone.utc))
    if end: q=q.where(AuditLog.created_at<datetime.combine(end+timedelta(days=1),datetime.min.time(),tzinfo=timezone.utc))
    total=db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows=db.scalars(q.order_by(AuditLog.created_at.desc()).offset(max(0,offset)).limit(max(1,min(limit,250)))).all()
    return {"items":[{"id":x.id,"actor_email":x.actor_email,"actor_role":x.actor_role,"action":x.action,"action_label":_action_label(x.action),"resource_type":x.resource_type,"resource_id":x.resource_id,"outcome":_outcome(x.action),"severity":"HIGH" if _outcome(x.action)=="Failure" else "INFO","category":"Security" if any(v in x.action.upper() for v in ("LOGIN","OTP","DENIED")) else "Administration","detail":x.detail,"request_id":None,"created_at":x.created_at.isoformat()} for x in rows],"total":total,"limit":max(1,min(limit,250)),"offset":max(0,offset)}
@router.get("/configuration")
def configuration(db:Session=Depends(get_db),a:PlatformAdmin=Depends(current_admin)):
    verification=nv.LAST_VERIFICATION or {}; checked=verification.get("checked_at")
    try: db.execute(text("SELECT 1")); database_status="Healthy"
    except Exception: database_status="Unavailable"
    tesseract=settings.tesseract_cmd.strip() or "tesseract"
    ocr_available=bool(shutil.which(tesseract))
    try:
        analysis_failed=db.scalar(select(func.count()).select_from(AnalysisRun).where(func.upper(AnalysisRun.status).in_(["FAILED","ERROR"]))) or 0
        extraction_failed=db.scalar(select(func.count()).select_from(ApplicationDocument).where(func.upper(ApplicationDocument.extraction_status).in_(["FAILED","ERROR"]))) or 0
    except Exception:
        database_status="Unavailable"; analysis_failed=None; extraction_failed=None
    nvidia_ok=bool(verification.get("inference_ok") and verification.get("embedding_ok"))
    return {"app_name":settings.app_name,"environment":settings.environment,"frontend_origin":settings.frontend_origin,"backend_health":"Healthy","health_checked_at":datetime.now(timezone.utc).isoformat(),"database_status":database_status,"max_upload_mb":settings.max_upload_size_mb,"runtime_version":sys.version.split()[0],"assignment_retry_interval_seconds":settings.assignment_retry_interval_seconds,"nvidia":{"provider":"NVIDIA","configured":bool(settings.nvidia_api_key.strip()),"status":"Unknown" if not checked else ("Healthy" if nvidia_ok else "Degraded"),"model":settings.nvidia_model,"embedding_model":settings.nvidia_embed_model,"api_key_masked":"Configured (value hidden)" if settings.nvidia_api_key else "Not configured","last_verification":checked,"last_error":"Recent connectivity check did not pass." if checked and not nvidia_ok else None,"timeout_seconds":settings.nvidia_timeout_seconds},"authentication":{"platform_admin":"Email and OTP","otp_expiry_minutes":settings.otp_expiry_minutes,"resend_cooldown_seconds":settings.otp_resend_cooldown_seconds,"login_lockout_minutes":settings.login_lockout_minutes,"login_max_failures":settings.login_max_failures,"smtp_configured":bool(settings.smtp_host.strip()),"email_delivery_test":"Not tracked"},"documents":{"ocr_engine":"Tesseract","ocr_status":"Available" if ocr_available else "Unavailable","ocr_page_limit":settings.ocr_max_pages,"analysis_failures":analysis_failed,"extraction_failures":extraction_failed,"guardrails_runtime":"Installed" if nv.LLMRails is not None else "Unavailable"},"note":"Values are read-only and sourced from backend configuration or persisted telemetry. Secrets and connection strings are never returned."}
@router.get("/users")
def users(db:Session=Depends(get_db),a:PlatformAdmin=Depends(current_admin)):
    cs=db.scalars(select(Customer).order_by(Customer.created_at.desc()) if hasattr(Customer,"created_at") else select(Customer).order_by(Customer.id.desc())).all()
    return [{"id":x.id,"full_name":x.full_name,"email":x.email,"mobile":x.mobile,"verified":x.is_verified,"role":"CUSTOMER"} for x in cs]


@router.get("/banks")
def list_banks(db:Session=Depends(get_db),a:PlatformAdmin=Depends(current_admin)):
    banks=db.scalars(select(Bank).order_by(Bank.created_at.desc())).all()
    return [{"id":b.id,"name":b.name,"code":b.code,"status":b.status,"institution_type":b.institution_type,"contact_email":b.contact_email,"contact_person":b.contact_person,"contact_phone":b.contact_phone,"address":b.address,"ifsc_code":b.ifsc_code,"license_number":b.license_number,"rejection_reason":b.rejection_reason,"created_at":b.created_at.isoformat(),"admin_count":db.scalar(select(func.count()).select_from(BankAdmin).where(BankAdmin.bank_id==b.id)) or 0} for b in banks]

@router.post("/banks",status_code=201)
def create_bank(data:BankCreate,db:Session=Depends(get_db),a:PlatformAdmin=Depends(current_admin)):
    name=data.name.strip(); code=(data.code or ("BANK-"+secrets.token_hex(5))).strip().upper(); email=data.contact_email.strip().casefold()
    if db.scalar(select(Bank).where(or_(func.lower(Bank.name)==name.casefold(),Bank.code==code,func.lower(Bank.contact_email)==email))): raise HTTPException(409,"A bank with this name, code or contact email already exists.")
    bank=Bank(name=name,code=code,institution_type=data.institution_type,contact_email=email,contact_phone=data.contact_phone.strip(),address=data.address.strip(),ifsc_code=data.ifsc_code.strip().upper(),license_number=data.license_number.strip(),status="PENDING")
    db.add(bank)
    try:
        db.flush(); audit(db,a,"BANK_REGISTERED","bank",bank.id,f"code={code}; status=PENDING"); db.commit()
    except IntegrityError:
        db.rollback(); raise HTTPException(409,"A bank with this name, code or contact email already exists.")
    return {"id":bank.id,"name":bank.name,"code":bank.code,"status":bank.status,"institution_type":bank.institution_type,"contact_email":bank.contact_email}

@router.patch("/banks/{bank_id}/status")
def update_bank_status(bank_id:int,status:str,db:Session=Depends(get_db),a:PlatformAdmin=Depends(current_admin)):
    status=status.upper()
    if status not in {"APPROVED","REJECTED","SUSPENDED"}: raise HTTPException(422,"Status must be APPROVED, REJECTED, or SUSPENDED.")
    bank=db.get(Bank,bank_id)
    if not bank: raise HTTPException(404,"Bank not found.")
    if status=="REJECTED": raise HTTPException(422,"Rejecting a registration requires a reason: use POST /admin/banks/{id}/decision.")
    bank.status=status; audit(db,a,"BANK_STATUS_CHANGED","bank",bank.id,f"status={status}"); db.commit()
    return {"id":bank.id,"name":bank.name,"code":bank.code,"status":bank.status}

@router.post("/bank-invitations",status_code=201)
def invite_bank_admin(data:BankAdminInviteIn,db:Session=Depends(get_db),a:PlatformAdmin=Depends(current_admin)):
    bank=db.get(Bank,data.bank_id)
    if not bank: raise HTTPException(404,"Bank not found.")
    if bank.status!="APPROVED": raise HTTPException(409,"Approve the bank before inviting a Bank Admin.")
    email=str(data.email).strip().casefold()
    if db.scalar(select(BankAdmin).where(BankAdmin.email==email)): raise HTTPException(409,"This email already has a Bank Admin account.")
    # Invalidate any prior unused invitations for this bank/email.
    for old in db.scalars(select(BankInvitation).where(BankInvitation.bank_id==bank.id,BankInvitation.email==email,BankInvitation.used_at.is_(None))).all(): old.used_at=datetime.now(timezone.utc)
    invitation=BankInvitation(bank_id=bank.id,email=email,full_name=data.full_name.strip(),token_hash="",expires_at=datetime.now(timezone.utc),created_by=a.email)
    db.add(invitation)
    _rotate_invitation(invitation,bank,a,db,"BANK_ADMIN_INVITED",f"bank={bank.code}; expires=48h")
    return {"invitation_id":invitation.id,"bank":bank.name,"email":email,"expires_at":invitation.expires_at.isoformat(),"delivery":"EMAIL_SENT"}

def _rotate_invitation(invitation,bank,admin,db,action,detail):
    raw=secrets.token_urlsafe(36); now=datetime.now(timezone.utc)
    invitation.token_hash=hashlib.sha256(raw.encode()).hexdigest()
    invitation.used_at=None
    invitation.expires_at=now+timedelta(hours=48)
    db.flush()
    audit(db,admin,action,"bank_invitation",invitation.id,detail)
    db.commit()
    link=f"{settings.frontend_base_url.rstrip('/')}/bank-admin?invite={raw}"
    try:
        send_email(invitation.email,f"{settings.app_name}: activate your Bank Admin access",f"Hello {invitation.full_name},\n\nYou have been invited to administer {bank.name}. Use this single-use link within 48 hours to set your password:\n{link}\n")
    except OTPDeliveryError:
        invitation.used_at=datetime.now(timezone.utc)
        audit(db,admin,"BANK_ADMIN_INVITATION_DELIVERY_FAILED","bank_invitation",invitation.id,"Email delivery failed; token invalidated.")
        db.commit()
        raise HTTPException(503,"Invitation email could not be delivered. The invitation token was invalidated.")

class AccountAction(BaseModel): active:bool; reason:str=Field(min_length=8,max_length=1000)
class ReadAction(BaseModel): read:bool=True

def _csv_response(rows, filename, headers=None):
    stream=io.StringIO(newline=""); writer=csv.writer(stream)
    columns=headers or (list(rows[0].keys()) if rows else ["id","actor_email","actor_role","action","action_label","resource_type","resource_id","outcome","severity","category","detail","request_id","created_at"])
    writer.writerow(columns)
    for row in rows:
        values=[]
        for key in columns:
            value=row.get(key,"")
            cell="" if value is None else str(value)
            if cell[:1] in {"=","+","-","@","\t","\r"}: cell="'"+cell
            values.append(cell)
        writer.writerow(values)
    return StreamingResponse(iter([stream.getvalue()]),media_type="text/csv",headers={"Content-Disposition":f'attachment; filename="{filename}"'})

@router.get("/customers")
def customer_directory(q:str="",status:str="all",verified:str="all",start:date|None=None,end:date|None=None,sort:str="newest",limit:int=25,offset:int=0,db:Session=Depends(get_db),a:PlatformAdmin=Depends(current_admin)):
    _check_period(start,end)
    if status.casefold() not in {"all","active","suspended"}: raise HTTPException(422,"Account status must be All, Active, or Suspended.")
    if verified.casefold() not in {"all","verified","pending"}: raise HTTPException(422,"Verification status must be All, Verified, or Pending.")
    if sort not in {"newest","oldest","name"}: raise HTTPException(422,"Sort must be newest, oldest, or name.")
    query=select(Customer)
    term=q.strip()
    if term:
        like=f"%{term.casefold()}%"
        if term.isdigit(): query=query.where(or_(Customer.id==int(term),func.lower(Customer.full_name).like(like),func.lower(Customer.email).like(like),Customer.mobile.like(like)))
        else: query=query.where(or_(func.lower(Customer.full_name).like(like),func.lower(Customer.email).like(like),Customer.mobile.like(f"%{term}%")))
    if status.lower() in {"active","suspended"}: query=query.where(Customer.is_active==(status.lower()=="active"))
    if verified.lower() in {"verified","pending"}: query=query.where(Customer.is_verified==(verified.lower()=="verified"))
    if start: query=query.where(Customer.created_at>=datetime.combine(start,datetime.min.time(),tzinfo=timezone.utc))
    if end: query=query.where(Customer.created_at<datetime.combine(end+timedelta(days=1),datetime.min.time(),tzinfo=timezone.utc))
    if sort=="oldest": query=query.order_by(Customer.created_at.asc(),Customer.id.asc())
    elif sort=="name": query=query.order_by(func.lower(Customer.full_name),Customer.id)
    else: query=query.order_by(Customer.created_at.desc(),Customer.id.desc())
    total=db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows=db.scalars(query.offset(max(0,offset)).limit(max(1,min(limit,50)))).all()
    items=[]
    for c in rows:
        mobile=c.mobile or ""; email=c.email or ""
        apps_count=db.scalar(select(func.count()).select_from(MortgageApplication).where(MortgageApplication.customer_id==c.id)) or 0
        items.append({"id":c.id,"full_name":c.full_name,"email":email[:1]+"***"+email[email.find("@"): ] if "@" in email else "***","mobile":("*"*max(0,len(mobile)-4))+mobile[-4:] if mobile else "","created_at":c.created_at.isoformat() if c.created_at else None,"verified":bool(c.is_verified),"active":bool(c.is_active),"application_count":apps_count,"last_login":None})
    return {"items":items,"total":total,"limit":max(1,min(limit,50)),"offset":max(0,offset)}

@router.get("/customers/{customer_id}")
def customer_details(customer_id:int,db:Session=Depends(get_db),a:PlatformAdmin=Depends(current_admin)):
    c=db.get(Customer,customer_id)
    if not c: raise HTTPException(404,"Customer not found.")
    counts=dict(db.execute(select(MortgageApplication.status,func.count()).where(MortgageApplication.customer_id==c.id).group_by(MortgageApplication.status)).all())
    return {"id":c.id,"full_name":c.full_name,"email":c.email,"mobile":c.mobile,"verified":c.is_verified,"active":c.is_active,"created_at":c.created_at.isoformat() if c.created_at else None,"last_login":None,"applications":counts}

@router.patch("/customers/{customer_id}/status")
def customer_status(customer_id:int,data:AccountAction,db:Session=Depends(get_db),a:PlatformAdmin=Depends(current_admin)):
    c=db.get(Customer,customer_id)
    if not c: raise HTTPException(404,"Customer not found.")
    c.is_active=data.active; action="CUSTOMER_REACTIVATED" if data.active else "CUSTOMER_SUSPENDED"
    audit(db,a,action,"customer",customer_id,data.reason.strip()); db.commit()
    return {"id":c.id,"active":c.is_active}

@router.get("/bank-admins")
def bank_admin_directory(q:str="",status:str="all",db:Session=Depends(get_db),a:PlatformAdmin=Depends(current_admin)):
    if status.casefold() not in {"all","active","suspended","pending","accepted","expired","revoked"}: raise HTTPException(422,"Unsupported Bank Admin or invitation status filter.")
    admins=db.scalars(select(BankAdmin).join(Bank).order_by(BankAdmin.created_at.desc())).all(); invitations=db.scalars(select(BankInvitation).order_by(BankInvitation.created_at.desc())).all()
    items=[]
    for u in admins:
        b=db.get(Bank,u.bank_id); term=q.strip().casefold()
        if term and not any(term in x.casefold() for x in (u.full_name,u.email,b.name if b else "")): continue
        if status.lower() in {"active","suspended"} and u.is_active!=(status.lower()=="active"): continue
        if status.lower() in {"pending","expired","revoked"}: continue
        items.append({"id":u.id,"kind":"account","full_name":u.full_name,"email":u.email,"bank_id":u.bank_id,"bank_name":b.name if b else "Unavailable","active":u.is_active,"invitation_status":"accepted","created_at":u.created_at.isoformat() if u.created_at else None,"last_login":None})
    for i in invitations:
        if db.scalar(select(BankAdmin.id).where(BankAdmin.email==i.email)): continue
        b=db.get(Bank,i.bank_id); term=q.strip().casefold()
        if term and not any(term in x.casefold() for x in (i.full_name,i.email,b.name if b else "")): continue
        if i.used_at: istatus="revoked"
        elif (i.expires_at.replace(tzinfo=timezone.utc) if i.expires_at.tzinfo is None else i.expires_at)<=datetime.now(timezone.utc): istatus="expired"
        else: istatus="pending"
        if status.lower() not in {"all",istatus}: continue
        items.append({"id":i.id,"kind":"invitation","full_name":i.full_name,"email":i.email,"bank_id":i.bank_id,"bank_name":b.name if b else "Unavailable","active":False,"invitation_status":istatus,"created_at":i.created_at.isoformat() if i.created_at else None,"expires_at":i.expires_at.isoformat()})
    all_accounts=db.scalars(select(BankAdmin)).all(); all_invitations=db.scalars(select(BankInvitation)).all(); now=datetime.now(timezone.utc)
    counts={"active":sum(bool(x.is_active) for x in all_accounts),"suspended":sum(not x.is_active for x in all_accounts),"accepted":len(all_accounts),"pending":0,"expired":0,"revoked":0}
    for invite in all_invitations:
        if any(x.email.casefold()==invite.email.casefold() for x in all_accounts): continue
        expiry=invite.expires_at.replace(tzinfo=timezone.utc) if invite.expires_at.tzinfo is None else invite.expires_at
        key="revoked" if invite.used_at else "expired" if expiry<=now else "pending"
        counts[key]+=1
    return {"items":items,"total":len(items),"counts":counts}

@router.patch("/bank-admins/{admin_id}/status")
def bank_admin_status(admin_id:int,data:AccountAction,db:Session=Depends(get_db),a:PlatformAdmin=Depends(current_admin)):
    u=db.get(BankAdmin,admin_id)
    if not u: raise HTTPException(404,"Bank Admin not found.")
    u.is_active=data.active; audit(db,a,"BANK_ADMIN_REACTIVATED" if data.active else "BANK_ADMIN_SUSPENDED","bank_admin",u.id,data.reason.strip()); db.commit()
    return {"id":u.id,"active":u.is_active}

@router.patch("/bank-admins/{admin_id}")
def edit_bank_admin(admin_id:int,data:BankAdminEditIn,db:Session=Depends(get_db),a:PlatformAdmin=Depends(current_admin)):
    u=db.get(BankAdmin,admin_id)
    if not u: raise HTTPException(404,"Bank Admin not found.")
    email=str(data.email).strip().casefold()
    duplicate=db.scalar(select(BankAdmin.id).where(func.lower(BankAdmin.email)==email,BankAdmin.id!=u.id))
    if duplicate: raise HTTPException(409,"This email is already assigned to a Bank Admin account.")
    old_email=u.email
    u.full_name=data.full_name.strip();u.email=email
    audit(db,a,"BANK_ADMIN_DETAILS_UPDATED","bank_admin",u.id,f"reason={data.reason.strip()}; email_changed={old_email.casefold()!=email}; bank_id={u.bank_id}")
    db.commit()
    return {"id":u.id,"kind":"account","full_name":u.full_name,"email":u.email,"bank_id":u.bank_id,"active":u.is_active,"invitation_status":"accepted"}

@router.patch("/bank-invitations/{invitation_id}")
def edit_bank_invitation(invitation_id:int,data:InvitationEditIn,db:Session=Depends(get_db),a:PlatformAdmin=Depends(current_admin)):
    invitation=db.get(BankInvitation,invitation_id)
    if not invitation: raise HTTPException(404,"Invitation not found.")
    if db.scalar(select(BankAdmin.id).where(func.lower(BankAdmin.email)==invitation.email.casefold())): raise HTTPException(409,"Invitation was already accepted; edit the account details instead.")
    bank=db.get(Bank,data.bank_id)
    if not bank: raise HTTPException(404,"Bank not found.")
    if bank.status!="APPROVED": raise HTTPException(409,"Select an approved bank before updating this invitation.")
    email=str(data.email).strip().casefold()
    if db.scalar(select(BankAdmin.id).where(func.lower(BankAdmin.email)==email)): raise HTTPException(409,"This email already has a Bank Admin account.")
    other=db.scalars(select(BankInvitation).where(BankInvitation.id!=invitation.id,BankInvitation.bank_id==bank.id,BankInvitation.used_at.is_(None))).all()
    if any(x.email.casefold()==email and (x.expires_at.replace(tzinfo=timezone.utc) if x.expires_at.tzinfo is None else x.expires_at)>datetime.now(timezone.utc) for x in other): raise HTTPException(409,"An active invitation already exists for this email and bank.")
    invitation.bank_id=bank.id;invitation.email=email;invitation.full_name=data.full_name.strip()
    _rotate_invitation(invitation,bank,a,db,"BANK_ADMIN_INVITATION_UPDATED",f"reason={data.reason.strip()}; bank={bank.code}; recipient corrected")
    return {"id":invitation.id,"kind":"invitation","full_name":invitation.full_name,"email":invitation.email,"bank_id":bank.id,"invitation_status":"pending","expires_at":invitation.expires_at.isoformat(),"delivery":"EMAIL_SENT"}

@router.post("/bank-invitations/{invitation_id}/resend")
def resend_bank_invitation(invitation_id:int,data:ReasonIn,db:Session=Depends(get_db),a:PlatformAdmin=Depends(current_admin)):
    invitation=db.get(BankInvitation,invitation_id)
    if not invitation: raise HTTPException(404,"Invitation not found.")
    if db.scalar(select(BankAdmin.id).where(func.lower(BankAdmin.email)==invitation.email.casefold())): raise HTTPException(409,"Invitation was already accepted; suspend the account instead.")
    bank=db.get(Bank,invitation.bank_id)
    if not bank or bank.status!="APPROVED": raise HTTPException(409,"The associated bank is not approved.")
    now=datetime.now(timezone.utc)
    for other in db.scalars(select(BankInvitation).where(BankInvitation.id!=invitation.id,BankInvitation.bank_id==bank.id,BankInvitation.used_at.is_(None))).all():
        expiry=other.expires_at.replace(tzinfo=timezone.utc) if other.expires_at.tzinfo is None else other.expires_at
        if other.email.casefold()==invitation.email.casefold() and expiry>now: raise HTTPException(409,"Another active invitation already exists for this email and bank.")
    _rotate_invitation(invitation,bank,a,db,"BANK_ADMIN_INVITATION_RESENT",f"reason={data.reason.strip()}; token rotated")
    return {"id":invitation.id,"status":"pending","expires_at":invitation.expires_at.isoformat(),"delivery":"EMAIL_SENT"}

@router.post("/bank-invitations/{invitation_id}/revoke")
def revoke_bank_invitation(invitation_id:int,data:AccountAction,db:Session=Depends(get_db),a:PlatformAdmin=Depends(current_admin)):
    i=db.get(BankInvitation,invitation_id)
    if not i: raise HTTPException(404,"Invitation not found.")
    if db.scalar(select(BankAdmin.id).where(func.lower(BankAdmin.email)==i.email.casefold())): raise HTTPException(409,"Invitation was already accepted; suspend the account instead.")
    if i.used_at: raise HTTPException(409,"Invitation is already revoked.")
    i.used_at=datetime.now(timezone.utc); audit(db,a,"BANK_ADMIN_INVITATION_REVOKED","bank_invitation",i.id,data.reason.strip()); db.commit()
    return {"id":i.id,"status":"revoked"}

@router.delete("/bank-invitations/{invitation_id}")
def delete_bank_invitation(invitation_id:int,data:ReasonIn,db:Session=Depends(get_db),a:PlatformAdmin=Depends(current_admin)):
    i=db.get(BankInvitation,invitation_id)
    if not i: raise HTTPException(404,"Invitation not found.")
    if db.scalar(select(BankAdmin.id).where(func.lower(BankAdmin.email)==i.email.casefold())): raise HTTPException(409,"Accepted account records cannot be deleted; suspend the account instead.")
    audit(db,a,"BANK_ADMIN_INVITATION_DELETED","bank_invitation",i.id,data.reason.strip())
    db.delete(i);db.commit()
    return {"id":invitation_id,"deleted":True}

@router.get("/monitoring")
def monitoring(hours:int=Query(default=24,ge=1,le=720),db:Session=Depends(get_db),a:PlatformAdmin=Depends(current_admin)):
    now=datetime.now(timezone.utc); since=now-timedelta(hours=hours); database="Healthy"
    try: db.execute(text("SELECT 1"))
    except Exception:
        return {"checked_at":now.isoformat(),"period_hours":hours,"services":[{"name":"FastAPI","status":"Healthy","last_checked":now.isoformat(),"details":"This monitoring endpoint responded successfully."},{"name":"Database","status":"Unavailable","last_checked":now.isoformat(),"details":"Database connection check failed."},{"name":"NVIDIA API","status":"Unknown","last_checked":None,"details":"Database telemetry unavailable; no live request was made."},{"name":"Nemotron analysis","status":"Unknown","last_checked":None,"details":"Persisted run telemetry unavailable."},{"name":"OCR","status":"Unknown","last_checked":None,"details":"Persisted extraction telemetry unavailable."},{"name":"RAG / retrieval","status":"Unknown","last_checked":None,"details":"Retrieval health telemetry is not persisted."},{"name":"NeMo Guardrails","status":"Unknown","last_checked":None,"details":"Guardrails invocation outcomes are not persisted."}],"incidents":[]}
    verification=nv.LAST_VERIFICATION or {}; checked=verification.get("checked_at"); check_time=None
    try: check_time=datetime.fromisoformat(checked.replace("Z","+00:00")) if checked else None
    except (ValueError,AttributeError): check_time=None
    nvidia_status="Unknown" if not check_time or now-check_time>timedelta(minutes=30) else ("Healthy" if verification.get("inference_ok") and verification.get("embedding_ok") else "Degraded")
    runs=db.scalars(select(AnalysisRun).where(AnalysisRun.created_at>=since).order_by(AnalysisRun.created_at.desc()).limit(500)).all()
    run_failures=[x for x in runs if (x.status or "").upper() in {"FAILED","ERROR"}]
    run_successes=[x for x in runs if (x.status or "").upper() in {"SUCCESS","SUCCEEDED","COMPLETED","ANALYSED"}]
    doc_rows=db.scalars(select(ApplicationDocument).where(ApplicationDocument.created_at>=since).order_by(ApplicationDocument.created_at.desc()).limit(500)).all()
    ocr_failures=[x for x in doc_rows if (x.extraction_status or "").upper() in {"FAILED","ERROR"}]
    tesseract=settings.tesseract_cmd.strip() or "tesseract"; ocr_available=bool(shutil.which(tesseract))
    ocr_status="Unavailable" if not ocr_available else ("Unknown" if not doc_rows else ("Degraded" if ocr_failures else "Healthy"))
    analysis_status="Unknown" if not runs else ("Degraded" if run_failures else ("Healthy" if run_successes else "Unknown"))
    incidents=[]
    for row in run_failures[:10]: incidents.append({"timestamp":row.created_at.isoformat(),"service":"Nemotron analysis","severity":"HIGH","summary":f"Analysis run {row.id} failed.","status":"Recorded"})
    for row in ocr_failures[:10]: incidents.append({"timestamp":row.created_at.isoformat(),"service":"OCR","severity":"MEDIUM","summary":f"Document extraction failed for record {row.id}.","status":"Recorded"})
    incidents.sort(key=lambda x:x["timestamp"],reverse=True)
    return {"checked_at":now.isoformat(),"period_hours":hours,"services":[{"name":"FastAPI","status":"Healthy","last_checked":now.isoformat(),"details":"This monitoring endpoint responded successfully."},{"name":"Database","status":database,"last_checked":now.isoformat(),"details":"SELECT 1 check" if database=="Healthy" else "Database connection check failed."},{"name":"NVIDIA API","status":nvidia_status,"last_checked":checked,"details":"Last controlled connectivity verification; no request was made by this page." if check_time else "No controlled connectivity check recorded in this process."},{"name":"Nemotron analysis","status":analysis_status,"last_checked":runs[0].created_at.isoformat() if runs else None,"successes":len(run_successes),"failures":len(run_failures),"details":f"{len(runs)} recorded runs in the selected period."},{"name":"OCR","status":ocr_status,"last_checked":doc_rows[0].created_at.isoformat() if doc_rows else now.isoformat() if not ocr_available else None,"failures":len(ocr_failures),"details":"Tesseract OCR executable was not found." if not ocr_available else f"{len(doc_rows)} document extraction records in the selected period." if doc_rows else "No document extraction records in the selected period."},{"name":"RAG / retrieval","status":"Unknown","last_checked":None,"details":"Retrieval health telemetry is not persisted."},{"name":"NeMo Guardrails","status":"Unknown","last_checked":None,"details":"Guardrails invocation outcomes are not persisted."}],"incidents":incidents}

def _sync_notifications(db):
    sources=[]
    for b in db.scalars(select(Bank).where(Bank.status=="PENDING")).all(): sources.append((f"bank_pending:{b.id}","Bank registration pending approval",f"{b.name} is awaiting a Platform Admin decision.","BANK","MEDIUM","bank",b.id))
    for run in db.scalars(select(AnalysisRun).where(func.upper(AnalysisRun.status).in_(["FAILED","ERROR"])).limit(500)).all(): sources.append((f"analysis_failed:{run.id}","Mortgage analysis failed",f"Nemotron analysis run {run.id} failed and may need operational review.","AI","HIGH","analysis_run",run.id))
    for log in db.scalars(select(AuditLog).where(or_(AuditLog.action.ilike("%FAILED%"),AuditLog.action.ilike("%DENIED%"))).order_by(AuditLog.created_at.desc()).limit(500)).all():
        label=_action_label(log.action)
        message=f"{label}. A {log.actor_role.replace('_',' ').title()} event was recorded." if log.actor_role else f"{label}."
        sources.append((f"security:{log.id}",label,message,"SECURITY","HIGH",log.resource_type,log.resource_id))
    for log in db.scalars(select(AuditLog).where(or_(AuditLog.action.ilike("BANK_APPROVED%"),AuditLog.action.ilike("BANK_REJECTED%"),AuditLog.action.ilike("BANK_ADMIN_INVITED%"),AuditLog.action.ilike("BANK_ADMIN_INVITATION_DELIVERY_FAILED%"))).order_by(AuditLog.created_at.desc()).limit(500)).all():
        severity="HIGH" if "FAILED" in log.action else "MEDIUM"
        label=_action_label(log.action)
        sources.append((f"admin_event:{log.id}",label,f"{label} for bank record {log.resource_id}.","BANK",severity,log.resource_type,log.resource_id))
    known={x.fingerprint for x in db.scalars(select(AdminNotification)).all()}
    for fingerprint,title,message,category,severity,resource,rid in sources:
        if fingerprint not in known: db.add(AdminNotification(fingerprint=fingerprint,title=title,message=message,category=category,severity=severity,resource_type=resource,resource_id=str(rid)))
    db.commit()

@router.get("/notifications")
def notifications(category:str="all",severity:str="all",read_status:str="all",unread:bool=False,q:str="",start:date|None=None,end:date|None=None,limit:int=25,offset:int=0,db:Session=Depends(get_db),a:PlatformAdmin=Depends(current_admin)):
    _check_period(start,end); _sync_notifications(db)
    if category.upper() not in {"ALL","BANK","AI","SECURITY"}: raise HTTPException(422,"Unsupported notification category.")
    if severity.upper() not in {"ALL","INFO","MEDIUM","HIGH","CRITICAL"}: raise HTTPException(422,"Unsupported notification severity.")
    query=select(AdminNotification).where(AdminNotification.deleted_at.is_(None))
    if category.lower()!="all": query=query.where(AdminNotification.category==category.upper())
    if severity.lower()!="all": query=query.where(AdminNotification.severity==severity.upper())
    status=read_status.lower()
    if unread: status="unread"
    if status not in {"all","read","unread"}: raise HTTPException(422,"read_status must be all, read, or unread.")
    if status=="read": query=query.where(AdminNotification.read_at.is_not(None))
    if status=="unread": query=query.where(AdminNotification.read_at.is_(None))
    if start: query=query.where(AdminNotification.created_at>=datetime.combine(start,datetime.min.time(),tzinfo=timezone.utc))
    if end: query=query.where(AdminNotification.created_at<datetime.combine(end+timedelta(days=1),datetime.min.time(),tzinfo=timezone.utc))
    if q.strip(): query=query.where(or_(AdminNotification.title.ilike(f"%{q.strip()}%"),AdminNotification.message.ilike(f"%{q.strip()}%")))
    total=db.scalar(select(func.count()).select_from(query.subquery())) or 0
    unread_count=db.scalar(select(func.count()).select_from(AdminNotification).where(AdminNotification.deleted_at.is_(None),AdminNotification.read_at.is_(None))) or 0
    rows=db.scalars(query.order_by(AdminNotification.created_at.desc()).offset(max(0,offset)).limit(max(1,min(limit,100)))).all()
    return {"items":[{"id":x.id,"title":x.title,"message":x.message,"category":x.category,"severity":x.severity,"resource_type":x.resource_type,"resource_id":x.resource_id,"read":bool(x.read_at),"created_at":x.created_at.isoformat()} for x in rows],"total":total,"unread_count":unread_count,"limit":max(1,min(limit,100)),"offset":max(0,offset)}

@router.patch("/notifications/{notification_id}/read")
def notification_read(notification_id:int,data:ReadAction,db:Session=Depends(get_db),a:PlatformAdmin=Depends(current_admin)):
    n=db.get(AdminNotification,notification_id)
    if not n or n.deleted_at: raise HTTPException(404,"Notification not found.")
    n.read_at=None if not data.read else datetime.now(timezone.utc); db.commit(); return {"id":n.id,"read":bool(n.read_at),"unread_count":db.scalar(select(func.count()).select_from(AdminNotification).where(AdminNotification.deleted_at.is_(None),AdminNotification.read_at.is_(None))) or 0}

@router.post("/notifications/read-all")
def notifications_read_all(db:Session=Depends(get_db),a:PlatformAdmin=Depends(current_admin)):
    rows=db.scalars(select(AdminNotification).where(AdminNotification.deleted_at.is_(None),AdminNotification.read_at.is_(None))).all()
    for row in rows: row.read_at=datetime.now(timezone.utc)
    db.commit(); return {"updated":len(rows),"unread_count":0}

@router.delete("/notifications/{notification_id}")
def notification_delete(notification_id:int,db:Session=Depends(get_db),a:PlatformAdmin=Depends(current_admin)):
    n=db.get(AdminNotification,notification_id)
    if not n or n.deleted_at: raise HTTPException(404,"Notification not found.")
    n.deleted_at=datetime.now(timezone.utc); audit(db,a,"ADMIN_NOTIFICATION_DELETED","admin_notification",n.id,"Notification removed; source audit/event record retained."); db.commit()
    return {"id":n.id,"deleted":True,"unread_count":db.scalar(select(func.count()).select_from(AdminNotification).where(AdminNotification.deleted_at.is_(None),AdminNotification.read_at.is_(None))) or 0}

@router.get("/reports")
def reports(start:date|None=None,end:date|None=None,db:Session=Depends(get_db),a:PlatformAdmin=Depends(current_admin)):
    _check_period(start,end)
    def counts(model, field):
        q=select(getattr(model,field),func.count()).group_by(getattr(model,field))
        if start and hasattr(model,"created_at"): q=q.where(model.created_at>=datetime.combine(start,datetime.min.time(),tzinfo=timezone.utc))
        if end and hasattr(model,"created_at"): q=q.where(model.created_at<datetime.combine(end+timedelta(days=1),datetime.min.time(),tzinfo=timezone.utc))
        return {str(k or "Unknown"):v for k,v in db.execute(q).all()}
    customers=counts(Customer,"is_active"); verified=counts(Customer,"is_verified")
    return {"period":{"start":start.isoformat() if start else None,"end":end.isoformat() if end else None},"banks_by_status":counts(Bank,"status"),"customers_by_status":{"Active":customers.get("True",customers.get("1",0)),"Suspended":customers.get("False",customers.get("0",0))},"customers_by_verification":{"Verified":verified.get("True",verified.get("1",0)),"Pending":verified.get("False",verified.get("0",0))},"applications_by_status":counts(MortgageApplication,"status"),"analysis_by_status":counts(AnalysisRun,"status"),"document_extraction_by_status":counts(ApplicationDocument,"extraction_status"),"audit_by_action":counts(AuditLog,"action")}

@router.get("/reports.csv")
def reports_csv(start:date|None=None,end:date|None=None,db:Session=Depends(get_db),a:PlatformAdmin=Depends(current_admin)):
    data=reports(start,end,db,a); rows=[]
    for category,key in (("Bank registrations","banks_by_status"),("Customer accounts","customers_by_status"),("Customer verification","customers_by_verification"),("Mortgage applications","applications_by_status"),("AI analysis","analysis_by_status"),("Document extraction","document_extraction_by_status"),("Administrative events","audit_by_action")):
        rows.extend({"category":category,"status_or_action":status,"count":count,"period_start":data["period"]["start"],"period_end":data["period"]["end"]} for status,count in data[key].items())
    return _csv_response(rows,"platform-report.csv",["category","status_or_action","count","period_start","period_end"])

@router.get("/audit-logs.csv")
def audit_csv(actor:str|None=None,action:str|None=None,resource_type:str|None=None,outcome:str|None=None,severity:str|None=None,category:str|None=None,start:date|None=None,end:date|None=None,db:Session=Depends(get_db),a:PlatformAdmin=Depends(current_admin)):
    rows=audit_logs(limit=250,offset=0,actor=actor,action=action,resource_type=resource_type,outcome=outcome,severity=severity,category=category,start=start,end=end,db=db,a=a)["items"]
    # Export metadata is restricted to event identity/status; contextual detail stays in the authorized UI.
    return _csv_response(rows,"security-audit.csv",["id","actor_email","actor_role","action","action_label","resource_type","resource_id","outcome","severity","category","request_id","created_at"])
