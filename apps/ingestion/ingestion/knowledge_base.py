"""Provision one Bedrock Knowledge Base (S3 Vectors) per document and let Bedrock ingest it.

Chunking and embedding are Bedrock's own: the data source uses one of Bedrock's built-in chunking
strategies (see ``chunking_options``) and the Knowledge Base embeds every chunk with its Titan
model. This module only stages the per-page Markdown (plus metadata sidecars) in S3 and starts
the ingestion job; ``check_ingestion`` later observes it, so large documents are not bound by a
Lambda's 15 minutes.
"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from .chunking_options import fingerprint
from .config import EMBEDDING_DIMENSIONS
from .pages import Page

logger = logging.getLogger(__name__)

INPUT_PREFIX = "kb-input/"


@dataclass(frozen=True)
class KnowledgeBaseRef:
    """Identifiers of a provisioned Knowledge Base.

    Attributes:
        kb_id: Knowledge Base id used by ``Retrieve``.
        kb_arn: Knowledge Base ARN.
        data_source_id: S3 data source Bedrock ingests from.
        index_arn: S3 Vectors index that stores the embeddings.
    """

    kb_id: str
    kb_arn: str
    data_source_id: str
    index_arn: str


def _error_code(error: Exception) -> str:
    return getattr(error, "response", {}).get("Error", {}).get("Code", "")


def input_prefix(doc_id: str) -> str:
    """Return the S3 prefix that holds one document's staged pages."""
    return f"{INPUT_PREFIX}{doc_id}/"


def ensure_knowledge_base(
    *,
    bedrock_agent,
    s3vectors,
    region: str,
    vector_bucket: str,
    kb_role_arn: str,
    embedding_model_id: str,
    name: str,
    index_name: str,
    bucket_arn: str,
    prefix: str,
    chunking: dict,
    poll_seconds: float = 3.0,
) -> KnowledgeBaseRef:
    """Create the vector index, Knowledge Base and S3 data source for one document.

    Each step tolerates a previous partial run, so a Lambda retry converges on the same
    resources instead of failing or duplicating them.

    Args:
        bedrock_agent: A ``bedrock-agent`` client.
        s3vectors: An ``s3vectors`` client.
        region: AWS region, used to build the embedding model ARN.
        vector_bucket: S3 Vectors bucket that holds the per-document index.
        kb_role_arn: Service role assumed by the Knowledge Base.
        embedding_model_id: Titan embedding model id Bedrock embeds chunks with.
        name: Knowledge Base name, unique per document.
        index_name: S3 Vectors index name for this document.
        bucket_arn: Documents bucket that holds the staged pages.
        prefix: Prefix of this document's staged pages inside that bucket.
        chunking: Bedrock ``chunkingConfiguration`` for the data source.
        poll_seconds: Delay between Knowledge Base status checks.

    Returns:
        The identifiers of the ready Knowledge Base.
    """
    try:
        s3vectors.create_index(
            vectorBucketName=vector_bucket,
            indexName=index_name,
            dataType="float32",
            dimension=EMBEDDING_DIMENSIONS,
            distanceMetric="cosine",
            metadataConfiguration={
                "nonFilterableMetadataKeys": [
                    "AMAZON_BEDROCK_TEXT",
                    "AMAZON_BEDROCK_METADATA",
                ]
            },
        )
    except Exception as error:
        if _error_code(error) != "ConflictException":
            raise
    index_arn = s3vectors.get_index(
        vectorBucketName=vector_bucket, indexName=index_name
    )["index"]["indexArn"]

    kb = _find_knowledge_base(bedrock_agent, name)
    if kb is None:
        kb = bedrock_agent.create_knowledge_base(
            name=name,
            description=f"Built-in semantic chunks of {name}",
            roleArn=kb_role_arn,
            knowledgeBaseConfiguration={
                "type": "VECTOR",
                "vectorKnowledgeBaseConfiguration": {
                    "embeddingModelArn": (
                        f"arn:aws:bedrock:{region}::foundation-model/{embedding_model_id}"
                    ),
                    "embeddingModelConfiguration": {
                        "bedrockEmbeddingModelConfiguration": {
                            "dimensions": EMBEDDING_DIMENSIONS,
                            "embeddingDataType": "FLOAT32",
                        }
                    },
                },
            },
            storageConfiguration={
                "type": "S3_VECTORS",
                "s3VectorsConfiguration": {"indexArn": index_arn},
            },
        )["knowledgeBase"]
    kb_id = kb["knowledgeBaseId"]
    while kb["status"] not in ("ACTIVE", "FAILED"):
        time.sleep(poll_seconds)
        kb = bedrock_agent.get_knowledge_base(knowledgeBaseId=kb_id)["knowledgeBase"]
    if kb["status"] == "FAILED":
        raise RuntimeError(f"Knowledge Base {kb_id} failed: {kb.get('failureReasons')}")

    return KnowledgeBaseRef(
        kb_id=kb_id,
        kb_arn=kb["knowledgeBaseArn"],
        data_source_id=_ensure_data_source(
            bedrock_agent, kb_id, bucket_arn, prefix, chunking
        ),
        index_arn=index_arn,
    )


