"""Automatic reviewer assignment: service-level rules + the full API workflow.

Customer submits -> reviewer auto-assigned -> reviewer sees it + is notified -> Bank Admin monitors.
No live Tesseract / NVIDIA needed; required-document uploads use a deterministic OCR fixture.
"""
import threading
import pytest
pytest.importorskip("fastapi"); pytest.importorskip("sqlalchemy"); pytest.importorskip("email_validator")
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from app.main import app
from app.database import SessionLocal
from app.models import (Bank, BankAdmin, Customer, MortgageApplication, Reviewer, ReviewAssignment,
                        AssignmentEvent, ReviewerNotification)
from app.security import hash_password, token_for
from app.services.assignment import auto_assign_application, retry_pending_assignments, run_retry_cycle, PENDING_STATUS

client = TestClient(app)
PW = "Str0ng-Passw0rd!xx"
H = lambda tok: {"Authorization": f"Bearer {tok}"}


def mk_bank(db, code):
    bank = Bank(name=f"Bank {code}", code=code, status="APPROVED", contact_email=f"{code.lower()}@bank.example")
    db.add(bank); db.flush(); return bank


def mk_reviewer(db, bank, n, **kw):
    r = Reviewer(full_name=f"Rev {bank.code} {n}", email=f"rev{n}-{bank.code.lower()}@example.com", password_hash=hash_password(PW),
                 bank_code=bank.code, bank_id=bank.id, is_active=True, **kw)
    db.add(r); db.flush(); return r


def mk_customer(db, tag):
    c = Customer(full_name="Cust " + tag, email=f"cust-{tag}@example.com", mobile="9999999999", password_hash=hash_password(PW), is_verified=True)
    db.add(c); db.flush(); return c


def mk_app(db, customer, bank, ref, status="SUBMITTED"):
    a = MortgageApplication(reference=ref, customer_id=customer.id, lender_name=bank.code, bank_id=bank.id, status=status)
    db.add(a); db.flush(); return a


def test_draft_is_never_assigned():
    with SessionLocal() as db:
        bank = mk_bank(db, "AA_DRAFT"); mk_reviewer(db, bank, 1); c = mk_customer(db, "draft")
        a = mk_app(db, c, bank, "AA-DRAFT-1", status="DRAFT")
        assert auto_assign_application(db, a) is None
        assert a.status == "DRAFT" and a.awaiting_assignment is False
        assert retry_pending_assignments(db, bank_id=bank.id) == 0
        db.rollback()


def test_unavailable_and_inactive_reviewers_are_skipped_then_retry_when_available():
    with SessionLocal() as db:
        bank = mk_bank(db, "AA_AVAIL"); c = mk_customer(db, "avail")
        away = mk_reviewer(db, bank, 1, is_available=False)
        off = mk_reviewer(db, bank, 2); off.is_active = False
        a = mk_app(db, c, bank, "AA-AVAIL-1"); a.submitted_at = a.created_at
        assert auto_assign_application(db, a) is None
        assert a.status == PENDING_STATUS and a.awaiting_assignment is True      # retained + flagged
        assert db.scalar(select(func.count()).select_from(ReviewAssignment).where(ReviewAssignment.application_id == a.id)) == 0
        away.is_available = True
        assert retry_pending_assignments(db, bank_id=bank.id) == 1
        assert a.status == "ASSIGNED" and a.awaiting_assignment is False
        assert db.scalar(select(ReviewAssignment).where(ReviewAssignment.application_id == a.id)).reviewer_id == away.id
        db.rollback()


def test_workload_balancing_across_many_submissions_and_no_cross_bank_leak():
    with SessionLocal() as db:
        bank, other = mk_bank(db, "AA_BAL"), mk_bank(db, "AA_OTHER"); c = mk_customer(db, "bal")
        r1, r2, r3 = (mk_reviewer(db, bank, i) for i in (1, 2, 3)); foreign = mk_reviewer(db, other, 9)
        for i in range(6):
            assert auto_assign_application(db, mk_app(db, c, bank, f"AA-BAL-{i}")) is not None
        loads = {r.id: db.scalar(select(func.count()).select_from(ReviewAssignment).where(ReviewAssignment.reviewer_id == r.id)) for r in (r1, r2, r3, foreign)}
        assert loads[r1.id] == loads[r2.id] == loads[r3.id] == 2 and loads[foreign.id] == 0
        db.rollback()


def test_capacity_is_respected_and_completed_reviews_free_capacity():
    with SessionLocal() as db:
        bank = mk_bank(db, "AA_CAP"); c = mk_customer(db, "cap")
        r = mk_reviewer(db, bank, 1, max_active_assignments=1)
        first, second = mk_app(db, c, bank, "AA-CAP-1"), mk_app(db, c, bank, "AA-CAP-2")
        assert auto_assign_application(db, first) is not None
        assert auto_assign_application(db, second) is None and second.status == PENDING_STATUS
        first.status = "COMPLETED"; db.flush()                       # capacity freed
        assert retry_pending_assignments(db, bank_id=bank.id) == 1 and second.status == "ASSIGNED"
        db.rollback()


