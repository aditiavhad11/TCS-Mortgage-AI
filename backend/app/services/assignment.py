"""Deterministic, bank-isolated AUTOMATIC reviewer assignment.

Rules
- Runs only for submitted applications (never DRAFT) and never from a Bank Admin action.
- Eligible reviewer = same bank, is_active, is_available, below max_active_assignments.
- Selection = general reviewers first, then lowest current workload, then the reviewer who
  has waited longest since their last assignment, then lowest id (fully deterministic).
- Workload counts only active assignments on applications that are not finished.
- Duplicate / concurrent assignment is prevented by the UNIQUE(application_id) constraint,
  a reviewer-row lock + capacity re-check inside a SAVEPOINT (PostgreSQL), and idempotent reads.
- No eligible reviewer, or any unexpected error => the submitted application is KEPT, flagged
  `awaiting_assignment` / status PENDING_ASSIGNMENT ("Awaiting Reviewer Assignment") and retried
  when a reviewer is created/activated/becomes available/frees capacity, and by a background loop.
- Every decision is written to `assignment_events` (with timestamps) and the audit log.
Assignment decisions never come from an LLM.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import func, select, and_, or_, case
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.models import (MortgageApplication, Reviewer, ReviewAssignment, AssignmentEvent, AuditLog, Bank,
                        CustomerNotification, ReviewerNotification)

log = logging.getLogger("assignment")

PENDING_STATUS = "PENDING_ASSIGNMENT"
PENDING_LABEL = "Awaiting Reviewer Assignment"
# Statuses in which a review is finished: they no longer consume reviewer capacity.
TERMINAL_STATUSES = ["APPROVED", "CANCELLED", "CLOSED", "COMPLETED", "DECLINED", "REJECTED", "WITHDRAWN"]
# Statuses from which an automatic assignment may be made.
ASSIGNABLE_STATUSES = ["SUBMITTED", PENDING_STATUS]
SYSTEM_EMAIL = "system@mortgage-ai.local"
GENERAL_SPECIALISATIONS = ["GENERAL_MORTGAGE_REVIEW", "GENERAL", "ALL"]


class _CapacityExceeded(Exception):
    pass


def _now():
    return datetime.now(timezone.utc)


def status_label(status: str, awaiting: bool = False) -> str:
    if awaiting or status == PENDING_STATUS:
        return PENDING_LABEL
    return (status or "").replace("_", " ").title()


def _event(db, application, reviewer_id, event_type, reason=""):
    db.add(AssignmentEvent(application_id=application.id, reviewer_id=reviewer_id, event_type=event_type, reason=(reason or "")[:500], created_at=_now()))


def _audit(db, action, application, detail):
    db.add(AuditLog(actor_email=SYSTEM_EMAIL, actor_role="SYSTEM", action=action, resource_type="application", resource_id=str(application.id), detail=detail[:1000]))


def reviewer_load(db: Session, reviewer_id: int) -> int:
    """Active, unfinished assignments held by a reviewer."""
    return db.scalar(
        select(func.count()).select_from(ReviewAssignment)
        .join(MortgageApplication, MortgageApplication.id == ReviewAssignment.application_id)
        .where(ReviewAssignment.reviewer_id == reviewer_id, ReviewAssignment.active.is_(True), MortgageApplication.status.notin_(TERMINAL_STATUSES))
    ) or 0


def _mark_pending(db, application, reason):
    """Flag the submitted application as awaiting assignment. Logs history only on the first transition."""
    first = not application.awaiting_assignment or application.status != PENDING_STATUS
    application.status = PENDING_STATUS
    application.awaiting_assignment = True
    application.assignment_attempts = (application.assignment_attempts or 0) + 1
    application.last_assignment_attempt_at = _now()
    if first:
        _event(db, application, None, "PENDING_ASSIGNMENT", reason)
        _audit(db, "APPLICATION_ASSIGNMENT_PENDING", application, f"reason={reason[:300]}")
        db.add(CustomerNotification(customer_id=application.customer_id, application_id=application.id, title="Awaiting reviewer assignment", message=f"Application {application.reference} was submitted and is waiting for an eligible reviewer. It will be assigned automatically; you do not need to select a reviewer.", event_type="ASSIGNMENT_PENDING"))


def _resolve_bank(db, application):
    if application.bank_id is not None:
        return db.get(Bank, application.bank_id)
    lender = (application.lender_name or "").strip()
    return db.scalar(select(Bank).where((Bank.code == lender.upper()) | (Bank.name == lender)))


def _candidates(db, application, bank):
    lender = (application.lender_name or "").strip().upper()
    workload = (
        select(ReviewAssignment.reviewer_id.label("reviewer_id"), func.count().label("load"))
        .join(MortgageApplication, MortgageApplication.id == ReviewAssignment.application_id)
        .where(ReviewAssignment.active.is_(True), MortgageApplication.status.notin_(TERMINAL_STATUSES))
        .group_by(ReviewAssignment.reviewer_id).subquery()
    )
    load = func.coalesce(workload.c.load, 0)
    if bank:
        same_bank = or_(Reviewer.bank_id == bank.id, and_(Reviewer.bank_id.is_(None), func.upper(func.trim(Reviewer.bank_code)) == bank.code.strip().upper()))
    else:
        same_bank = and_(Reviewer.bank_id.is_(None), func.upper(func.trim(Reviewer.bank_code)) == lender)
    return db.execute(
        select(Reviewer, load.label("load"))
        .outerjoin(workload, workload.c.reviewer_id == Reviewer.id)
        .where(Reviewer.is_active.is_(True), Reviewer.is_available.isnot(False), same_bank, load < Reviewer.max_active_assignments)
        .order_by(
            case((func.upper(Reviewer.specialisation).in_(GENERAL_SPECIALISATIONS), 0), else_=1),
            load.asc(),
            case((Reviewer.last_assigned_at.is_(None), 0), else_=1),
            Reviewer.last_assigned_at.asc(),
            Reviewer.id.asc(),
        )
    ).all()


def _active_assignment(db, application):
    return db.scalar(select(ReviewAssignment).where(ReviewAssignment.application_id == application.id, ReviewAssignment.active.is_(True)))


def _finish_assignment(db, application, reviewer, load):
    now = _now()
    reviewer.last_assigned_at = now
    application.status = "ASSIGNED"
    application.awaiting_assignment = False
    application.assignment_attempts = (application.assignment_attempts or 0) + 1
    application.last_assignment_attempt_at = now
    _event(db, application, reviewer.id, "ASSIGNED", f"automatic assignment; specialisation={reviewer.specialisation}; workload_before={load}")
    _audit(db, "APPLICATION_AUTO_ASSIGNED", application, f"reviewer_id={reviewer.id}; bank_code={reviewer.bank_code}; workload_before={load}")
    db.add(CustomerNotification(customer_id=application.customer_id, application_id=application.id, title="Application assigned for review", message=f"Application {application.reference} has entered the bank review workflow. You cannot choose or change the assigned reviewer.", event_type="APPLICATION_ASSIGNED"))
    db.add(ReviewerNotification(reviewer_id=reviewer.id, application_id=application.id, title="New application assigned", message=f"Application {application.reference} was automatically assigned to you. Open your review queue to start.", event_type="APPLICATION_ASSIGNED"))


def _assign(db, application, notify_resubmission):
    if application.status == "DRAFT":  # drafts are never assigned
        return None
    current = _active_assignment(db, application)
    if current:  # idempotent: never create a second assignment
        if application.status in ASSIGNABLE_STATUSES + ["DOCUMENTS_REQUESTED", "ADDITIONAL_INFORMATION_REQUIRED"]:
            was_resubmission = application.status == "SUBMITTED"
            application.status = "ASSIGNED"
            application.awaiting_assignment = False
            if notify_resubmission and was_resubmission:
                _event(db, application, current.reviewer_id, "RESUBMITTED", "customer resubmitted; existing reviewer retained")
                db.add(ReviewerNotification(reviewer_id=current.reviewer_id, application_id=application.id, title="Application resubmitted", message=f"Application {application.reference} was resubmitted by the customer.", event_type="APPLICATION_RESUBMITTED"))
        return current
    if application.status not in ASSIGNABLE_STATUSES:
        return None
    if not (application.lender_name or "").strip() and application.bank_id is None:
        return None

    bank = _resolve_bank(db, application)
    if application.bank_id is not None and bank is None:
        _mark_pending(db, application, "Invalid bank reference")
        return None
    if bank is not None and bank.status != "APPROVED":
        _mark_pending(db, application, "Bank is not approved")
        return None
    if bank is not None:
        application.bank_id = bank.id

    for reviewer, load in _candidates(db, application, bank):
        try:
            # SAVEPOINT: a lost race rolls back only this attempt, never the caller's submission.
            with db.begin_nested():
                db.execute(select(Reviewer.id).where(Reviewer.id == reviewer.id).with_for_update())  # row lock on PostgreSQL; no-op on SQLite
                assignment = ReviewAssignment(application_id=application.id, reviewer_id=reviewer.id, assigned_by="system:auto-assignment", assigned_at=_now(), active=True)
                db.add(assignment)
                db.flush()
                if reviewer_load(db, reviewer.id) > reviewer.max_active_assignments:
                    raise _CapacityExceeded()
        except _CapacityExceeded:
            continue  # another submission took the last slot; try the next reviewer
        except IntegrityError:
            winner = _active_assignment(db, application)
            if winner:  # a concurrent request assigned this application first
                application.status = "ASSIGNED"
                application.awaiting_assignment = False
                return winner
            _mark_pending(db, application, "Concurrent assignment conflict; retry required")
            return None
        _finish_assignment(db, application, reviewer, load)
        db.flush()
        return assignment

    _mark_pending(db, application, "No active, available same-bank reviewer with capacity")
    return None


def auto_assign_application(db: Session, application: MortgageApplication, notify_resubmission: bool = False) -> ReviewAssignment | None:
    """Assign a submitted application to an eligible same-bank reviewer, or keep it awaiting assignment.

    Never raises for assignment problems: the submission is always retained. The caller commits.
    """
    try:
        with db.begin_nested():
            return _assign(db, application, notify_resubmission)
    except Exception as exc:  # noqa: BLE001 - submission must survive any assignment failure
        log.exception("Automatic assignment failed for application %s", getattr(application, "id", "?"))
        try:
            _mark_pending(db, application, f"Assignment error: {type(exc).__name__}")
            db.flush()
        except Exception:  # pragma: no cover - last resort, keep the request alive
            log.exception("Could not flag application %s as awaiting assignment", getattr(application, "id", "?"))
        return None


def release_reviewer_assignments(db: Session, reviewer: Reviewer, reason: str) -> list[MortgageApplication]:
    """Free every unfinished application held by a reviewer (e.g. deactivated) and flag it for automatic reassignment."""
    released = []
    rows = db.scalars(select(ReviewAssignment).where(ReviewAssignment.reviewer_id == reviewer.id, ReviewAssignment.active.is_(True))).all()
    for assignment in rows:
        application = db.get(MortgageApplication, assignment.application_id)
        if application is None or application.status in TERMINAL_STATUSES:
            continue
        _event(db, application, reviewer.id, "REASSIGNMENT_REQUIRED", reason)
        db.delete(assignment)  # UNIQUE(application_id) requires the old row to go; history is kept in assignment_events
        db.flush()
        application.status = PENDING_STATUS
        application.awaiting_assignment = True
        _audit(db, "APPLICATION_REASSIGNMENT_PENDING", application, f"previous_reviewer_id={reviewer.id}; reason={reason[:200]}")
        released.append(application)
    db.flush()
    return released


def _bank_key(application):
    return (application.bank_id, (application.lender_name or "").strip().upper())


def retry_pending_assignments(db: Session, bank_code: str | None = None, bank_id: int | None = None, limit: int = 500) -> int:
    """Retry applications awaiting assignment, oldest first. Safe to call repeatedly (idempotent)."""
    db.flush()
    has_assignment = select(ReviewAssignment.application_id).where(ReviewAssignment.active.is_(True))
    query = select(MortgageApplication).where(
        or_(MortgageApplication.status == PENDING_STATUS, MortgageApplication.awaiting_assignment.is_(True)),
        MortgageApplication.status.notin_(TERMINAL_STATUSES + ["DRAFT"]),
        MortgageApplication.id.notin_(has_assignment),
    )
    code = (bank_code or "").strip().upper()
    if bank_id is not None:
        cond = MortgageApplication.bank_id == bank_id
        if code:
            cond = or_(cond, and_(MortgageApplication.bank_id.is_(None), func.upper(func.trim(MortgageApplication.lender_name)) == code))
        query = query.where(cond)
    elif code:
        query = query.where(func.upper(func.trim(MortgageApplication.lender_name)) == code)
    rows = db.scalars(query.order_by(func.coalesce(MortgageApplication.submitted_at, MortgageApplication.created_at).asc(), MortgageApplication.id.asc()).limit(limit)).all()
    assigned, exhausted = 0, set()
    for application in rows:
        key = _bank_key(application)
        if key in exhausted:  # first failure for a bank means no capacity for the rest of its queue
            continue
        if auto_assign_application(db, application) is not None:
            assigned += 1
        else:
            exhausted.add(key)
    return assigned


def run_retry_cycle() -> int:
    """Background entry point: retry every awaiting application in its own short transaction."""
    from app.database import SessionLocal
    total = 0
    with SessionLocal() as db:
        ids = db.scalars(select(MortgageApplication.id).where(MortgageApplication.awaiting_assignment.is_(True), MortgageApplication.status == PENDING_STATUS).order_by(MortgageApplication.id)).all()
    for app_id in ids:
        with SessionLocal() as db:
            application = db.get(MortgageApplication, app_id)
            if application is None or application.status != PENDING_STATUS:
                continue
            try:
                if auto_assign_application(db, application) is not None:
                    total += 1
                db.commit()
            except Exception:  # noqa: BLE001
                db.rollback()
                log.exception("Retry cycle failed for application %s", app_id)
    return total
