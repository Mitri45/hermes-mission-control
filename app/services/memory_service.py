"""Memory service for agent memory management."""

import json
from datetime import datetime
from pathlib import Path

import yaml

from app.core.config import get_settings
from app.models.schemas import MemoryEntry, MemoryResponse, PersonalityInfo


class MemoryService:
    """Service for managing agent memory."""

    PERSONALITIES = ["concise", "technical", "creative", "pirate", "kawaii", "noir"]

    def __init__(self):
        self.settings = get_settings()
        self.memory_dir = self.settings.memory_dir

    def _read_yaml(self, path: Path) -> dict:
        """Read YAML file safely."""
        if not path.exists():
            return {}
        try:
            with open(path) as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}

    def _read_json(self, path: Path) -> dict:
        """Read JSON file safely."""
        if not path.exists():
            return {}
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            return {}

    def get_memory(self) -> MemoryResponse:
        """Get memory entries and personality."""
        entries = []

        # Read from memory directory
        if self.memory_dir.exists():
            for mem_file in self.memory_dir.glob("*.yaml"):
                try:
                    data = self._read_yaml(mem_file)
                    for key, value in data.items():
                        if isinstance(value, dict):
                            updated_at = value.get("updated_at")
                            value_str = json.dumps(value.get("value", value))
                        else:
                            updated_at = None
                            value_str = str(value)

                        entries.append(
                            MemoryEntry(
                                key=key,
                                value=value_str[:500],  # Limit length
                                updated_at=datetime.fromisoformat(updated_at)
                                if updated_at
                                else datetime.fromtimestamp(mem_file.stat().st_mtime),
                            )
                        )
                except Exception:
                    continue

        # Also read from memory.json if exists
        memory_json = self.settings.hermes_home / "memory.json"
        if memory_json.exists():
            try:
                data = self._read_json(memory_json)
                for key, value in data.items():
                    if key not in [e.key for e in entries]:
                        entries.append(
                            MemoryEntry(
                                key=key,
                                value=json.dumps(value)[:500],
                                updated_at=datetime.utcnow(),
                            )
                        )
            except Exception:
                pass

        # Sort by updated_at
        entries.sort(key=lambda x: x.updated_at, reverse=True)

        # Get current personality from config
        personality = self.get_current_personality()

        return MemoryResponse(
            entries=entries[:50],  # Limit to 50 entries
            personality=PersonalityInfo(
                current=personality,
                available=self.PERSONALITIES,
            ),
        )

    def get_current_personality(self) -> str:
        """Get current personality from config."""
        config_file = self.settings.config_file
        if config_file.exists():
            try:
                with open(config_file) as f:
                    config = yaml.safe_load(f)
                    return config.get("personality", "creative")
            except Exception:
                pass

        # Check environment variable
        import os

        return os.environ.get("HERMES_PERSONALITY", "creative")


# Singleton instance
memory_service = MemoryService()
