from datetime import datetime, timedelta, timezone
import hashlib, secrets, json, re, logging
from pathlib import Path
import tempfile
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr, Field, model_validator, ValidationError
from sqlalchemy import select, func, or_, and_, delete, update
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from app.database import get_db
from app.models import Bank, BankAdmin, BankInvitation, Reviewer, ReviewerInvitation, MortgageApplication, ReviewAssignment, ReviewEvent, Customer, ApplicationDocument, AuditLog, PolicyDocument, PolicyChunk, AssignmentEvent, BankAdminNotification
from app.security import hash_password, verify_password, token_for, token_subject, token_claims, is_locked, note_failure, clear_failures, needs_rehash
from app.config import MIN_PASSWORD_LENGTH
from app.services.policy_rag import index_policy, _page_chunks
from app.services.ocr import extract_text
from app.services.policy_rag import retrieve_hybrid
from app.services.nvidia import answer_policy_question, NVIDIAConfigurationError, NVIDIAInputRejected, validate_ai_request
from app.services.assignment import retry_pending_assignments, release_reviewer_assignments, reviewer_load, status_label, PENDING_STATUS, TERMINAL_STATUSES
from app.services.mailer import send_email, OTPDeliveryError
from app.config import settings
from datetime import timedelta
from urllib.parse import quote
from app.security import is_locked, note_failure, clear_failures

router = APIRouter(tags=["Bank administration"])
bearer = HTTPBearer(auto_error=False)
logger = logging.getLogger(__name__)

class LoginIn(BaseModel): email: EmailStr; password: str
class AcceptInviteIn(BaseModel): token: str = Field(min_length=32, max_length=256); password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=128)
class ReviewerIn(BaseModel):
    model_config = {"extra": "forbid"}
    full_name: str = Field(min_length=2, max_length=160)
    email: EmailStr
    specialisation: str = Field(default="GENERAL_MORTGAGE_REVIEW", pattern="^(GENERAL_MORTGAGE_REVIEW|INCOME_TAX|PROPERTY_VALUATION|TERMS_CONDITIONS)$")
    max_active_assignments: int = Field(default=10, ge=1, le=100)
class ReviewerActivationIn(BaseModel):
    token: str = Field(min_length=32, max_length=256)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=128)
class ReviewerUpdateIn(BaseModel): full_name:str=Field(min_length=2,max_length=160); email:EmailStr; specialisation:str=Field(pattern="^(GENERAL_MORTGAGE_REVIEW|INCOME_TAX|PROPERTY_VALUATION|TERMS_CONDITIONS)$"); max_active_assignments:int=Field(ge=1,le=100); reason:str=Field(min_length=8,max_length=1000)
class BankPolicyIn(BaseModel):
    title:str=Field(min_length=3,max_length=200)
    policy_version:str=Field(min_length=1,max_length=80)
    category:str=Field(min_length=2,max_length=100)
    content:str=Field(min_length=20,max_length=1000000)
    active:bool=True
    customer_visible:bool=False
    customer_summary:str=Field(default="",max_length=20000)
    @model_validator(mode="after")
    def customer_summary_required_when_shared(self):
        if self.customer_visible and len(self.customer_summary.strip()) < 20:
            raise ValueError("A customer-safe summary of at least 20 characters is required before customer-visible policy retrieval can be enabled.")
        return self
class CustomerPolicyVersionIn(BaseModel):
    title:str=Field(min_length=3,max_length=200)
    policy_version:str=Field(min_length=1,max_length=80)
    category:str=Field(min_length=2,max_length=100)
    customer_summary:str=Field(min_length=20,max_length=20000)
    @model_validator(mode="after")
    def require_customer_safe_metadata(self):
        if len(self.title.strip())<3 or not self.policy_version.strip() or len(self.category.strip())<2 or len(self.customer_summary.strip())<20:
            raise ValueError("Enter a title, version, category, and customer-safe summary with their required non-empty lengths.")
        return self
class BankPolicyQuestionIn(BaseModel):
    question: str = Field(min_length=5, max_length=2000)
class BankProfileUpdate(BaseModel): contact_email: EmailStr
class NotificationReadIn(BaseModel): read:bool
class ApplicationArchiveIn(BaseModel): reason:str=Field(min_length=8,max_length=1000)


def current_bank_admin(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)):
    if not credentials: raise HTTPException(401, "Bank Admin authentication required.")
    claims = token_claims(credentials.credentials)
    sub = claims.get("sub") if claims else None
    role = str(claims.get("role", "")).strip().upper() if claims else ""
    # Signed tokens from the former bank_admin subject spelling are accepted only
    # when their verified role claim is Bank Admin and the subject resolves to an
    # active persisted account. Frontend role labels never grant access.
    if role != "BANK_ADMIN" or not isinstance(sub, str): raise HTTPException(403, "Bank Admin role required.")
    match = re.fullmatch(r"(?:bankadmin|bank_admin|bank-admin):(\d+)", sub.strip(), flags=re.IGNORECASE)
    if not match: raise HTTPException(403, "Bank Admin role required.")
    uid = int(match.group(1))
    admin = db.get(BankAdmin, uid)
    if not admin or not admin.is_active: raise HTTPException(401, "Bank Admin account is inactive or unavailable.")
    bank = db.get(Bank, admin.bank_id)
    if not bank or bank.status != "APPROVED": raise HTTPException(403, "Your bank is not approved or is inactive.")
    return admin


def audit(db, actor, action, resource, rid="", detail=""):
    db.add(AuditLog(actor_email=actor.email, actor_role="BANK_ADMIN", action=action, resource_type=resource, resource_id=str(rid), detail=detail[:4000]))

@router.post("/bank-admin/login")
def login(data: LoginIn, db: Session = Depends(get_db)):
    email = data.email.lower().strip(); key = "bankadmin:" + email
    if is_locked(key): raise HTTPException(429, "Too many failed sign-in attempts. Try again later.")
    user = db.scalar(select(BankAdmin).where(BankAdmin.email == email))
    if not user or not user.is_active or not verify_password(data.password, user.password_hash):
        note_failure(key)
        db.add(AuditLog(actor_email=email[:255], actor_role="BANK_ADMIN", action="LOGIN_FAILED", resource_type="bank_admin", resource_id=email)); db.commit()
        raise HTTPException(401, "Invalid Bank Admin credentials.")
    bank = db.get(Bank, user.bank_id)
    if not bank or bank.status != "APPROVED": raise HTTPException(403, "Bank is not approved.")
    clear_failures(key)
    if needs_rehash(user.password_hash): user.password_hash = hash_password(data.password); db.commit()  # upgrade legacy hash to PBKDF2
    return {"access_token": token_for(f"bankadmin:{user.id}"), "token_type": "bearer", "bank_admin": {"id": user.id, "full_name": user.full_name, "email": user.email, "role": "BANK_ADMIN", "bank": {"id": bank.id, "name": bank.name, "code": bank.code}}}

@router.post("/bank-admin/accept-invitation")
def accept_invitation(data: AcceptInviteIn, db: Session = Depends(get_db)):
    token_hash = hashlib.sha256(data.token.encode()).hexdigest()
    invitation = db.scalar(select(BankInvitation).where(BankInvitation.token_hash == token_hash))
    now = datetime.now(timezone.utc)
    if not invitation or invitation.used_at or invitation.expires_at.replace(tzinfo=timezone.utc) <= now:
        raise HTTPException(400, "Invitation is invalid, expired, or already used.")
    bank = db.get(Bank, invitation.bank_id)
    if not bank or bank.status != "APPROVED": raise HTTPException(403, "Bank must be approved before invitation acceptance.")
    if db.scalar(select(BankAdmin).where(BankAdmin.email == invitation.email)): raise HTTPException(409, "A Bank Admin account already exists for this email.")
    user = BankAdmin(bank_id=bank.id, full_name=invitation.full_name, email=invitation.email, password_hash=hash_password(data.password), is_active=True)
    db.add(user); invitation.used_at = now
    db.add(AuditLog(actor_email=invitation.email, actor_role="BANK_ADMIN", action="INVITATION_ACCEPTED", resource_type="bank", resource_id=str(bank.id), detail="Bank Admin invitation accepted."))
    db.commit()
    return {"message": "Invitation accepted. You can now sign in.", "email": user.email, "bank": bank.name}