def test_duplicate_assignment_is_idempotent_and_history_has_timestamps():
    with SessionLocal() as db:
        bank = mk_bank(db, "AA_DUP"); c = mk_customer(db, "dup"); mk_reviewer(db, bank, 1); mk_reviewer(db, bank, 2)
        a = mk_app(db, c, bank, "AA-DUP-1")
        one = auto_assign_application(db, a); a.status = "SUBMITTED"; two = auto_assign_application(db, a)
        assert one.id == two.id
        assert db.scalar(select(func.count()).select_from(ReviewAssignment).where(ReviewAssignment.application_id == a.id)) == 1
        events = db.scalars(select(AssignmentEvent).where(AssignmentEvent.application_id == a.id)).all()
        assert [e.event_type for e in events] == ["ASSIGNED"] and events[0].created_at is not None
        assert db.scalar(select(func.count()).select_from(ReviewerNotification).where(ReviewerNotification.application_id == a.id)) == 1
        db.rollback()


def test_background_retry_cycle_assigns_waiting_applications():
    with SessionLocal() as db:
        bank = mk_bank(db, "AA_LOOP"); c = mk_customer(db, "loop")
        a = mk_app(db, c, bank, "AA-LOOP-1"); auto_assign_application(db, a)
        assert a.status == PENDING_STATUS
        mk_reviewer(db, bank, 1); db.commit(); aid = a.id
    assert run_retry_cycle() >= 1
    with SessionLocal() as db:
        assert db.get(MortgageApplication, aid).status == "ASSIGNED"


