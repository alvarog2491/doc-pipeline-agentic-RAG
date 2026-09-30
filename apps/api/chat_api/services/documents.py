"""Short-lived links to the PDF pages an answer cites."""

import asyncio
import os
import unicodedata

from botocore.config import Config

from chat_api.core.config import get_boto3_session

_UPLOAD_PREFIX = "uploads/"


def _s3_client():
    """Build an S3 client pinned to the API's region.

    ECS provides ``AWS_REGION`` while boto3 reads ``AWS_DEFAULT_REGION``, so the region must be
    passed explicitly: without it boto3 falls back to the global endpoint and signs links for
    ``us-east-1``, which S3 rejects for a bucket in another region.
    """
    region = os.environ.get("AWS_REGION") or os.environ["AWS_DEFAULT_REGION"]
    return get_boto3_session().client(
        "s3",
        region_name=region,
        endpoint_url=f"https://s3.{region}.amazonaws.com",
        config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
    )


def _presign(bucket: str, key: str, ttl: int) -> str:
    return _s3_client().generate_presigned_url(
        "get_object",
        Params={
            "Bucket": bucket,
            "Key": key,
            "ResponseContentType": "application/pdf",
            "ResponseContentDisposition": "inline",
        },
        ExpiresIn=ttl,
    )


async def page_link(bucket: str, key: str, page: int, ttl: int) -> str | None:
    """Presign a link that opens the cited page of an uploaded PDF.

    Args:
        bucket: Documents bucket.
        key: S3 key reported by the Knowledge Base; only ``uploads/`` keys are linked.
        page: One-based page number.
        ttl: Link lifetime in seconds.

    Returns:
        A ``...#page=N`` URL, or ``None`` when the key is not an uploaded PDF.
    """
    if not key.startswith(_UPLOAD_PREFIX) or ".." in key:
        return None
    url = await asyncio.to_thread(_presign, bucket, key, ttl)
    return f"{url}#page={page}"


_MAX_STEM = 100
_ALLOWED_PUNCTUATION = " ._-()"


def upload_key(filename: str) -> str | None:
    """Reduce a user-supplied filename to a safe S3 key under ``uploads/``.

    Directory parts are discarded (both ``/`` and ``\\``), characters other than letters,
    digits and ``space . _ - ( )`` are removed, and the extension is normalised to ``.pdf``.

    Args:
        filename: Name as the browser reports it.

    Returns:
        ``uploads/<name>.pdf``, or ``None`` when nothing usable remains.
    """
    name = unicodedata.normalize("NFC", filename).replace("\\", "/").rsplit("/", 1)[-1]
    if name.lower().endswith(".pdf"):
        name = name[:-4]
    stem = "".join(c for c in name if c.isalnum() or c in _ALLOWED_PUNCTUATION)
    stem = " ".join(stem.split())[:_MAX_STEM].strip(" ._-")
    return f"{_UPLOAD_PREFIX}{stem}.pdf" if stem else None


def _post(
    bucket: str, key: str, ttl: int, max_bytes: int, metadata: dict[str, str]
) -> dict:
    fields = {"Content-Type": "application/pdf", **metadata}
    conditions: list = [
        {"Content-Type": "application/pdf"},
        ["content-length-range", 1, max_bytes],
    ]
    conditions += [{name: value} for name, value in metadata.items()]
    return _s3_client().generate_presigned_post(
        bucket, key, Fields=fields, Conditions=conditions, ExpiresIn=ttl
    )


async def upload_ticket(
    bucket: str, key: str, *, ttl: int, max_bytes: int, metadata: dict[str, str]
) -> dict:
    """Presign a browser upload of one PDF straight to S3.

    The policy pins the exact key, the content type, any ``x-amz-meta-*`` values (how the
    ingestion Lambda learns the chunking choice) and a size range, so S3 itself rejects
    anything else. The PDF never passes through the API.

    Args:
        bucket: Documents bucket.
        key: Object key from ``upload_key``.
        ttl: Ticket lifetime in seconds.
        max_bytes: Largest accepted object.
        metadata: Signed ``x-amz-meta-*`` fields to attach to the object.

    Returns:
        ``{"url": ..., "fields": {...}}`` as produced by boto3.
    """
    return await asyncio.to_thread(_post, bucket, key, ttl, max_bytes, metadata)
