"""Lambda entrypoints for the upload -> Textract -> Knowledge Base (built-in chunking) pipeline."""

from __future__ import annotations

import hashlib
import json
import logging
from urllib.parse import unquote_plus

import boto3

from .chunking_options import ChunkingOptions, resolve_options, to_bedrock
from .config import UPLOAD_PREFIX, Settings, slugify
from .elements import parse_elements
from .knowledge_base import (
    delete_knowledge_base,
    ensure_knowledge_base,
    ingestion_outcome,
    input_prefix,
    stage_pages,
    start_ingestion,
)
from .pages import build_pages
from .registry import FAILED, INDEXING, PROCESSING, READY, Registry

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def doc_id_for(key: str) -> str:
    """Derive the stable document id for an uploaded object key.

    The name keeps the id readable in the dropdown; the hash keeps two different uploads
    with the same filename apart.

    Args:
        key: S3 object key of the PDF.

    Returns:
        Slug of the filename plus a six-character key hash.
    """
    stem = key.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    digest = hashlib.sha1(key.encode()).hexdigest()[:6]
    return f"{slugify(stem)[:50]}-{digest}"


def _display_name(key: str) -> str:
    return key.rsplit("/", 1)[-1].rsplit(".", 1)[0].replace("_", " ").strip()


def _is_upload(key: str) -> bool:
    return key.startswith(UPLOAD_PREFIX) and key.lower().endswith(".pdf")


def _s3_records(event: dict):
    """Yield ``(bucket, key, etag)`` for each S3 notification record."""
    for record in event.get("Records", []):
        s3 = record["s3"]
        yield (
            s3["bucket"]["name"],
            unquote_plus(s3["object"]["key"]),
            s3["object"].get("eTag", ""),
        )


def _registry(settings: Settings) -> Registry:
    return Registry(boto3.resource("dynamodb").Table(settings.registry_table))


def start_extraction(event: dict, _context: object = None) -> dict:
    """Start an asynchronous Textract analysis for each uploaded PDF.

    Triggered by ``s3:ObjectCreated`` on ``uploads/*.pdf``. The registry entry is created
    immediately in ``PROCESSING`` so the document shows up while Textract runs, and records the
    chunking strategy requested through the object's metadata.

    Args:
        event: S3 notification event.
        _context: Lambda context (unused).

    Returns:
        A mapping with the list of started ``doc_id`` values.
    """
    settings = Settings.from_env()
    registry = _registry(settings)
    textract = boto3.client("textract")
    s3 = boto3.client("s3")
    started = []
    for bucket, key, etag in _s3_records(event):
        if not _is_upload(key):
            logger.info("Ignoring non-PDF or out-of-prefix key %s", key)
            continue
        doc_id = doc_id_for(key)
        # How to chunk this PDF is chosen at upload time through S3 object metadata.
        metadata = s3.head_object(Bucket=bucket, Key=key).get("Metadata", {})
        chunking = resolve_options(metadata)
        job = textract.start_document_analysis(
            DocumentLocation={"S3Object": {"Bucket": bucket, "Name": key}},
            FeatureTypes=["LAYOUT", "TABLES"],
            JobTag=doc_id,
            ClientRequestToken=hashlib.sha1(f"{key}{etag}".encode()).hexdigest(),
            NotificationChannel={
                "SNSTopicArn": settings.textract_topic_arn,
                "RoleArn": settings.textract_role_arn,
            },
        )
        registry.update(
            doc_id,
            name=_display_name(key),
            bucket=bucket,
            source_key=key,
            status=PROCESSING,
            textract_job_id=job["JobId"],
            chunking=chunking.to_dict(),
            error="",
        )
        started.append(doc_id)
        logger.info("Started Textract job %s for %s", job["JobId"], doc_id)
    return {"started": started}


def _all_blocks(textract, job_id: str) -> list[dict]:
    blocks: list[dict] = []
    token = None
    while True:
        kwargs = {"JobId": job_id, **({"NextToken": token} if token else {})}
        page = textract.get_document_analysis(**kwargs)
        blocks.extend(page["Blocks"])
        token = page.get("NextToken")
        if not token:
            return blocks


def process_result(event: dict, _context: object = None) -> dict:
    """Stage a finished Textract job as pages and have Bedrock chunk and embed them.

    Triggered by the Textract completion SNS topic. On success the registry entry moves to
    ``READY`` with the Knowledge Base id; on any failure it moves to ``FAILED`` and the
    error is re-raised so Lambda's async retry can converge (every step is idempotent).

    Args:
        event: SNS event whose message is Textract's completion notification.
        _context: Lambda context (unused).

    Returns:
        A mapping with the ``doc_id`` values that reached ``READY``.
    """
    settings = Settings.from_env()
    registry = _registry(settings)
    textract = boto3.client("textract")
    ready = []
    for record in event.get("Records", []):
        message = json.loads(record["Sns"]["Message"])
        doc_id = message["JobTag"]
        if message["Status"] != "SUCCEEDED":
            registry.update(
                doc_id, status=FAILED, error=f"Textract {message['Status']}"
            )
            continue
        try:
            _ingest(settings, registry, textract, doc_id, message["JobId"])
            ready.append(doc_id)
        except Exception as error:
            registry.update(doc_id, status=FAILED, error=str(error)[:500])
            raise
    return {"ready": ready}


