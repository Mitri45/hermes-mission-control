#!/usr/bin/env python3
"""Run one Mission Control chat turn using the main Hermes runtime environment."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from gateway.run import _load_gateway_config, _resolve_gateway_model, _resolve_runtime_agent_kwargs
from hermes_cli.tools_config import _get_platform_tools
from hermes_state import SessionDB
from run_agent import AIAgent


def main() -> int:
    payload = json.load(sys.stdin)
    session_id = str(payload["session_id"])
    message = str(payload["message"])

    db = SessionDB()
    history = db.get_messages_as_conversation(session_id)

    runtime_kwargs = _resolve_runtime_agent_kwargs()
    user_config = _load_gateway_config()
    model = _resolve_gateway_model(user_config)
    enabled_toolsets = sorted(_get_platform_tools(user_config, "api_server"))

    agent = AIAgent(
        model=model,
        **runtime_kwargs,
        max_iterations=90,
        quiet_mode=True,
        verbose_logging=False,
        enabled_toolsets=enabled_toolsets,
        session_id=session_id,
        platform="mission_control",
        session_db=db,
        ephemeral_system_prompt=(
            "You are Hermes Mission Control chat. "
            "Respond concisely, operate like a technical control-room assistant, "
            "and assume the operator is looking at live Hermes system state."
        ),
    )

    result = agent.run_conversation(
        user_message=message,
        conversation_history=history,
        task_id=session_id,
    )

    json.dump(
        {
            "response": result.get("final_response") or "",
            "model": result.get("model"),
            "provider": result.get("provider"),
            "base_url": result.get("base_url"),
        },
        sys.stdout,
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
