import base64
import json

import pytest
from chat_api.core.config import Settings

MB = 1024 * 1024


@pytest.fixture(autouse=True)
def _aws(monkeypatch):
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.setenv("AWS_REGION", "eu-central-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIDEXAMPLE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")


def _post(client, **overrides):
    body = {"filename": "Manual.pdf", "sizeBytes": 5 * MB, **overrides}
    return client.post("/v1/documents/upload", json=body)


def _policy(ticket):
    return json.loads(base64.b64decode(ticket["fields"]["policy"]))


def test_issues_a_presigned_post_scoped_to_one_key_with_a_size_limit(client):
    response = _post(client)

    assert response.status_code == 200
    ticket = response.json()
    assert ticket["url"].startswith("https://docs-bucket.s3.eu-central-1.amazonaws.com")
    assert ticket["key"] == "uploads/Manual.pdf"
    assert ticket["fields"]["key"] == "uploads/Manual.pdf"
    assert ticket["maxBytes"] == 100 * MB
    conditions = _policy(ticket)["conditions"]
    assert ["content-length-range", 1, 100 * MB] in conditions
    assert {"Content-Type": "application/pdf"} in conditions
    assert {"key": "uploads/Manual.pdf"} in conditions


def test_the_chunking_choice_is_signed_into_the_upload_as_object_metadata(client):
    ticket = _post(client, chunking="hierarchical", maxTokens=400).json()

    assert ticket["fields"]["x-amz-meta-chunking"] == "hierarchical"
    assert ticket["fields"]["x-amz-meta-max-tokens"] == "400"
    conditions = _policy(ticket)["conditions"]
    assert {"x-amz-meta-chunking": "hierarchical"} in conditions


def test_without_a_choice_no_chunking_metadata_is_sent_so_bedrock_defaults_apply(
    client,
):
    ticket = _post(client).json()

    assert not any(name.startswith("x-amz-meta-") for name in ticket["fields"])


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("../../etc/passwd.pdf", "uploads/passwd.pdf"),
        ("C:\\Users\\me\\Report Q3.PDF", "uploads/Report Q3.pdf"),
        ("weird<>|name?.pdf", "uploads/weirdname.pdf"),
        ("informe año 2026.pdf", "uploads/informe año 2026.pdf"),
        ("no-extension", "uploads/no-extension.pdf"),
    ],
)
def test_filenames_are_reduced_to_a_safe_key_under_uploads(client, raw, expected):
    assert _post(client, filename=raw).json()["key"] == expected


@pytest.mark.parametrize(
    "overrides",
    [
        {"filename": ""},
        {"filename": "   .pdf"},
        {"filename": "a" * 400 + ".pdf", "sizeBytes": 0},
        {"sizeBytes": 0},
        {"sizeBytes": 100 * MB + 1},
        {"chunking": "banana"},
        {"maxTokens": 10},
        {"maxTokens": 5000},
        {"contentType": "text/plain"},
    ],
)
def test_invalid_uploads_are_rejected_before_anything_is_signed(client, overrides):
    assert _post(client, **overrides).status_code == 422


def test_the_size_limit_is_configurable(client):
    from chat_api.main import app

    app.state.settings = Settings("registry", "docs-bucket", max_upload_bytes=2 * MB)

    assert _post(client, sizeBytes=3 * MB).status_code == 422
    assert _post(client, sizeBytes=MB).json()["maxBytes"] == 2 * MB


def test_long_filenames_are_truncated_but_keep_the_pdf_extension(client):
    key = _post(client, filename="x" * 240 + ".pdf").json()["key"]

    assert key.endswith(".pdf") and len(key) <= len("uploads/") + 120
