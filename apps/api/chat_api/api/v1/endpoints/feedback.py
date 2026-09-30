import logging
from enum import Enum
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from chat_api.services.agentcore import AgentCoreResponseError, submit_feedback

router = APIRouter()
logger = logging.getLogger(__name__)

MAX_COMMENT_CHARACTERS = 2_000


class FeedbackOutcome(str, Enum):
    """Whether the conversation helped the user."""

    helpful = "helpful"
    not_helpful = "not_helpful"


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    session_id: UUID = Field(alias="sessionId")
    outcome: FeedbackOutcome
    comment: str | None = Field(default=None, max_length=MAX_COMMENT_CHARACTERS)

    @model_validator(mode="after")
    def _require_comment_when_not_helpful(self) -> "FeedbackRequest":
        if self.outcome is FeedbackOutcome.not_helpful and not (
            self.comment and self.comment.strip()
        ):
            raise ValueError("comment is required when outcome is not_helpful")
        return self


class FeedbackResponse(BaseModel):
    status: str


@router.post("/feedback")
async def create_feedback(request: FeedbackRequest) -> FeedbackResponse:
    comment = request.comment.strip() if request.comment else None
    try:
        await submit_feedback(
            str(request.session_id),
            outcome=request.outcome.value,
            comment=comment or None,
        )
    except AgentCoreResponseError:
        logger.exception(
            "Feedback submission failed: session_id=%s", request.session_id
        )
        raise HTTPException(status_code=502, detail="Could not record feedback")

    return FeedbackResponse(status="ok")