def _find_knowledge_base(bedrock_agent, name: str) -> dict | None:
    for page in bedrock_agent.get_paginator("list_knowledge_bases").paginate():
        for summary in page["knowledgeBaseSummaries"]:
            if summary["name"] == name:
                return bedrock_agent.get_knowledge_base(
                    knowledgeBaseId=summary["knowledgeBaseId"]
                )["knowledgeBase"]
    return None


def _ensure_data_source(
    bedrock_agent, kb_id: str, bucket_arn: str, prefix: str, chunking: dict
) -> str:
    """Return the data source with the wanted chunking, recreating it when that changed.

    Bedrock cannot change a data source's chunking after creation, so the configuration's
    fingerprint is kept in the description; a re-upload that asks for different chunking
    replaces the data source (and, through ``dataDeletionPolicy``, its old vectors).
    """
    description = f"chunking:{fingerprint(chunking)}"
    for summary in bedrock_agent.list_data_sources(knowledgeBaseId=kb_id)[
        "dataSourceSummaries"
    ]:
        if summary.get("description") == description:
            return summary["dataSourceId"]
        bedrock_agent.delete_data_source(
            knowledgeBaseId=kb_id, dataSourceId=summary["dataSourceId"]
        )
    return bedrock_agent.create_data_source(
        knowledgeBaseId=kb_id,
        name="pages",
        description=description,
        dataDeletionPolicy="DELETE",
        dataSourceConfiguration={
            "type": "S3",
            "s3Configuration": {"bucketArn": bucket_arn, "inclusionPrefixes": [prefix]},
        },
        vectorIngestionConfiguration={"chunkingConfiguration": chunking},
    )["dataSource"]["dataSourceId"]


def page_key(prefix: str, page: Page) -> str:
    """Return the S3 key of a page's Markdown file."""
    return f"{prefix}page-{page.number:04d}.md"


