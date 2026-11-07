from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models import PlatformAdmin
from app.security import hash_password
from app.security import token_for_admin_otp
from app.config import settings
from sqlalchemy import select, func

client = TestClient(app)
PW = "BankAdmin-Test-Password-2026!"
def headers(token): return {"Authorization": f"Bearer {token}"}

def test_platform_admin_bank_approval_invitation_and_bank_admin_scope(monkeypatch):
    delivered=[]
    monkeypatch.setattr("app.routers.admin.send_email", lambda _to, _subject, body: delivered.append(body))
    monkeypatch.setattr("app.routers.bank_admin.send_email", lambda _to, _subject, body: delivered.append(body))
    email = "platform-banks-test@example.com"
    settings.initial_admin_email = email
    with SessionLocal() as db:
        admin = db.query(PlatformAdmin).filter_by(email=email).first()
        if not admin:
            admin = PlatformAdmin(full_name="Platform Test Admin", email=email, password_hash=hash_password(PW), is_active=True)
            db.add(admin); db.commit(); db.refresh(admin)
        admin_id = admin.id
    admin_token = token_for_admin_otp(f"admin:{admin_id}")
    bank_r = client.post("/api/v1/admin/banks", headers=headers(admin_token), json={"name":"Test Bank Scoped","code":"TBSCOPE","institution_type":"Other","contact_email":"contact@testbank.example","contact_phone":"9876543210","address":"1 Test Finance Road, Pune, Maharashtra","ifsc_code":"","license_number":""})
    assert bank_r.status_code == 201, bank_r.text
    bank = bank_r.json(); assert bank["status"] == "PENDING"
    assert client.post("/api/v1/admin/bank-invitations", headers=headers(admin_token), json={"bank_id":bank["id"],"full_name":"Scoped Admin","email":"scoped-admin@example.com"}).status_code == 409
    approved = client.patch(f"/api/v1/admin/banks/{bank['id']}/status?status=APPROVED", headers=headers(admin_token))
    assert approved.status_code == 200 and approved.json()["status"] == "APPROVED"
    inv = client.post("/api/v1/admin/bank-invitations", headers=headers(admin_token), json={"bank_id":bank["id"],"full_name":"Scoped Admin","email":"scoped-admin@example.com"})
    assert inv.status_code == 201, inv.text
    assert "invitation_token" not in inv.json()
    token = delivered[-1].split("invite=")[1].split()[0]
    accepted = client.post("/api/v1/bank-admin/accept-invitation", json={"token":token,"password":"Scoped-Bank-Admin-Password-2026!"})
    assert accepted.status_code == 200, accepted.text
    assert client.post("/api/v1/bank-admin/accept-invitation", json={"token":token,"password":"Another-Password-2026!"}).status_code == 400
    login2 = client.post("/api/v1/bank-admin/login", json={"email":"scoped-admin@example.com","password":"Scoped-Bank-Admin-Password-2026!"})
    assert login2.status_code == 200, login2.text
    bank_token = login2.json()["access_token"]
    assert client.get("/api/v1/bank-admin/me", headers=headers(bank_token)).json()["bank"]["code"] == "TBSCOPE"
    dashboard = client.get("/api/v1/bank-admin/dashboard", headers=headers(bank_token))
    assert dashboard.status_code == 200, dashboard.text
    assert dashboard.json()["bank"]["code"] == "TBSCOPE"
    created = client.post("/api/v1/bank-admin/reviewers", headers=headers(bank_token), json={"full_name":"Scoped Reviewer","email":"scoped-reviewer@example.com"})
    assert created.status_code == 201, created.text
    assert created.json()["account_status"] == "INVITATION_PENDING" and created.json()["delivery"] == "EMAIL_SENT"
    assert client.get("/api/v1/admin/banks", headers=headers(bank_token)).status_code in (401, 403)
    assert client.get("/api/v1/bank-admin/dashboard", headers=headers(admin_token)).status_code == 403
    assert client.get("/api/v1/bank-admin/reviewers", headers=headers(bank_token)).json()[0]["email"] == "scoped-reviewer@example.com"

