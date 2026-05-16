"""Mission Control chat routes."""

from functools import lru_cache

from fastapi import APIRouter

from app.models.schemas import ChatRequest, ChatResponse, ChatSessionResponse
from app.services.chat_service import ChatService

router = APIRouter(prefix="/chat", tags=["chat"])


@lru_cache
def get_chat_service() -> ChatService:
    return ChatService()


@router.get("/session/{session_id}", response_model=ChatSessionResponse)
async def get_chat_session(session_id: str):
    """Return the stored Mission Control chat transcript for one session."""
    return await get_chat_service().get_session(session_id)


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Send a message to the real Hermes runtime and continue the same chat session."""
    return await get_chat_service().send_message(
        request.message,
        session_id=request.session_id,
    )
