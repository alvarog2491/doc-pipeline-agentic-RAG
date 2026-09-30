"""Publish the evaluation handbook through the real ingestion pipeline and find its Knowledge Base."""

from __future__ import annotations

import hashlib
import logging
import os
import time

import boto3
from fixture.pdf_builder import build_pdf

logger = logging.getLogger(__name__)

FIXTURE_KEY = "uploads/eval-handbook.pdf"
_POLL_SECONDS = 10.0


class FixtureError(RuntimeError):
    """The evaluation document could not be made ready."""


def _registry_item(table, doc_id_prefix: str = "eval-handbook") -> dict | None:
    items = table.scan().get("Items", [])
    return next(
        (i for i in items if str(i.get("doc_id", "")).startswith(doc_id_prefix)), None
    )


def ensure_fixture_document(
    *,
    bucket: str | None = None,
    registry_table: str | None = None,
    timeout_s: float = 900.0,
) -> str:
    """Upload the handbook (when new or changed) and wait until its Knowledge Base is ready.

    The upload exercises the production path end to end: S3 trigger, Textract, semantic
    chunking, Knowledge Base creation. A content hash on the object skips re-uploading an
    unchanged handbook.

    Args:
        bucket: Documents bucket; defaults to ``DOCUMENTS_BUCKET``.
        registry_table: Registry table; defaults to ``REGISTRY_TABLE``.
        timeout_s: How long to wait for ``READY``.

    Returns:
        The Knowledge Base id of the handbook.

    Raises:
        FixtureError: If ingestion fails or does not finish in time.
    """
    bucket = bucket or os.environ["DOCUMENTS_BUCKET"]
    registry_table = registry_table or os.environ["REGISTRY_TABLE"]
    pdf = build_pdf()
    digest = hashlib.sha256(pdf).hexdigest()
    s3 = boto3.client("s3")
    table = boto3.resource("dynamodb").Table(registry_table)

    try:
        current = s3.head_object(Bucket=bucket, Key=FIXTURE_KEY)["Metadata"].get(
            "fixture-sha"
        )
    except s3.exceptions.ClientError:
        current = None
    item = _registry_item(table)
    if current == digest and item and item.get("status") == "READY":
        logger.info("Evaluation handbook is up to date (kb_id=%s)", item["kb_id"])
        return str(item["kb_id"])

    started = time.time()
    logger.info("Uploading the evaluation handbook to s3://%s/%s", bucket, FIXTURE_KEY)
    s3.put_object(
        Bucket=bucket,
        Key=FIXTURE_KEY,
        Body=pdf,
        ContentType="application/pdf",
        Metadata={"fixture-sha": digest},
    )
    deadline = started + timeout_s
    while time.time() < deadline:
        time.sleep(_POLL_SECONDS)
        item = _registry_item(table)
        if item and item.get("status") == "FAILED":
            raise FixtureError(f"Ingestion failed: {item.get('error')}")
        if item and item.get("status") == "READY" and item.get("kb_id"):
            updated = str(item.get("updated_at", ""))
            if updated and updated > time.strftime(
                "%Y-%m-%dT%H:%M:%S", time.gmtime(started)
            ):
                return str(item["kb_id"])
    raise FixtureError("Timed out waiting for the evaluation handbook to become READY")