def test_bank_policy_retrieval_is_scoped_and_global_policies_remain_visible():
    from app.models import Bank, PolicyDocument
    from app.services.policy_rag import retrieve_policy_chunks
    with SessionLocal() as db:
        bank_a = Bank(name="RAG Scope Bank A", code="RAG_A", status="APPROVED", contact_email="a@rag.example")
        bank_b = Bank(name="RAG Scope Bank B", code="RAG_B", status="APPROVED", contact_email="b@rag.example")
        db.add_all([bank_a, bank_b]); db.flush()
        db.add_all([
            PolicyDocument(title="Global Repayment Policy", policy_version="1", category="Fees", content="Early repayment fee is described in the global mortgage policy.", active=True, created_by="test"),
            PolicyDocument(title="Bank A Repayment Policy", policy_version="1", category="Fees", content="Early repayment fee for Bank A is 1 percent under this approved policy.", active=True, created_by="test", bank_id=bank_a.id),
            PolicyDocument(title="Bank B Secret Policy", policy_version="1", category="Fees", content="Early repayment fee for Bank B is 9 percent confidential policy.", active=True, created_by="test", bank_id=bank_b.id),
        ]); db.commit()
        rows = retrieve_policy_chunks(db, "early repayment fee", bank_id=bank_a.id)
        titles = {x["title"] for x in rows}
        assert "Global Repayment Policy" in titles
        assert "Bank A Repayment Policy" in titles
        assert "Bank B Secret Policy" not in titles


def test_bank_policy_api_accepts_verified_legacy_role_subject_and_stays_bank_scoped():
    import jwt
    from datetime import datetime, timedelta, timezone
    from app.models import Bank, BankAdmin, PolicyDocument
    from app.config import settings
    with SessionLocal() as db:
        one=Bank(name="Policy API Bank One",code="POLICY_API_ONE",status="APPROVED",contact_email="one@policy-api.example")
        two=Bank(name="Policy API Bank Two",code="POLICY_API_TWO",status="APPROVED",contact_email="two@policy-api.example")
        db.add_all([one,two]);db.flush()
        admin=BankAdmin(bank_id=one.id,full_name="Policy API Admin",email="policy-api-admin@example.com",password_hash=hash_password(PW))
        db.add(admin)
        db.add_all([PolicyDocument(bank_id=one.id,title="Own Bank Policy",policy_version="1",category="Mortgage",content="Bank scoped policy content for API authorization testing.",created_by="test"),PolicyDocument(bank_id=two.id,title="Other Bank Policy",policy_version="1",category="Mortgage",content="Secret from another bank that must not be listed.",created_by="test")])
        db.commit();admin_id=admin.id
    expiry=datetime.now(timezone.utc)+timedelta(minutes=20)
    legacy=jwt.encode({"sub":f"bank_admin:{admin_id}","role":"BANK_ADMIN","iat":datetime.now(timezone.utc),"exp":expiry},settings.jwt_secret_key,algorithm="HS256")
    policies=client.get("/api/v1/bank-admin/policies",headers=headers(legacy))
    assert policies.status_code==200,policies.text
    assert [x["title"] for x in policies.json()]==["Own Bank Policy"]
    wrong_role=jwt.encode({"sub":f"bank_admin:{admin_id}","role":"PLATFORM_ADMIN","iat":datetime.now(timezone.utc),"exp":expiry},settings.jwt_secret_key,algorithm="HS256")
    assert client.get("/api/v1/bank-admin/policies",headers=headers(wrong_role)).status_code==403


