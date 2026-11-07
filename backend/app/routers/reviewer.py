from datetime import datetime, timezone
import json
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import ReviewerNotification, Reviewer, MortgageApplication, ApplicationDocument, ReviewAssignment, ReviewEvent, Customer, PolicyDocument, Bank, CustomerNotification
from app.security import verify_password, token_for, token_subject, hash_password, needs_rehash
from app.dependencies import current_customer
from app.services.policy_rag import retrieve_hybrid
from app.services.audit import record
from app.services.assignment import retry_pending_assignments, reviewer_load, status_label
from app.services.scenario_runner import run_for_application
from app.schemas import ScenarioIn
from app.routers.documents import file_response, _analysis_state
from app.security import is_locked,note_failure,clear_failures
from app.services.nvidia import answer_policy_question, NVIDIAConfigurationError, NVIDIAInputRejected, validate_ai_request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/reviewer", tags=["Reviewer workflow"])
bearer = HTTPBearer(auto_error=False)
class LoginIn(BaseModel):
    email: str
    password: str
class ActionIn(BaseModel):
    action: str = Field(pattern="^(start_review|request_documents|add_note|escalate|recommend_approve|recommend_decline|complete)$")
    note: str = Field(default="", max_length=5000)


def current_reviewer(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)):
    if not credentials:
        raise HTTPException(401, "Reviewer authentication required.")
    sub = token_subject(credentials.credentials)
    if not sub or not sub.startswith("reviewer:"):
        raise HTTPException(401, "A reviewer access token is required.")
    try: rid = int(sub.split(":", 1)[1])
    except ValueError: raise HTTPException(401, "Invalid reviewer token.")
    reviewer = db.get(Reviewer, rid)
    if not reviewer or not reviewer.is_active:
        raise HTTPException(401, "Reviewer account is inactive or unavailable.")
    return reviewer

def _bank_for_application(db, app):
    if app.bank_id is not None:
        return db.get(Bank, app.bank_id)
    lender = (app.lender_name or "").strip()
    if not lender:
        return None
    return db.scalar(select(Bank).where((Bank.code == lender.upper()) | (Bank.name == lender)))

def _reviewer_can_access_application(db, app, reviewer):
    app_bank = _bank_for_application(db, app)
    if app.bank_id is not None and app_bank is None:
        return False
    reviewer_bank = db.get(Bank, reviewer.bank_id) if reviewer.bank_id is not None else db.scalar(select(Bank).where(Bank.code == (reviewer.bank_code or "").strip().upper()))
    if reviewer.bank_id is not None and reviewer_bank is None:
        return False
    if app_bank is not None:
        if app_bank.status != "APPROVED":
            return False
        if reviewer_bank is not None:
            return reviewer_bank.id == app_bank.id
        # Legacy reviewers without bank_id may only match by exact bank code.
        return (reviewer.bank_code or "").strip().upper() == app_bank.code.upper()
    # Unknown/legacy lender: require an exact code match and never allow a populated bank_id to bypass it.
    return reviewer.bank_id is None and (reviewer.bank_code or "").strip().upper() == (app.lender_name or "").strip().upper()

def assigned(db, aid, reviewer):
    row = db.scalar(select(ReviewAssignment).where(ReviewAssignment.application_id == aid, ReviewAssignment.reviewer_id == reviewer.id, ReviewAssignment.active == True))
    if not row: raise HTTPException(404, "Application is not assigned to this reviewer.")
    app = db.get(MortgageApplication, aid)
    if not app: raise HTTPException(404, "Application not found.")
    if not _reviewer_can_access_application(db, app, reviewer):
        raise HTTPException(404, "Application is not available to this reviewer's bank.")
    return app

KYC_CATEGORY = "KYC"

def kyc_summary(app, docs):
    kyc_docs = [d for d in docs if d.category == KYC_CATEGORY]
    return {"status": app.kyc_status or "PENDING", "verified_by": app.kyc_verified_by, "verified_at": app.kyc_verified_at.isoformat() if app.kyc_verified_at else None, "note": app.kyc_note or "",
            "kyc_documents": len(kyc_docs), "kyc_documents_verified": sum(1 for d in kyc_docs if d.verification_status == "VERIFIED"),
            "attestation": "Reviewer-attested checklist; no external identity-verification service is integrated."}

def _json_value(value, default):
    try:
        return json.loads(value or "")
    except (TypeError, ValueError):
        return default

