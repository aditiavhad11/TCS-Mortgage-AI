from fastapi.testclient import TestClient
from app.main import app

def test_health():
    r = TestClient(app).get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

def test_ai_status_is_honest():
    r = TestClient(app).get("/api/v1/ai/status")
    assert r.status_code == 200
    assert r.json()["live_inference_tested"] is False
