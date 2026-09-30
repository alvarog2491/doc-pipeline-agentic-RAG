"""The deployed agent: one real answer through the Gateway, and the documents behind it."""

from __future__ import annotations

import datetime
import json
import os
import sys
import uuid
from urllib.parse import urlparse

import httpx
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

from .. import terraform
from ..aws import aws_call
from ..context import Context
from ..shell import REPO_ROOT
from ..ui import die, info

DEFAULT_SMOKE_TEST_PROMPT = "Give me a one-sentence summary of this document."


def ready_knowledge_base(ctx: Context) -> str | None:
    """The Knowledge Base id of the first READY document in the registry, or None."""
    table = terraform.output(ctx, "registry_table")
    with aws_call(f"cannot read the document registry '{table}'"):
        items = (
            ctx.aws.session.resource("dynamodb").Table(table).scan().get("Items", [])
        )
    ready = sorted(
        (i for i in items if i.get("status") == "READY" and i.get("kb_id")),
        key=lambda i: str(i.get("doc_id")),
    )
    return str(ready[0]["kb_id"]) if ready else None


def _sigv4_headers(
    ctx: Context, url: str, body: bytes, extra: dict[str, str]
) -> dict[str, str]:
    credentials = ctx.aws.session.get_credentials().get_frozen_credentials()
    host = urlparse(url).netloc
    timestamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
    request = AWSRequest(
        method="POST",
        url=url,
        data=body,
        headers={
            "host": host,
            "x-amz-date": timestamp,
            **{k.lower(): v for k, v in extra.items()},
        },
    )
    SigV4Auth(credentials, "bedrock-agentcore", ctx.config.region).add_auth(request)
    headers = {
        "Host": host,
        "X-Amz-Date": request.headers["x-amz-date"],
        "Authorization": request.headers["Authorization"],
        **extra,
    }
    if credentials.token:
        headers["X-Amz-Security-Token"] = credentials.token
    return headers


def _read_events(response: httpx.Response) -> tuple[str, str]:
    """Return ``(route, answer)`` folded out of the runtime's event stream."""
    chunks: list[str] = []
    route = ""
    for line in response.iter_lines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            message = json.loads(data)
        except json.JSONDecodeError:
            continue
        if isinstance(message, dict):
            if isinstance(message.get("chunk"), str):
                chunks.append(message["chunk"])
            elif isinstance(message.get("route"), str):
                route = message["route"]
    return route, "".join(chunks)


def smoke_test(ctx: Context) -> None:
    """Invoke the deployed agent once through the Gateway and assert it answers.

    Everything else `deploy verify` checks is infrastructure. None of that exercises the
    model, a Knowledge Base, the Langfuse credentials, or the Gateway's IAM path to the
    runtime - an agent whose SSM parameter is missing is healthy by every other measure and
    answers nothing. This mirrors apps/agents/evaluations/agent_client.py: the same
    SigV4-signed `POST <gateway>/invocations` with the same streaming contract the API uses.

    It needs a document to ask about: the first READY one. With none, non-production
    environments publish the evaluation handbook through the real pipeline; production is
    never given a fixture document, so the answer check is skipped there.
    """
    knowledge_base_id = ready_knowledge_base(ctx)
    if knowledge_base_id is None:
        if ctx.config.env == "prod":
            info(
                "  no READY document in prod - skipping the answer check (upload one to enable it)"
            )
            return
        info(
            "  no READY document - publishing the evaluation handbook through the pipeline"
        )
        sys.path.insert(0, str(REPO_ROOT / "apps" / "agents" / "evaluations"))
        from fixture.document import ensure_fixture_document

        os.environ.setdefault(
            "DOCUMENTS_BUCKET", terraform.output(ctx, "documents_bucket")
        )
        os.environ.setdefault("REGISTRY_TABLE", terraform.output(ctx, "registry_table"))
        knowledge_base_id = ensure_fixture_document()

    url = f"{terraform.output(ctx, 'gateway_url').rstrip('/')}/invocations"
    prompt = os.environ.get("SMOKE_TEST_PROMPT") or DEFAULT_SMOKE_TEST_PROMPT
    timeout = float(os.environ.get("SMOKE_TEST_TIMEOUT", "300"))
    body = json.dumps({"prompt": prompt, "knowledgeBaseId": knowledge_base_id}).encode()
    # The runtime requires a 33-100 character session id; a fresh one per smoke test keeps
    # the call off any conversation a real user is holding.
    headers = _sigv4_headers(
        ctx,
        url,
        body,
        {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": f"smoke-{uuid.uuid4()}-{uuid.uuid4()}",
        },
    )

    info(f"POST {url}")
    with (
        httpx.Client(
            timeout=httpx.Timeout(connect=10.0, read=timeout, write=10.0, pool=10.0)
        ) as client,
        client.stream("POST", url, content=body, headers=headers) as response,
    ):
        if response.status_code >= 400:
            detail = response.read().decode(errors="replace")[:2000]
            raise die(f"agent returned HTTP {response.status_code}: {detail}")
        route, answer = _read_events(response)

    if not answer.strip():
        raise die(
            "agent returned an empty answer - the Gateway and runtime are reachable, but the "
            "agent produced nothing (check the runtime's application log group)"
        )
    info(
        f"  route={route or '?'}; agent answered {len(answer)} chars: {' '.join(answer.split())[:200]}..."
    )
