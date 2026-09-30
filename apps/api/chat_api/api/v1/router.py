from fastapi import APIRouter

from chat_api.api.v1.endpoints import chat, documents, feedback, knowledge_bases

router = APIRouter(prefix="/v1")
router.include_router(chat.router)
router.include_router(knowledge_bases.router)
router.include_router(documents.router)
router.include_router(feedback.router)
