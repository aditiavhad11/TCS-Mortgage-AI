import pytest
pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")
pytest.importorskip("email_validator")

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/v1/auth/login", {"email": "customer@example.com", "password": "correct-password"}),
        ("/api/v1/reviewer/login", {"email": "reviewer@example.com", "password": "correct-password"}),
        ("/api/v1/bank-admin/login", {"email": "bank-admin@example.com", "password": "correct-password"}),
        ("/api/v1/admin/login", {"email": "platform-admin@example.com"}),
    ],
)
def test_login_dependency_failure_is_a_server_error_not_a_success(monkeypatch, path, payload):
    def unavailable_db():
        raise RuntimeError("database unavailable")
        yield

    monkeypatch.setitem(app.dependency_overrides, get_db, unavailable_db)
    response = TestClient(app, raise_server_exceptions=False).post(path, json=payload)

    assert response.status_code == 500
    assert "access_token" not in response.text