@router.get("/bank-admin/me")
def me(admin: BankAdmin = Depends(current_bank_admin), db: Session = Depends(get_db)):
    bank = db.get(Bank, admin.bank_id)
    return {"id": admin.id, "full_name": admin.full_name, "email": admin.email, "role": "BANK_ADMIN", "bank": {"id": bank.id, "name": bank.name, "code": bank.code}}

def _bank_apps_cond(bank):
    return or_(MortgageApplication.bank_id == bank.id, and_(MortgageApplication.bank_id.is_(None), MortgageApplication.lender_name.in_([bank.name, bank.code])))

def _event_row(db, e, app=None, reviewer=None):
    app = app or db.get(MortgageApplication, e.application_id)
    reviewer = reviewer or (db.get(Reviewer, e.reviewer_id) if e.reviewer_id else None)
    return {"id": e.id, "application_id": e.application_id, "reference": app.reference if app else None, "event_type": e.event_type, "reason": e.reason, "reviewer_id": e.reviewer_id, "reviewer_name": reviewer.full_name if reviewer else None, "reviewer_email": reviewer.email if reviewer else None, "created_at": e.created_at.isoformat()}

@router.get("/bank-admin/dashboard")
def dashboard(admin: BankAdmin = Depends(current_bank_admin), db: Session = Depends(get_db)):
    """Read-only monitoring. Assignments are made by the backend engine; Bank Admin cannot assign."""
    bank = db.get(Bank, admin.bank_id)
    cond = and_(_bank_apps_cond(bank),MortgageApplication.archived_at.is_(None))
    apps = select(MortgageApplication.id).where(cond)
    app_count = db.scalar(select(func.count()).select_from(MortgageApplication).where(cond)) or 0
    archived_count=db.scalar(select(func.count()).select_from(MortgageApplication).where(_bank_apps_cond(bank),MortgageApplication.archived_at.is_not(None))) or 0
    reviewer_cond = or_(Reviewer.bank_id == bank.id, and_(Reviewer.bank_id.is_(None), Reviewer.bank_code == bank.code))
    reviewer_rows=db.scalars(select(Reviewer).where(reviewer_cond).order_by(Reviewer.full_name)).all()
    reviewer_count=len(reviewer_rows)
    workloads={r.id:reviewer_load(db,r.id) for r in reviewer_rows}
    available=sum(1 for r in reviewer_rows if r.is_active and r.is_available is not False and workloads[r.id]<r.max_active_assignments)
    assigned = db.scalar(select(func.count()).select_from(ReviewAssignment).join(MortgageApplication, MortgageApplication.id == ReviewAssignment.application_id).where(ReviewAssignment.active == True, ReviewAssignment.application_id.in_(apps), MortgageApplication.status.notin_(TERMINAL_STATUSES))) or 0
    awaiting = db.scalar(select(func.count()).select_from(MortgageApplication).where(cond, MortgageApplication.status == PENDING_STATUS)) or 0
    status_rows = db.execute(select(MortgageApplication.status, func.count()).where(cond, MortgageApplication.status != "DRAFT").group_by(MortgageApplication.status)).all()
    recent = db.scalars(select(AssignmentEvent).where(AssignmentEvent.application_id.in_(apps)).order_by(AssignmentEvent.created_at.desc(), AssignmentEvent.id.desc()).limit(10)).all()
    active_policies=db.scalar(select(func.count()).select_from(PolicyDocument).where(PolicyDocument.bank_id==bank.id,PolicyDocument.active.is_(True))) or 0
    statuses={k:v for k,v in status_rows}
    return {"generated_at":datetime.now(timezone.utc).isoformat(),"bank": {"id": bank.id, "name": bank.name, "code": bank.code, "status": bank.status}, "applications": app_count,"archived_applications":archived_count, "reviewers": reviewer_count, "active_reviewers":sum(1 for r in reviewer_rows if r.is_active), "available_reviewers": available, "active_assignments": assigned, "awaiting_assignment": awaiting, "in_review":statuses.get("IN_REVIEW",0)+statuses.get("ASSIGNED",0), "documents_requested":statuses.get("DOCUMENTS_REQUESTED",0)+statuses.get("ADDITIONAL_INFORMATION_REQUIRED",0), "escalated":statuses.get("ESCALATED",0), "active_policies":active_policies, "status_counts": statuses, "reviewer_workload":[{"id":r.id,"full_name":r.full_name,"specialisation":r.specialisation,"active_assignments":workloads[r.id],"max_active_assignments":r.max_active_assignments,"available":r.is_active and r.is_available is not False and workloads[r.id]<r.max_active_assignments,"active":r.is_active} for r in reviewer_rows], "recent_assignment_activity": [_event_row(db, e) for e in recent], "assignment_mode": "AUTOMATIC"}

@router.get("/bank-admin/assignment-history")
def assignment_history(application_id: int | None = None, limit: int = 100, admin: BankAdmin = Depends(current_bank_admin), db: Session = Depends(get_db)):
    bank = db.get(Bank, admin.bank_id)
    apps = select(MortgageApplication.id).where(_bank_apps_cond(bank))
    q = select(AssignmentEvent).where(AssignmentEvent.application_id.in_(apps))
    if application_id is not None:
        q = q.where(AssignmentEvent.application_id == application_id)
    rows = db.scalars(q.order_by(AssignmentEvent.created_at.desc(), AssignmentEvent.id.desc()).limit(max(1, min(limit, 500)))).all()
    return [_event_row(db, e) for e in rows]


def _sync_bank_admin_notifications(db:Session,bank:Bank):
    """Create one persistent bank notification per existing assignment event without mutating the source event."""
    apps=select(MortgageApplication.id).where(_bank_apps_cond(bank))
    events=db.scalars(select(AssignmentEvent).where(AssignmentEvent.application_id.in_(apps)).order_by(AssignmentEvent.created_at.desc(),AssignmentEvent.id.desc()).limit(200)).all()
    known=set(db.scalars(select(BankAdminNotification.fingerprint).where(BankAdminNotification.bank_id==bank.id)).all())
    labels={"ASSIGNED":"Application assigned to a reviewer","PENDING_ASSIGNMENT":"Application awaiting reviewer assignment","REASSIGNMENT_REQUIRED":"Application needs reassignment","RESUBMITTED":"Application resubmitted","REVIEW_COMPLETED":"Review completed"}
    for event in events:
        fingerprint=f"assignment-event:{event.id}"
        if fingerprint in known: continue
        app=db.get(MortgageApplication,event.application_id)
        reviewer=db.get(Reviewer,event.reviewer_id) if event.reviewer_id else None
        title=labels.get(event.event_type,event.event_type.replace("_"," ").strip().capitalize() or "Assignment activity")
        severity="HIGH" if event.event_type in {"PENDING_ASSIGNMENT","REASSIGNMENT_REQUIRED","ASSIGNMENT_ERROR"} else "INFO"
        db.add(BankAdminNotification(bank_id=bank.id,fingerprint=fingerprint,title=title,message=f"{app.reference if app else 'Application'}: {event.reason or title}",category="ASSIGNMENT",severity=severity,resource_type="application",resource_id=str(event.application_id),created_at=event.created_at))
        known.add(fingerprint)
    db.commit()


