import pytest
from chat_api.core.config import Settings
from chat_api.main import app
from chat_api.services import registry
from fastapi.testclient import TestClient

KB_ID = "ABCDE12345"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("REGISTRY_TABLE", "registry")
    monkeypatch.setenv("DOCUMENTS_BUCKET", "docs-bucket")
    monkeypatch.setenv("AGENT_GATEWAY_URL", "http://agents:8080")
    registry.clear_cache()
    yield
    registry.clear_cache()


@pytest.fixture
def documents(monkeypatch):
    """Registry contents served to the API; tests mutate this list."""
    items = [
        {"doc_id": "b-1", "name": "Bravo guide", "status": "PROCESSING"},
        {
            "doc_id": "a-1",
            "name": "Alpha manual",
            "status": "READY",
            "kb_id": KB_ID,
            "pages": 12,
        },
    ]

    async def list_documents(_table):
        return sorted(items, key=lambda i: i["name"].lower())

    monkeypatch.setattr(registry, "list_documents", list_documents)
    return items


@pytest.fixture
def client(documents):
    with TestClient(app) as test_client:
        app.state.settings = Settings("registry", "docs-bucket")
        yield test_client
