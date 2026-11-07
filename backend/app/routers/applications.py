from datetime import datetime, date, timezone
from pathlib import Path
import re
import json, secrets
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select, or_, update as sql_update, delete
from app.database import get_db
from app.dependencies import current_customer
from app.models import Customer, MortgageApplication, Bank, ApplicationDocument, AuditLog, CustomerNotification, ReviewerNotification, AnalysisRun, ReviewAssignment, ReviewEvent, AssignmentEvent
from app.schemas import ApplicationIn
from app.config import settings
from app.services.calculations import estimate_metrics
from app.services.audit import record
from app.services.assignment import auto_assign_application, status_label

router = APIRouter(prefix="/applications", tags=["Applications"])

# This is an intake completeness baseline, not a credit-eligibility or lender approval policy.
# Bank-specific requirements should be represented by approved policy/configuration when available.
BASE_REQUIRED_DOCS = {"KYC", "Bank Statement"}
CATEGORY_DISPLAY = {
    "Mortgage Application": "Mortgage Application",
    "KYC": "KYC Documents — Identity/Address Proof",
    "Income Proof / Salary Slip": "Income Proof / Salary Slips",
    "Bank Statement": "Bank Statements",
    "ITR": "Income Tax Returns (ITR)",
    "Sale / Purchase Agreement": "Sale/Purchase Agreement",
    "Property Title": "Property Title Documents",
    "Property Valuation": "Property Valuation Report",
    "Loan Agreement": "Loan Agreement",
    "Amortization Schedule": "Amortization Schedule",
    "Terms / Disclosure": "Terms & Conditions / Disclosure Documents",
}

@router.get("/approved-banks")
def approved_banks(db: Session = Depends(get_db)):
    return [{"id": b.id, "name": b.name, "code": b.code} for b in db.scalars(select(Bank).where(Bank.status == "APPROVED").order_by(Bank.name)).all()]

def _json(value, default):
    try:
        parsed = json.loads(value or "")
        return parsed if isinstance(parsed, type(default)) else default
    except (ValueError, TypeError):
        return default

def _safe_customer_details(raw):
    details = _json(raw, {})
    bank_details = details.get("bank") if isinstance(details.get("bank"), dict) else None
    if bank_details and bank_details.get("account_number"):
        value = str(bank_details["account_number"])
        bank_details["account_number"] = ("•" * max(0, len(value) - 4)) + value[-4:]
        details["bank"] = bank_details
    return details

def _stored_details(details):
    # Bank account numbers are not required for this intake flow and must not be newly persisted.
    safe = json.loads(json.dumps(details or {}))
    bank_details = safe.get("bank") if isinstance(safe.get("bank"), dict) else None
    if bank_details is not None:
        bank_details.pop("account_number", None)
    return safe

def out(a):
    return {k: getattr(a, k) for k in ["id", "reference", "customer_id", "status", "lender_name", "product_name", "property_address", "property_value", "requested_loan", "annual_income", "monthly_debt", "interest_rate", "tenure_years", "customer_notes", "kyc_status", "kyc_note"]} | {
        "details": _safe_customer_details(getattr(a, "form_data_json", "{}")),
        "consents": _json(getattr(a, "consents_json", "{}"), {}),
        "created_at": a.created_at.isoformat(), "updated_at": a.updated_at.isoformat(),
        "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None,
        "last_saved_at": a.updated_at.isoformat(),
        "awaiting_assignment": bool(getattr(a, "awaiting_assignment", False)),
        "status_label": status_label(a.status, bool(getattr(a, "awaiting_assignment", False))),
    }

def owned(db, aid, cid):
    a = db.scalar(select(MortgageApplication).where(MortgageApplication.id == aid, MortgageApplication.customer_id == cid))
    if not a:
        raise HTTPException(404, "Application not found.")
    return a

def _detail(a, section, key, default=""):
    return (_json(a.form_data_json, {}).get(section) or {}).get(key, default)

def _number(value):
    try:
        number = float(value)
        return number if number >= 0 and number < float("inf") else 0.0
    except (TypeError, ValueError):
        return 0.0

def required_documents_for(a):
    required = set(BASE_REQUIRED_DOCS)
    employment = str(_detail(a, "employment", "employment_type", "")).lower()
    purpose = str(_detail(a, "loan", "purpose", "")).lower()
    if "self" in employment or "business" in employment:
        required.add("ITR")
    else:
        required.add("Income Proof / Salary Slip")
    if any(x in purpose for x in ("purchase", "balance transfer", "balance_transfer")):
        required.add("Sale / Purchase Agreement")
        required.add("Property Title")
    return required