def summary(db, app):
    customer = db.get(Customer, app.customer_id)
    docs = db.scalars(select(ApplicationDocument).where(ApplicationDocument.application_id == app.id).order_by(ApplicationDocument.created_at.desc())).all()
    details = {}
    details = _json_value(getattr(app, "form_data_json", "{}"), {})
    if not isinstance(details, dict):
        details = {}
    # Never return legacy account numbers to reviewer clients; only a masked suffix is allowed.
    bank_details = details.get("bank") if isinstance(details.get("bank"), dict) else {}
    if bank_details.get("account_number"):
        raw_account = str(bank_details["account_number"])
        bank_details["account_number"] = ("•" * max(0, len(raw_account)-4)) + raw_account[-4:]
        details["bank"] = bank_details
    documents = []
    for document in docs:
        analysis_status = _analysis_state(document)
        analysis_result = _json_value(document.analysis_result_json, {}) if analysis_status == "ANALYSED" else None
        if not isinstance(analysis_result, dict):
            analysis_result = None
        documents.append({
            "id":document.id,"category":document.category,
            "category_label":{"KYC":"KYC Documents — Identity/Address Proof","Income Proof / Salary Slip":"Income Proof / Salary Slips","Bank Statement":"Bank Statements","ITR":"Income Tax Returns (ITR)","Sale / Purchase Agreement":"Sale/Purchase Agreement","Property Title":"Property Title Documents","Property Valuation":"Property Valuation Report","Terms / Disclosure":"Terms & Conditions / Disclosure Documents"}.get(document.category,document.category),
            "filename":document.original_filename,"extracted_text":document.edited_text if document.edited_text is not None else document.extracted_text,
            "original_text":document.extracted_text,"extracted_fields":_json_value(document.extracted_fields_json, {}),
            "corrected_fields":_json_value(document.corrected_fields_json, {}),
            "field_correction_history":_json_value(document.field_correction_history_json, []),
            "extraction_status":document.extraction_status,"extraction_message":document.extraction_message,
            "verification_status":document.verification_status,"verified_by":document.verified_by,
            "verified_at":document.verified_at.isoformat() if document.verified_at else None,
            "verification_note":document.verification_note,"analysis_status":analysis_status,
            "analysis_error":document.analysis_error if analysis_status in {"FAILED","NEEDS_REANALYSIS"} else "",
            "analysis_result":analysis_result,
            "analysis_completed_at":document.analysis_completed_at.isoformat() if document.analysis_completed_at else None,
        })
    return {"kyc":kyc_summary(app,docs),"id":app.id,"reference":app.reference,"status":app.status,"lender_name":app.lender_name,"product_name":app.product_name,"property_address":app.property_address,"property_value":app.property_value,"requested_loan":app.requested_loan,"annual_income":app.annual_income,"monthly_debt":app.monthly_debt,"interest_rate":app.interest_rate,"tenure_years":app.tenure_years,"customer_notes":app.customer_notes,"details":details,"submitted_at":app.submitted_at.isoformat() if app.submitted_at else None,"customer":{"full_name":customer.full_name if customer else "Unavailable","email":customer.email if customer else "Unavailable"},"documents":documents}

def queue_summary(db, app, assignment):
    customer = db.get(Customer, app.customer_id)
    details = _json_value(getattr(app, "form_data_json", "{}"), {})
    applicant = details.get("applicant") if isinstance(details, dict) else {}
    borrower_name = applicant.get("full_name") if isinstance(applicant, dict) else None
    documents = db.scalars(select(ApplicationDocument).where(
        ApplicationDocument.application_id == app.id
    ).order_by(ApplicationDocument.created_at.desc())).all()
    return {
        "id": app.id,
        "reference": app.reference,
        "status": app.status,
        "status_label": status_label(app.status),
        "lender_name": app.lender_name,
        "product_name": app.product_name,
        "property_value": app.property_value,
        "requested_loan": app.requested_loan,
        "submitted_at": app.submitted_at.isoformat() if app.submitted_at else None,
        "assigned_at": assignment.assigned_at.isoformat() if assignment.assigned_at else None,
        "customer": {"full_name": borrower_name or (customer.full_name if customer else "Unavailable")},
        "documents": [{
            "category": document.category,
            "filename": document.original_filename,
            "extraction_status": document.extraction_status,
        } for document in documents],
    }

