"""Application-scoped retrieval over uploaded OCR evidence."""
import json
import re

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import ApplicationDocument, ApplicationDocumentChunk
from app.services.rag_core import chunk_text, cosine, lexical_score, rrf

PAGE_MARKER = re.compile(r"(?:^|\n)\[PAGE\s+(\d+)\]\s*\n", re.IGNORECASE)


def _page_sections(text: str) -> list[tuple[int | None, str]]:
    matches = list(PAGE_MARKER.finditer(text or ""))
    if not matches:
        return [(None, (text or "").strip())] if (text or "").strip() else []
    sections = []
    if text[:matches[0].start()].strip():
        sections.append((None, text[:matches[0].start()].strip()))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        page_text = text[match.end():end].strip()
        if page_text:
            sections.append((int(match.group(1)), page_text))
    return sections


def _source_chunks(document: ApplicationDocument) -> list[dict]:
    sources = [("ORIGINAL_OCR", document.extracted_text or "")]
    if document.edited_text is not None:
        sources.append(("CUSTOMER_CORRECTED_UNVERIFIED", document.edited_text))
    chunks = []
    for variant, text in sources:
        index = 0
        for page, section in _page_sections(text):
            for chunk in chunk_text(section):
                chunks.append({"chunk_index": index, "source_variant": variant, "page_number": page, "text": chunk})
                index += 1
    return chunks


async def index_document(db: Session, document: ApplicationDocument) -> dict:
    """Replace a document's indexed OCR/correction chunks; retain text if embeddings are unavailable."""
    db.execute(delete(ApplicationDocumentChunk).where(ApplicationDocumentChunk.document_id == document.id))
    if getattr(document, "category_match_status", "UNVERIFIED") == "MISMATCH_PENDING":
        db.commit()
        return {"document_id": document.id, "chunks": 0, "embedded": 0, "embedding_status": "category_mismatch_pending"}
    chunks = _source_chunks(document)
    vectors = [None] * len(chunks)
    embedding_status = "not_configured"
    if settings.nvidia_api_key.strip() and chunks:
        try:
            from app.services.nvidia import embed_texts

            vectors = await embed_texts([chunk["text"] for chunk in chunks], "passage")
            if len(vectors) != len(chunks):
                raise ValueError("Embedding result count did not match the document chunks.")
            embedding_status = "embedded"
        except Exception as error:
            embedding_status = f"failed:{type(error).__name__}"
    for chunk, vector in zip(chunks, vectors):
        db.add(ApplicationDocumentChunk(
            document_id=document.id,
            chunk_index=chunk["chunk_index"],
            source_variant=chunk["source_variant"],
            source_filename=document.original_filename,
            source_category=document.category,
            page_number=chunk["page_number"],
            text=chunk["text"],
            embedding_json=json.dumps(vector) if vector else None,
            embed_model=settings.nvidia_embed_model if vector else "",
        ))
    db.commit()
    return {
        "document_id": document.id,
        "chunks": len(chunks),
        "embedded": sum(vector is not None for vector in vectors),
        "embedding_status": embedding_status,
    }


async def retrieve_document_hybrid(
    db: Session, question: str, application_id: int, limit: int = 5
) -> tuple[list[dict], str]:
    """Retrieve only chunks owned by the requested application."""
    rows = db.scalars(
        select(ApplicationDocumentChunk)
        .join(ApplicationDocument, ApplicationDocument.id == ApplicationDocumentChunk.document_id)
        .where(ApplicationDocument.application_id == application_id)
    ).all()
    lexical = []
    for row in rows:
        score = lexical_score(question, f"{row.source_category} {row.source_filename}", row.text)
        if score is not None:
            lexical.append((row.id, score))
    lexical.sort(key=lambda item: item[1], reverse=True)
    lexical = lexical[:8]

    method = "lexical"
    vector_rows = [
        row for row in rows
        if row.embedding_json and row.embed_model == settings.nvidia_embed_model
    ]
    if settings.nvidia_api_key.strip() and vector_rows:
        try:
            from app.services.nvidia import embed_texts

            query_vector = (await embed_texts([question[:2000]], "query"))[0]
            ranked = sorted(
                (
                    (cosine(query_vector, json.loads(row.embedding_json)), row.id)
                    for row in vector_rows
                ),
                key=lambda item: item[0],
                reverse=True,
            )
            vector_ids = [row_id for score, row_id in ranked[:8] if score >= 0.2]
            fused_ids = rrf([[row_id for row_id in vector_ids], [row_id for row_id, _ in lexical]])
            by_id = {row.id: row for row in rows}
            lexical_scores = dict(lexical)
            vector_scores = {row_id: score for score, row_id in ranked}
            results = []
            for row_id in fused_ids[:max(1, min(limit, 8))]:
                row = by_id[row_id]
                score = max(lexical_scores.get(row_id, 0), vector_scores.get(row_id, 0))
                results.append(_result(row, score, "hybrid"))
            return results, "hybrid_vector_lexical"
        except Exception:
            method = "lexical_fallback_embedding_failed"

    by_id = {row.id: row for row in rows}
    return [
        _result(by_id[row_id], score, "lexical")
        for row_id, score in lexical[:max(1, min(limit, 8))]
    ], method


def _result(row: ApplicationDocumentChunk, score: float, method: str) -> dict:
    return {
        "document_id": row.document_id,
        "filename": row.source_filename,
        "category": row.source_category,
        "page_number": row.page_number,
        "source_variant": row.source_variant,
        "chunk_index": row.chunk_index,
        "score": round(score, 4),
        "text": row.text,
        "method": method,
    }
