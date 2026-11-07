"""REAL NVIDIA verification (needs NVIDIA_API_KEY in backend/.env and network). Run from backend/:
    python scripts/verify_nvidia.py
Checks: configured chat model is listed for your key, a real chat completion works, embeddings work,
and a real document-analysis + policy-QA round trip returns valid JSON. Uses synthetic text only.
Exit code 0 only if inference succeeded."""
import asyncio, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import settings
from app.services import nvidia as nv

async def main():
    if not settings.nvidia_api_key.strip():
        print("NVIDIA_API_KEY is not set in backend/.env - nothing was verified."); return 2
    res = await nv.verify_connectivity(); print(json.dumps(res, indent=2))
    if not res["inference_ok"]: return 1
    a = await nv.analyze("Synthetic test. Valuation report states property value INR 4300000. Loan requested INR 4000000.", "valuation_ltv")
    print("analyze json_valid:", a["json_valid"]); print(json.dumps(a["analysis"], indent=2)[:1500])
    q = await nv.answer_policy_question("What is the maximum LTV for salaried borrowers?", [{"policy_id": 1, "title": "LTV Policy", "policy_version": "2.0", "category": "Credit", "text": "The maximum loan to value ratio for salaried borrowers is 80 percent."}])
    print("policy QA:", json.dumps(q, indent=2)[:1500])
    return 0 if a["json_valid"] and q.get("grounded") else 1

sys.exit(asyncio.run(main()))