@router.post("/login")
def login(data: LoginIn, db: Session = Depends(get_db)):
    email = data.email.lower().strip(); key = "reviewer:" + email
    if is_locked(key): raise HTTPException(429, "Too many failed sign-in attempts. Try again later.")
    reviewer = db.scalar(select(Reviewer).where(Reviewer.email == email))
    if not reviewer or not reviewer.is_active or not verify_password(data.password, reviewer.password_hash):
        note_failure(key); record(db, email, "REVIEWER", "LOGIN_FAILED", "reviewer", email); db.commit()
        raise HTTPException(401, "Invalid reviewer credentials.")
    if needs_rehash(reviewer.password_hash): reviewer.password_hash = hash_password(data.password)  # upgrade legacy hash to PBKDF2
    clear_failures(key); record(db, email, "REVIEWER", "LOGIN_SUCCESS", "reviewer", reviewer.id); db.commit()
    return {"access_token": token_for(f"reviewer:{reviewer.id}"), "token_type":"bearer", "reviewer":{"id":reviewer.id,"full_name":reviewer.full_name,"email":reviewer.email,"bank_code":reviewer.bank_code}}

@router.get("/me")
def me(db: Session = Depends(get_db), reviewer: Reviewer = Depends(current_reviewer)):
    unread = db.scalar(select(func.count()).select_from(ReviewerNotification).where(ReviewerNotification.reviewer_id == reviewer.id, ReviewerNotification.read_at.is_(None))) or 0
    return {"id":reviewer.id,"full_name":reviewer.full_name,"email":reviewer.email,"bank_code":reviewer.bank_code,"is_available":reviewer.is_available is not False,"active_load":reviewer_load(db,reviewer.id),"max_active_assignments":reviewer.max_active_assignments,"unread_notifications":unread}

@router.patch("/availability")
def set_availability(available: bool, db: Session = Depends(get_db), reviewer: Reviewer = Depends(current_reviewer)):
    """Reviewer self-service availability. Becoming available triggers automatic assignment of waiting applications."""
    reviewer.is_available = available
    record(db, reviewer.email, "REVIEWER", "REVIEWER_AVAILABLE" if available else "REVIEWER_UNAVAILABLE", "reviewer", reviewer.id)
    newly_assigned = 0
    if available:
        newly_assigned = retry_pending_assignments(db, bank_code=reviewer.bank_code, bank_id=reviewer.bank_id)
    db.commit()
    return {"is_available": reviewer.is_available, "newly_assigned": newly_assigned}

@router.get("/notifications")
def notifications(unread_only: bool = False, db: Session = Depends(get_db), reviewer: Reviewer = Depends(current_reviewer)):
    q = select(ReviewerNotification).where(ReviewerNotification.reviewer_id == reviewer.id)
    if unread_only: q = q.where(ReviewerNotification.read_at.is_(None))
    rows = db.scalars(q.order_by(ReviewerNotification.created_at.desc(), ReviewerNotification.id.desc()).limit(100)).all()
    return [{"id":n.id,"application_id":n.application_id,"title":n.title,"message":n.message,"event_type":n.event_type,"read":n.read_at is not None,"created_at":n.created_at.isoformat()} for n in rows]

@router.post("/notifications/read-all")
def read_all_notifications(db: Session = Depends(get_db), reviewer: Reviewer = Depends(current_reviewer)):
    now = datetime.now(timezone.utc)
    rows = db.scalars(select(ReviewerNotification).where(ReviewerNotification.reviewer_id == reviewer.id, ReviewerNotification.read_at.is_(None))).all()
    for n in rows: n.read_at = now
    db.commit()
    return {"marked_read": len(rows)}

@router.post("/notifications/{nid}/read")
def read_notification(nid: int, db: Session = Depends(get_db), reviewer: Reviewer = Depends(current_reviewer)):
    n = db.scalar(select(ReviewerNotification).where(ReviewerNotification.id == nid, ReviewerNotification.reviewer_id == reviewer.id))
    if not n: raise HTTPException(404, "Notification not found.")
    if n.read_at is None: n.read_at = datetime.now(timezone.utc)
    db.commit()
    return {"id": n.id, "read": True}

@router.get("/applications")
def queue(status: str | None = None, db: Session = Depends(get_db), reviewer: Reviewer = Depends(current_reviewer)):
    q = select(ReviewAssignment).where(ReviewAssignment.reviewer_id == reviewer.id, ReviewAssignment.active == True).order_by(ReviewAssignment.assigned_at.desc())
    rows = db.scalars(q).all(); results=[]
    for assignment in rows:
        app = db.get(MortgageApplication, assignment.application_id)
        if not app or not _reviewer_can_access_application(db, app, reviewer): continue
        if status and app.status.lower() != status.lower(): continue
        results.append(queue_summary(db, app, assignment))
    return results

