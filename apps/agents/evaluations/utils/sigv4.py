"""Sign AgentCore evaluation requests with AWS Signature Version 4."""

import datetime
import os
from urllib.parse import urlparse

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

# One session for the whole run: resolving the credential provider chain is what emits
# botocore's "Found credentials in ..." log, and an experiment signs one request per
# dataset item. The session still refreshes expiring credentials itself on later reads.
_SESSION = boto3.Session()


def sigv4_sign(
    method: str, url: str, body: bytes, extra_headers: dict[str, str]
) -> dict[str, str]:
    """Sign an HTTP request for the Bedrock AgentCore service.

    Args:
        method: HTTP method, such as ``POST``.
        url: Absolute request URL.
        body: Serialized request body.
        extra_headers: Caller-provided headers to include in the signature and result.

    Returns:
        Request headers containing the SigV4 authorization fields and caller headers.

    Raises:
        KeyError: If no AWS region is configured.
        AttributeError: If the active AWS session has no credentials.
    """
    credentials = _SESSION.get_credentials().get_frozen_credentials()
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
