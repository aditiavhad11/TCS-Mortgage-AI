from app.services.policy_rag import chunk_text, retrieve_policy_chunks
from app.models import PolicyDocument
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.database import Base

def test_chunk_text_preserves_content():
    text = "Mortgage income verification policy. " * 100
    chunks = chunk_text(text)
    assert len(chunks) > 1
    assert all(chunks)

def test_page_markers_are_case_insensitive_and_preserve_source_pages():
    from app.services.policy_rag import _page_chunks
    assert _page_chunks("[Page 1]\nFirst page text.\n\n[Page 2]\nSecond page text.") == [
        (1, "First page text."), (2, "Second page text.")
    ]

def test_retrieval_returns_active_policy_and_version():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(PolicyDocument(title="Income Verification", policy_version="2026.1", category="Income", content="For salaried borrowers, verify income using salary slips and income tax returns for available prior years.", active=True, created_by="test"))
        db.add(PolicyDocument(title="Archived Vehicle Policy", policy_version="1", category="Vehicle", content="Vehicle financing policy for used car loans.", active=False, created_by="test"))
        db.commit()
        rows = retrieve_policy_chunks(db, "verify salaried borrower income using tax returns", limit=5)
        assert rows
        assert rows[0]["title"] == "Income Verification"
        assert rows[0]["policy_version"] == "2026.1"
        assert all(x["title"] != "Archived Vehicle Policy" for x in rows)

def test_customer_policy_retrieval_exposes_only_explicit_customer_safe_summary():
    import asyncio
    from sqlalchemy import select
    from app.models import PolicyChunk
    from app.services.policy_rag import retrieve_policy_chunks, index_policy
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        policy = PolicyDocument(title="Residential Income Policy", policy_version="2.0", category="Income", content="INTERNAL CONFIDENTIAL: reviewer-only risk escalation thresholds and internal decision notes.", active=True, customer_visible=True, customer_summary="Customers should provide available income proof and bank statements for their mortgage application.", created_by="bank-admin")
        internal = PolicyDocument(title="Private Underwriting Notes", policy_version="1.0", category="Internal", content="CONFIDENTIAL internal underwriting escalation process for bank reviewers only.", active=True, customer_visible=False, customer_summary="", created_by="bank-admin")
        db.add_all([policy, internal]); db.commit()
        asyncio.run(index_policy(db, policy)); asyncio.run(index_policy(db, internal))
        rows = retrieve_policy_chunks(db, "income proof bank statements mortgage application", limit=8, customer_visible_only=True)
        assert rows and all(row["audience"] == "CUSTOMER" for row in rows)
        assert any("Customers should provide" in row["text"] for row in rows)
        assert all("CONFIDENTIAL" not in row["text"] for row in rows)
        chunks = db.scalars(select(PolicyChunk).where(PolicyChunk.policy_id == policy.id)).all()
        assert {c.audience for c in chunks} == {"INTERNAL", "CUSTOMER"}

def test_correcting_customer_summary_replaces_placeholder_chunks_and_preserves_pdf_pages(monkeypatch):
    import asyncio
    from sqlalchemy import select
    from app.config import settings
    from app.models import PolicyChunk
    from app.services.policy_rag import index_policy, retrieve_policy_chunks
    monkeypatch.setattr(settings, "nvidia_api_key", "")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        policy = PolicyDocument(
            title="Illustrative Home Loan Policy", policy_version="1.0", category="Mortgage",
            content="[PAGE 1]\nINTERNAL source: applicant document checklist and approval terms.\n[PAGE 2]\nPrivate processing notes.",
            active=True, customer_visible=True,
            customer_summary="This creates a new active policy version. Only the customer-approved summary below is indexed.",
            created_by="bank-admin",
        )
        db.add(policy); db.commit()
        asyncio.run(index_policy(db, policy))
        before = retrieve_policy_chunks(db, "What documents may I need for a home loan?", bank_id=None, customer_visible_only=True)
        assert before and "new active policy version" in before[0]["text"]

        policy.customer_summary = (
            "[PAGE 1]\nFor this demonstration, customers may be asked for government-issued identity and address proof, "
            "recent salary slips or self-employed income records, recent bank statements, tax records when required, "
            "and applicable sale, title, and valuation documents. Submitting documents does not guarantee approval.\n"
            "[PAGE 2]\nThis illustrative demo is not a real lender policy."
        )
        db.commit()
        asyncio.run(index_policy(db, policy))
        after = retrieve_policy_chunks(db, "What documents may I need for a home loan?", bank_id=None, customer_visible_only=True)
        assert after and "government-issued identity" in after[0]["text"]
        assert all("new active policy version" not in row["text"] for row in after)
        assert all("Private processing notes" not in row["text"] for row in after)
        chunks = db.scalars(select(PolicyChunk).where(PolicyChunk.policy_id == policy.id, PolicyChunk.audience == "CUSTOMER")).all()
        assert {chunk.page_number for chunk in chunks} == {1, 2}

