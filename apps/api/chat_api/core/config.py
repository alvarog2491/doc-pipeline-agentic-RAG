"""SigV4 signing for AgentCore Gateway requests and environment-derived settings."""

import datetime
import os
from dataclasses import dataclass
from urllib.parse import urlparse

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

_boto3_session: boto3.Session | None = None


def get_boto3_session() -> boto3.Session:
    """Return the process-wide boto3 session."""
    global _boto3_session
    if _boto3_session is None:
        _boto3_session = boto3.Session()
    return _boto3_session


@dataclass(frozen=True)
class Settings:
    """Runtime configuration read from the environment.

    Attributes:
        registry_table: DynamoDB table of ingested documents.
        documents_bucket: S3 bucket that holds the uploaded PDFs.
        link_ttl_seconds: Lifetime of presigned citation links.
        max_upload_bytes: Largest PDF a browser may upload.
        upload_ttl_seconds: Lifetime of an upload ticket.
    """

    registry_table: str
    documents_bucket: str
    link_ttl_seconds: int = 900
    max_upload_bytes: int = 100 * 1024 * 1024
    upload_ttl_seconds: int = 600

    @classmethod
    def from_env(cls) -> "Settings":
        """Read settings from ``REGISTRY_TABLE``, ``DOCUMENTS_BUCKET`` and ``MAX_UPLOAD_MB``."""
        return cls(
            registry_table=os.environ["REGISTRY_TABLE"],
            documents_bucket=os.environ["DOCUMENTS_BUCKET"],
            max_upload_bytes=int(os.environ.get("MAX_UPLOAD_MB", "100")) * 1024 * 1024,
        )


def sigv4_sign(
    method: str,
    url: str,
    body: bytes,
    extra_headers: dict[str, str],
) -> dict[str, str]:
    """Sign a request for the AgentCore Gateway with the task role's credentials.

    Args:
        method: HTTP method.
        url: Full request URL.
        body: Request body bytes.
        extra_headers: Headers to sign and send unchanged.

    Returns:
        The complete header mapping to send.
    """
    credentials = get_boto3_session().get_credentials().get_frozen_credentials()
    host = urlparse(url).netloc
    region = os.environ.get("AWS_REGION") or os.environ["AWS_DEFAULT_REGION"]
    timestamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
    request_headers = {
        "host": host,
        "x-amz-date": timestamp,
        **{key.lower(): value for key, value in extra_headers.items()},
    }
    aws_request = AWSRequest(method=method, url=url, data=body, headers=request_headers)
    SigV4Auth(credentials, "bedrock-agentcore", region).add_auth(aws_request)
    signed_headers = {
        "Host": host,
        "X-Amz-Date": aws_request.headers["x-amz-date"],
        "Authorization": aws_request.headers["Authorization"],
    }
    if credentials.token:
        signed_headers["X-Amz-Security-Token"] = credentials.token
    signed_headers.update(extra_headers)
    return signed_headers
