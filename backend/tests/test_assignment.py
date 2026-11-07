from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.models import MortgageApplication, Reviewer, ReviewAssignment, AuditLog
from app.services.assignment import auto_assign_application


def session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return Session(engine)


def test_auto_assign_uses_exact_bank_and_least_workload():
    with session_factory() as db:
        app = MortgageApplication(reference="MRT-TEST01", customer_id=1, status="SUBMITTED", lender_name="BANK-A")
        # Create a minimal customer to satisfy the FK.
        from app.models import Customer
        customer = Customer(full_name="Test Customer", email="customer@example.test", mobile="12345678", password_hash="unused", is_verified=True)
        db.add(customer); db.flush(); app.customer_id = customer.id; db.add(app)
        a = Reviewer(full_name="Reviewer A", email="a@example.test", password_hash="unused", bank_code="BANK-A", is_active=True)
        b = Reviewer(full_name="Reviewer B", email="b@example.test", password_hash="unused", bank_code="BANK-A", is_active=True)
        other = Reviewer(full_name="Reviewer Other", email="other@example.test", password_hash="unused", bank_code="BANK-B", is_active=True)
        db.add_all([a, b, other]); db.flush()
        # Give A a higher workload; B must be selected. The workload assignment's
        # application row is not required for this isolated count query.
        existing_app = MortgageApplication(reference="MRT-TEST02", customer_id=customer.id, status="IN_REVIEW", lender_name="BANK-A")
        db.add(existing_app); db.flush()
        db.add(ReviewAssignment(application_id=existing_app.id, reviewer_id=a.id, assigned_by="test", active=True)); db.flush()
        row = auto_assign_application(db, app)
        assert row is not None and row.reviewer_id == b.id
        assert db.scalar(select(AuditLog).where(AuditLog.action == "APPLICATION_AUTO_ASSIGNED")) is not None


def test_auto_assign_leaves_application_unassigned_without_exact_bank_match():
    with session_factory() as db:
        from app.models import Customer
        customer = Customer(full_name="Test Customer", email="customer2@example.test", mobile="12345678", password_hash="unused", is_verified=True)
        db.add(customer); db.flush()
        app = MortgageApplication(reference="MRT-TEST03", customer_id=customer.id, status="SUBMITTED", lender_name="BANK-X")
        db.add(app); db.flush()
        db.add(Reviewer(full_name="Reviewer", email="reviewer@example.test", password_hash="unused", bank_code="BANK-DEMO", is_active=True)); db.flush()
        assert auto_assign_application(db, app) is None
        assert db.scalar(select(ReviewAssignment).where(ReviewAssignment.application_id == app.id)) is None


def test_auto_assign_accepts_legacy_reviewer_for_exact_approved_bank_code():
    from app.models import Bank, Customer
    with session_factory() as db:
        bank = Bank(name="Bank Legacy", code="BANK-L", contact_email="ops@bank-l.example", status="APPROVED")
        customer = Customer(full_name="Legacy Customer", email="legacy@example.test", mobile="123456789", password_hash="unused", is_verified=True)
        db.add_all([bank, customer]); db.flush()
        app = MortgageApplication(reference="MRT-LEGACY01", customer_id=customer.id, status="SUBMITTED", lender_name="BANK-L", bank_id=bank.id)
        legacy = Reviewer(full_name="Legacy Reviewer", email="legacy-reviewer@example.test", password_hash="unused", bank_code="BANK-L", bank_id=None, is_active=True)
        db.add_all([app, legacy]); db.flush()
        assigned = auto_assign_application(db, app)
        assert assigned is not None
        assert assigned.reviewer_id == legacy.id

def test_auto_assignment_respects_capacity_and_prefers_general_reviewers():
    with session_factory() as db:
        from app.models import Customer
        customer = Customer(full_name="Capacity Customer", email="capacity@example.test", mobile="1234567890", password_hash="unused", is_verified=True)
        db.add(customer); db.flush()
        existing_app = MortgageApplication(reference="MRT-CAP01", customer_id=customer.id, status="ASSIGNED", lender_name="BANK-CAP")
        new_app = MortgageApplication(reference="MRT-CAP02", customer_id=customer.id, status="SUBMITTED", lender_name="BANK-CAP")
        db.add_all([existing_app, new_app]); db.flush()
        general = Reviewer(full_name="General Reviewer", email="general-cap@example.test", password_hash="unused", bank_code="BANK-CAP", is_active=True, specialisation="GENERAL_MORTGAGE_REVIEW", max_active_assignments=1)
        specialist = Reviewer(full_name="Property Specialist", email="property-cap@example.test", password_hash="unused", bank_code="BANK-CAP", is_active=True, specialisation="PROPERTY_VALUATION", max_active_assignments=5)
        db.add_all([general, specialist]); db.flush()
        db.add(ReviewAssignment(application_id=existing_app.id, reviewer_id=general.id, assigned_by="test", active=True)); db.flush()
        assigned = auto_assign_application(db, new_app)
        assert assigned is not None and assigned.reviewer_id == specialist.id
        assert new_app.status == "ASSIGNED"


def test_pending_assignment_retries_automatically_when_reviewer_becomes_available():
    with session_factory() as db:
        from app.models import Customer
        from app.services.assignment import retry_pending_assignments
        customer = Customer(full_name="Pending Customer", email="pending@example.test", mobile="1234567890", password_hash="unused", is_verified=True)
        db.add(customer); db.flush()
        app = MortgageApplication(reference="MRT-PENDING01", customer_id=customer.id, status="SUBMITTED", lender_name="BANK-PENDING")
        db.add(app); db.flush()
        assert auto_assign_application(db, app) is None
        assert app.status == "PENDING_ASSIGNMENT"
        reviewer = Reviewer(full_name="New Reviewer", email="new-pending@example.test", password_hash="unused", bank_code="BANK-PENDING", is_active=True)
        db.add(reviewer); db.flush()
        assert retry_pending_assignments(db, bank_code="BANK-PENDING") == 1
        assert app.status == "ASSIGNED"
        assert db.scalar(select(ReviewAssignment).where(ReviewAssignment.application_id == app.id, ReviewAssignment.active.is_(True))) is not None
