"""Token consumption routes."""

from fastapi import APIRouter

from app.models.schemas import TokensResponse
from app.services.token_service import token_service

router = APIRouter(prefix="/tokens", tags=["tokens"])


@router.get("", response_model=TokensResponse)
async def get_token_usage():
    """Get token consumption statistics."""
    return token_service.get_token_usage()
