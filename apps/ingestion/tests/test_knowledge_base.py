import json

import pytest
from ingestion.chunking_options import ChunkingOptions, fingerprint, to_bedrock
from ingestion.knowledge_base import (
    KnowledgeBaseRef,
    delete_knowledge_base,
    ensure_knowledge_base,
    ingestion_outcome,
    input_prefix,
    page_key,
    stage_pages,
    start_ingestion,
)
from ingestion.pages import Page

SEMANTIC = to_bedrock(ChunkingOptions())


class Conflict(Exception):
    def __init__(self):
        self.response = {"Error": {"Code": "ConflictException"}}


class FakeS3Vectors:
    def __init__(self, conflict=False):
        self.conflict, self.created, self.deleted = conflict, [], []

    def create_index(self, **kwargs):
        if self.conflict:
            raise Conflict()
        self.created.append(kwargs)

    def get_index(self, **kwargs):
        return {"index": {"indexArn": f"arn:index/{kwargs['indexName']}"}}

    def delete_index(self, **kwargs):
        self.deleted.append(kwargs)


class FakeAgent:
    def __init__(
        self, existing=None, job_statuses=("IN_PROGRESS", "COMPLETE"), stats=None
    ):
        self.kbs = existing or []
        self.created_kb, self.created_source = [], []
        self.sources = []
        self.statuses = ["CREATING", "ACTIVE"]
        self.job_statuses = list(job_statuses)
        self.stats = stats

    def get_paginator(self, _name):
        agent = self

        class Paginator:
            def paginate(self):
                yield {"knowledgeBaseSummaries": agent.kbs}

        return Paginator()

    def get_knowledge_base(self, knowledgeBaseId):
        status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        return {
            "knowledgeBase": {
                "knowledgeBaseId": knowledgeBaseId,
                "knowledgeBaseArn": f"arn:kb/{knowledgeBaseId}",
                "status": status,
            }
        }

    def create_knowledge_base(self, **kwargs):
        self.created_kb.append(kwargs)
        return {
            "knowledgeBase": {
                "knowledgeBaseId": "KB1",
                "knowledgeBaseArn": "arn:kb/KB1",
                "status": "CREATING",
            }
        }

    def list_data_sources(self, knowledgeBaseId):
        return {"dataSourceSummaries": self.sources}

    def create_data_source(self, **kwargs):
        self.created_source.append(kwargs)
        self.sources = [{"dataSourceId": "DS1"}]
        return {"dataSource": {"dataSourceId": "DS1"}}

    def start_ingestion_job(self, **kwargs):
        return {"ingestionJob": {"ingestionJobId": "J1", "status": "STARTING"}}

    def get_ingestion_job(self, **kwargs):
        status = (
            self.job_statuses.pop(0)
            if len(self.job_statuses) > 1
            else self.job_statuses[0]
        )
        return {
            "ingestionJob": {
                "ingestionJobId": "J1",
                "status": status,
                "statistics": self.stats,
            }
        }

    def delete_data_source(self, **kwargs):
        self.sources = []

    def delete_knowledge_base(self, **kwargs):
        self.kbs = []


class FakeS3:
    def __init__(self, existing=()):
        self.objects = {key: b"old" for key in existing}
        self.deleted = []

    def get_paginator(self, _name):
        s3 = self

        class Paginator:
            def paginate(self, Bucket, Prefix):
                yield {
                    "Contents": [{"Key": k} for k in s3.objects if k.startswith(Prefix)]
                }

        return Paginator()

    def delete_objects(self, Bucket, Delete):
        for obj in Delete["Objects"]:
            self.objects.pop(obj["Key"], None)
            self.deleted.append(obj["Key"])

    def put_object(self, Bucket, Key, Body, ContentType):
        self.objects[Key] = Body


def _ensure(agent, s3v, chunking=None):
    return ensure_knowledge_base(
        bedrock_agent=agent,
        s3vectors=s3v,
        region="eu-central-1",
        vector_bucket="vb",
        kb_role_arn="arn:role",
        embedding_model_id="amazon.titan-embed-text-v2:0",
        name="docpipe-dev-manual-abc123",
        index_name="manual-abc123",
        bucket_arn="arn:aws:s3:::docs",
        prefix="kb-input/manual-abc123/",
        chunking=chunking or SEMANTIC,
        poll_seconds=0,
    )


def test_creates_index_kb_and_an_s3_data_source_with_bedrocks_semantic_chunking():
    agent, s3v = FakeAgent(), FakeS3Vectors()

    ref = _ensure(agent, s3v)

    assert ref == KnowledgeBaseRef(
        "KB1", "arn:kb/KB1", "DS1", "arn:index/manual-abc123"
    )
    assert (
        s3v.created[0]["dimension"] == 1024
        and s3v.created[0]["distanceMetric"] == "cosine"
    )
    assert agent.created_kb[0]["storageConfiguration"]["type"] == "S3_VECTORS"
    embedding = agent.created_kb[0]["knowledgeBaseConfiguration"][
        "vectorKnowledgeBaseConfiguration"
    ]
    assert embedding["embeddingModelArn"].endswith(
        "foundation-model/amazon.titan-embed-text-v2:0"
    )
    source = agent.created_source[0]
    assert source["dataSourceConfiguration"] == {
        "type": "S3",
        "s3Configuration": {
            "bucketArn": "arn:aws:s3:::docs",
            "inclusionPrefixes": ["kb-input/manual-abc123/"],
        },
    }
    assert source["vectorIngestionConfiguration"]["chunkingConfiguration"] == SEMANTIC
    assert SEMANTIC["chunkingStrategy"] == "SEMANTIC"
    assert source["description"] == f"chunking:{fingerprint(SEMANTIC)}"
    assert source["dataDeletionPolicy"] == "DELETE"


