"""WebSocket routes for real-time operations."""

import base64
import os

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.core.config import get_settings
from app.services.websocket_manager import websocket_manager

router = APIRouter(prefix="/operations", tags=["websocket"])
AUTH_SUBPROTOCOL_PREFIX = "hermes-auth."
TRANSPORT_SUBPROTOCOL = "hermes-ops.v1"


def _parse_subprotocols(websocket: WebSocket) -> list[str]:
    header = websocket.headers.get("sec-websocket-protocol", "")
    if not header:
        return []
    return [part.strip() for part in header.split(",") if part.strip()]


def _decode_subprotocol_token(encoded: str) -> str:
    # The frontend uses base64url without padding; restore padding before decode.
    padded = encoded + "=" * (-len(encoded) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        return raw.decode("utf-8").strip()
    except Exception:
        return ""


def _extract_token_from_subprotocol(websocket: WebSocket) -> tuple[str, str | None]:
    for protocol in _parse_subprotocols(websocket):
        if not protocol.startswith(AUTH_SUBPROTOCOL_PREFIX):
            continue
        encoded = protocol[len(AUTH_SUBPROTOCOL_PREFIX):]
        token = _decode_subprotocol_token(encoded)
        if token:
            return token, protocol
    return "", None


def _extract_bearer_token(websocket: WebSocket) -> tuple[str, str | None]:
    """Extract bearer token from Authorization header, subprotocol, or query params."""
    auth_header = websocket.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header.split(" ", 1)[1].strip(), None

    subprotocol_token, subprotocol = _extract_token_from_subprotocol(websocket)
    if subprotocol_token:
        return subprotocol_token, subprotocol

    query_token = websocket.query_params.get("token") or websocket.query_params.get("access_token")
    return (query_token or "").strip(), None


def _websocket_cloudflare_authorized(websocket: WebSocket, settings) -> bool:
    if settings.dashboard_auth_mode != "cloudflare":
        return False

    if settings.dashboard_shared_secret:
        shared = websocket.headers.get("x-hermes-origin-secret", "").strip()
        if shared != settings.dashboard_shared_secret:
            return False
    else:
        client_host = (websocket.client.host if websocket.client else "") or ""
        if client_host not in {"127.0.0.1", "::1", "localhost"}:
            configured_host = (
                os.environ.get("MC_HOST")
                or os.environ.get("HOST")
                or settings.host
                or ""
            ).strip().lower()
            if configured_host not in {"127.0.0.1", "::1", "localhost"}:
                return False

    has_access_identity = bool(
        websocket.headers.get("cf-access-authenticated-user-email", "").strip()
        or websocket.headers.get("cf-access-jwt-assertion", "").strip()
    )
    has_service_token = bool(
        websocket.headers.get("cf-access-client-id", "").strip()
        and websocket.headers.get("cf-access-client-secret", "").strip()
    )
    return has_access_identity or has_service_token


def _select_accept_subprotocol(websocket: WebSocket, auth_subprotocol: str | None) -> str | None:
    offered = _parse_subprotocols(websocket)
    if TRANSPORT_SUBPROTOCOL in offered:
        return TRANSPORT_SUBPROTOCOL
    if auth_subprotocol and auth_subprotocol in offered:
        return auth_subprotocol
    return None


@router.websocket("/stream")
async def operations_stream(websocket: WebSocket):
    """WebSocket endpoint for real-time operations stream.

    Streams agent activity including:
    - Tool calls
    - Thoughts
    - File operations
    - Completion events
    """
    settings = get_settings()
    token, auth_subprotocol = _extract_bearer_token(websocket)
    if (not token or token != settings.bearer_token) and not _websocket_cloudflare_authorized(websocket, settings):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Unauthorized")
        return

    await websocket_manager.connect(
        websocket,
        subprotocol=_select_accept_subprotocol(websocket, auth_subprotocol),
    )
    try:
        while True:
            # Receive and handle messages from client
            data = await websocket.receive_text()
            # Echo back or handle control messages
            await websocket_manager.broadcast({"type": "ack", "data": data})
    except WebSocketDisconnect:
        websocket_manager.disconnect(websocket)
    except Exception:
        websocket_manager.disconnect(websocket)