def test_bank_policy_qa_retrieves_only_the_authenticated_admin_bank(monkeypatch):
    import jwt
    from datetime import datetime, timedelta, timezone
    from app.models import Bank, BankAdmin
    from app.config import settings

    with SessionLocal() as db:
        own_bank = Bank(name="Policy QA Own Bank", code="POLICY_QA_OWN", status="APPROVED", contact_email="own@policy-qa.example")
        other_bank = Bank(name="Policy QA Other Bank", code="POLICY_QA_OTHER", status="APPROVED", contact_email="other@policy-qa.example")
        db.add_all([own_bank, other_bank]); db.flush()
        admin = BankAdmin(bank_id=own_bank.id, full_name="Policy QA Admin", email="policy-qa-admin@example.com", password_hash=hash_password(PW))
        db.add(admin); db.commit()
        admin_id, own_bank_id = admin.id, own_bank.id

    expires = datetime.now(timezone.utc) + timedelta(minutes=20)
    token = jwt.encode({"sub": f"bank_admin:{admin_id}", "role": "BANK_ADMIN", "iat": datetime.now(timezone.utc), "exp": expires}, settings.jwt_secret_key, algorithm="HS256")
    calls = []

    async def scoped_retrieve(_db, question, limit, bank_id):
        calls.append(("retrieve", bank_id))
        return ([{"policy_id": 1, "bank_id": bank_id, "title": "Own Bank Policy", "policy_version": "3", "category": "Mortgage", "text": "Mortgage fees are listed in this policy."}], "vector")

    async def answer(question, sources):
        calls.append(("answer", [source["bank_id"] for source in sources]))
        return {"answer": "The retrieved evidence describes the policy fees.", "citations": [], "grounded": False}

    monkeypatch.setattr("app.routers.bank_admin.retrieve_hybrid", scoped_retrieve)
    monkeypatch.setattr("app.routers.bank_admin.answer_policy_question", answer)
    response = client.post("/api/v1/bank-admin/policies/qa", headers=headers(token), json={"question": "What mortgage fees apply?"})

    assert response.status_code == 200, response.text
    assert calls == [("retrieve", own_bank_id), ("answer", [own_bank_id])]
    assert response.json()["retrieval_status"] == "RETRIEVED"


