from app.services.rag_core import chunk_text, tokens, lexical_score, cosine, rrf

def test_chunking_overlaps_and_covers():
    text = " ".join(f"word{i}" for i in range(1000))
    chunks = chunk_text(text)
    assert len(chunks) > 1 and all(chunks)
    assert chunks[0].split()[0] == "word0" and chunks[-1].split()[-1] == "word999"

def test_stopwords_removed():
    assert tokens("What is the LTV of a loan?") == ["ltv", "loan"]

def test_lexical_prefers_relevant_chunk():
    q = "maximum loan to value ratio for salaried borrowers"
    good = lexical_score(q, "LTV Policy", "The maximum loan to value ratio for salaried borrowers is 80 percent.")
    bad = lexical_score(q, "Vehicle", "Used car financing requires a hypothecation endorsement on the registration certificate.")
    assert good is not None and (bad is None or good > bad)

def test_cosine_and_rrf():
    assert cosine([1, 0], [1, 0]) == 1.0 and cosine([1, 0], [0, 1]) == 0.0 and cosine([], [1]) == 0.0
    assert rrf([["a", "b", "c"], ["b", "a"]])[:2] == ["a", "b"] or rrf([["a", "b", "c"], ["b", "a"]])[:2] == ["b", "a"]
    assert rrf([["x"], ["y", "x"]])[0] == "x"

def test_vector_rank_is_semantic_ordering():
    import pytest; pytest.importorskip("sqlalchemy")
    from app.services.policy_rag import vector_rank
    # Test vectors only exercise the ranking math; they are not model output.
    assert vector_rank([1, 0], [("far", [0, 1]), ("near", [0.9, 0.1]), ("mid", [0.5, 0.5])]) == ["near", "mid"]