def _ingest(
    settings: Settings, registry: Registry, textract, doc_id: str, job_id: str
) -> None:
    """Stage the pages, provision the Knowledge Base and start Bedrock's ingestion job.

    The job is not awaited: the registry moves to ``INDEXING`` and ``check_ingestion`` finishes
    the document, so a very large PDF is not limited by this Lambda's timeout.
    """
    item = registry.get(doc_id) or {}
    bucket = item["bucket"]
    prefix = input_prefix(doc_id)
    region = boto3.session.Session().region_name
    pages = build_pages(parse_elements(_all_blocks(textract, job_id)))
    if not pages:
        raise ValueError(
            "Textract found no text in this PDF (blank, or an image Textract could not read)"
        )

    stage_pages(
        boto3.client("s3"),
        bucket=bucket,
        prefix=prefix,
        doc_id=doc_id,
        source=item.get("source_key", ""),
        pages=pages,
    )
    stored = item.get("chunking") or {}
    options = ChunkingOptions(
        strategy=str(stored.get("strategy", "semantic")),
        max_tokens=int(stored.get("max_tokens", 300)),
    )
    bedrock_agent = boto3.client("bedrock-agent")
    ref = ensure_knowledge_base(
        bedrock_agent=bedrock_agent,
        s3vectors=boto3.client("s3vectors"),
        region=region,
        vector_bucket=settings.vector_bucket,
        kb_role_arn=settings.kb_role_arn,
        embedding_model_id=settings.embedding_model_id,
        name=f"docpipe-{settings.env}-{doc_id}"[:100],
        index_name=doc_id,
        bucket_arn=f"arn:aws:s3:::{bucket}",
        prefix=prefix,
        chunking=to_bedrock(options),
    )
    registry.update(
        doc_id,
        status=INDEXING,
        kb_id=ref.kb_id,
        kb_arn=ref.kb_arn,
        data_source_id=ref.data_source_id,
        index_name=doc_id,
        pages=len(pages),
        ingestion_job_id=start_ingestion(bedrock_agent, ref),
        error="",
    )
    logger.info(
        "Document %s: %d pages staged, indexing in %s", doc_id, len(pages), ref.kb_id
    )


def check_ingestion(_event: object = None, _context: object = None) -> dict:
    """Finish documents whose Bedrock ingestion job has ended.

    Runs on a one-minute schedule. Each ``INDEXING`` document's job is inspected: a finished job
    moves the document to ``READY``, a failed one to ``FAILED`` with the reason, and a running one
    is left for the next tick.

    Args:
        _event: Scheduler event (unused).
        _context: Lambda context (unused).

    Returns:
        A mapping with the ``ready`` and ``failed`` ``doc_id`` values of this tick.
    """
    settings = Settings.from_env()
    registry = _registry(settings)
    bedrock_agent = boto3.client("bedrock-agent")
    ready, failed = [], []
    for item in registry.list_by_status(INDEXING):
        doc_id = item["doc_id"]
        state, detail = ingestion_outcome(
            bedrock_agent,
            kb_id=item["kb_id"],
            data_source_id=item["data_source_id"],
            job_id=item["ingestion_job_id"],
        )
        if state == "COMPLETE":
            registry.update(
                doc_id,
                status=READY,
                chunk_count=int(detail.get("numberOfNewDocumentsIndexed", 0))
                + int(detail.get("numberOfModifiedDocumentsIndexed", 0)),
                error="",
            )
            ready.append(doc_id)
        elif state == "FAILED":
            registry.update(doc_id, status=FAILED, error=detail["error"][:500])
            failed.append(doc_id)
    return {"ready": ready, "failed": failed}


def on_delete(event: dict, _context: object = None) -> dict:
    """Remove a document's Knowledge Base, vector index and registry entry.

    Triggered by ``s3:ObjectRemoved`` on ``uploads/*.pdf``.

    Args:
        event: S3 notification event.
        _context: Lambda context (unused).

    Returns:
        A mapping with the deleted ``doc_id`` values.
    """
    settings = Settings.from_env()
    registry = _registry(settings)
    deleted = []
    for bucket, key, _etag in _s3_records(event):
        if not _is_upload(key):
            continue
        doc_id = doc_id_for(key)
        item = registry.get(doc_id)
        if item:
            delete_knowledge_base(
                bedrock_agent=boto3.client("bedrock-agent"),
                s3vectors=boto3.client("s3vectors"),
                s3=boto3.client("s3"),
                bucket=bucket,
                vector_bucket=settings.vector_bucket,
                item=item,
                prefix=input_prefix(doc_id),
            )
            registry.delete(doc_id)
        deleted.append(doc_id)
    return {"deleted": deleted}