def test_bank_reviewer_edit_is_scoped_unique_and_respects_live_workload():
    from app.models import Bank, BankAdmin, Reviewer, Customer, MortgageApplication, ReviewAssignment, AssignmentEvent
    from app.security import token_for
    with SessionLocal() as db:
        bank=Bank(name="Reviewer Edit Bank",code="REVIEWER_EDIT_BANK",status="APPROVED",contact_email="reviewer-edit-bank@example.com")
        other=Bank(name="Reviewer Edit Other Bank",code="REVIEWER_EDIT_OTHER",status="APPROVED",contact_email="reviewer-edit-other@example.com")
        db.add_all([bank,other]);db.flush()
        admin=BankAdmin(bank_id=bank.id,full_name="Reviewer Edit Admin",email="reviewer-edit-admin@example.com",password_hash=hash_password(PW))
        reviewer=Reviewer(bank_id=bank.id,bank_code=bank.code,full_name="Existing Reviewer",email="existing-reviewer-edit@example.com",password_hash=hash_password(PW),max_active_assignments=2)
        other_reviewer=Reviewer(bank_id=other.id,bank_code=other.code,full_name="Other Reviewer",email="other-reviewer-edit@example.com",password_hash=hash_password(PW))
        customer=__import__("app.models",fromlist=["Customer"]).Customer(full_name="Review Customer",email="reviewer-edit-customer@example.com",mobile="9999999912",password_hash=hash_password(PW))
        db.add_all([admin,reviewer,other_reviewer,customer]);db.flush()
        app=MortgageApplication(reference="REVIEWER-EDIT-APP",customer_id=customer.id,bank_id=bank.id,lender_name=bank.code,status="IN_REVIEW")
        app2=MortgageApplication(reference="REVIEWER-EDIT-APP2",customer_id=customer.id,bank_id=bank.id,lender_name=bank.code,status="IN_REVIEW")
        db.add_all([app,app2]);db.flush();db.add_all([ReviewAssignment(application_id=app.id,reviewer_id=reviewer.id,active=True),ReviewAssignment(application_id=app2.id,reviewer_id=reviewer.id,active=True)]);db.commit();admin_id=admin.id;reviewer_id=reviewer.id;other_id=other_reviewer.id
        from app.services.assignment import reviewer_load
        assert reviewer_load(db,reviewer_id)==2
    h=headers(token_for(f"bankadmin:{admin_id}"))
    base={"full_name":"Updated Reviewer","email":"updated-reviewer@example.com","specialisation":"INCOME_TAX","max_active_assignments":1,"reason":"Operations staffing adjustment"}
    too_small=client.patch(f"/api/v1/bank-admin/reviewers/{reviewer_id}",headers=h,json=base)
    assert too_small.status_code==409,too_small.json()
    changed=client.patch(f"/api/v1/bank-admin/reviewers/{reviewer_id}",headers=h,json={**base,"max_active_assignments":3})
    assert changed.status_code==200 and changed.json()["email"]=="updated-reviewer@example.com" and changed.json()["active_assignments"]==2
    dashboard=client.get("/api/v1/bank-admin/dashboard",headers=h).json()
    assert dashboard["applications"]==2 and dashboard["status_counts"]["IN_REVIEW"]==2
    workload=next(x for x in dashboard["reviewer_workload"] if x["id"]==reviewer_id)
    assert workload["active_assignments"]==2 and workload["max_active_assignments"]==3 and workload["available"] is True
    assert client.patch(f"/api/v1/bank-admin/reviewers/{reviewer_id}",headers=h,json={**base,"email":"other-reviewer-edit@example.com","max_active_assignments":3}).status_code==409
    assert client.patch(f"/api/v1/bank-admin/reviewers/{other_id}",headers=h,json={**base,"max_active_assignments":3}).status_code==404
    assert client.patch(f"/api/v1/bank-admin/reviewers/{reviewer_id}/active?active=false",headers=h).status_code==422
    deactivated=client.patch(f"/api/v1/bank-admin/reviewers/{reviewer_id}/active?active=false&reason=Confirmed%20staffing%20change",headers=h)
    assert deactivated.status_code==200 and deactivated.json()["is_active"] is False
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ReviewAssignment).where(ReviewAssignment.reviewer_id==reviewer_id,ReviewAssignment.active.is_(True)))==0
        assert db.scalar(select(AssignmentEvent).where(AssignmentEvent.event_type=="REASSIGNMENT_REQUIRED",AssignmentEvent.reviewer_id==reviewer_id))