@router.get("/bank-admin/notifications")
def bank_admin_notifications(q:str="",category:str="all",severity:str="all",read_status:str="all",archived:bool=False,limit:int=30,offset:int=0,admin:BankAdmin=Depends(current_bank_admin),db:Session=Depends(get_db)):
    bank=db.get(Bank,admin.bank_id)
    _sync_bank_admin_notifications(db,bank)
    query=select(BankAdminNotification).where(BankAdminNotification.bank_id==bank.id)
    if not archived: query=query.where(BankAdminNotification.archived_at.is_(None))
    if category.casefold()!="all": query=query.where(BankAdminNotification.category==category.strip().upper())
    if severity.casefold()!="all": query=query.where(BankAdminNotification.severity==severity.strip().upper())
    if read_status.casefold()=="read": query=query.where(BankAdminNotification.read_at.is_not(None))
    elif read_status.casefold()=="unread": query=query.where(BankAdminNotification.read_at.is_(None))
    elif read_status.casefold()!="all": raise HTTPException(422,"Read status must be all, read or unread.")
    term=q.strip()
    if term: query=query.where(or_(func.lower(BankAdminNotification.title).contains(term.casefold()),func.lower(BankAdminNotification.message).contains(term.casefold()),BankAdminNotification.resource_id.contains(term)))
    total=db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows=db.scalars(query.order_by(BankAdminNotification.created_at.desc(),BankAdminNotification.id.desc()).offset(max(0,offset)).limit(max(1,min(limit,100)))).all()
    unread=db.scalar(select(func.count()).select_from(BankAdminNotification).where(BankAdminNotification.bank_id==bank.id,BankAdminNotification.archived_at.is_(None),BankAdminNotification.read_at.is_(None))) or 0
    return {"items":[{"id":x.id,"title":x.title,"message":x.message,"category":x.category,"severity":x.severity,"resource_type":x.resource_type,"resource_id":x.resource_id,"read":x.read_at is not None,"archived":x.archived_at is not None,"created_at":x.created_at.isoformat()} for x in rows],"total":total,"unread_count":unread,"limit":max(1,min(limit,100)),"offset":max(0,offset)}


@router.patch("/bank-admin/notifications/{notification_id}/read")
def set_bank_admin_notification_read(notification_id:int,data:NotificationReadIn,admin:BankAdmin=Depends(current_bank_admin),db:Session=Depends(get_db)):
    row=db.scalar(select(BankAdminNotification).where(BankAdminNotification.id==notification_id,BankAdminNotification.bank_id==admin.bank_id))
    if not row: raise HTTPException(404,"Notification not found.")
    row.read_at=datetime.now(timezone.utc) if data.read else None
    audit(db,admin,"BANK_NOTIFICATION_READ" if data.read else "BANK_NOTIFICATION_UNREAD","bank_notification",row.id)
    db.commit()
    return {"id":row.id,"read":row.read_at is not None}


@router.delete("/bank-admin/notifications/{notification_id}")
def archive_bank_admin_notification(notification_id:int,admin:BankAdmin=Depends(current_bank_admin),db:Session=Depends(get_db)):
    row=db.scalar(select(BankAdminNotification).where(BankAdminNotification.id==notification_id,BankAdminNotification.bank_id==admin.bank_id))
    if not row: raise HTTPException(404,"Notification not found.")
    if row.archived_at: raise HTTPException(409,"Notification is already archived.")
    row.archived_at=datetime.now(timezone.utc)
    audit(db,admin,"BANK_NOTIFICATION_ARCHIVED","bank_notification",row.id,"Source assignment history retained.")
    db.commit()
    unread=db.scalar(select(func.count()).select_from(BankAdminNotification).where(BankAdminNotification.bank_id==admin.bank_id,BankAdminNotification.archived_at.is_(None),BankAdminNotification.read_at.is_(None))) or 0
    return {"id":row.id,"archived":True,"unread_count":unread}

@router.api_route("/bank-admin/assignments", methods=["POST", "PUT", "PATCH", "DELETE"])
@router.api_route("/bank-admin/applications/{application_id}/assign", methods=["POST", "PUT", "PATCH", "DELETE"])
def manual_assignment_disabled(application_id: int | None = None, admin: BankAdmin = Depends(current_bank_admin)):
    raise HTTPException(403, "Manual reviewer assignment is disabled. Applications are assigned automatically by the backend.")

@router.get("/bank-admin/applications")
def applications(include_archived:bool=False,admin: BankAdmin = Depends(current_bank_admin), db: Session = Depends(get_db)):
    bank = db.get(Bank, admin.bank_id)
    condition=_bank_apps_cond(bank) if include_archived else and_(_bank_apps_cond(bank),MortgageApplication.archived_at.is_(None))
    rows = db.scalars(select(MortgageApplication).where(condition, MortgageApplication.status != "DRAFT").order_by(MortgageApplication.created_at.desc())).all()
    result=[]
    for app in rows:
        customer=db.get(Customer,app.customer_id)
        assignment=db.scalar(select(ReviewAssignment).where(ReviewAssignment.application_id==app.id,ReviewAssignment.active==True))
        reviewer=db.get(Reviewer,assignment.reviewer_id) if assignment else None
        try: details=json.loads(getattr(app,"form_data_json","{}") or "{}")
        except (TypeError,ValueError): details={}
        bank_details=details.get("bank") if isinstance(details.get("bank"),dict) else {}
        if bank_details.get("account_number"):
            raw_account=str(bank_details["account_number"]); bank_details["account_number"]=("•"*max(0,len(raw_account)-4))+raw_account[-4:]; details["bank"]=bank_details
        documents=db.scalars(select(ApplicationDocument).where(ApplicationDocument.application_id==app.id)).all()
        result.append({"id":app.id,"reference":app.reference,"status":app.status,"lender_name":app.lender_name,"product_name":app.product_name,"requested_loan":app.requested_loan,"property_value":app.property_value,"customer_name":customer.full_name if customer else "Unavailable","reviewer_email":reviewer.email if reviewer else None,"reviewer_name":reviewer.full_name if reviewer else None,"has_active_assignment":bool(assignment and assignment.active),"assigned_at":assignment.assigned_at.isoformat() if assignment and assignment.assigned_at else None,"awaiting_assignment":app.status==PENDING_STATUS,"status_label":status_label(app.status,app.status==PENDING_STATUS),"assignment_attempts":app.assignment_attempts or 0,"last_assignment_attempt_at":app.last_assignment_attempt_at.isoformat() if app.last_assignment_attempt_at else None,"created_at":app.created_at.isoformat() if app.created_at else None,"updated_at":app.updated_at.isoformat() if app.updated_at else None,"submitted_at":app.submitted_at.isoformat() if app.submitted_at else None,"archived_at":app.archived_at.isoformat() if app.archived_at else None,"outstanding_action":"Awaiting eligible reviewer" if app.status==PENDING_STATUS else "Customer documents requested" if app.status in {"DOCUMENTS_REQUESTED","ADDITIONAL_INFORMATION_REQUIRED"} else "Escalated for review" if app.status=="ESCALATED" else "—","details":details,"document_summary":[{"category":d.category,"filename":d.original_filename,"extraction_status":d.extraction_status,"verification_status":d.verification_status} for d in documents]})
    return result


@router.post("/bank-admin/applications/{application_id}/archive")
def archive_application(application_id:int,data:ApplicationArchiveIn,admin:BankAdmin=Depends(current_bank_admin),db:Session=Depends(get_db)):
    bank=db.get(Bank,admin.bank_id); app=db.scalar(select(MortgageApplication).where(MortgageApplication.id==application_id,_bank_apps_cond(bank)))
    if not app or app.status=="DRAFT": raise HTTPException(404,"Submitted application not found in your bank.")
    if app.archived_at: raise HTTPException(409,"Application is already archived.")
    if app.status not in TERMINAL_STATUSES: raise HTTPException(409,"Only completed or terminal applications can be archived.")
    if db.scalar(select(ReviewAssignment.id).where(ReviewAssignment.application_id==app.id,ReviewAssignment.active.is_(True))): raise HTTPException(409,"Application still has an active reviewer assignment and cannot be archived.")
    app.archived_at=datetime.now(timezone.utc);audit(db,admin,"BANK_APPLICATION_ARCHIVED","application",app.id,data.reason.strip());db.commit()
    return {"id":app.id,"reference":app.reference,"archived":True,"archived_at":app.archived_at.isoformat()}


