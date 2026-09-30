from uuid import uuid4

import pytest
from chat_api.api.v1.endpoints import feedback as feedback_endpoint
from chat_api.main import app
from chat_api.services.agentcore import AgentCoreResponseError
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    return TestClient(app)


def test_feedback_forwards_not_helpful_with_comment(client, monkeypatch):
    calls = []

    async def fake_submit(session_id, *, outcome, comment):
        calls.append((session_id, outcome, comment))

    monkeypatch.setattr(feedback_endpoint, "submit_feedback", fake_submit)
    session_id = str(uuid4())

    response = client.post(
        "/v1/feedback",
        json={
            "sessionId": session_id,
            "outcome": "not_helpful",
            "comment": "  no citations  ",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert calls == [(session_id, "not_helpful", "no citations")]


def test_feedback_drops_blank_comment_for_solved(client, monkeypatch):
    calls = []

    async def fake_submit(session_id, *, outcome, comment):
        calls.append((session_id, outcome, comment))

    monkeypatch.setattr(feedback_endpoint, "submit_feedback", fake_submit)

    response = client.post(
        "/v1/feedback",
        json={"sessionId": str(uuid4()), "outcome": "helpful", "comment": "   "},
    )

    assert response.status_code == 200
    assert calls[0][1] == "helpful"
    assert calls[0][2] is None


def test_feedback_forwards_helpful(client, monkeypatch):
    calls = []

    async def fake_submit(session_id, *, outcome, comment):
        calls.append((session_id, outcome, comment))

    monkeypatch.setattr(feedback_endpoint, "submit_feedback", fake_submit)

    response = client.post(
        "/v1/feedback",
        json={"sessionId": str(uuid4()), "outcome": "helpful"},
    )

    assert response.status_code == 200
    assert calls[0][1] == "helpful"


def test_feedback_rejects_not_helpful_without_comment(client, monkeypatch):
    monkeypatch.setattr(feedback_endpoint, "submit_feedback", lambda *a, **k: None)

    response = client.post(
        "/v1/feedback",
        json={"sessionId": str(uuid4()), "outcome": "not_helpful"},
    )
    assert response.status_code == 422


def test_feedback_rejects_unknown_outcome(client):
    response = client.post(
        "/v1/feedback", json={"sessionId": str(uuid4()), "outcome": "maybe"}
    )
    assert response.status_code == 422


def test_feedback_rejects_non_uuid_session(client):
    response = client.post(
        "/v1/feedback", json={"sessionId": "not-a-uuid", "outcome": "helpful"}
    )
    assert response.status_code == 422


def test_feedback_returns_502_when_gateway_fails(client, monkeypatch):
    async def fake_submit(session_id, *, outcome, comment):
        raise AgentCoreResponseError("boom")

    monkeypatch.setattr(feedback_endpoint, "submit_feedback", fake_submit)

    response = client.post(
        "/v1/feedback", json={"sessionId": str(uuid4()), "outcome": "helpful"}
    )
    assert response.status_code == 502