def test_bank_notifications_are_scoped_deduplicated_and_archived_without_deleting_history():
    from app.models import Bank, BankAdmin, Customer, MortgageApplication, AssignmentEvent, BankAdminNotification
    from app.security import token_for
    with SessionLocal() as db:
        bank=Bank(name="Notification Scope Bank",code="NOTIFY_SCOPE",status="APPROVED",contact_email="notify-scope@example.com")
        other=Bank(name="Notification Foreign Bank",code="NOTIFY_FOREIGN",status="APPROVED",contact_email="notify-foreign@example.com")
        db.add_all([bank,other]);db.flush()
        admin=BankAdmin(bank_id=bank.id,full_name="Notification Admin",email="notify-admin@example.com",password_hash=hash_password(PW))
        foreign_admin=BankAdmin(bank_id=other.id,full_name="Foreign Notification Admin",email="notify-foreign-admin@example.com",password_hash=hash_password(PW))
        customer=Customer(full_name="Notification Customer",email="notify-customer@example.com",mobile="9999999913",password_hash=hash_password(PW))
        db.add_all([admin,foreign_admin,customer]);db.flush()
        app=MortgageApplication(reference="NOTIFY-SCOPE-APP",customer_id=customer.id,bank_id=bank.id,lender_name=bank.code,status="PENDING_ASSIGNMENT")
        db.add(app);db.flush()
        event=AssignmentEvent(application_id=app.id,event_type="PENDING_ASSIGNMENT",reason="No eligible reviewer currently available")
        db.add(event);db.commit();admin_id=admin.id;foreign_id=foreign_admin.id;event_id=event.id
    h=headers(token_for(f"bankadmin:{admin_id}"));foreign_h=headers(token_for(f"bankadmin:{foreign_id}"))
    first=client.get("/api/v1/bank-admin/notifications",headers=h)
    again=client.get("/api/v1/bank-admin/notifications",headers=h)
    assert first.status_code==again.status_code==200
    note=next(x for x in first.json()["items"] if x["resource_id"])
    assert first.json()["unread_count"]==again.json()["unread_count"]==1
    assert client.get("/api/v1/bank-admin/notifications",headers=foreign_h).json()["total"]==0
    read=client.patch(f"/api/v1/bank-admin/notifications/{note['id']}/read",headers=h,json={"read":True})
    assert read.status_code==200 and read.json()["read"] is True
    archived=client.delete(f"/api/v1/bank-admin/notifications/{note['id']}",headers=h)
    assert archived.status_code==200 and archived.json()["archived"] is True and archived.json()["unread_count"]==0
    with SessionLocal() as db:
        assert db.get(AssignmentEvent,event_id) is not None
        assert db.get(BankAdminNotification,note["id"]).archived_at is not None


def test_bank_application_archive_is_terminal_only_and_preserves_records():
    from app.models import Bank, BankAdmin, Customer, MortgageApplication, ApplicationDocument, AssignmentEvent, AuditLog
    from app.security import token_for
    with SessionLocal() as db:
        bank=Bank(name="Archive Lifecycle Bank",code="APP_ARCHIVE_BANK",status="APPROVED",contact_email="app-archive@example.com")
        db.add(bank);db.flush()
        admin=BankAdmin(bank_id=bank.id,full_name="Archive Admin",email="app-archive-admin@example.com",password_hash=hash_password(PW))
        customer=Customer(full_name="Archive Customer",email="app-archive-customer@example.com",mobile="9999999914",password_hash=hash_password(PW))
        db.add_all([admin,customer]);db.flush()
        active=MortgageApplication(reference="APP-ARCHIVE-ACTIVE",customer_id=customer.id,bank_id=bank.id,lender_name=bank.code,status="IN_REVIEW")
        finished=MortgageApplication(reference="APP-ARCHIVE-FINISHED",customer_id=customer.id,bank_id=bank.id,lender_name=bank.code,status="COMPLETED")
        db.add_all([active,finished]);db.flush()
        event=AssignmentEvent(application_id=finished.id,event_type="REVIEW_COMPLETED",reason="Review is complete")
        db.add(event);db.commit();admin_id=admin.id;active_id=active.id;finished_id=finished.id;event_id=event.id
    h=headers(token_for(f"bankadmin:{admin_id}"))
    reason={"reason":"Retain completed case out of active operations"}
    assert client.post(f"/api/v1/bank-admin/applications/{active_id}/archive",headers=h,json=reason).status_code==409
    archived=client.post(f"/api/v1/bank-admin/applications/{finished_id}/archive",headers=h,json=reason)
    assert archived.status_code==200 and archived.json()["archived"] is True
    assert finished_id not in [x["id"] for x in client.get("/api/v1/bank-admin/applications",headers=h).json()]
    archived_rows=client.get("/api/v1/bank-admin/applications?include_archived=true",headers=h).json()
    assert next(x for x in archived_rows if x["id"]==finished_id)["archived_at"]
    dashboard=client.get("/api/v1/bank-admin/dashboard",headers=h).json()
    assert dashboard["applications"]==1 and dashboard["archived_applications"]==1
    with SessionLocal() as db:
        assert db.get(AssignmentEvent,event_id) is not None
        assert db.scalar(select(AuditLog).where(AuditLog.action=="BANK_APPLICATION_ARCHIVED",AuditLog.resource_id==str(finished_id)))
    restored=client.post(f"/api/v1/bank-admin/applications/{finished_id}/restore",headers=h,json={"reason":"Return completed case to active history view"})
    assert restored.status_code==200 and restored.json()["archived"] is False


