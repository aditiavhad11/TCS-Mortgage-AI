import asyncio
import json

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import Base
from app.models import (
    ApplicationDocument,
    ApplicationDocumentChunk,
    Customer,
    MortgageApplication,
)
from app.services.document_rag import index_document, retrieve_document_hybrid


def _database():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def _application(db, reference, email, filename, text):
    customer = Customer(
        full_name=reference,
        email=email,
        mobile="9999999999",
        password_hash="test",
    )
    db.add(customer)
    db.flush()
    application = MortgageApplication(reference=reference, customer_id=customer.id)
    db.add(application)
    db.flush()
    document = ApplicationDocument(
        application_id=application.id,
        category="Property Valuation Report",
        original_filename=filename,
        stored_filename=f"{reference}.pdf",
        content_type="application/pdf",
        size_bytes=1,
        extracted_text=text,
        extraction_status="COMPLETED",
    )
    db.add(document)
    db.commit()
    return application, document


def test_document_index_preserves_page_and_variant_and_replaces_stale_chunks(monkeypatch):
    monkeypatch.setattr(settings, "nvidia_api_key", "")
    engine = _database()
    with Session(engine) as db:
        _, document = _application(
            db,
            "RAG-APP-1",
            "rag-app-1@example.com",
            "valuation.pdf",
            "[PAGE 1]\nIndependent property valuation amount INR 4300000.",
        )
        result = asyncio.run(index_document(db, document))
        assert result["chunks"] == 1 and result["embedding_status"] == "not_configured"
        document.edited_text = "[PAGE 2]\nCustomer corrected property valuation amount INR 4400000."
        db.commit()
        asyncio.run(index_document(db, document))
        chunks = db.scalars(
            select(ApplicationDocumentChunk)
            .where(ApplicationDocumentChunk.document_id == document.id)
            .order_by(ApplicationDocumentChunk.source_variant)
        ).all()
        assert len(chunks) == 2
        assert {(row.page_number, row.source_variant) for row in chunks} == {
            (1, "ORIGINAL_OCR"),
            (2, "CUSTOMER_CORRECTED_UNVERIFIED"),
        }
        assert all(row.source_filename == "valuation.pdf" for row in chunks)
        assert "4300000" in next(row.text for row in chunks if row.source_variant == "ORIGINAL_OCR")
        assert "4400000" in next(row.text for row in chunks if row.source_variant != "ORIGINAL_OCR")

        document.extracted_text = "[PAGE 1]\nUpdated valuation figure INR 4500000."
        document.edited_text = None
        db.commit()
        asyncio.run(index_document(db, document))
        chunks = db.scalars(
            select(ApplicationDocumentChunk).where(
                ApplicationDocumentChunk.document_id == document.id
            )
        ).all()
        assert len(chunks) == 1 and "4500000" in chunks[0].text
        assert "4300000" not in chunks[0].text and "4400000" not in chunks[0].text


def test_document_retrieval_is_application_scoped_and_reports_empty_results(monkeypatch):
    monkeypatch.setattr(settings, "nvidia_api_key", "")
    engine = _database()
    with Session(engine) as db:
        app_a, doc_a = _application(
            db,
            "RAG-APP-A",
            "rag-app-a@example.com",
            "bank-a-valuation.pdf",
            "[PAGE 3]\nIndependent property valuation report states market value INR 4300000.",
        )
        app_b, doc_b = _application(
            db,
            "RAG-APP-B",
            "rag-app-b@example.com",
            "bank-b-valuation.pdf",
            "[PAGE 8]\nIndependent property valuation report states market value INR 9900000.",
        )
        asyncio.run(index_document(db, doc_a))
        asyncio.run(index_document(db, doc_b))
        results, method = asyncio.run(
            retrieve_document_hybrid(
                db, "independent property valuation market value", app_a.id
            )
        )
        assert method == "lexical" and results
        assert {item["document_id"] for item in results} == {doc_a.id}
        assert results[0]["filename"] == "bank-a-valuation.pdf"
        assert results[0]["page_number"] == 3
        assert "9900000" not in json.dumps(results)

        empty, _ = asyncio.run(
            retrieve_document_hybrid(db, "unrelated vehicle registration details", app_a.id)
        )
        assert empty == []


def test_document_retrieval_uses_nvidia_query_embeddings_and_fuses_results(monkeypatch):
    monkeypatch.setattr(settings, "nvidia_api_key", "test-key")
    calls = []

    async def fake_embed_texts(texts, input_type):
        calls.append((texts, input_type))
        if input_type == "query":
            return [[1.0, 0.0]]
        return [[1.0, 0.0] if "property valuation" in text.lower() else [0.0, 1.0] for text in texts]

    monkeypatch.setattr("app.services.nvidia.embed_texts", fake_embed_texts)
    engine = _database()
    with Session(engine) as db:
        app, document = _application(
            db,
            "RAG-APP-V",
            "rag-app-v@example.com",
            "valuation.pdf",
            "[PAGE 4]\nCertified independent property valuation report.",
        )
        indexed = asyncio.run(index_document(db, document))
        results, method = asyncio.run(
            retrieve_document_hybrid(db, "property valuation value", app.id)
        )
        assert indexed["embedded"] == 1 and method == "hybrid_vector_lexical"
        assert results and results[0]["filename"] == "valuation.pdf"
        assert [kind for _, kind in calls] == ["passage", "query"]