def document_checklist(db, a):
    docs = db.scalars(select(ApplicationDocument).where(ApplicationDocument.application_id == a.id)).all()
    present = {d.category for d in docs}
    required = required_documents_for(a)
    return [{"category": k, "label": CATEGORY_DISPLAY.get(k, k), "required": k in required,
             "status": "UPLOADED" if k in present else ("MISSING" if k in required else "OPTIONAL"),
             "document_ids": [d.id for d in docs if d.category == k]} for k in CATEGORY_DISPLAY]

def _validate_for_submission(db, a):
    errors = []
    details = _json(a.form_data_json, {})
    applicant = details.get("applicant") or {}
    loan = details.get("loan") or {}
    employment = details.get("employment") or {}
    bank = details.get("bank") or {}
    property_data = details.get("property") or {}
    consents = _json(a.consents_json, {})
    checks = [
        (bool(a.lender_name.strip()), "Select an approved lender."),
        (a.requested_loan > 0, "Enter a requested loan amount greater than zero."),
        (bool(str(loan.get("purpose", "")).strip()), "Select a loan purpose."),
        (bool(str(applicant.get("full_name", "")).strip()), "Enter the applicant's full name."),
        (bool(str(applicant.get("date_of_birth", "")).strip()), "Enter the applicant's date of birth."),
        (bool(str(applicant.get("mobile", "")).strip()), "Enter the applicant's mobile number."),
        (bool(str(applicant.get("email", "")).strip()), "Enter the applicant's email address."),
        (bool(str(applicant.get("residential_address", "")).strip()), "Enter the residential address."),
        (bool(str(employment.get("employment_type", "")).strip()), "Select the employment type."),
        (bool(str(employment.get("occupation", "")).strip()), "Enter the occupation."),
        (bool(str(employment.get("employer_name", "")).strip()) if str(employment.get("employment_type", "")).lower() in {"salaried", "business owner", "self-employed"} else True, "Enter the employer / business name for this employment type."),
        (a.annual_income > 0 or _number(employment.get("monthly_income")) > 0, "Enter monthly or annual income greater than zero."),
        (bool(str(property_data.get("property_type", "")).strip()), "Select the property type."),
        (bool(a.property_address.strip()), "Enter the property address."),
        (a.property_value > 0, "Enter the declared property/agreement value."),
        (consents.get("truthful_information") is True, "Confirm that the information supplied is accurate."),
        (consents.get("privacy_consent") is True, "Confirm the privacy and document-processing consent."),
    ]
    errors.extend(message for ok, message in checks if not ok)
    allowed_purposes={"Home Purchase","Home Construction","Home Improvement","Home Extension","Balance Transfer"}
    allowed_employment={"Salaried","Self-employed","Business owner","Professional","Other"}
    allowed_property={"Apartment / Flat","Independent House","Plot / Land","Under-construction property","Other"}
    if loan.get("purpose") and loan.get("purpose") not in allowed_purposes:
        errors.append("Select a supported loan purpose.")
    if employment.get("employment_type") and employment.get("employment_type") not in allowed_employment:
        errors.append("Select a supported employment type.")
    if property_data.get("property_type") and property_data.get("property_type") not in allowed_property:
        errors.append("Select a supported property type.")
    dob=str(applicant.get("date_of_birth", "")).strip()
    if dob:
        try:
            if date.fromisoformat(dob) >= datetime.now(timezone.utc).date(): errors.append("Date of birth must be a past date.")
        except ValueError:
            errors.append("Enter a valid date of birth.")
    mobile_digits="".join(ch for ch in str(applicant.get("mobile", "")) if ch.isdigit())
    if applicant.get("mobile") and not 10 <= len(mobile_digits) <= 15: errors.append("Enter a valid applicant mobile number.")
    email_value=str(applicant.get("email", "")).strip()
    if email_value and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email_value): errors.append("Enter a valid applicant email address.")
    if loan.get("co_applicant_required"):
        co=details.get("co_applicant") or {}
        if not str(co.get("full_name", "")).strip(): errors.append("Enter the co-applicant's full name or turn off the co-applicant option.")
        if not str(co.get("relationship", "")).strip(): errors.append("Enter the co-applicant's relationship.")
    for section_name, section, numeric_keys in [("employment", employment, ("monthly_income", "annual_income", "other_income")), ("loan", loan, ("down_payment",)), ("property", property_data, ("estimated_market_value",)), ("co_applicant", details.get("co_applicant") or {}, ("annual_income",))]:
        for key in numeric_keys:
            raw=section.get(key)
            if raw not in (None, ""):
                try:
                    if float(raw) < 0 or float(raw) == float("inf") or float(raw) != float(raw): raise ValueError
                except (TypeError, ValueError): errors.append(f"Enter a valid non-negative number for {key.replace('_',' ')}.")
    if current_ifsc := str(bank.get("ifsc", "")).strip():
        if not re.fullmatch(r"[A-Za-z]{4}0[A-Za-z0-9]{6}", current_ifsc): errors.append("Enter a valid IFSC code or leave it blank if not required.")
    docs = db.scalars(select(ApplicationDocument).where(ApplicationDocument.application_id == a.id)).all()
    present = {d.category for d in docs}
    for category in sorted(required_documents_for(a) - present):
        errors.append(f"Upload the required document: {CATEGORY_DISPLAY.get(category, category)}.")
    by_category={}
    for document in docs: by_category.setdefault(document.category, []).append(document)
    for category in sorted(required_documents_for(a) & present):
        category_docs=by_category.get(category, [])
        if category_docs and not any(d.extraction_status == "COMPLETED" or bool((d.extracted_text or "").strip()) or bool((d.edited_text or "").strip()) for d in category_docs):
            errors.append(f"The required {CATEGORY_DISPLAY.get(category, category)} could not be read. Upload a clearer file or correct the extracted text before submitting.")
    if a.lender_name.strip():
        bank_row = db.scalar(select(Bank).where(or_(Bank.code == a.lender_name.strip().upper(), Bank.name == a.lender_name.strip())))
        if not bank_row:
            errors.append("Select a lender from the approved banks list.")
        elif bank_row.status != "APPROVED":
            errors.append("The selected lender is not approved for applications.")
    return errors

