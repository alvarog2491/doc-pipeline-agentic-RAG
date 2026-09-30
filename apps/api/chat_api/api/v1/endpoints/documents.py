"""``POST /v1/documents/upload``: let the browser upload a PDF straight to the ingestion pipeline."""

from fastapi import APIRouter, HTTPException, Request

from chat_api.core.config import Settings
from chat_api.core.protocol import UploadRequest, UploadTicket
from chat_api.services import documents

router = APIRouter()


@router.post("/documents/upload")
async def create_upload(body: UploadRequest, request: Request) -> UploadTicket:
    """Issue a presigned S3 POST for one PDF.

    Uploading to the returned URL triggers the ingestion pipeline (Textract, Bedrock chunking
    and embedding, a new Knowledge Base); the document then appears in ``GET
    /v1/knowledge-bases`` as ``PROCESSING`` and later ``READY``. Uploading a file with the same
    name replaces and re-ingests that document.

    Args:
        body: The file's name and size, plus an optional chunking choice.
        request: Incoming request, used to reach application settings.

    Returns:
        A ticket the browser posts the file to directly.

    Raises:
        HTTPException: 422 when the name is unusable or the file exceeds the size limit.
    """
    settings: Settings = request.app.state.settings
    key = documents.upload_key(body.filename)
    if key is None:
        raise HTTPException(
            status_code=422, detail="The file name has no usable characters"
        )
    if body.size_bytes > settings.max_upload_bytes:
        raise HTTPException(
            status_code=422,
            detail=f"The file exceeds the {settings.max_upload_bytes // (1024 * 1024)} MB limit",
        )

    metadata: dict[str, str] = {}
    if body.chunking:
        metadata["x-amz-meta-chunking"] = body.chunking
    if body.max_tokens:
        metadata["x-amz-meta-max-tokens"] = str(body.max_tokens)
    ticket = await documents.upload_ticket(
        settings.documents_bucket,
        key,
        ttl=settings.upload_ttl_seconds,
        max_bytes=settings.max_upload_bytes,
        metadata=metadata,
    )
    return UploadTicket(
        url=ticket["url"],
        fields=ticket["fields"],
        key=key,
        max_bytes=settings.max_upload_bytes,
    )