def test_bank_policy_lifecycle_is_scoped_versioned_and_validates_customer_safe_summary():
    from app.models import Bank, BankAdmin, PolicyDocument
    from app.security import token_for
    with SessionLocal() as db:
        one=Bank(name="Policy Lifecycle One",code="POL_LIFE_ONE",status="APPROVED",contact_email="pol-life-one@example.com")
        two=Bank(name="Policy Lifecycle Two",code="POL_LIFE_TWO",status="APPROVED",contact_email="pol-life-two@example.com")
        db.add_all([one,two]);db.flush()
        a=BankAdmin(bank_id=one.id,full_name="Policy Lifecycle Admin",email="pol-life-admin@example.com",password_hash=hash_password(PW))
        b=BankAdmin(bank_id=two.id,full_name="Policy Lifecycle Other",email="pol-life-other@example.com",password_hash=hash_password(PW))
        db.add_all([a,b]);db.commit();aid=a.id;bid=b.id
    h=headers(token_for(f"bankadmin:{aid}"));other=headers(token_for(f"bankadmin:{bid}"))
    payload={"title":"Income Evidence Standard","policy_version":"1.0","category":"Income","content":"Review the submitted income evidence using the established bank process and record any missing items.","active":True,"customer_visible":False,"customer_summary":""}
    created=client.post("/api/v1/bank-admin/policies",headers=h,json=payload)
    assert created.status_code==201,created.text
    pid=created.json()["id"]
    assert client.post("/api/v1/bank-admin/policies",headers=h,json=payload).status_code==409
    unsafe={**payload,"title":"Customer Summary Validation","customer_visible":True,"customer_summary":"short"}
    assert client.post("/api/v1/bank-admin/policies",headers=h,json=unsafe).status_code==422
    assert client.get("/api/v1/bank-admin/policies",headers=other).json()==[]
    assert client.patch(f"/api/v1/bank-admin/policies/{pid}/active?active=false",headers=other).status_code==404
    assert client.patch(f"/api/v1/bank-admin/policies/{pid}/active?active=false",headers=h).json()["active"] is False
    with SessionLocal() as db:
        assert db.get(PolicyDocument,pid).active is False


def test_reviewer_cannot_access_cross_bank_assignment_even_if_legacy_assignment_exists():
    from app.models import Bank, Reviewer, MortgageApplication, ReviewAssignment, Customer
    from app.routers.reviewer import _reviewer_can_access_application
    with SessionLocal() as db:
        bank_a = Bank(name="Isolation Bank A", code="ISO_A", status="APPROVED", contact_email="a@iso.example")
        bank_b = Bank(name="Isolation Bank B", code="ISO_B", status="APPROVED", contact_email="b@iso.example")
        db.add_all([bank_a, bank_b]); db.flush()
        customer = Customer(full_name="Isolation Customer", email="isolation-customer@example.com", mobile="9999999999", password_hash=hash_password(PW), is_verified=True)
        reviewer = __import__("app.models", fromlist=["Reviewer"]).Reviewer(full_name="Bank A Reviewer", email="isolation-reviewer@example.com", password_hash=hash_password(PW), bank_code="ISO_A", bank_id=bank_a.id, is_active=True)
        db.add_all([customer, reviewer]); db.flush()
        app = MortgageApplication(reference="ISO-CROSS-BANK", customer_id=customer.id, lender_name="ISO_B", bank_id=bank_b.id, status="SUBMITTED", requested_loan=100000, property_value=150000, annual_income=50000, monthly_debt=0, interest_rate=8, tenure_years=20)
        db.add(app); db.commit(); db.refresh(app); db.refresh(reviewer)
        assert _reviewer_can_access_application(db, app, reviewer) is False