@router.get("/applications/{aid}")
def detail(aid:int, db:Session=Depends(get_db), reviewer:Reviewer=Depends(current_reviewer)):
    app=assigned(db,aid,reviewer); data=summary(db,app)
    record(db,reviewer.email,"REVIEWER","APPLICATION_VIEWED","application",aid); db.commit()
    assignment=db.scalar(select(ReviewAssignment).where(ReviewAssignment.application_id==aid,ReviewAssignment.reviewer_id==reviewer.id,ReviewAssignment.active.is_(True)))
    data["assigned_at"]=assignment.assigned_at.isoformat() if assignment and assignment.assigned_at else None
    data["history"]=[{"id":e.id,"event_type":e.event_type,"note":e.note,"created_at":e.created_at.isoformat()} for e in db.scalars(select(ReviewEvent).where(ReviewEvent.application_id==aid).order_by(ReviewEvent.created_at.desc())).all()]
    return data

@router.post("/applications/{aid}/actions")
def action(aid:int, data:ActionIn, db:Session=Depends(get_db), reviewer:Reviewer=Depends(current_reviewer)):
    app=assigned(db,aid,reviewer); action=data.action; note=data.note.strip()
    if action in {"request_documents","add_note","escalate","recommend_approve","recommend_decline"} and not note:
        raise HTTPException(422,"A note explaining this action is required.")
    if app.status in {"COMPLETED","CLOSED"} and action not in {"add_note"}:
        raise HTTPException(409,"This review is completed; only notes can be added.")
    if app.status in {"RECOMMEND_APPROVE","RECOMMEND_DECLINE","ESCALATED"} and action not in {"complete","add_note"}:
        raise HTTPException(409,"A recommendation or escalation has already been submitted; only completion or notes are allowed.")
    if action=="start_review":
        if app.status not in {"ASSIGNED","SUBMITTED","DOCUMENTS_REQUESTED","ADDITIONAL_INFORMATION_REQUIRED"}:
            raise HTTPException(409,"Review can only be started for an assigned or returned application.")
        app.status="IN_REVIEW"
    elif action=="request_documents":
        if app.status not in {"ASSIGNED","SUBMITTED","IN_REVIEW","DOCUMENTS_REQUESTED","ADDITIONAL_INFORMATION_REQUIRED"}:
            raise HTTPException(409,"Additional information cannot be requested at this review status.")
        app.status="DOCUMENTS_REQUESTED"
    elif action=="escalate":
        if app.status not in {"ASSIGNED","SUBMITTED","IN_REVIEW","DOCUMENTS_REQUESTED","ADDITIONAL_INFORMATION_REQUIRED"}:
            raise HTTPException(409,"This application cannot be escalated at its current review status.")
        app.status="ESCALATED"
    elif action=="recommend_approve":
        if app.status!="IN_REVIEW":
            raise HTTPException(409,"Start or resume the review before submitting a recommendation.")
        if app.kyc_status!="VERIFIED": raise HTTPException(409,"KYC must be verified before recommending approval.")
        app.status="RECOMMEND_APPROVE"
    elif action=="recommend_decline":
        if app.status!="IN_REVIEW":
            raise HTTPException(409,"Start or resume the review before submitting a recommendation.")
        app.status="RECOMMEND_DECLINE"
    elif action=="complete":
        if app.status not in {"RECOMMEND_APPROVE","RECOMMEND_DECLINE","ESCALATED"}:
            raise HTTPException(409,"Add a recommendation or escalate before completing the review.")
        app.status="COMPLETED"
    event=ReviewEvent(application_id=aid,reviewer_id=reviewer.id,event_type=action.upper(),note=note)
    record(db,reviewer.email,"REVIEWER","REVIEW_"+action.upper(),"application",aid,f"status={app.status}")
    db.add(event)
    title_map={"start_review":"Review started","request_documents":"Additional information requested","escalate":"Application review escalated","recommend_approve":"Review assessment submitted","recommend_decline":"Review assessment submitted","complete":"Review assessment completed","add_note":"Application review updated"}
    message_map={"start_review":f"Review of application {app.reference} has started.","request_documents":f"The bank requested additional information for application {app.reference}. Please open Documents & Requests and review the request.","escalate":f"Application {app.reference} requires further internal review.","recommend_approve":f"The reviewer submitted an assessment for application {app.reference}. This is not the final loan decision.","recommend_decline":f"The reviewer submitted an assessment for application {app.reference}. This is not the final loan decision.","complete":f"The reviewer assessment for application {app.reference} is complete. The authorised bank decision process is separate.","add_note":f"A review update was recorded for application {app.reference}."}
    db.add(CustomerNotification(customer_id=app.customer_id,application_id=app.id,title=title_map.get(action,"Application updated"),message=message_map.get(action,f"Application {app.reference} was updated."),event_type="REVIEW_"+action.upper()))
    app.updated_at=datetime.now(timezone.utc)
    if action=="complete":
        db.flush(); retry_pending_assignments(db,bank_code=reviewer.bank_code,bank_id=reviewer.bank_id)  # capacity freed
    db.commit(); db.refresh(app)
    return {"message":"Review action recorded.","status":app.status,"event_id":event.id}


