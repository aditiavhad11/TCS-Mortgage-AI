"""Bank-scoped policy retrieval with separate internal and customer-safe chunk audiences."""
import json
import re
from sqlalchemy import select, delete, or_
from sqlalchemy.orm import Session
from app.config import settings
from app.models import PolicyDocument, PolicyChunk
from app.services.rag_core import chunk_text, tokens, lexical_score, cosine, rrf  # noqa: F401

_PAGE_MARKER = re.compile(r"(?im)^\s*\[PAGE\s+(\d+)\]\s*$")


def _page_chunks(text: str) -> list[tuple[int | None, str]]:
    """Chunk by source page first so page citations survive policy indexing."""
    source = (text or "").strip()
    if not source:
        return []
    markers = list(_PAGE_MARKER.finditer(source))
    if not markers:
        return [(None, chunk) for chunk in chunk_text(source)]
    sections: list[tuple[int | None, str]] = []
    if source[:markers[0].start()].strip():
        sections.extend((None, chunk) for chunk in chunk_text(source[:markers[0].start()].strip()))
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(source)
        page_text = source[marker.end():end].strip()
        sections.extend((int(marker.group(1)), chunk) for chunk in chunk_text(page_text))
    return sections


def _active(db, bank_id=None, customer_visible_only=False, bank_ids=None):
    if bank_id is not None:
        scope=or_(PolicyDocument.bank_id.is_(None),PolicyDocument.bank_id==bank_id)
    elif bank_ids is not None and len(bank_ids):
        scope=or_(PolicyDocument.bank_id.is_(None),PolicyDocument.bank_id.in_(list(bank_ids)))
    else:
        scope=PolicyDocument.bank_id.is_(None)
    query=select(PolicyDocument).where(PolicyDocument.active.is_(True), scope)
    if customer_visible_only: query=query.where(PolicyDocument.customer_visible.is_(True), PolicyDocument.customer_summary != "")
    return db.scalars(query.order_by(PolicyDocument.created_at.desc())).all()


def _content_for(policy, customer_visible_only=False):
    # The customer flag authorizes only the explicitly bank-approved summary. Full source text remains INTERNAL.
    return (policy.customer_summary or "") if customer_visible_only else policy.content


def _row(p, idx, text, score, method, audience="INTERNAL", page_number=None):
    filename=(p.source_filename or "").replace("\\","/").rsplit("/",1)[-1] or None
    return {"policy_id": p.id, "bank_id": p.bank_id, "title": p.title, "policy_version": p.policy_version,
            "category": p.category, "source_filename": filename, "chunk_index": idx, "page_number": page_number,
            "source_reference": f"policy:{p.id}:v{p.policy_version}:{audience.lower()}:{idx}",
            "score": score, "text": text, "method": method, "audience": audience}


def retrieve_policy_chunks(db: Session, question: str, limit: int = 5, bank_id: int | None = None, customer_visible_only: bool = False, policy_id: int | None = None, bank_ids=None) -> list[dict]:
    cands = []; audience="CUSTOMER" if customer_visible_only else "INTERNAL"
    for policy in _active(db, bank_id, customer_visible_only, bank_ids):
        if policy_id is not None and policy.id != policy_id:
            continue
        for idx, (page_number, chunk) in enumerate(_page_chunks(_content_for(policy, customer_visible_only))):
            score = lexical_score(question, f"{policy.title} {policy.category}", chunk)
            if score is not None:
                cands.append(_row(policy, idx, chunk, score, "lexical", audience, page_number))
    cands.sort(key=lambda row: (row["score"], row["policy_id"], row["chunk_index"]), reverse=True)
    return cands[:max(1, min(limit, 8))]


def vector_rank(query_vec, chunks, limit=8):
    scored = sorted(((cosine(query_vec, vector), key) for key, vector in chunks), key=lambda item: -item[0])
    return [key for score, key in scored[:limit] if score > 0]


