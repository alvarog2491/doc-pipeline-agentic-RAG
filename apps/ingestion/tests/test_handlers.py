import json

import pytest
from ingestion import handlers
from ingestion.knowledge_base import KnowledgeBaseRef
from ingestion.registry import FAILED, INDEXING, PROCESSING, READY


class FakeRegistry:
    def __init__(self):
        self.items = {}

    def get(self, doc_id):
        return self.items.get(doc_id)

    def update(self, doc_id, **fields):
        self.items.setdefault(doc_id, {"doc_id": doc_id}).update(fields)

    def delete(self, doc_id):
        self.items.pop(doc_id, None)


class FakeTextract:
    def __init__(self, blocks=None):
        self.started = []
        self.blocks = blocks or []

    def start_document_analysis(self, **kwargs):
        self.started.append(kwargs)
        return {"JobId": "job-1"}

    def get_document_analysis(self, JobId, NextToken=None):
        if NextToken is None and len(self.blocks) > 1:
            return {"Blocks": self.blocks[0], "NextToken": "n"}
        return {"Blocks": self.blocks[-1]}


class FakeS3:
    def __init__(self, metadata=None):
        self.metadata = metadata or {}

    def head_object(self, Bucket, Key):
        return {"Metadata": self.metadata}


def _clients(textract=None, s3=None):
    """A ``boto3.client`` stand-in that hands each service its own fake."""
    fakes = {"textract": textract or FakeTextract(), "s3": s3 or FakeS3()}
    return lambda name: fakes.get(name, object())


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for key, value in {
        "ENV": "dev",
        "REGISTRY_TABLE": "t",
        "VECTOR_BUCKET": "vb",
        "KB_ROLE_ARN": "arn:role",
        "TEXTRACT_TOPIC_ARN": "arn:topic",
        "TEXTRACT_ROLE_ARN": "arn:trole",
    }.items():
        monkeypatch.setenv(key, value)


def _s3_event(key, etag="e1"):
    return {
        "Records": [
            {"s3": {"bucket": {"name": "b"}, "object": {"key": key, "eTag": etag}}}
        ]
    }


def test_doc_id_is_stable_readable_and_distinct_per_key():
    a = handlers.doc_id_for("uploads/My Manual_v2.pdf")
    assert a == handlers.doc_id_for("uploads/My Manual_v2.pdf")
    assert a.startswith("my-manual-v2-")
    assert a != handlers.doc_id_for("uploads/sub/My Manual_v2.pdf")


def test_start_extraction_launches_textract_and_registers_processing(monkeypatch):
    registry, textract = FakeRegistry(), FakeTextract()
    monkeypatch.setattr(handlers, "_registry", lambda _s: registry)
    monkeypatch.setattr(handlers.boto3, "client", _clients(textract))

    result = handlers.start_extraction(_s3_event("uploads/Install+Guide.pdf"))

    [doc_id] = result["started"]
    call = textract.started[0]
    assert call["DocumentLocation"]["S3Object"] == {
        "Bucket": "b",
        "Name": "uploads/Install Guide.pdf",
    }
    assert call["FeatureTypes"] == ["LAYOUT", "TABLES"]
    assert call["JobTag"] == doc_id
    assert registry.items[doc_id]["status"] == PROCESSING
    assert registry.items[doc_id]["name"] == "Install Guide"


def test_start_extraction_records_the_chunking_requested_at_upload(monkeypatch):
    registry = FakeRegistry()
    monkeypatch.setattr(handlers, "_registry", lambda _s: registry)
    metadata = {"chunking": "hierarchical", "max-tokens": "250"}
    monkeypatch.setattr(handlers.boto3, "client", _clients(s3=FakeS3(metadata)))

    [doc_id] = handlers.start_extraction(_s3_event("uploads/deck.pdf"))["started"]

    assert registry.items[doc_id]["chunking"] == {
        "strategy": "hierarchical",
        "max_tokens": 250,
    }


def test_start_extraction_defaults_to_semantic_chunking(monkeypatch):
    registry = FakeRegistry()
    monkeypatch.setattr(handlers, "_registry", lambda _s: registry)
    monkeypatch.setattr(handlers.boto3, "client", _clients())

    [doc_id] = handlers.start_extraction(_s3_event("uploads/paper.pdf"))["started"]

    assert registry.items[doc_id]["chunking"] == {
        "strategy": "semantic",
        "max_tokens": 300,
    }


def test_start_extraction_ignores_other_prefixes_and_types(monkeypatch):
    registry, textract = FakeRegistry(), FakeTextract()
    monkeypatch.setattr(handlers, "_registry", lambda _s: registry)
    monkeypatch.setattr(handlers.boto3, "client", _clients(textract))

    for key in ("other/x.pdf", "uploads/x.txt"):
        assert handlers.start_extraction(_s3_event(key)) == {"started": []}
    assert textract.started == []


def _sns(status="SUCCEEDED", doc_id="doc-1"):
    message = {"JobId": "job-1", "Status": status, "JobTag": doc_id}
    return {"Records": [{"Sns": {"Message": json.dumps(message)}}]}


def test_process_result_marks_failed_textract_jobs(monkeypatch):
    registry = FakeRegistry()
    monkeypatch.setattr(handlers, "_registry", lambda _s: registry)
    monkeypatch.setattr(handlers.boto3, "client", _clients())

    assert handlers.process_result(_sns("FAILED")) == {"ready": []}
    assert registry.items["doc-1"]["status"] == FAILED