def test_assignment_error_keeps_submission_and_flags_it(monkeypatch):
    import app.services.assignment as svc
    with SessionLocal() as db:
        bank = mk_bank(db, "AA_ERR"); c = mk_customer(db, "err"); mk_reviewer(db, bank, 1)
        a = mk_app(db, c, bank, "AA-ERR-1")
        monkeypatch.setattr(svc, "_candidates", lambda *x, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        assert auto_assign_application(db, a) is None
        assert a.status == PENDING_STATUS and a.awaiting_assignment is True
        monkeypatch.undo()
        assert retry_pending_assignments(db, bank_id=bank.id) == 1
        db.rollback()


def test_full_api_workflow_submit_assign_reviewer_sees_bank_admin_monitors(monkeypatch):
    with SessionLocal() as db:
        bank = mk_bank(db, "AA_E2E")
        cust = mk_customer(db, "e2e")
        rev = mk_reviewer(db, bank, 1)
        admin = BankAdmin(bank_id=bank.id, full_name="E2E Admin", email="e2e-admin@example.com", password_hash=hash_password(PW), is_active=True)
        db.add(admin); db.commit()
        cust_id, rev_id, admin_id, bank_code = cust.id, rev.id, admin.id, bank.code
    c_tok, r_tok, a_tok = token_for(cust_id), token_for(f"reviewer:{rev_id}"), token_for(f"bankadmin:{admin_id}")

    payload = {"lender_name": bank_code, "product_name": "Home Loan", "property_address": "Pune", "property_value": 5000000, "requested_loan": 4000000,
               "annual_income": 1200000, "monthly_debt": 0, "interest_rate": 8.5, "tenure_years": 20,
               "details": {"applicant": {"full_name": "E2E", "date_of_birth": "1990-01-01", "mobile": "9999999999", "email": "cust-e2e@example.com", "residential_address": "Pune"},
                           "loan": {"purpose": "Home Purchase"}, "employment": {"employment_type": "Salaried", "occupation": "Engineer", "employer_name": "X", "monthly_income": 100000},
                           "property": {"property_type": "Apartment / Flat"}},
               "consents": {"truthful_information": True, "privacy_consent": True}}
    created = client.post("/api/v1/applications", headers=H(c_tok), json=payload)
    assert created.status_code in (200, 201), created.text
    aid = created.json()["id"]

    # draft: nothing assigned, reviewer queue empty, bank admin sees no draft
    assert client.get("/api/v1/reviewer/applications", headers=H(r_tok)).json() == []
    assert aid not in [x["id"] for x in client.get("/api/v1/bank-admin/applications", headers=H(a_tok)).json()]

    # Submission correctly requires minimum evidence documents. Use valid images and a
    # deterministic OCR fixture so the workflow test does not depend on Tesseract.
    import io
    from PIL import Image
    image = io.BytesIO(); Image.new("RGB", (40, 40), "white").save(image, "PNG")
    monkeypatch.setattr("app.routers.documents.extract_text", lambda path: ("Applicant name: E2E\nAnnual income: 1200000\nProperty value: 5000000", "COMPLETED", "Test OCR extraction"))
    for category, filename in [("Bank Statement", "bank.png"), ("Income Proof / Salary Slip", "salary.png"), ("KYC", "kyc.png"), ("Property Title", "title.png"), ("Sale / Purchase Agreement", "agreement.png")]:
        uploaded = client.post(f"/api/v1/applications/{aid}/documents", headers=H(c_tok), data={"category": category}, files={"file": (filename, image.getvalue(), "image/png")})
        assert uploaded.status_code == 200, uploaded.text
    submitted = client.post(f"/api/v1/applications/{aid}/submit", headers=H(c_tok))
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "ASSIGNED"                                   # assigned in the same request, no manual step

    # reviewer sees it + notification
    assert [x["id"] for x in client.get("/api/v1/reviewer/applications", headers=H(r_tok)).json()] == [aid]
    notes = client.get("/api/v1/reviewer/notifications", headers=H(r_tok)).json()
    assert len(notes) == 1 and notes[0]["application_id"] == aid and notes[0]["read"] is False
    assert client.get("/api/v1/reviewer/me", headers=H(r_tok)).json()["unread_notifications"] == 1
    assert client.post(f"/api/v1/reviewer/notifications/{notes[0]['id']}/read", headers=H(r_tok)).status_code == 200
    assert client.get("/api/v1/reviewer/me", headers=H(r_tok)).json()["unread_notifications"] == 0

    # bank admin monitors; cannot assign manually
    dash = client.get("/api/v1/bank-admin/dashboard", headers=H(a_tok)).json()
    assert dash["active_assignments"] == 1 and dash["awaiting_assignment"] == 0 and dash["assignment_mode"] == "AUTOMATIC"
    row = next(x for x in client.get("/api/v1/bank-admin/applications", headers=H(a_tok)).json() if x["id"] == aid)
    assert row["reviewer_email"] == f"rev1-{bank_code.lower()}@example.com" and row["assigned_at"]
    hist = client.get(f"/api/v1/bank-admin/assignment-history?application_id={aid}", headers=H(a_tok)).json()
    assert [h["event_type"] for h in hist] == ["ASSIGNED"] and hist[0]["created_at"]
    for method in ("post", "put", "patch"):
        assert getattr(client, method)("/api/v1/bank-admin/assignments", headers=H(a_tok), json={"application_id": aid, "reviewer_id": rev_id}).status_code == 403
        assert getattr(client, method)(f"/api/v1/bank-admin/applications/{aid}/assign", headers=H(a_tok), json={"reviewer_id": rev_id}).status_code == 403

    # reviewer goes unavailable -> next submission waits (kept + flagged) -> becomes available -> auto-assigned
    assert client.patch("/api/v1/reviewer/availability?available=false", headers=H(r_tok)).json()["is_available"] is False
    p2 = client.post("/api/v1/applications", headers=H(c_tok), json=payload).json()["id"]
    for category, filename in [("Bank Statement", "bank2.png"), ("Income Proof / Salary Slip", "salary2.png"), ("KYC", "kyc2.png"), ("Property Title", "title2.png"), ("Sale / Purchase Agreement", "agreement2.png")]:
        uploaded = client.post(f"/api/v1/applications/{p2}/documents", headers=H(c_tok), data={"category": category}, files={"file": (filename, image.getvalue(), "image/png")})
        assert uploaded.status_code == 200, uploaded.text
    waiting_response = client.post(f"/api/v1/applications/{p2}/submit", headers=H(c_tok))
    assert waiting_response.status_code == 200, waiting_response.text
    waiting = waiting_response.json()
    assert waiting["status"] == "PENDING_ASSIGNMENT" and waiting["awaiting_assignment"] is True and waiting["status_label"] == "Awaiting Reviewer Assignment"
    assert client.get("/api/v1/bank-admin/dashboard", headers=H(a_tok)).json()["awaiting_assignment"] == 1
    back = client.patch("/api/v1/reviewer/availability?available=true", headers=H(r_tok)).json()
    assert back["newly_assigned"] == 1
    assert client.get(f"/api/v1/applications/{p2}", headers=H(c_tok)).json()["status"] == "ASSIGNED"
    assert sorted(x["id"] for x in client.get("/api/v1/reviewer/applications", headers=H(r_tok)).json()) == sorted([aid, p2])
    types = [h["event_type"] for h in client.get(f"/api/v1/bank-admin/assignment-history?application_id={p2}", headers=H(a_tok)).json()]
    assert types == ["ASSIGNED", "PENDING_ASSIGNMENT"]                               # newest first


def test_concurrent_submissions_never_double_assign_or_exceed_capacity():
    """Threads race on the same single-slot reviewer; exactly one wins, the rest wait."""
    with SessionLocal() as db:
        bank = mk_bank(db, "AA_RACE"); c = mk_customer(db, "race"); mk_reviewer(db, bank, 1, max_active_assignments=1)
        ids = [mk_app(db, c, bank, f"AA-RACE-{i}").id for i in range(4)]; db.commit()
    def work(app_id):
        with SessionLocal() as db:
            auto_assign_application(db, db.get(MortgageApplication, app_id)); db.commit()
    threads = [threading.Thread(target=work, args=(i,)) for i in ids]
    [t.start() for t in threads]; [t.join() for t in threads]
    with SessionLocal() as db:
        assigned = db.scalar(select(func.count()).select_from(ReviewAssignment).where(ReviewAssignment.application_id.in_(ids), ReviewAssignment.active.is_(True)))
        assert assigned == 1