class ReviewFindingIn(BaseModel):
    category: str = Field(min_length=2, max_length=80)
    severity: str = Field(pattern="^(LOW|MEDIUM|HIGH|CRITICAL)$")
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=5, max_length=5000)
    document_id: int | None = Field(default=None, ge=1)
    field_name: str = Field(default="", max_length=160)
    source_evidence: str = Field(default="", max_length=5000)

class ReviewChecklistIn(BaseModel):
    phase: str = Field(min_length=2, max_length=100)
    checklist: list[dict] = Field(min_length=1, max_length=100)
    note: str = Field(default="", max_length=3000)


@router.get("/applications/{aid}/findings")
def list_review_findings(aid: int, db: Session = Depends(get_db), reviewer: Reviewer = Depends(current_reviewer)):
    """Return persisted structured findings recorded by this application's assigned reviewer."""
    assigned(db, aid, reviewer)
    events = db.scalars(select(ReviewEvent).where(
        ReviewEvent.application_id == aid,
        ReviewEvent.reviewer_id == reviewer.id,
        ReviewEvent.event_type == "FINDING_RECORDED"
    ).order_by(ReviewEvent.created_at.desc(), ReviewEvent.id.desc())).all()
    results = []
    for event in events:
        try:
            item = json.loads(event.note)
            if isinstance(item, dict):
                item.update({"id": event.id, "created_at": event.created_at.isoformat()})
                results.append(item)
        except (TypeError, ValueError):
            continue
    return results


@router.post("/applications/{aid}/findings")
def create_review_finding(aid: int, data: ReviewFindingIn, db: Session = Depends(get_db), reviewer: Reviewer = Depends(current_reviewer)):
    """Persist a source-linked finding; never turns an AI flag into a final lending decision."""
    app = assigned(db, aid, reviewer)
    if app.status in {"COMPLETED", "CLOSED"}:
        raise HTTPException(409, "This review is completed; findings can no longer be changed.")
    if data.document_id is not None:
        doc = db.scalar(select(ApplicationDocument).where(
            ApplicationDocument.id == data.document_id,
            ApplicationDocument.application_id == aid
        ))
        if not doc:
            raise HTTPException(404, "Source document not found for this application.")
    finding = data.model_dump()
    finding["reviewer_email"] = reviewer.email
    event = ReviewEvent(application_id=aid, reviewer_id=reviewer.id,
                        event_type="FINDING_RECORDED", note=json.dumps(finding, ensure_ascii=False))
    db.add(event)
    record(db, reviewer.email, "REVIEWER", "FINDING_RECORDED", "application", aid,
           f"severity={data.severity}; category={data.category}")
    db.commit()
    db.refresh(event)
    return {"id": event.id, **finding, "created_at": event.created_at.isoformat()}


@router.post("/applications/{aid}/checklist")
def save_review_checklist(aid: int, data: ReviewChecklistIn, db: Session = Depends(get_db), reviewer: Reviewer = Depends(current_reviewer)):
    """Save a phase-specific checklist as an auditable review event for extensible workflows."""
    app = assigned(db, aid, reviewer)
    if app.status in {"COMPLETED", "CLOSED"}:
        raise HTTPException(409, "This review is completed; its checklist is read-only.")
    normalized = []
    seen = set()
    for item in data.checklist:
        if not isinstance(item, dict):
            raise HTTPException(422, "Each checklist item must be an object.")
        label = str(item.get("label", "")).strip()[:200]
        status = str(item.get("status", "PENDING")).upper()
        if not label or status not in {"PENDING", "PASS", "FAIL", "NOT_APPLICABLE"}:
            raise HTTPException(422, "Each checklist item needs a label and a valid status.")
        key = label.casefold()
        if key in seen:
            raise HTTPException(422, "Checklist item labels must be unique within a phase.")
        seen.add(key)
        normalized.append({"label": label, "status": status, "note": str(item.get("note", "")).strip()[:1000]})
    payload = {"phase": data.phase.strip(), "checklist": normalized, "note": data.note.strip()}
    event = ReviewEvent(application_id=aid, reviewer_id=reviewer.id,
                        event_type="CHECKLIST_SAVED", note=json.dumps(payload, ensure_ascii=False))
    db.add(event)
    record(db, reviewer.email, "REVIEWER", "CHECKLIST_SAVED", "application", aid, f"phase={data.phase}")
    db.commit()
    db.refresh(event)
    return {"id": event.id, **payload, "created_at": event.created_at.isoformat()}


