import pytest
from chat_api.main import app
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    return TestClient(app)


def test_preflight_allows_vercel_origin(client):
    response = client.options(
        "/v1/feedback",
        headers={
            "Origin": "https://foo.vercel.app",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://foo.vercel.app"
    assert "POST" in response.headers["access-control-allow-methods"]


def test_preflight_rejects_unlisted_origin(client):
    response = client.options(
        "/v1/feedback",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert "access-control-allow-origin" not in response.headers
