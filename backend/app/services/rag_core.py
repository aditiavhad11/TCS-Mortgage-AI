"""Pure retrieval helpers (no DB / network): chunking, lexical scoring, cosine similarity, rank fusion."""
import math, re
from collections import Counter

TOKEN_RE = re.compile(r"[a-zA-Z0-9₹]+")
CHUNK_CHARS = 1200
OVERLAP_CHARS = 180
STOPWORDS = frozenset("a an the of for to in on at by with and or is are was were be been what which who whom how do does did can could should would may might must shall this that these those it its as from than then into per any all not no if when where whether about our your their his her has have had".split())

def tokens(text: str) -> list[str]:
    return [t.lower() for t in TOKEN_RE.findall(text or "") if len(t) > 1 and t.lower() not in STOPWORDS]

def chunk_text(text: str) -> list[str]:
    text = (text or "").strip()
    if not text: return []
    chunks, start = [], 0
    while start < len(text):
        end = min(len(text), start + CHUNK_CHARS)
        if end < len(text):
            boundary = text.rfind(" ", start + CHUNK_CHARS // 2, end)
            if boundary > start: end = boundary
        piece = text[start:end].strip()
        if piece: chunks.append(piece)
        if end >= len(text): break
        start = max(start + 1, end - OVERLAP_CHARS)
    return chunks

def lexical_score(question: str, header: str, chunk: str):
    """Return score or None when the chunk is not relevant."""
    q_tokens = tokens(question)
    if not q_tokens: return None
    q_counts = Counter(q_tokens);c_tokens = tokens(f"{header} {chunk}")
    if not c_tokens: return None
    c_counts = Counter(c_tokens)
    overlap = sum(min(q_counts[t], c_counts.get(t, 0)) for t in q_counts)
    coverage = len(set(q_tokens) & set(c_counts)) / max(1, len(set(q_tokens)))
    if overlap > 0 and coverage >= 0.12: return round(overlap / math.sqrt(len(c_tokens)) + coverage, 4)
    return None

def cosine(a, b) -> float:
    if not a or not b or len(a) != len(b): return 0.0
    dot = sum(x * y for x, y in zip(a, b));na = math.sqrt(sum(x * x for x in a));nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0

def rrf(rankings: list[list], k: int = 60) -> list:
    """Reciprocal-rank fusion over lists of hashable ids (best first); returns ids best-first."""
    score: dict = {}
    for ranking in rankings:
        for pos, key in enumerate(ranking): score[key] = score.get(key, 0.0) + 1.0 / (k + pos + 1)
    return sorted(score, key=lambda x: (-score[x], str(x)))
