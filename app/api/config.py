"""Configuration routes."""

from fastapi import APIRouter

from app.models.schemas import AgentConfig, AgentConfigUpdate
from app.services.config_service import config_service

router = APIRouter(prefix="/config", tags=["config"])


@router.get("", response_model=AgentConfig)
async def get_config():
    """Get current agent configuration."""
    return config_service.get_config()


@router.post("", response_model=AgentConfig)
async def update_config(update: AgentConfigUpdate):
    """Update agent configuration."""
    return config_service.update_config(update)