def test_bank_admin_cannot_toggle_reviewer_with_conflicting_populated_bank_id():
    from app.models import Bank, BankAdmin, Reviewer
    from app.security import token_for
    with SessionLocal() as db:
        bank_a = Bank(name="Toggle Bank A", code="TOGGLE_A", status="APPROVED", contact_email="a@toggle.example")
        bank_b = Bank(name="Toggle Bank B", code="TOGGLE_B", status="APPROVED", contact_email="b@toggle.example")
        db.add_all([bank_a, bank_b]); db.flush()
        admin = BankAdmin(bank_id=bank_a.id, full_name="Toggle Bank Admin", email="toggle-admin@example.com", password_hash=hash_password(PW), is_active=True)
        reviewer = Reviewer(full_name="Conflicting Reviewer", email="conflicting-reviewer@example.com", password_hash=hash_password(PW), bank_code=bank_a.code, bank_id=bank_b.id, is_active=True)
        db.add_all([admin, reviewer]); db.commit(); db.refresh(reviewer); db.refresh(admin)
        reviewer_id, admin_id = reviewer.id, admin.id
    response = client.patch(f"/api/v1/bank-admin/reviewers/{reviewer_id}/active?active=false", headers=headers(token_for(f"bankadmin:{admin_id}")))
    assert response.status_code == 404, response.text


def test_reviewer_policy_qa_retrieves_only_global_and_own_bank_policies(monkeypatch):
    from app.models import Bank, Reviewer, PolicyDocument
    from app.security import token_for
    import app.routers.reviewer as reviewer_router
    seen = {}
    async def capture_sources(question, sources):
        seen["titles"] = {source["title"] for source in sources}
        return {"answer": "captured test context", "citations": [], "grounded": False}
    monkeypatch.setattr(reviewer_router, "answer_policy_question", capture_sources)
    with SessionLocal() as db:
        bank_a = Bank(name="Policy QA Bank A", code="PQA_A", status="APPROVED", contact_email="a@pqa.example")
        bank_b = Bank(name="Policy QA Bank B", code="PQA_B", status="APPROVED", contact_email="b@pqa.example")
        db.add_all([bank_a, bank_b]); db.flush()
        reviewer = Reviewer(full_name="Policy QA Reviewer", email="policy-qa-reviewer@example.com", password_hash=hash_password(PW), bank_code=bank_a.code, bank_id=bank_a.id, is_active=True)
        db.add(reviewer)
        db.add_all([
            PolicyDocument(title="PQA Global Repayment", policy_version="1", category="Fees", content="Early repayment fee policy says consult the approved global schedule.", active=True, created_by="test"),
            PolicyDocument(title="PQA Bank A Repayment", policy_version="1", category="Fees", content="Early repayment fee at Bank A is one percent under this policy.", active=True, created_by="test", bank_id=bank_a.id),
            PolicyDocument(title="PQA Bank B Private Repayment", policy_version="1", category="Fees", content="Early repayment fee at Bank B is nine percent under this private policy.", active=True, created_by="test", bank_id=bank_b.id),
        ])
        db.commit(); db.refresh(reviewer); reviewer_id = reviewer.id
    response = client.post("/api/v1/reviewer/policy-qa", headers=headers(token_for(f"reviewer:{reviewer_id}")), json={"question":"What is the early repayment fee?"})
    assert response.status_code == 200, response.text
    assert "PQA Global Repayment" in seen["titles"]
    assert "PQA Bank A Repayment" in seen["titles"]
    assert "PQA Bank B Private Repayment" not in seen["titles"]