def test_process_result_ingests_and_marks_ready(monkeypatch):
    registry = FakeRegistry()
    registry.update("doc-1", source_key="uploads/a.pdf", chunk_count=0)
    monkeypatch.setattr(handlers, "_registry", lambda _s: registry)
    monkeypatch.setattr(handlers.boto3, "client", _clients())
    seen = {}

    def fake_ingest(settings, reg, textract, doc_id, job_id):
        seen["args"] = (doc_id, job_id)
        reg.update(doc_id, status=READY, kb_id="KB1")

    monkeypatch.setattr(handlers, "_ingest", fake_ingest)

    assert handlers.process_result(_sns()) == {"ready": ["doc-1"]}
    assert seen["args"] == ("doc-1", "job-1")
    assert registry.items["doc-1"]["kb_id"] == "KB1"


def test_process_result_records_failure_and_reraises(monkeypatch):
    registry = FakeRegistry()
    monkeypatch.setattr(handlers, "_registry", lambda _s: registry)
    monkeypatch.setattr(handlers.boto3, "client", _clients())

    def boom(*_a):
        raise ValueError("Textract returned no extractable text")

    monkeypatch.setattr(handlers, "_ingest", boom)

    with pytest.raises(ValueError):
        handlers.process_result(_sns())
    assert registry.items["doc-1"]["status"] == FAILED
    assert "no extractable text" in registry.items["doc-1"]["error"]


def test_on_delete_removes_knowledge_base_and_registry_entry(monkeypatch):
    registry = FakeRegistry()
    doc_id = handlers.doc_id_for("uploads/a.pdf")
    registry.update(doc_id, kb_id="KB1", index_name=doc_id)
    monkeypatch.setattr(handlers, "_registry", lambda _s: registry)
    monkeypatch.setattr(handlers.boto3, "client", _clients())
    deleted = {}
    monkeypatch.setattr(
        handlers, "delete_knowledge_base", lambda **kw: deleted.update(kw["item"])
    )

    assert handlers.on_delete(_s3_event("uploads/a.pdf")) == {"deleted": [doc_id]}
    assert deleted["kb_id"] == "KB1"
    assert registry.get(doc_id) is None


def _layout_blocks():
    line = {"Id": "l", "BlockType": "LINE", "Text": "Hello world.", "Page": 1}
    layout = {
        "Id": "p",
        "BlockType": "LAYOUT_TEXT",
        "Page": 1,
        "Relationships": [{"Type": "CHILD", "Ids": ["l"]}],
    }
    return [line, layout]


def test_ingest_stages_pages_starts_bedrock_and_moves_to_indexing_without_waiting(
    monkeypatch,
):
    registry = FakeRegistry()
    registry.update(
        "doc-1",
        bucket="b",
        source_key="uploads/a.pdf",
        chunking={"strategy": "fixed", "max_tokens": 200},
    )
    seen = {}
    monkeypatch.setattr(
        handlers.boto3, "client", _clients(FakeTextract([_layout_blocks()]))
    )
    monkeypatch.setattr(
        handlers, "stage_pages", lambda s3, **kw: seen.update(staged=kw)
    )

    def ensure(**kw):
        seen["ensure"] = kw
        return KnowledgeBaseRef("KB1", "arn", "DS1", "idx")

    monkeypatch.setattr(handlers, "ensure_knowledge_base", ensure)
    monkeypatch.setattr(handlers, "start_ingestion", lambda agent, ref: "JOB1")

    handlers._ingest(
        handlers.Settings.from_env(),
        registry,
        FakeTextract([_layout_blocks()]),
        "doc-1",
        "job-1",
    )

    item = registry.items["doc-1"]
    assert (item["status"], item["ingestion_job_id"], item["kb_id"], item["pages"]) == (
        INDEXING,
        "JOB1",
        "KB1",
        1,
    )
    assert (
        seen["staged"]["source"] == "uploads/a.pdf"
        and seen["staged"]["pages"][0].markdown == "Hello world."
    )
    assert seen["ensure"]["chunking"]["chunkingStrategy"] == "FIXED_SIZE"


def test_ingest_fails_clearly_when_textract_finds_no_text(monkeypatch):
    registry = FakeRegistry()
    registry.update("doc-1", bucket="b", source_key="uploads/a.pdf")
    monkeypatch.setattr(handlers.boto3, "client", _clients())

    with pytest.raises(ValueError, match="no text"):
        handlers._ingest(
            handlers.Settings.from_env(), registry, FakeTextract([[]]), "doc-1", "job-1"
        )


class ListingRegistry(FakeRegistry):
    def list_by_status(self, status):
        return [i for i in self.items.values() if i.get("status") == status]


def test_check_ingestion_finishes_ended_jobs_and_leaves_running_ones(monkeypatch):
    registry = ListingRegistry()
    for doc_id in ("done", "bad", "busy"):
        registry.update(
            doc_id,
            status=INDEXING,
            kb_id="KB",
            data_source_id="DS",
            ingestion_job_id=doc_id,
        )
    registry.update("other", status=READY)
    outcomes = {
        "done": (
            "COMPLETE",
            {"numberOfNewDocumentsIndexed": 4, "numberOfModifiedDocumentsIndexed": 1},
        ),
        "bad": ("FAILED", {"error": "ingestion job FAILED: quota"}),
        "busy": ("RUNNING", {}),
    }
    monkeypatch.setattr(handlers, "_registry", lambda _s: registry)
    monkeypatch.setattr(handlers.boto3, "client", _clients())
    monkeypatch.setattr(
        handlers, "ingestion_outcome", lambda agent, **kw: outcomes[kw["job_id"]]
    )

    result = handlers.check_ingestion({})

    assert result == {"ready": ["done"], "failed": ["bad"]}
    assert (
        registry.items["done"]["status"] == READY
        and registry.items["done"]["chunk_count"] == 5
    )
    assert (
        registry.items["bad"]["status"] == FAILED
        and "quota" in registry.items["bad"]["error"]
    )
    assert registry.items["busy"]["status"] == INDEXING