@router.post("/bank-admin/applications/{application_id}/restore")
def restore_application(application_id:int,data:ApplicationArchiveIn,admin:BankAdmin=Depends(current_bank_admin),db:Session=Depends(get_db)):
    bank=db.get(Bank,admin.bank_id);app=db.scalar(select(MortgageApplication).where(MortgageApplication.id==application_id,_bank_apps_cond(bank)))
    if not app or app.status=="DRAFT": raise HTTPException(404,"Submitted application not found in your bank.")
    if not app.archived_at: raise HTTPException(409,"Application is not archived.")
    app.archived_at=None;audit(db,admin,"BANK_APPLICATION_RESTORED","application",app.id,data.reason.strip());db.commit()
    return {"id":app.id,"reference":app.reference,"archived":False}

REVIEWER_INVITATION_HOURS = 48
REVIEWER_INVITATION_COOLDOWN_SECONDS = 60

def _reviewer_in_bank(row: Reviewer, bank: Bank) -> bool:
    if row.bank_id is not None:
        return row.bank_id == bank.id
    return (row.bank_code or "").strip().upper() == bank.code.strip().upper()

def _reviewer_invite_state(row: Reviewer, invitation: ReviewerInvitation | None, now: datetime) -> str:
    if invitation and invitation.used_at:
        return "ACTIVE" if row.is_active else "DEACTIVATED"
    if invitation and invitation.revoked_at:
        return "INVITATION_REVOKED"
    if invitation and (invitation.expires_at.replace(tzinfo=timezone.utc) if invitation.expires_at.tzinfo is None else invitation.expires_at) <= now:
        return "INVITATION_EXPIRED"
    if invitation:
        return "INVITATION_PENDING"
    return "ACTIVE" if row.is_active else "DEACTIVATED"

def _new_reviewer_invitation(db: Session, admin: BankAdmin, reviewer: Reviewer, bank: Bank, prior=None):
    now = datetime.now(timezone.utc)
    if prior and not prior.used_at and not prior.revoked_at:
        prior.revoked_at = now
    raw_token = secrets.token_urlsafe(36)
    invitation = ReviewerInvitation(
        reviewer_id=reviewer.id,
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        expires_at=now + timedelta(hours=REVIEWER_INVITATION_HOURS),
        created_by=admin.email,
        created_at=now,
    )
    db.add(invitation)
    db.flush()
    link = f"{settings.frontend_base_url.rstrip('/')}/reviewer?activate={quote(raw_token)}"
    send_email(
        reviewer.email,
        f"Activate your {settings.app_name} reviewer account",
        f"Hello {reviewer.full_name},\n\n{admin.full_name} invited you to join {bank.name} as a mortgage reviewer.\n\nOpen this secure, single-use link to set your password and activate your account:\n{link}\n\nThe link expires in {REVIEWER_INVITATION_HOURS} hours. If you were not expecting this invitation, you can ignore this email.",
    )
    return invitation

@router.get("/bank-admin/reviewers/summary")
def reviewer_summary(admin: BankAdmin = Depends(current_bank_admin), db: Session = Depends(get_db)):
    bank = db.get(Bank, admin.bank_id)
    reviewers = db.scalars(select(Reviewer).where(or_(Reviewer.bank_id == bank.id, and_(Reviewer.bank_id.is_(None), func.upper(func.trim(Reviewer.bank_code)) == bank.code.upper())))).all()
    invitation_rows = db.scalars(select(ReviewerInvitation).join(Reviewer, Reviewer.id == ReviewerInvitation.reviewer_id).where(or_(Reviewer.bank_id == bank.id, and_(Reviewer.bank_id.is_(None), func.upper(func.trim(Reviewer.bank_code)) == bank.code.upper()))).order_by(ReviewerInvitation.id.desc())).all()
    latest = {}
    for invitation in invitation_rows:
        latest.setdefault(invitation.reviewer_id, invitation)
    now = datetime.now(timezone.utc)
    activated = [r for r in reviewers if _reviewer_invite_state(r, latest.get(r.id), now) in {"ACTIVE", "DEACTIVATED"}]
    active = [r for r in activated if r.is_active]
    loads = {r.id: reviewer_load(db, r.id) for r in active}
    eligible = [r for r in active if r.is_available is not False and loads[r.id] < (r.max_active_assignments or 0)]
    pending = sum(1 for r in reviewers if _reviewer_invite_state(r, latest.get(r.id), now) == "INVITATION_PENDING")
    unavailable = sum(1 for r in activated if not r.is_active or r.is_available is False or reviewer_load(db, r.id) >= (r.max_active_assignments or 0))
    return {
        "total_reviewers": len(activated),
        "available_assignment_capacity": sum(max(0, (r.max_active_assignments or 0) - loads[r.id]) for r in eligible),
        "pending_invitations": pending,
        "unavailable_reviewers": unavailable,
        "definitions": {
            "total_reviewers": "Activated reviewer accounts, including deactivated accounts; pending invitations are excluded.",
            "available_assignment_capacity": "Open slots across active, available reviewers, calculated from active unfinished assignments.",
            "pending_invitations": "Unused, unrevoked invitations that have not expired.",
            "unavailable_reviewers": "Activated reviewers that are deactivated, marked unavailable, or at capacity.",
        },
    }

@router.get("/bank-admin/reviewers")
def reviewers(admin: BankAdmin = Depends(current_bank_admin), db: Session = Depends(get_db)):
    bank = db.get(Bank, admin.bank_id)
    rows = db.scalars(select(Reviewer).where(or_(Reviewer.bank_id == bank.id, and_(Reviewer.bank_id.is_(None), func.upper(func.trim(Reviewer.bank_code)) == bank.code.upper()))).order_by(func.lower(Reviewer.full_name), Reviewer.id)).all()
    invitation_rows = db.scalars(select(ReviewerInvitation).join(Reviewer, Reviewer.id == ReviewerInvitation.reviewer_id).where(or_(Reviewer.bank_id == bank.id, and_(Reviewer.bank_id.is_(None), func.upper(func.trim(Reviewer.bank_code)) == bank.code.upper()))).order_by(ReviewerInvitation.id.desc())).all()
    latest = {}
    for invitation in invitation_rows:
        latest.setdefault(invitation.reviewer_id, invitation)
    now = datetime.now(timezone.utc)
    result = []
    for row in rows:
        load = reviewer_load(db, row.id)
        state = _reviewer_invite_state(row, latest.get(row.id), now)
        available = state == "ACTIVE" and row.is_active and row.is_available is not False and load < (row.max_active_assignments or 0)
        reason = "Invitation pending" if state == "INVITATION_PENDING" else "Invitation expired" if state == "INVITATION_EXPIRED" else "Invitation revoked" if state == "INVITATION_REVOKED" else "Reviewer deactivated" if not row.is_active else "Reviewer unavailable" if row.is_available is False else "Capacity reached" if load >= (row.max_active_assignments or 0) else "Eligible for assignment"
        result.append({"id":row.id,"full_name":row.full_name,"email":row.email,"is_active":row.is_active,"account_status":state,"specialisation":row.specialisation,"max_active_assignments":row.max_active_assignments,"is_available":row.is_available is not False,"eligible":available,"eligibility_reason":reason,"last_assigned_at":row.last_assigned_at.isoformat() if row.last_assigned_at else None,"created_at":row.created_at.isoformat() if row.created_at else None,"invited_at":latest[row.id].created_at.isoformat() if row.id in latest else None,"activated_at":latest[row.id].used_at.isoformat() if row.id in latest and latest[row.id].used_at else None,"active_assignments":load,"remaining_capacity":max(0,(row.max_active_assignments or 0)-load)})
    return result

