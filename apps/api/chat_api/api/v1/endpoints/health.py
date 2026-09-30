from fastapi import APIRouter
from pydantic import BaseModel

from chat_api.core.protocol import PROTOCOL_VERSION

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    version: str


@router.get("/health")
def health() -> HealthResponse:
    """Report liveness for the load balancer."""
    return HealthResponse(status="ok", version=PROTOCOL_VERSION)