async def index_policy(db: Session, policy: PolicyDocument) -> dict:
    """Replace active policy chunks, keeping private content and customer-safe summaries separate."""
    from app.services.nvidia import embed_texts
    db.execute(delete(PolicyChunk).where(PolicyChunk.policy_id == policy.id))
    if not policy.active:
        db.commit()
        return {"policy_id": policy.id, "chunks": 0, "customer_summary_chunks": 0, "embedded": 0, "error": None, "customer_visible": False}
    internal_chunks=_page_chunks(policy.content)
    customer_chunks=_page_chunks(policy.customer_summary) if policy.customer_visible and (policy.customer_summary or "").strip() else []
    combined=[text for _,text in internal_chunks+customer_chunks]
    vectors=[None]*len(combined);error=None
    if settings.nvidia_api_key.strip() and combined:
        try:
            vectors=await embed_texts(combined,"passage")
            if len(vectors)!=len(combined): raise ValueError("Embedding result count did not match policy chunks.")
        except Exception as exc:
            error=type(exc).__name__
    for idx,(page_number,text) in enumerate(internal_chunks):
        vector=vectors[idx]
        db.add(PolicyChunk(policy_id=policy.id,chunk_index=idx,text=text,embedding_json=json.dumps(vector) if vector else None,embed_model=settings.nvidia_embed_model if vector else "",audience="INTERNAL",page_number=page_number))
    offset=len(internal_chunks)
    for idx,(page_number,text) in enumerate(customer_chunks):
        vector=vectors[offset+idx]
        db.add(PolicyChunk(policy_id=policy.id,chunk_index=idx,text=text,embedding_json=json.dumps(vector) if vector else None,embed_model=settings.nvidia_embed_model if vector else "",audience="CUSTOMER",page_number=page_number))
    db.commit()
    return {"policy_id":policy.id,"chunks":len(internal_chunks),"customer_summary_chunks":len(customer_chunks),"embedded":sum(vector is not None for vector in vectors),"error":error,"customer_visible":bool(customer_chunks)}


async def retrieve_hybrid(db: Session, question: str, limit: int = 5, bank_id: int | None = None, customer_visible_only: bool = False, policy_id: int | None = None, bank_ids=None) -> tuple[list[dict], str]:
    lexical=retrieve_policy_chunks(db,question,limit=8,bank_id=bank_id,customer_visible_only=customer_visible_only,policy_id=policy_id,bank_ids=bank_ids)
    method="lexical";audience="CUSTOMER" if customer_visible_only else "INTERNAL"
    if settings.nvidia_api_key.strip():
        active={policy.id:policy for policy in _active(db,bank_id,customer_visible_only,bank_ids) if policy_id is None or policy.id == policy_id}
        rows=db.scalars(select(PolicyChunk).where(PolicyChunk.audience==audience,PolicyChunk.policy_id.in_(list(active)),PolicyChunk.embedding_json.is_not(None))).all() if active else []
        if rows:
            try:
                from app.services.nvidia import embed_texts
                query_vector=(await embed_texts([question[:2000]],"query"))[0]
                ranked=vector_rank(query_vector,[((row.policy_id,row.chunk_index),json.loads(row.embedding_json)) for row in rows])
                by_key={(row.policy_id,row.chunk_index):row for row in rows}
                lexical_keys=[(item["policy_id"],item["chunk_index"]) for item in lexical]
                fused=rrf([ranked,lexical_keys]);lex_by={(item["policy_id"],item["chunk_index"]):item for item in lexical};out=[]
                for key in fused[:max(1,min(limit,8))]:
                    if key in lex_by:
                        item=dict(lex_by[key]);item["method"]="hybrid"
                    elif key in by_key:
                        row=by_key[key]
                        item=_row(active[row.policy_id],row.chunk_index,row.text,round(cosine(query_vector,json.loads(row.embedding_json)),4),"vector",audience,row.page_number)
                    else:
                        continue
                    out.append(item)
                return out,"hybrid_vector_lexical"
            except Exception:
                method="lexical_fallback_embedding_failed"
    return lexical[:max(1,min(limit,8))],method