def stage_pages(
    s3, *, bucket: str, prefix: str, doc_id: str, source: str, pages: list[Page]
) -> None:
    """Replace a document's staged pages with the given ones.

    Every page is a Markdown file with a ``.metadata.json`` sidecar carrying the attributes
    Bedrock stores with each chunk (``doc_id``, ``source``, ``page``, ``section``). Files left
    by a previous version of the PDF are deleted first, so the next ingestion job also drops
    their vectors.

    Args:
        s3: An S3 client.
        bucket: Documents bucket.
        prefix: This document's staging prefix.
        doc_id: Document identifier.
        source: S3 key of the source PDF, stored as citation metadata.
        pages: Pages to stage.
    """
    stale = []
    for listing in s3.get_paginator("list_objects_v2").paginate(
        Bucket=bucket, Prefix=prefix
    ):
        stale += [{"Key": obj["Key"]} for obj in listing.get("Contents", [])]
    for start in range(0, len(stale), 1000):
        s3.delete_objects(
            Bucket=bucket, Delete={"Objects": stale[start : start + 1000]}
        )

    def put(page: Page) -> None:
        key = page_key(prefix, page)
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=page.markdown.encode(),
            ContentType="text/markdown",
        )
        metadata = {
            "metadataAttributes": {
                "doc_id": doc_id,
                "source": source,
                "page": page.number,
                # Bedrock rejects oversized attribute values; a heading is context, not data.
                "section": (page.section or "-")[:200],
            }
        }
        s3.put_object(
            Bucket=bucket,
            Key=f"{key}.metadata.json",
            Body=json.dumps(metadata).encode(),
            ContentType="application/json",
        )

    # Thousands of pages are thousands of tiny objects; upload them concurrently.
    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(put, pages))


def start_ingestion(bedrock_agent, ref: KnowledgeBaseRef) -> str:
    """Start Bedrock's ingestion job (chunk, embed, store) and return its id without waiting."""
    job = bedrock_agent.start_ingestion_job(
        knowledgeBaseId=ref.kb_id, dataSourceId=ref.data_source_id
    )["ingestionJob"]
    return job["ingestionJobId"]


def ingestion_outcome(
    bedrock_agent, *, kb_id: str, data_source_id: str, job_id: str
) -> tuple[str, dict]:
    """Report an ingestion job's state.

    Returns:
        ``("RUNNING", {})`` while Bedrock is working, ``("COMPLETE", statistics)`` on success, or
        ``("FAILED", {"error": ...})`` when the job failed, was stopped, or indexed nothing.
    """
    job = bedrock_agent.get_ingestion_job(
        knowledgeBaseId=kb_id, dataSourceId=data_source_id, ingestionJobId=job_id
    )["ingestionJob"]
    status = job["status"]
    if status in ("STARTING", "IN_PROGRESS"):
        return "RUNNING", {}
    if status != "COMPLETE":
        return "FAILED", {
            "error": f"ingestion job {status}: {job.get('failureReasons')}"
        }
    stats = job.get("statistics", {})
    if stats.get("numberOfDocumentsFailed"):
        return "FAILED", {
            "error": f"{stats['numberOfDocumentsFailed']} page(s) failed to ingest"
        }
    return "COMPLETE", stats


def delete_knowledge_base(
    *,
    bedrock_agent,
    s3vectors,
    s3,
    bucket: str,
    vector_bucket: str,
    item: dict,
    prefix: str,
) -> None:
    """Delete a document's data source, Knowledge Base, vector index and staged pages."""
    kb_id = item.get("kb_id")
    if kb_id:
        try:
            for source in bedrock_agent.list_data_sources(knowledgeBaseId=kb_id)[
                "dataSourceSummaries"
            ]:
                bedrock_agent.delete_data_source(
                    knowledgeBaseId=kb_id, dataSourceId=source["dataSourceId"]
                )
            bedrock_agent.delete_knowledge_base(knowledgeBaseId=kb_id)
        except Exception as error:
            if _error_code(error) != "ResourceNotFoundException":
                raise
    if item.get("index_name"):
        try:
            s3vectors.delete_index(
                vectorBucketName=vector_bucket, indexName=item["index_name"]
            )
        except Exception as error:
            if _error_code(error) not in (
                "NotFoundException",
                "ResourceNotFoundException",
            ):
                raise
    stale = []
    for listing in s3.get_paginator("list_objects_v2").paginate(
        Bucket=bucket, Prefix=prefix
    ):
        stale += [{"Key": obj["Key"]} for obj in listing.get("Contents", [])]
    for start in range(0, len(stale), 1000):
        s3.delete_objects(
            Bucket=bucket, Delete={"Objects": stale[start : start + 1000]}
        )