@router.get("/bank-admin/reviewers/{reviewer_id}")
def reviewer_profile(reviewer_id:int, admin:BankAdmin=Depends(current_bank_admin), db:Session=Depends(get_db)):
    bank=db.get(Bank,admin.bank_id); row=db.get(Reviewer,reviewer_id)
    if not row or not _reviewer_in_bank(row,bank): raise HTTPException(404,"Reviewer not found in your bank.")
    invitation=db.scalar(select(ReviewerInvitation).where(ReviewerInvitation.reviewer_id==row.id).order_by(ReviewerInvitation.id.desc()))
    now=datetime.now(timezone.utc); state=_reviewer_invite_state(row,invitation,now); load=reviewer_load(db,row.id)
    if state=="INVITATION_PENDING": reason="Invitation pending"
    elif state=="INVITATION_EXPIRED": reason="Invitation expired"
    elif state=="INVITATION_REVOKED": reason="Invitation revoked"
    elif not row.is_active: reason="Reviewer deactivated"
    elif row.is_available is False: reason="Reviewer marked unavailable"
    elif load >= (row.max_active_assignments or 0): reason="Capacity reached"
    else: reason="Eligible for assignment"
    assignments=db.execute(select(ReviewAssignment, MortgageApplication).join(MortgageApplication, MortgageApplication.id==ReviewAssignment.application_id).where(ReviewAssignment.reviewer_id==row.id,ReviewAssignment.active.is_(True)).order_by(ReviewAssignment.assigned_at.desc()).limit(100)).all()
    review_events=db.execute(select(ReviewEvent, MortgageApplication.reference, MortgageApplication.status).join(MortgageApplication,MortgageApplication.id==ReviewEvent.application_id).where(ReviewEvent.reviewer_id==row.id).order_by(ReviewEvent.created_at.desc(),ReviewEvent.id.desc()).limit(100)).all()
    audit_rows=db.scalars(select(AuditLog).where(AuditLog.resource_type=="reviewer",AuditLog.resource_id==str(row.id),AuditLog.action.like("REVIEWER_%")).order_by(AuditLog.created_at.desc(),AuditLog.id.desc()).limit(100)).all()
    completed=db.scalar(select(func.count()).select_from(ReviewEvent).where(ReviewEvent.reviewer_id==row.id,ReviewEvent.event_type.in_(["COMPLETE","COMPLETED"]))) or 0
    return {
        "profile":{"id":row.id,"full_name":row.full_name,"email":row.email,"bank_name":bank.name,"bank_code":bank.code,"specialisation":row.specialisation,"account_status":state,"is_active":row.is_active,"is_available":row.is_available is not False,"created_at":row.created_at.isoformat() if row.created_at else None,"invited_at":invitation.created_at.isoformat() if invitation else None,"activated_at":invitation.used_at.isoformat() if invitation and invitation.used_at else None,"eligibility_reason":reason},
        "workload":{"active_assignments":load,"max_active_assignments":row.max_active_assignments,"remaining_capacity":max(0,(row.max_active_assignments or 0)-load),"eligible":state=="ACTIVE" and row.is_active and row.is_available is not False and load<(row.max_active_assignments or 0)},
        "analytics":{"completed_reviews":completed,"active_assignments":load,"period":"Available retained review events; no fixed reporting window is configured.","note":"Completed reviews are counted from recorded COMPLETE review events. Quality scores and turnaround targets are not configured."},
        "assigned_applications":[{"id":app.id,"reference":app.reference,"product_name":app.product_name,"status":status_label(app.status,app.awaiting_assignment),"assigned_at":assignment.assigned_at.isoformat() if assignment.assigned_at else None,"requested_loan":app.requested_loan} for assignment,app in assignments],
        "review_history":[{"id":event.id,"event_type":event.event_type,"application_reference":reference,"application_status":status_label(status),"created_at":event.created_at.isoformat() if event.created_at else None} for event,reference,status in review_events],
        "administrative_activity":[{"action":audit.action,"actor":audit.actor_email,"created_at":audit.created_at.isoformat() if audit.created_at else None,"detail":audit.detail} for audit in audit_rows],
    }

@router.post("/bank-admin/reviewers", status_code=201)
def create_reviewer(data: ReviewerIn, admin: BankAdmin = Depends(current_bank_admin), db: Session = Depends(get_db)):
    bank = db.get(Bank, admin.bank_id)
    email = str(data.email).strip().casefold()
    recent = db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.actor_email == admin.email, AuditLog.action.in_(["REVIEWER_INVITATION_CREATED", "REVIEWER_INVITATION_RESENT"]), AuditLog.created_at >= datetime.now(timezone.utc) - timedelta(minutes=15))) or 0
    if recent >= 20: raise HTTPException(429, "Reviewer invitation limit reached. Try again later.")
    if db.scalar(select(Reviewer.id).where(func.lower(Reviewer.email) == email)):
        raise HTTPException(409, "A reviewer with this email already exists.")
    # An independently generated password is hashed and discarded; only the invitee sets a usable password.
    row = Reviewer(full_name=data.full_name.strip(), email=email, password_hash=hash_password(secrets.token_urlsafe(48)), bank_code=bank.code, bank_id=bank.id, is_active=False, specialisation=data.specialisation, max_active_assignments=data.max_active_assignments)
    db.add(row)
    db.flush()
    try:
        invitation = _new_reviewer_invitation(db, admin, row, bank)
        audit(db, admin, "REVIEWER_INVITATION_CREATED", "reviewer", row.id, f"bank={bank.code}; invitation_id={invitation.id}; delivery=EMAIL_SENT")
        db.commit()
    except Exception as exc:
        db.rollback()
        db.add(AuditLog(actor_email=admin.email, actor_role="BANK_ADMIN", action="REVIEWER_INVITATION_DELIVERY_FAILED", resource_type="reviewer", resource_id="", detail=f"bank={bank.code}; delivery failure={type(exc).__name__}"))
        db.commit()
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(503, "Reviewer invitation could not be delivered. Confirm email service settings and try again.") from exc
    return {"id":row.id,"full_name":row.full_name,"email":row.email,"account_status":"INVITATION_PENDING","specialisation":row.specialisation,"max_active_assignments":row.max_active_assignments,"invitation_expires_at":invitation.expires_at.isoformat(),"delivery":"EMAIL_SENT"}

@router.post("/bank-admin/reviewers/{reviewer_id}/resend-invitation")
def resend_reviewer_invitation(reviewer_id:int, admin:BankAdmin=Depends(current_bank_admin), db:Session=Depends(get_db)):
    bank=db.get(Bank,admin.bank_id); row=db.get(Reviewer,reviewer_id)
    if not row or not _reviewer_in_bank(row,bank): raise HTTPException(404,"Reviewer not found in your bank.")
    if row.is_active: raise HTTPException(409,"An activated reviewer does not have a pending invitation.")
    previous=db.scalar(select(ReviewerInvitation).where(ReviewerInvitation.reviewer_id==row.id).order_by(ReviewerInvitation.id.desc()))
    if previous and previous.used_at: raise HTTPException(409,"This reviewer has already activated the account. Reactivate the account instead.")
    if previous:
        created=previous.created_at.replace(tzinfo=timezone.utc) if previous.created_at.tzinfo is None else previous.created_at
        remaining=REVIEWER_INVITATION_COOLDOWN_SECONDS-int((datetime.now(timezone.utc)-created).total_seconds())
        if remaining>0: raise HTTPException(429,f"Please wait {remaining} seconds before resending this invitation.")
    try:
        invitation=_new_reviewer_invitation(db,admin,row,bank,previous)
        audit(db,admin,"REVIEWER_INVITATION_RESENT","reviewer",row.id,f"bank={bank.code}; invitation_id={invitation.id}; delivery=EMAIL_SENT")
        db.commit()
    except Exception as exc:
        db.rollback()
        db.add(AuditLog(actor_email=admin.email,actor_role="BANK_ADMIN",action="REVIEWER_INVITATION_DELIVERY_FAILED",resource_type="reviewer",resource_id=str(reviewer_id),detail=f"bank={bank.code}; delivery failure={type(exc).__name__}"))
        db.commit()
        if isinstance(exc,HTTPException): raise
        raise HTTPException(503,"Reviewer invitation could not be delivered. The previous invitation remains valid; confirm email service settings and try again.") from exc
    return {"id":row.id,"account_status":"INVITATION_PENDING","invitation_expires_at":invitation.expires_at.isoformat(),"delivery":"EMAIL_SENT"}

