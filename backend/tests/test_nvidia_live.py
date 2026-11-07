"""Opt-in LIVE NVIDIA tests (real network + quota). Synthetic text only.  RUN_NVIDIA_EVAL=1 pytest tests/test_nvidia_live.py -v"""
import os
import pytest

pytestmark = pytest.mark.skipif(os.getenv("RUN_NVIDIA_EVAL") != "1", reason="Set RUN_NVIDIA_EVAL=1 (and NVIDIA_API_KEY in backend/.env) to run live NVIDIA calls")

async def test_model_listed_inference_and_embeddings():
    from app.services.nvidia import verify_connectivity
    r = await verify_connectivity()
    assert r["model_listed"] is True, r["errors"]
    assert r["inference_ok"] is True, r["errors"]
    assert r["embedding_ok"] is True, r["errors"]

async def test_analyze_returns_valid_json():
    from app.services.nvidia import analyze
    r = await analyze("Synthetic test only. Property valuation INR 4300000. Declared value INR 5000000.", "valuation_ltv")
    assert r["provider"] == "NVIDIA" and r["raw_response"].strip() and r["json_valid"] is True

async def test_policy_qa_cites_only_supplied_sources():
    from app.services.nvidia import answer_policy_question
    src = [{"policy_id": 1, "title": "LTV Policy", "policy_version": "2.0", "category": "Credit", "text": "The maximum loan to value ratio for salaried borrowers is 80 percent."}]
    r = await answer_policy_question("What is the maximum LTV for salaried borrowers?", src)
    assert r["grounded"] is True and {c["policy_version"] for c in r["citations"]} == {"2.0"} and "80" in r["answer"]
