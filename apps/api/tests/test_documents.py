from urllib.parse import parse_qs, urlparse

import pytest
from chat_api.services import documents


@pytest.fixture(autouse=True)
def _aws(monkeypatch):
    # ECS sets AWS_REGION only; boto3 itself reads AWS_DEFAULT_REGION, so nothing else may assume it.
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.setenv("AWS_REGION", "eu-central-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIDEXAMPLE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")


async def test_presigned_links_use_the_regional_endpoint_and_region_scoped_credentials():
    link = await documents.page_link("docs-bucket", "uploads/a.pdf", 4, 900)

    parsed = urlparse(link)
    assert parsed.hostname == "docs-bucket.s3.eu-central-1.amazonaws.com"
    query = parse_qs(parsed.query)
    assert "/eu-central-1/s3/aws4_request" in query["X-Amz-Credential"][0]
    assert query["X-Amz-Expires"] == ["900"]
    assert parsed.fragment == "page=4"


async def test_only_uploaded_pdfs_are_linked():
    assert await documents.page_link("b", "other/x.pdf", 1, 60) is None
    assert await documents.page_link("b", "uploads/../secret", 1, 60) is None