@router.post("/bank-admin/reviewers/{reviewer_id}/revoke-invitation")
def revoke_reviewer_invitation(reviewer_id:int, admin:BankAdmin=Depends(current_bank_admin), db:Session=Depends(get_db)):
    bank=db.get(Bank,admin.bank_id); row=db.get(Reviewer,reviewer_id)
    if not row or not _reviewer_in_bank(row,bank): raise HTTPException(404,"Reviewer not found in your bank.")
    invitation=db.scalar(select(ReviewerInvitation).where(ReviewerInvitation.reviewer_id==row.id).order_by(ReviewerInvitation.id.desc()))
    if row.is_active or not invitation or invitation.used_at or invitation.revoked_at: raise HTTPException(409,"This reviewer does not have a revocable pending invitation.")
    invitation.revoked_at=datetime.now(timezone.utc)
    audit(db,admin,"REVIEWER_INVITATION_REVOKED","reviewer",row.id,f"bank={bank.code}; invitation_id={invitation.id}")
    db.commit()
    return {"id":row.id,"account_status":"INVITATION_REVOKED"}

@router.post("/reviewer/accept-invitation")
def activate_reviewer(data:ReviewerActivationIn, db:Session=Depends(get_db)):
    token_hash=hashlib.sha256(data.token.encode()).hexdigest(); lock_key="reviewer-activation:"+token_hash
    if is_locked(lock_key): raise HTTPException(429,"Too many activation attempts. Request a new invitation.")
    invitation=db.scalar(select(ReviewerInvitation).where(ReviewerInvitation.token_hash==token_hash))
    now=datetime.now(timezone.utc)
    if not invitation or invitation.used_at or invitation.revoked_at or (invitation.expires_at.replace(tzinfo=timezone.utc) if invitation.expires_at.tzinfo is None else invitation.expires_at)<=now:
        note_failure(lock_key)
        if invitation and not invitation.used_at and not invitation.revoked_at:
            invitation.revoked_at=now;db.commit()
        raise HTTPException(400,"This reviewer invitation is invalid, expired, revoked or already used. Request a new invitation.")
    changed=db.execute(update(ReviewerInvitation).where(ReviewerInvitation.id==invitation.id,ReviewerInvitation.used_at.is_(None),ReviewerInvitation.revoked_at.is_(None),ReviewerInvitation.expires_at>now).values(used_at=now).execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        db.rollback();note_failure(lock_key);raise HTTPException(400,"This reviewer invitation is invalid, expired, revoked or already used. Request a new invitation.")
    row=db.get(Reviewer,invitation.reviewer_id)
    if not row:
        db.rollback();raise HTTPException(400,"This reviewer invitation is invalid, expired, revoked or already used. Request a new invitation.")
    row.password_hash=hash_password(data.password);row.is_active=True
    bank=db.get(Bank,row.bank_id) if row.bank_id else db.scalar(select(Bank).where(func.upper(Bank.code)==(row.bank_code or "").strip().upper()))
    db.add(AuditLog(actor_email=row.email,actor_role="REVIEWER",action="REVIEWER_ACTIVATED",resource_type="reviewer",resource_id=str(row.id),detail=f"bank={bank.code if bank else row.bank_code}; invitation_id={invitation.id}"))
    if bank and bank.status == "APPROVED": retry_pending_assignments(db,bank_code=bank.code,bank_id=bank.id)
    clear_failures(lock_key)
    db.commit()
    return {"message":"Reviewer account activated. You can now sign in.","email":row.email}

@router.patch("/bank-admin/reviewers/{reviewer_id}")
def update_reviewer(reviewer_id:int,data:ReviewerUpdateIn,admin:BankAdmin=Depends(current_bank_admin),db:Session=Depends(get_db)):
    bank=db.get(Bank,admin.bank_id); row=db.get(Reviewer,reviewer_id)
    if not row or not (row.bank_id==bank.id or (row.bank_id is None and row.bank_code.strip().upper()==bank.code.upper())): raise HTTPException(404,"Reviewer not found in your bank.")
    email=str(data.email).strip().casefold()
    if db.scalar(select(Reviewer.id).where(func.lower(Reviewer.email)==email,Reviewer.id!=row.id)): raise HTTPException(409,"A reviewer with this email already exists.")
    if email != (row.email or "").strip().casefold() and not row.is_active:
        pending=db.scalar(select(ReviewerInvitation).where(ReviewerInvitation.reviewer_id==row.id,ReviewerInvitation.used_at.is_(None),ReviewerInvitation.revoked_at.is_(None)).order_by(ReviewerInvitation.id.desc()))
        if pending:
            pending.revoked_at=datetime.now(timezone.utc)
            audit(db,admin,"REVIEWER_INVITATION_REVOKED","reviewer",row.id,f"bank={bank.code}; reason=recipient email changed; {data.reason.strip()}")
    load=reviewer_load(db,row.id)
    if data.max_active_assignments<load: raise HTTPException(409,f"Workload limit cannot be lower than the current {load} active assignments.")
    row.full_name=data.full_name.strip();row.email=email;row.specialisation=data.specialisation;row.max_active_assignments=data.max_active_assignments
    audit(db,admin,"REVIEWER_DETAILS_UPDATED","reviewer",row.id,f"bank={bank.code}; reason={data.reason.strip()}")
    db.commit()
    return {"id":row.id,"full_name":row.full_name,"email":row.email,"is_active":row.is_active,"is_available":row.is_available is not False,"specialisation":row.specialisation,"active_assignments":load,"max_active_assignments":row.max_active_assignments}

@router.patch("/bank-admin/reviewers/{reviewer_id}/active")
def toggle_reviewer(reviewer_id: int, active: bool, reason:str="", admin: BankAdmin = Depends(current_bank_admin), db: Session = Depends(get_db)):
    bank=db.get(Bank,admin.bank_id); row=db.get(Reviewer,reviewer_id)
    if not row or not (row.bank_id == bank.id or (row.bank_id is None and row.bank_code.strip().upper() == bank.code.upper())): raise HTTPException(404,"Reviewer not found in your bank.")
    if len(reason.strip())<8: raise HTTPException(422,"A reason of at least 8 characters is required for reviewer status changes.")
    if active:
        invitation=db.scalar(select(ReviewerInvitation).where(ReviewerInvitation.reviewer_id==row.id).order_by(ReviewerInvitation.id.desc()))
        if invitation and not invitation.used_at: raise HTTPException(409,"The reviewer must activate their invitation before their account can be reactivated.")
    row.is_active=active
    db.flush()
    if active:
        retry_pending_assignments(db,bank_code=bank.code,bank_id=bank.id)
    else:
        release_reviewer_assignments(db,row,"Previous reviewer was deactivated; automatic reassignment initiated.")
        retry_pending_assignments(db,bank_code=bank.code,bank_id=bank.id)
    audit(db,admin,"REVIEWER_ACTIVATED" if active else "REVIEWER_SUSPENDED","reviewer",row.id,reason.strip()); db.commit()
    return {"id":row.id,"is_active":row.is_active}


@router.get("/bank-admin/policies")
def list_bank_policies(admin: BankAdmin = Depends(current_bank_admin), db: Session = Depends(get_db)):
    rows=db.scalars(select(PolicyDocument).where(PolicyDocument.bank_id==admin.bank_id).order_by(PolicyDocument.created_at.desc())).all()
    policy_ids=[p.id for p in rows]
    chunks=db.scalars(select(PolicyChunk).where(PolicyChunk.policy_id.in_(policy_ids))).all() if policy_ids else []
    chunks_by_policy={}
    for chunk in chunks: chunks_by_policy.setdefault(chunk.policy_id,[]).append(chunk)
    result=[]
    for p in rows:
        policy_chunks=chunks_by_policy.get(p.id,[])
        internal_chunks=_page_chunks(p.content) if p.active else []
        customer_chunks=_page_chunks(p.customer_summary) if p.active and p.customer_visible else []
        internal_expected=len(internal_chunks)
        customer_expected=len(customer_chunks)
        internal_actual=sum(chunk.audience=="INTERNAL" for chunk in policy_chunks)
        customer_actual=sum(chunk.audience=="CUSTOMER" for chunk in policy_chunks)
        internal_rows=sorted((chunk for chunk in policy_chunks if chunk.audience=="INTERNAL"),key=lambda chunk:chunk.chunk_index)
        customer_rows=sorted((chunk for chunk in policy_chunks if chunk.audience=="CUSTOMER"),key=lambda chunk:chunk.chunk_index)
        internal_match=len(internal_rows)==internal_expected and all((row.page_number,row.text)==expected for row,expected in zip(internal_rows,internal_chunks))
        customer_match=len(customer_rows)==customer_expected and all((row.page_number,row.text)==expected for row,expected in zip(customer_rows,customer_chunks))
        expected=internal_expected+customer_expected
        actual=internal_actual+customer_actual
        indexing_state="ARCHIVED" if not p.active else "NOT_SEARCHABLE" if not expected else "COMPLETED" if internal_match and customer_match and actual==expected else "INCOMPLETE"
        embedded=sum(bool(chunk.embedding_json) for chunk in policy_chunks)
        embedding_state="NOT_APPLICABLE" if not expected else "NOT_CONFIGURED" if not settings.nvidia_api_key.strip() else "COMPLETED" if embedded==expected else "PARTIAL" if embedded else "UNAVAILABLE"
        customer_state="INACTIVE" if not p.active else "INTERNAL_ONLY" if not p.customer_visible else "SUMMARY_MISSING" if not customer_expected else "INDEXING_INCOMPLETE" if not customer_match else "AVAILABLE"
        result.append({"id":p.id,"title":p.title,"policy_version":p.policy_version,"category":p.category,"content":p.content,"active":p.active,"customer_visible":p.customer_visible,"customer_summary":p.customer_summary,"source_filename":p.source_filename,"has_source_pdf":bool(p.stored_filename),"created_by":p.created_by,"created_at":p.created_at.isoformat(),"text_status":"TEXT_SAVED" if (p.content or "").strip() else "NO_TEXT_SAVED","indexing_status":indexing_state,"indexed_chunks":actual,"expected_chunks":expected,"embedding_status":embedding_state,"customer_availability":customer_state,"customer_chunks":customer_actual})
    return result

def _policy_pdf_bytes(filename: str | None, content_type: str | None, data: bytes) -> str:
    safe_name=Path(filename or "policy.pdf").name[:255]
    if Path(safe_name).suffix.casefold()!=".pdf":
        raise HTTPException(415,"Upload a PDF policy file.")
    if content_type and content_type not in {"application/pdf","application/octet-stream"}:
        raise HTTPException(415,"The uploaded file must be a PDF.")
    limit=settings.max_upload_size_mb*1024*1024
    if not data: raise HTTPException(400,"The uploaded PDF is empty.")
    if len(data)>limit: raise HTTPException(413,f"Policy PDF exceeds the {settings.max_upload_size_mb} MB upload limit.")
    if not data.startswith(b"%PDF"):
        raise HTTPException(415,"The uploaded file does not have a valid PDF signature.")
    return safe_name

def _verify_policy_pdf(data: bytes) -> None:
    try:
        import fitz
        document=fitz.open(stream=data,filetype="pdf")
        try:
            if document.needs_pass:
                raise HTTPException(422,"Password-protected PDFs are not supported. Upload an unencrypted policy PDF.")
            if document.page_count<1:
                raise HTTPException(422,"The PDF contains no pages.")
        finally:
            document.close()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(422,"The PDF is malformed or unreadable. Verify it opens correctly, then retry.")

@router.post("/bank-admin/policies/extract")
async def extract_bank_policy_pdf(file: UploadFile = File(...), admin: BankAdmin = Depends(current_bank_admin)):
    data=await file.read(settings.max_upload_size_mb*1024*1024+1)
    filename=_policy_pdf_bytes(file.filename,file.content_type,data)
    _verify_policy_pdf(data)
    digest=hashlib.sha256(data).hexdigest()
    with tempfile.TemporaryDirectory(prefix="bank-policy-extract-") as temp_dir:
        path=Path(temp_dir)/"policy.pdf"
        path.write_bytes(data)
        text,status,message=await run_in_threadpool(extract_text,path)
    if status=="FAILED":
        status="NEEDS_REVIEW"
        message="Text extraction failed. Confirm this is an unencrypted, readable PDF and retry."
    return {"filename":filename,"extraction_digest":digest,"extraction_status":status,"extraction_message":message,"extracted_text":text,"page_count":len(re.findall(r"(?m)^\[PAGE \d+\]$",text))}

def _supersede_bank_policy_versions(db: Session, admin: BankAdmin, title: str) -> None:
    for old in db.scalars(select(PolicyDocument).where(PolicyDocument.bank_id==admin.bank_id,PolicyDocument.title==title,PolicyDocument.active.is_(True))).all():
        old.active=False
        db.execute(delete(PolicyChunk).where(PolicyChunk.policy_id==old.id))

async def _save_bank_policy(data: BankPolicyIn, admin: BankAdmin, db: Session, source_filename: str | None = None, stored_filename: str | None = None):
    existing=db.scalar(select(PolicyDocument).where(PolicyDocument.bank_id==admin.bank_id,PolicyDocument.title==data.title,PolicyDocument.policy_version==data.policy_version))
    if existing:
        if stored_filename: (_policy_pdf_dir()/stored_filename).unlink(missing_ok=True)
        raise HTTPException(409,"This policy version already exists for your bank.")
    if data.active:
        _supersede_bank_policy_versions(db,admin,data.title)
    row=PolicyDocument(bank_id=admin.bank_id,title=data.title,policy_version=data.policy_version,category=data.category,content=data.content,active=data.active,customer_visible=data.customer_visible,customer_summary=data.customer_summary.strip(),created_by=admin.email,source_filename=source_filename,stored_filename=stored_filename)
    db.add(row)
    try:
        db.flush()
        db.add(AuditLog(actor_email=admin.email,actor_role="BANK_ADMIN",action="BANK_POLICY_CREATED",resource_type="policy",resource_id=str(row.id),detail=f"bank_id={admin.bank_id}; version={row.policy_version}; source_pdf={bool(stored_filename)}"))
        db.commit();db.refresh(row)
    except Exception:
        db.rollback()
        if stored_filename:
            (_policy_pdf_dir()/stored_filename).unlink(missing_ok=True)
        raise
    indexing=await index_policy(db,row)
    return {"id":row.id,"title":row.title,"policy_version":row.policy_version,"bank_id":admin.bank_id,"active":row.active,"customer_visible":row.customer_visible,"source_filename":row.source_filename,"indexing":indexing}

def _policy_pdf_dir() -> Path:
    return Path(settings.uploads_dir).resolve()/"policy_pdfs"

@router.post("/bank-admin/policies/qa")
async def bank_policy_qa(data:BankPolicyQuestionIn,admin:BankAdmin=Depends(current_bank_admin),db:Session=Depends(get_db)):
    try:
        validate_ai_request(data.question,"policy_question")
        sources,method=await retrieve_hybrid(db,data.question,limit=5,bank_id=admin.bank_id)
        result=await answer_policy_question(data.question,sources)
    except NVIDIAInputRejected as e:
        raise HTTPException(422,str(e))
    except NVIDIAConfigurationError as e:
        raise HTTPException(503,str(e))
    except Exception as error:
        logger.error("Bank policy Q&A failed (%s).", type(error).__name__)
        raise HTTPException(502,"Bank policy Q&A is temporarily unavailable. Please retry.")
    result["retrieval_method"]=method
    result["sources_retrieved"]=len(sources)
    result["retrieval_status"]="RETRIEVED" if sources else "FAILED" if "embedding_failed" in method else "NO_RELEVANT_EVIDENCE"
    return result

@router.post("/bank-admin/policies",status_code=201)
async def create_bank_policy(data: BankPolicyIn, admin: BankAdmin = Depends(current_bank_admin), db: Session = Depends(get_db)):
    return await _save_bank_policy(data,admin,db)

@router.post("/bank-admin/policies/from-pdf",status_code=201)
async def create_bank_policy_from_pdf(
    title:str=Form(...),policy_version:str=Form(...),category:str=Form(...),content:str=Form(...),
    active:bool=Form(True),customer_visible:bool=Form(False),customer_summary:str=Form(""),
    extraction_digest:str=Form(...),file:UploadFile=File(...),
    admin:BankAdmin=Depends(current_bank_admin),db:Session=Depends(get_db),
):
    data_bytes=await file.read(settings.max_upload_size_mb*1024*1024+1)
    source_filename=_policy_pdf_bytes(file.filename,file.content_type,data_bytes)
    _verify_policy_pdf(data_bytes)
    actual_digest=hashlib.sha256(data_bytes).hexdigest()
    if not re.fullmatch(r"[a-fA-F0-9]{64}",extraction_digest) or not secrets.compare_digest(actual_digest,extraction_digest.casefold()):
        raise HTTPException(409,"The selected PDF changed after text extraction. Upload it again before saving.")
    try:
        policy_data=BankPolicyIn(title=title.strip(),policy_version=policy_version.strip(),category=category.strip(),content=content,active=active,customer_visible=customer_visible,customer_summary=customer_summary)
    except ValidationError as error:
        raise HTTPException(422,error.errors())
    directory=_policy_pdf_dir();directory.mkdir(parents=True,exist_ok=True)
    stored_filename=secrets.token_hex(16)+".pdf"
    (directory/stored_filename).write_bytes(data_bytes)
    return await _save_bank_policy(policy_data,admin,db,source_filename,stored_filename)

@router.get("/bank-admin/policies/{policy_id}/file")
def download_bank_policy_pdf(policy_id:int,admin:BankAdmin=Depends(current_bank_admin),db:Session=Depends(get_db)):
    policy=db.scalar(select(PolicyDocument).where(PolicyDocument.id==policy_id,PolicyDocument.bank_id==admin.bank_id))
    if not policy or not policy.stored_filename: raise HTTPException(404,"Policy PDF not found for this bank.")
    directory=_policy_pdf_dir();path=(directory/policy.stored_filename).resolve()
    if directory not in path.parents or not path.is_file(): raise HTTPException(404,"Policy PDF is unavailable.")
    return FileResponse(path,media_type="application/pdf",filename=policy.source_filename or "policy.pdf",headers={"X-Content-Type-Options":"nosniff","Cache-Control":"private, no-store","Content-Security-Policy":"default-src 'none'"})

@router.patch("/bank-admin/policies/{policy_id}/active")
async def toggle_bank_policy(policy_id:int,active:bool,admin:BankAdmin=Depends(current_bank_admin),db:Session=Depends(get_db)):
    row=db.scalar(select(PolicyDocument).where(PolicyDocument.id==policy_id,PolicyDocument.bank_id==admin.bank_id))
    if not row: raise HTTPException(404,"Policy not found in your bank.")
    row.active=active;db.add(AuditLog(actor_email=admin.email,actor_role="BANK_ADMIN",action="BANK_POLICY_ACTIVATED" if active else "BANK_POLICY_ARCHIVED",resource_type="policy",resource_id=str(row.id),detail=f"bank_id={admin.bank_id}"));db.commit()
    indexing=await index_policy(db,row)
    return {"id":row.id,"active":row.active,"indexing":indexing}

@router.post("/bank-admin/policies/{policy_id}/reindex")
async def reindex_bank_policy(policy_id:int,admin:BankAdmin=Depends(current_bank_admin),db:Session=Depends(get_db)):
    row=db.scalar(select(PolicyDocument).where(PolicyDocument.id==policy_id,PolicyDocument.bank_id==admin.bank_id))
    if not row: raise HTTPException(404,"Policy not found in your bank.")
    if not row.active: raise HTTPException(409,"Activate this policy version before rebuilding its retrieval index.")
    indexing=await index_policy(db,row)
    db.add(AuditLog(actor_email=admin.email,actor_role="BANK_ADMIN",action="BANK_POLICY_REINDEXED",resource_type="policy",resource_id=str(row.id),detail=f"chunks={indexing.get('chunks',0)}; customer_chunks={indexing.get('customer_summary_chunks',0)}; embedding_error={indexing.get('error') or 'none'}"))
    db.commit()
    return {"id":row.id,"indexing":indexing}

@router.post("/bank-admin/policies/{policy_id}/customer-versions",status_code=201)
async def publish_customer_policy_version(policy_id:int,data:CustomerPolicyVersionIn,admin:BankAdmin=Depends(current_bank_admin),db:Session=Depends(get_db)):
    source=db.scalar(select(PolicyDocument).where(PolicyDocument.id==policy_id,PolicyDocument.bank_id==admin.bank_id))
    if not source: raise HTTPException(404,"Policy not found in your bank.")
    if not source.active: raise HTTPException(409,"Activate the source policy before publishing a customer-safe version.")
    if not (source.content or "").strip(): raise HTTPException(409,"This policy has no saved source text to publish.")
    existing=db.scalar(select(PolicyDocument).where(PolicyDocument.bank_id==admin.bank_id,PolicyDocument.title==data.title.strip(),PolicyDocument.policy_version==data.policy_version.strip()))
    if existing: raise HTTPException(409,"This policy title and version already exist for your bank.")
    if db.scalar(select(PolicyDocument.id).where(PolicyDocument.bank_id==admin.bank_id,PolicyDocument.title==data.title.strip(),PolicyDocument.active.is_(True))):
        _supersede_bank_policy_versions(db,admin,data.title.strip())
    published=PolicyDocument(bank_id=admin.bank_id,title=data.title.strip(),policy_version=data.policy_version.strip(),category=data.category.strip(),content=source.content,active=True,customer_visible=True,customer_summary=data.customer_summary.strip(),created_by=admin.email,source_filename=source.source_filename,stored_filename=source.stored_filename)
    db.add(published)
    try:
        db.flush()
        db.add(AuditLog(actor_email=admin.email,actor_role="BANK_ADMIN",action="BANK_CUSTOMER_POLICY_VERSION_PUBLISHED",resource_type="policy",resource_id=str(published.id),detail=f"source_policy_id={source.id}; version={published.policy_version}; source_pdf={bool(published.stored_filename)}"))
        db.commit();db.refresh(published)
    except Exception:
        db.rollback()
        raise
    indexing=await index_policy(db,published)
    return {"id":published.id,"title":published.title,"policy_version":published.policy_version,"active":published.active,"customer_visible":published.customer_visible,"source_filename":published.source_filename,"indexing":indexing}


@router.get("/bank-admin/bank")
def get_bank_profile(admin:BankAdmin=Depends(current_bank_admin),db:Session=Depends(get_db)):
    bank=db.get(Bank,admin.bank_id)
    return {"id":bank.id,"name":bank.name,"code":bank.code,"status":bank.status,"contact_email":bank.contact_email}

@router.patch("/bank-admin/bank")
def update_bank_profile(data:BankProfileUpdate,admin:BankAdmin=Depends(current_bank_admin),db:Session=Depends(get_db)):
    bank=db.get(Bank,admin.bank_id); bank.contact_email=data.contact_email.lower().strip()
    audit(db,admin,"BANK_PROFILE_UPDATED","bank",bank.id,"contact email updated")
    db.commit()
    return {"id":bank.id,"name":bank.name,"code":bank.code,"status":bank.status,"contact_email":bank.contact_email}
