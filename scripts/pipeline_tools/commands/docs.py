"""Uploading PDFs to the ingestion pipeline and seeing what it produced."""

from __future__ import annotations

import time
from pathlib import Path

from .. import terraform
from ..aws import aws_call
from ..context import Context
from ..ui import die, info

WAIT_SECONDS = 3600  # large PDFs take a while to extract and index
POLL_SECONDS = 10


def _registry_items(ctx: Context) -> list[dict]:
    table = terraform.output(ctx, "registry_table")
    with aws_call(f"cannot read the document registry '{table}'"):
        items = (
            ctx.aws.session.resource("dynamodb").Table(table).scan().get("Items", [])
        )
    return sorted(items, key=lambda item: str(item.get("name", "")).lower())


def upload(
    ctx: Context,
    pdf: str,
    *,
    wait: bool,
    chunking: str | None = None,
    max_tokens: int | None = None,
) -> None:
    """Upload a PDF to ``uploads/``, which triggers Textract, chunking and a new Knowledge Base.

    Args:
        ctx: Command context.
        pdf: Path to the PDF to upload.
        wait: Block until the document is READY (or FAILED).
        chunking: Bedrock chunking strategy for this PDF: semantic (default), hierarchical,
            fixed or none. Sent as S3 object metadata, which the ingestion Lambda reads.
        max_tokens: Target maximum tokens per chunk.
    """
    ctx.refuse_managed()
    path = Path(pdf)
    if not path.is_file() or path.suffix.lower() != ".pdf":
        raise die(f"'{pdf}' is not a PDF file")
    bucket = terraform.output(ctx, "documents_bucket")
    key = f"uploads/{path.name}"
    started = time.time()
    extra = {"ContentType": "application/pdf"}
    metadata = {
        name: str(value)
        for name, value in (("chunking", chunking), ("max-tokens", max_tokens))
        if value
    }
    if metadata:
        extra["Metadata"] = metadata
    with aws_call(f"cannot upload {path.name} to s3://{bucket}/{key}"):
        ctx.aws.client("s3").upload_file(str(path), bucket, key, ExtraArgs=extra)
    info(f"uploaded s3://{bucket}/{key}")
    if not wait:
        info("processing continues in the background; see `make list-documents`")
        return

    marker = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(started))
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        time.sleep(POLL_SECONDS)
        for item in _registry_items(ctx):
            if (
                item.get("source_key") == key
                and str(item.get("updated_at", "")) > marker
            ):
                status = item.get("status")
                if status == "READY":
                    info(
                        f"READY: {item.get('name')} ({item.get('pages')} pages, kb_id={item.get('kb_id')})"
                    )
                    return
                if status == "FAILED":
                    raise die(f"ingestion failed: {item.get('error')}")
        info("  still processing...")
    raise die(f"timed out after {WAIT_SECONDS}s waiting for {path.name}")


def list_documents(ctx: Context) -> None:
    """Print every ingested document with its status and Knowledge Base id."""
    items = _registry_items(ctx)
    if not items:
        info(
            "no documents yet - upload one with `make upload-document PDF=path/to/file.pdf`"
        )
        return
    for item in items:
        print(
            f"{item.get('status')!s:<11} {item.get('kb_id') or '-'!s:<12} "
            f"{item.get('pages') or '-'!s:>4} pages  {item.get('name')}"
        )