@router.get("/applications/{aid}/checklists")
def list_review_checklists(aid: int, db: Session = Depends(get_db), reviewer: Reviewer = Depends(current_reviewer)):
    assigned(db, aid, reviewer)
    events = db.scalars(select(ReviewEvent).where(
        ReviewEvent.application_id == aid,
        ReviewEvent.reviewer_id == reviewer.id,
        ReviewEvent.event_type == "CHECKLIST_SAVED"
    ).order_by(ReviewEvent.created_at.desc(), ReviewEvent.id.desc())).all()
    results = []
    for event in events:
        try:
            item = json.loads(event.note)
            if isinstance(item, dict):
                item.update({"id": event.id, "created_at": event.created_at.isoformat()})
                results.append(item)
        except (TypeError, ValueError):
            continue
    return results


class ReviewerPolicyQuestionIn(BaseModel):
    question: str = Field(min_length=5, max_length=2000)

@router.post("/policy-qa")
async def reviewer_policy_qa(data: ReviewerPolicyQuestionIn, db: Session = Depends(get_db), reviewer: Reviewer = Depends(current_reviewer)):
    try:
        validate_ai_request(data.question,"policy_question")
    except NVIDIAInputRejected as e:
        raise HTTPException(422,str(e))
    bank = db.get(Bank, reviewer.bank_id) if reviewer.bank_id is not None else db.scalar(select(Bank).where(Bank.code == (reviewer.bank_code or "").strip().upper()))
    sources,method=await retrieve_hybrid(db, data.question, limit=5, bank_id=bank.id if bank else None)
    try:
        result=await answer_policy_question(data.question, sources)
    except NVIDIAInputRejected as e:
        raise HTTPException(422,str(e))
    except NVIDIAConfigurationError as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        raise HTTPException(502, f"NVIDIA policy QA failed ({type(e).__name__}): {str(e)[:200]}")
    result["retrieval_method"]=method
    result["vector_store"]="policy_chunks table (JSON embeddings, in-process cosine)" if "vector" in method else "not used for this query"
    result["sources_retrieved"]=len(sources)
    result["retrieval_status"]="RETRIEVED" if sources else "FAILED" if "embedding_failed" in method else "NO_RELEVANT_EVIDENCE"
    return result


@router.get("/applications/{aid}/documents/{did}/file")
def reviewer_download(aid:int, did:int, db:Session=Depends(get_db), reviewer:Reviewer=Depends(current_reviewer)):
    assigned(db,aid,reviewer)
    d=db.scalar(select(ApplicationDocument).where(ApplicationDocument.id==did,ApplicationDocument.application_id==aid))
    if not d: raise HTTPException(404,"Document not found.")
    record(db,reviewer.email,"REVIEWER","DOCUMENT_DOWNLOADED","document",did,f"application={aid}"); db.commit()
    return file_response(d)