def test_reindex_replaces_old_policy_chunks_and_bank_scope_isolated(monkeypatch):
    import asyncio
    from sqlalchemy import select
    from app.config import settings
    from app.models import Bank, PolicyChunk
    from app.services.policy_rag import index_policy, retrieve_policy_chunks
    monkeypatch.setattr(settings, "nvidia_api_key", "")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        bank_a = Bank(name="RAG Bank A", code="RAG-A", status="APPROVED")
        bank_b = Bank(name="RAG Bank B", code="RAG-B", status="APPROVED")
        db.add_all([bank_a, bank_b]); db.flush()
        policy_a = PolicyDocument(bank_id=bank_a.id, title="Income Policy", policy_version="2.0", category="Income", content="RAG-A salaried borrowers verify tax returns and salary slips.", active=True, created_by="test")
        policy_b = PolicyDocument(bank_id=bank_b.id, title="Income Policy", policy_version="2.0", category="Income", content="RAG-B salaried borrowers verify tax returns and salary slips.", active=True, created_by="test")
        db.add_all([policy_a, policy_b]); db.commit()
        asyncio.run(index_policy(db, policy_a))
        policy_a.content = "RAG-A salaried borrowers provide updated tax returns."
        db.commit()
        asyncio.run(index_policy(db, policy_a))
        chunks_a = db.scalars(select(PolicyChunk).where(PolicyChunk.policy_id == policy_a.id)).all()
        assert len(chunks_a) == 1 and "updated tax returns" in chunks_a[0].text
        rows = retrieve_policy_chunks(db, "salaried borrowers verify tax returns", bank_id=bank_a.id)
        assert rows and {row["policy_id"] for row in rows} == {policy_a.id}

def test_policy_answer_sends_retrieved_source_and_validates_citation(monkeypatch):
    import asyncio
    import json
    import types
    from app.config import settings
    from app.services import nvidia
    monkeypatch.setattr(settings, "nvidia_api_key", "test-key")
    captured = []
    async def fake_completion(_client, **kwargs):
        captured.extend(kwargs["messages"])
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=json.dumps({
            "answer": "The supplied policy excerpt states a maximum LTV of 80 percent.",
            "citations": ["P1"],
            "insufficient_evidence": False,
        })))])
    monkeypatch.setattr(nvidia, "_client", lambda: object())
    monkeypatch.setattr(nvidia, "_guarded_chat_completion", fake_completion)
    sources = [{"policy_id": 17, "title": "LTV Policy", "policy_version": "2026.2", "category": "Credit", "text": "Maximum loan to value is 80 percent."}]
    answer = asyncio.run(nvidia.answer_policy_question("What is the maximum LTV?", sources))
    assert answer["grounded"] is True
    assert answer["citations"][0]["policy_version"] == "2026.2"
    assert "Maximum loan to value is 80 percent." in captured[1]["content"]

def test_empty_policy_retrieval_explicitly_reports_missing_evidence(monkeypatch):
    import asyncio
    from app.config import settings
    from app.services.nvidia import answer_policy_question
    monkeypatch.setattr(settings, "nvidia_api_key", "test-key")
    result = asyncio.run(answer_policy_question("What is the maximum LTV?", []))
    assert result["grounded"] is False
    assert result["citations"] == []
    assert result["reason"] == "no_relevant_policy_chunks"
    assert "could not find relevant content" in result["answer"]

def test_hybrid_policy_retrieval_filters_other_banks_before_vector_ranking(monkeypatch):
    import asyncio
    from app.config import settings
    from app.models import Bank
    from app.services.policy_rag import index_policy, retrieve_hybrid
    monkeypatch.setattr(settings, "nvidia_api_key", "test-key")
    async def fake_embed_texts(texts, input_type):
        if input_type == "query":
            return [[1.0, 0.0]]
        return [[1.0, 0.0] if "RAG-B" in text else [0.0, 1.0] for text in texts]
    monkeypatch.setattr("app.services.nvidia.embed_texts", fake_embed_texts)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        bank_a = Bank(name="Hybrid Bank A", code="HYBRID-A", status="APPROVED")
        bank_b = Bank(name="Hybrid Bank B", code="HYBRID-B", status="APPROVED")
        db.add_all([bank_a, bank_b]); db.flush()
        policy_a = PolicyDocument(bank_id=bank_a.id, title="Mortgage Income", policy_version="1", category="Income", content="RAG-A salaried income verification tax returns.", active=True, created_by="test")
        policy_b = PolicyDocument(bank_id=bank_b.id, title="Mortgage Income", policy_version="1", category="Income", content="RAG-B salaried income verification tax returns.", active=True, created_by="test")
        db.add_all([policy_a, policy_b]); db.commit()
        asyncio.run(index_policy(db, policy_a))
        asyncio.run(index_policy(db, policy_b))
        rows, method = asyncio.run(
            retrieve_hybrid(db, "salaried income verification tax returns", bank_id=bank_a.id)
        )
        assert method == "hybrid_vector_lexical"
        assert rows and {row["policy_id"] for row in rows} == {policy_a.id}
        assert rows[0]["bank_id"] == bank_a.id
