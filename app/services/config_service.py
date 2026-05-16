"""Configuration service."""

import os
from pathlib import Path

import yaml

from app.core.config import get_settings
from app.models.schemas import AgentConfig, AgentConfigUpdate


class ConfigService:
    """Service for managing agent configuration."""

    DEFAULT_CONFIG = {
        "model": "MiniMax-M2.7",
        "provider": "minimax",
        "base_url": "https://api.minimax.io/anthropic",
        "personality": "creative",
        "max_turns": 60,
        "linear_backend": "claude-code",
    }

    def __init__(self):
        self.settings = get_settings()

    def _read_config(self) -> dict:
        """Read config from file or return defaults."""
        config_file = self.settings.config_file
        if config_file.exists():
            try:
                with open(config_file) as f:
                    return yaml.safe_load(f) or {}
            except Exception:
                pass

        # Try to read from environment
        return {
            "model": os.environ.get("HERMES_MODEL", self.DEFAULT_CONFIG["model"]),
            "provider": os.environ.get("HERMES_PROVIDER", self.DEFAULT_CONFIG["provider"]),
            "base_url": os.environ.get("HERMES_BASE_URL", self.DEFAULT_CONFIG["base_url"]),
            "personality": os.environ.get("HERMES_PERSONALITY", self.DEFAULT_CONFIG["personality"]),
            "max_turns": int(os.environ.get("HERMES_MAX_TURNS", self.DEFAULT_CONFIG["max_turns"])),
            "linear_backend": os.environ.get(
                "HERMES_LINEAR_DEFAULT_BACKEND", self.DEFAULT_CONFIG["linear_backend"]
            ),
        }

    @staticmethod
    def _normalize_model_settings(config: dict) -> tuple[str, str, str]:
        """Return (model, provider, base_url) across flat and nested config shapes."""
        raw_model = config.get("model")
        if isinstance(raw_model, dict):
            model = str(raw_model.get("default") or raw_model.get("model") or "")
            provider = str(raw_model.get("provider") or config.get("provider") or "")
            base_url = str(raw_model.get("base_url") or config.get("base_url") or "")
            return model, provider, base_url

        return (
            str(config.get("model") or ""),
            str(config.get("provider") or ""),
            str(config.get("base_url") or ""),
        )

    def get_config(self) -> AgentConfig:
        """Get current configuration."""
        config = self._read_config()
        model, provider, base_url = self._normalize_model_settings(config)
        return AgentConfig(
            model=model or self.DEFAULT_CONFIG["model"],
            provider=provider or self.DEFAULT_CONFIG["provider"],
            base_url=base_url or self.DEFAULT_CONFIG["base_url"],
            personality=config.get("personality", self.DEFAULT_CONFIG["personality"]),
            max_turns=config.get("max_turns", self.DEFAULT_CONFIG["max_turns"]),
            linear_backend=config.get("linear_backend", self.DEFAULT_CONFIG["linear_backend"]),
        )

    def update_config(self, update: AgentConfigUpdate) -> AgentConfig:
        """Update configuration."""
        current = self._read_config()
        model_shape = current.get("model")
        has_nested_model = isinstance(model_shape, dict)
        if has_nested_model:
            model_settings = dict(model_shape)
        else:
            model_settings = {}

        if update.model is not None:
            if has_nested_model:
                model_settings["default"] = update.model
            else:
                current["model"] = update.model
        if update.provider is not None:
            if has_nested_model:
                model_settings["provider"] = update.provider
            else:
                current["provider"] = update.provider
        if update.base_url is not None:
            if has_nested_model:
                model_settings["base_url"] = update.base_url
            else:
                current["base_url"] = update.base_url
        if update.personality is not None:
            current["personality"] = update.personality
        if update.max_turns is not None:
            current["max_turns"] = update.max_turns
        if update.linear_backend is not None:
            current["linear_backend"] = update.linear_backend
        if has_nested_model:
            current["model"] = model_settings

        # Save to file
        try:
            self.settings.config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.settings.config_file, "w") as f:
                yaml.dump(current, f, default_flow_style=False)
        except IOError:
            pass

        return self.get_config()


# Singleton instance
config_service = ConfigService()