def test_is_idempotent_when_resources_already_exist():
    agent = FakeAgent(
        existing=[{"name": "docpipe-dev-manual-abc123", "knowledgeBaseId": "KB9"}]
    )
    agent.statuses = ["ACTIVE"]
    agent.sources = [
        {"dataSourceId": "DS9", "description": f"chunking:{fingerprint(SEMANTIC)}"}
    ]

    ref = _ensure(agent, FakeS3Vectors(conflict=True))

    assert (ref.kb_id, ref.data_source_id) == ("KB9", "DS9")
    assert agent.created_kb == [] and agent.created_source == []


def test_stage_pages_writes_markdown_with_metadata_sidecars_after_clearing_stale_files():
    prefix = input_prefix("doc")
    s3 = FakeS3(
        existing=[f"{prefix}page-0009.md", f"{prefix}page-0009.md.metadata.json"]
    )
    pages = [Page(1, "Intro", "# Intro\n\nHello"), Page(2, "", "Body")]

    stage_pages(
        s3,
        bucket="docs",
        prefix=prefix,
        doc_id="doc",
        source="uploads/doc.pdf",
        pages=pages,
    )

    assert set(s3.objects) == {
        page_key(prefix, pages[0]),
        page_key(prefix, pages[0]) + ".metadata.json",
        page_key(prefix, pages[1]),
        page_key(prefix, pages[1]) + ".metadata.json",
    }
    assert s3.objects[page_key(prefix, pages[0])] == b"# Intro\n\nHello"
    attributes = json.loads(s3.objects[page_key(prefix, pages[1]) + ".metadata.json"])[
        "metadataAttributes"
    ]
    assert attributes == {
        "doc_id": "doc",
        "source": "uploads/doc.pdf",
        "page": 2,
        "section": "-",
    }
    assert f"{prefix}page-0009.md" in s3.deleted  # the old version's page is gone


def test_changed_chunking_recreates_the_data_source_because_bedrock_cannot_edit_it():
    agent = FakeAgent(
        existing=[{"name": "docpipe-dev-manual-abc123", "knowledgeBaseId": "KB9"}]
    )
    agent.statuses = ["ACTIVE"]
    agent.sources = [
        {"dataSourceId": "OLD", "description": f"chunking:{fingerprint(SEMANTIC)}"}
    ]
    fixed = to_bedrock(ChunkingOptions("fixed", 200))

    ref = _ensure(agent, FakeS3Vectors(conflict=True), chunking=fixed)

    assert ref.data_source_id == "DS1"
    assert (
        agent.created_source[0]["vectorIngestionConfiguration"]["chunkingConfiguration"]
        == fixed
    )


def test_start_ingestion_returns_the_job_id_without_waiting():
    assert (
        start_ingestion(FakeAgent(), KnowledgeBaseRef("KB1", "arn", "DS1", "idx"))
        == "J1"
    )


@pytest.mark.parametrize(
    "status,stats,expected,fragment",
    [
        ("IN_PROGRESS", None, "RUNNING", None),
        ("STARTING", None, "RUNNING", None),
        ("COMPLETE", {"numberOfNewDocumentsIndexed": 3}, "COMPLETE", None),
        ("FAILED", None, "FAILED", "ingestion job FAILED"),
        ("STOPPED", None, "FAILED", "STOPPED"),
        ("COMPLETE", {"numberOfDocumentsFailed": 2}, "FAILED", "2 page"),
    ],
)
def test_ingestion_outcome_maps_job_states(status, stats, expected, fragment):
    agent = FakeAgent(job_statuses=(status,), stats=stats)

    state, detail = ingestion_outcome(
        agent, kb_id="KB1", data_source_id="DS1", job_id="J1"
    )

    assert state == expected
    if fragment:
        assert fragment in detail["error"]
    if expected == "COMPLETE":
        assert detail == {"numberOfNewDocumentsIndexed": 3}


def test_delete_removes_source_kb_index_and_staged_pages():
    agent, s3v = FakeAgent(), FakeS3Vectors()
    agent.sources = [{"dataSourceId": "DS1"}]
    agent.kbs = [{"name": "x"}]
    s3 = FakeS3(existing=["kb-input/doc/page-0001.md", "uploads/doc.pdf"])

    delete_knowledge_base(
        bedrock_agent=agent,
        s3vectors=s3v,
        s3=s3,
        bucket="docs",
        vector_bucket="vb",
        item={"kb_id": "KB1", "index_name": "manual-abc123"},
        prefix="kb-input/doc/",
    )

    assert agent.sources == [] and agent.kbs == []
    assert s3v.deleted == [{"vectorBucketName": "vb", "indexName": "manual-abc123"}]
    assert list(s3.objects) == [
        "uploads/doc.pdf"
    ]  # the source PDF itself is never touched
