"""``GET /v1/knowledge-bases``: the documents a user can ask about."""

from fastapi import APIRouter, Request

from chat_api.core.config import Settings
from chat_api.core.protocol import KnowledgeBase, KnowledgeBaseList
from chat_api.services import registry

router = APIRouter()


@router.get("/knowledge-bases")
async def list_knowledge_bases(request: Request) -> KnowledgeBaseList:
    """List ingested documents, including ones still processing or failed.

    Args:
        request: Incoming request, used to reach application settings.

    Returns:
        Documents sorted by name; only ``READY`` ones can be chatted with.
    """
    settings: Settings = request.app.state.settings
    items = await registry.list_documents(settings.registry_table)
    return KnowledgeBaseList(
        knowledge_bases=[
            KnowledgeBase(
                id=str(item.get("kb_id") or item["doc_id"]),
                name=str(item.get("name", item["doc_id"])),
                status=item.get("status", "PROCESSING"),
                pages=int(item["pages"]) if item.get("pages") is not None else None,
                updated_at=item.get("updated_at"),
            )
            for item in items
        ]
    )