@router.post("/applications/{aid}/scenarios/{name}")
async def reviewer_scenario(aid:int, name:str, body:ScenarioIn, db:Session=Depends(get_db), reviewer:Reviewer=Depends(current_reviewer)):
    app=assigned(db,aid,reviewer)
    if name not in {"valuation_ltv","income_tax","terms_conditions"}:
        raise HTTPException(422,f"Unknown scenario '{name}'.")
    try:
        validate_ai_request(f"Mortgage policy evidence request: {name}","document_analysis",name)
    except NVIDIAInputRejected as e:
        raise HTTPException(422,str(e))
    try: result=run_for_application(db,app,name,body)
    except ValueError as e: raise HTTPException(422,str(e))
    policy_questions={
        "valuation_ltv":"property valuation market valuation purchase price lender loan-to-value LTV limits",
        "income_tax":"income tax return ITR salary slips bank statements income verification requirements",
        "terms_conditions":"mortgage loan terms interest rate tenure EMI fees prepayment default clauses conditions",
    }
    bank=db.get(Bank,reviewer.bank_id) if reviewer.bank_id is not None else db.scalar(select(Bank).where(Bank.code==(reviewer.bank_code or "").strip().upper()))
    try:
        policies,method=await retrieve_hybrid(db,policy_questions[name],limit=5,bank_id=bank.id if bank else None)
        result["policy_evidence"]=[{"policy_id":p["policy_id"],"bank_id":p.get("bank_id"),"title":p["title"],"policy_version":p["policy_version"],"category":p["category"],"chunk_index":p["chunk_index"],"excerpt":p["text"],"retrieval_method":p.get("method")} for p in policies]
        result["policy_retrieval_status"]="RETRIEVED" if policies else "FAILED" if "embedding_failed" in method else "NO_RELEVANT_POLICY_EVIDENCE"
        result["policy_retrieval_method"]=method
    except Exception as e:
        result["policy_evidence"]=[]
        result["policy_retrieval_status"]="FAILED"
        result["policy_retrieval_method"]=f"retrieval_error:{type(e).__name__}"
    record(db,reviewer.email,"REVIEWER","SCENARIO_RUN","application",aid,name); db.commit(); return result


class KYCIn(BaseModel):
    status: str = Field(pattern="^(VERIFIED|REJECTED|NEEDS_REVIEW)$")
    note: str = Field(default="", max_length=3000)

@router.post("/applications/{aid}/kyc")
def set_kyc(aid:int,data:KYCIn,db:Session=Depends(get_db),reviewer:Reviewer=Depends(current_reviewer)):
    app=assigned(db,aid,reviewer); note=data.note.strip()
    if app.status in {"COMPLETED","CLOSED"}: raise HTTPException(409,"This review is completed; KYC can no longer be changed.")
    if data.status in {"REJECTED","NEEDS_REVIEW"} and not note: raise HTTPException(422,"Provide a reason for a rejected or needs-review KYC outcome.")
    docs=db.scalars(select(ApplicationDocument).where(ApplicationDocument.application_id==aid)).all()
    kyc_docs=[d for d in docs if d.category==KYC_CATEGORY]
    if data.status=="VERIFIED":
        if not kyc_docs: raise HTTPException(409,"No KYC document has been uploaded for this application.")
        unverified=[d for d in kyc_docs if d.verification_status!="VERIFIED"]
        if unverified: raise HTTPException(409,f"{len(unverified)} KYC document(s) are not verified yet. Verify each KYC document first.")
    now=datetime.now(timezone.utc)
    app.kyc_status=data.status;app.kyc_verified_by=reviewer.email;app.kyc_verified_at=now;app.kyc_note=note;app.updated_at=now
    db.add(ReviewEvent(application_id=aid,reviewer_id=reviewer.id,event_type="KYC_"+data.status,note=note))
    record(db,reviewer.email,"REVIEWER","KYC_"+data.status,"application",aid,f"note={note[:500]}");db.commit();db.refresh(app)
    return kyc_summary(app,docs)

class DocumentVerificationIn(BaseModel):
    status: str = Field(pattern="^(VERIFIED|REJECTED|NEEDS_REVIEW)$")
    note: str = Field(default="", max_length=3000)

@router.patch("/applications/{aid}/documents/{did}/verification")
def verify_document(aid:int,did:int,data:DocumentVerificationIn,db:Session=Depends(get_db),reviewer:Reviewer=Depends(current_reviewer)):
    app=assigned(db,aid,reviewer)
    doc=db.scalar(select(ApplicationDocument).where(ApplicationDocument.id==did,ApplicationDocument.application_id==aid))
    if not doc: raise HTTPException(404,"Document not found.")
    if data.status in {"REJECTED","NEEDS_REVIEW"} and not data.note.strip(): raise HTTPException(422,"Provide a reason for rejected or needs-review documents.")
    doc.verification_status=data.status;doc.verified_by=reviewer.email;doc.verified_at=datetime.now(timezone.utc);doc.verification_note=data.note.strip()
    record(db,reviewer.email,"REVIEWER","DOCUMENT_"+data.status,"document",did,f"application={aid}; note={data.note.strip()[:500]}");db.commit();db.refresh(doc)
    return {"id":doc.id,"verification_status":doc.verification_status,"verified_by":doc.verified_by,"verified_at":doc.verified_at.isoformat() if doc.verified_at else None,"verification_note":doc.verification_note}