@router.get("")
def listing(db: Session = Depends(get_db), u: Customer = Depends(current_customer)):
    rows = db.scalars(select(MortgageApplication).where(MortgageApplication.customer_id == u.id).order_by(MortgageApplication.updated_at.desc())).all()
    return [out(a) | {"document_checklist": document_checklist(db, a)} for a in rows]

@router.post("")
def create(data: ApplicationIn, db: Session = Depends(get_db), u: Customer = Depends(current_customer)):
    payload = data.model_dump(exclude={"details", "consents"})
    a = MortgageApplication(reference="MRT-" + secrets.token_hex(4).upper(), customer_id=u.id, **payload,
                            form_data_json=json.dumps(_stored_details(data.details)), consents_json=json.dumps(data.consents))
    db.add(a); db.flush()
    record(db, u.email, "CUSTOMER", "APPLICATION_CREATED", "application", a.id, a.reference)
    db.add(CustomerNotification(customer_id=u.id, application_id=a.id, title="Draft created", message=f"Application {a.reference} was created as a draft.", event_type="APPLICATION_CREATED"))
    db.commit(); db.refresh(a)
    return out(a)

@router.get("/{aid}")
def get_one(aid: int, db: Session = Depends(get_db), u: Customer = Depends(current_customer)):
    a = owned(db, aid, u.id)
    return out(a) | {"document_checklist": document_checklist(db, a)}

@router.delete("/{aid}")
def delete_draft(aid: int, db: Session = Depends(get_db), u: Customer = Depends(current_customer)):
    a = owned(db, aid, u.id)
    if a.status != "DRAFT":
        raise HTTPException(409, "Only draft applications can be deleted.")
    # A draft should not have reviewer history. Preserve that history if inconsistent records exist.
    if any(db.scalar(select(model.id).where(model.application_id == aid).limit(1)) is not None
           for model in (ReviewAssignment, ReviewEvent, AssignmentEvent)):
        raise HTTPException(409, "This application has review history and cannot be deleted.")

    documents = db.scalars(select(ApplicationDocument).where(ApplicationDocument.application_id == aid)).all()
    upload_root = Path(settings.uploads_dir).resolve()
    paths = []
    for doc in documents:
        path = (upload_root / doc.stored_filename).resolve()
        if upload_root in path.parents:
            paths.append(path)

    # Retain notifications but detach the optional application reference; preserve independent audit history.
    db.execute(sql_update(CustomerNotification).where(CustomerNotification.application_id == aid).values(application_id=None))
    db.execute(sql_update(ReviewerNotification).where(ReviewerNotification.application_id == aid).values(application_id=None))
    db.execute(delete(AnalysisRun).where(AnalysisRun.application_id == aid))
    record(db, u.email, "CUSTOMER", "APPLICATION_DRAFT_DELETED", "application", aid, a.reference)
    db.delete(a)  # ApplicationDocument rows cascade with the application.
    db.commit()
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            # Database deletion remains successful; storage cleanup can be retried operationally.
            pass
    return {"id": aid, "deleted": True}

