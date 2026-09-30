"""Public wire contract of the REST + SSE API (major version ``v1``).

Requests are validated here before anything reaches the agent. Server events are sent as
Server-Sent Events whose ``event`` field is the ``type`` below and whose ``data`` is the
JSON of the matching model.
"""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

PROTOCOL_VERSION = "v1"
MAX_PROMPT_CHARACTERS = 4_000
KNOWLEDGE_BASE_PATTERN = r"^[0-9A-Za-z]{10}$"
MAX_FILENAME_CHARACTERS = 255
ChunkingStrategy = Literal["semantic", "hierarchical", "fixed", "none"]


class ChatRequest(BaseModel):
    """Body of ``POST /v1/chat/stream``."""

    model_config = ConfigDict(extra="forbid")

    session_id: UUID = Field(alias="sessionId")
    knowledge_base_id: str = Field(
        alias="knowledgeBaseId", pattern=KNOWLEDGE_BASE_PATTERN
    )
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_CHARACTERS)


class _Event(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    request_id: str = Field(alias="requestId")
    sequence: int = Field(ge=0, description="Monotonic per stream, starting at 0.")


class RouteEvent(_Event):
    """The orchestrator's classification of the request."""

    type: Literal["route"] = "route"
    route: Literal["easy", "hard", "guide"]


class ProgressEvent(_Event):
    """A transient status line; not part of the answer."""

    type: Literal["progress"] = "progress"
    text: str


class DeltaEvent(_Event):
    """A piece of the answer text, in order."""

    type: Literal["delta"] = "delta"
    text: str


class Citation(BaseModel):
    """A page of the source PDF an answer cites as ``[[id]]``."""

    id: int
    page: int
    section: str
    url: str | None = Field(default=None, description="Short-lived link to the PDF.")


class CitationsEvent(_Event):
    """The citations resolved for the finished answer."""

    type: Literal["citations"] = "citations"
    citations: list[Citation]


class CompletedEvent(_Event):
    """The stream finished normally."""

    type: Literal["completed"] = "completed"


class ErrorEvent(_Event):
    """The stream failed; ``code`` is stable, ``message`` is generic."""

    type: Literal["error"] = "error"
    code: Literal["agent_unavailable", "internal_error"]
    message: str


ServerEvent = Annotated[
    RouteEvent
    | ProgressEvent
    | DeltaEvent
    | CitationsEvent
    | CompletedEvent
    | ErrorEvent,
    Field(discriminator="type"),
]


class KnowledgeBase(BaseModel):
    """One selectable document."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    status: Literal["PROCESSING", "INDEXING", "READY", "FAILED"]
    pages: int | None = None
    updated_at: str | None = Field(default=None, alias="updatedAt")


class KnowledgeBaseList(BaseModel):
    """Response of ``GET /v1/knowledge-bases``."""

    knowledge_bases: list[KnowledgeBase] = Field(alias="knowledgeBases")

    model_config = ConfigDict(populate_by_name=True)


class UploadRequest(BaseModel):
    """Body of ``POST /v1/documents/upload``: what the browser is about to upload."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    filename: str = Field(min_length=1, max_length=MAX_FILENAME_CHARACTERS)
    size_bytes: int = Field(alias="sizeBytes", ge=1)
    content_type: Literal["application/pdf"] = Field(
        default="application/pdf", alias="contentType"
    )
    chunking: ChunkingStrategy | None = Field(
        default=None,
        description="Bedrock chunking strategy; omit for the semantic default.",
    )
    max_tokens: int | None = Field(default=None, alias="maxTokens", ge=50, le=1500)


class UploadTicket(BaseModel):
    """A presigned S3 POST: send ``fields`` then the file, as multipart form data, to ``url``."""

    model_config = ConfigDict(populate_by_name=True)

    url: str
    fields: dict[str, str]
    key: str
    max_bytes: int = Field(alias="maxBytes")