@router.post("/applications/{aid}/documents/{did}/reanalyze")
async def reviewer_reanalyze_document(aid:int,did:int,db:Session=Depends(get_db),reviewer:Reviewer=Depends(current_reviewer)):
    """Re-run the existing AI pipeline only when this assigned reviewer's document is stale."""
    app=assigned(db,aid,reviewer)
    doc=db.scalar(select(ApplicationDocument).where(ApplicationDocument.id==did,ApplicationDocument.application_id==aid))
    if not doc: raise HTTPException(404,"Document not found.")
    if doc.analysis_status=="ANALYSING": raise HTTPException(409,"Analysis is already running for this document.")
    if _analysis_state(doc)!="NEEDS_REANALYSIS":
        raise HTTPException(409,"This document does not currently require reanalysis.")
    from app.routers.ai import _perform_document_analysis
    return await _perform_document_analysis(db,app,doc,reviewer.email,"REVIEWER",force=True)

class ReviewerDocumentFieldsIn(BaseModel):
    corrected_fields: dict[str, object] = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=3, max_length=1000)

@router.patch("/applications/{aid}/documents/{did}/fields")
def correct_document_fields(aid:int,did:int,data:ReviewerDocumentFieldsIn,db:Session=Depends(get_db),reviewer:Reviewer=Depends(current_reviewer)):
    app=assigned(db,aid,reviewer)
    if app.status in {"COMPLETED","CLOSED"}:
        raise HTTPException(409,"This review is completed; document fields are read-only.")
    doc=db.scalar(select(ApplicationDocument).where(ApplicationDocument.id==did,ApplicationDocument.application_id==aid))
    if not doc: raise HTTPException(404,"Document not found.")
    original=_json_value(doc.extracted_fields_json,{})
    current=_json_value(doc.corrected_fields_json,{})
    history=_json_value(doc.field_correction_history_json,[])
    if not isinstance(original,dict): original={}
    if not isinstance(current,dict): current={}
    if not isinstance(history,list): history=[]
    if not data.reason.strip():
        raise HTTPException(422,"Provide a reason for the reviewer correction.")
    if any(field not in original and field not in current for field in data.corrected_fields):
        raise HTTPException(422,"Only fields extracted from this document can be corrected.")
    changed_fields={}
    for field,value in data.corrected_fields.items():
        original_entry=original.get(field)
        original_value=original_entry.get("value") if isinstance(original_entry,dict) else original_entry
        current_entry=current.get(field)
        previous_value=(current_entry.get("value") if isinstance(current_entry,dict) else current_entry) if field in current else original_value
        if value!=previous_value:
            changed_fields[field]=value
    if not changed_fields:
        raise HTTPException(422,"At least one corrected field must differ from its current value.")
    now=datetime.now(timezone.utc).isoformat()
    for field,value in changed_fields.items():
        original_entry=original.get(field)
        original_value=original_entry.get("value") if isinstance(original_entry,dict) else original_entry
        current_entry=current.get(field)
        previous_value=(current_entry.get("value") if isinstance(current_entry,dict) else current_entry) if field in current else original_value
        current[field]={
            "value":value,
            "source":"REVIEWER_CORRECTION",
            "original_value":original_value,
            "edited":value!=original_value,
        }
        if value!=previous_value:
            history.append({
                "field":field,
                "previous_value":previous_value,
                "original_value":original_value,
                "corrected_value":value,
                "actor_reviewer_id":reviewer.id,
                "actor_reviewer_email":reviewer.email,
                "changed_at":now,
                "reason":data.reason.strip(),
            })
    doc.corrected_fields_json=json.dumps(current,ensure_ascii=False)
    doc.field_correction_history_json=json.dumps(history[-200:],ensure_ascii=False)
    if doc.verification_status=="VERIFIED":
        doc.verification_status="PENDING"
        doc.verification_note="Reset: reviewer-corrected structured fields require re-verification."
        if doc.category==KYC_CATEGORY and app.kyc_status=="VERIFIED":
            app.kyc_status="PENDING"
            app.kyc_note="Reset: reviewer-corrected KYC fields require re-verification."
    record(db,reviewer.email,"REVIEWER","REVIEWER_DOCUMENT_FIELDS_CORRECTED","document",did,
           f"application={aid}; fields={','.join(changed_fields.keys())}")
    db.commit()
    db.refresh(doc)
    return {
        "id":doc.id,
        "corrected_fields":_json_value(doc.corrected_fields_json,{}),
        "field_correction_history":_json_value(doc.field_correction_history_json,[]),
        "verification_status":doc.verification_status,
    }