@router.put("/{aid}")
def update(aid: int, data: ApplicationIn, db: Session = Depends(get_db), u: Customer = Depends(current_customer)):
    a = owned(db, aid, u.id)
    if a.status not in {"DRAFT", "DOCUMENTS_REQUESTED", "ADDITIONAL_INFORMATION_REQUIRED"}:
        raise HTTPException(409, "Only a draft or an application awaiting additional information can be edited.")
    payload = data.model_dump(exclude={"details", "consents"})
    for k, v in payload.items():
        setattr(a, k, v)
    a.form_data_json = json.dumps(_stored_details(data.details))
    a.consents_json = json.dumps(data.consents)
    a.updated_at = datetime.now(timezone.utc)
    record(db, u.email, "CUSTOMER", "APPLICATION_DRAFT_SAVED", "application", a.id, a.reference)
    db.commit(); db.refresh(a)
    return out(a) | {"document_checklist": document_checklist(db, a)}

@router.get("/{aid}/document-requirements")
def requirements(aid: int, db: Session = Depends(get_db), u: Customer = Depends(current_customer)):
    a = owned(db, aid, u.id)
    return {"items": document_checklist(db, a), "note": "Intake checklist baseline. Bank-specific requirements and later-stage documents must follow the applicable approved bank policy."}

@router.post("/{aid}/submit")
def submit(aid: int, db: Session = Depends(get_db), u: Customer = Depends(current_customer)):
    a = owned(db, aid, u.id)
    if a.status not in {"DRAFT", "DOCUMENTS_REQUESTED", "ADDITIONAL_INFORMATION_REQUIRED"}:
        raise HTTPException(409, "This application cannot be submitted from its current status.")
    errors = _validate_for_submission(db, a)
    if errors:
        raise HTTPException(422, {"message": "Application validation failed.", "errors": errors})
    bank = db.scalar(select(Bank).where(or_(Bank.code == a.lender_name.strip().upper(), Bank.name == a.lender_name.strip())))
    if bank:
        a.bank_id = bank.id
    a.status = "SUBMITTED"
    a.submitted_at = datetime.now(timezone.utc)
    a.updated_at = a.submitted_at
    record(db, u.email, "CUSTOMER", "APPLICATION_SUBMITTED", "application", a.id, a.reference)
    db.add(CustomerNotification(customer_id=u.id, application_id=a.id, title="Application submitted", message=f"Application {a.reference} was submitted successfully. Document checks and review workflow will determine the next status.", event_type="APPLICATION_SUBMITTED"))
    # Automatic assignment happens only here (a real submission), inside the same transaction.
    # It never raises: on failure the application stays submitted and is flagged Awaiting Reviewer Assignment.
    auto_assign_application(db, a, notify_resubmission=True)
    db.commit(); db.refresh(a)
    return out(a)

@router.get("/{aid}/activity")
def activity(aid: int, db: Session = Depends(get_db), u: Customer = Depends(current_customer)):
    a = owned(db, aid, u.id)
    logs = db.scalars(select(AuditLog).where(
        or_(AuditLog.resource_id == str(a.id), AuditLog.detail.contains(f"application={a.id}")),
        AuditLog.action.in_(["APPLICATION_CREATED", "APPLICATION_DRAFT_SAVED", "APPLICATION_SUBMITTED", "DOCUMENT_UPLOADED", "DOCUMENT_TEXT_EDITED", "AI_ANALYSIS_RUN", "REVIEW_DOCUMENTS_REQUESTED", "REVIEW_START_REVIEW", "REVIEW_COMPLETE", "REVIEW_REQUEST_DOCUMENTS", "REVIEW_RECOMMEND_APPROVE", "REVIEW_RECOMMEND_DECLINE", "REVIEW_ESCALATE", "APPLICATION_DECISION_RECORDED"])
    ).order_by(AuditLog.created_at.desc()).limit(100)).all()
    return [{"id": x.id, "action": x.action, "created_at": x.created_at.isoformat(), "message": x.action.replace("_", " ").title()} for x in logs]

@router.get("/{aid}/estimates")
def estimates(aid: int, db: Session = Depends(get_db), u: Customer = Depends(current_customer)):
    a = owned(db, aid, u.id)
    monthly_income = _number(_detail(a, "employment", "monthly_income", 0))
    annual_for_estimate = a.annual_income if a.annual_income > 0 else monthly_income * 12
    result = estimate_metrics(a.property_value, a.requested_loan, annual_for_estimate, a.monthly_debt, a.interest_rate, a.tenure_years)
    if a.annual_income <= 0 and monthly_income > 0:
        result["income_basis"] = "Estimated from declared monthly income × 12; not a verified annual income."
    return result
