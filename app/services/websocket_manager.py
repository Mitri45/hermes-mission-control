"""WebSocket connection manager."""

import asyncio
import json
from datetime import datetime
from typing import Callable

from fastapi import WebSocket

from app.models.schemas import OperationEvent


class WebSocketManager:
    """Manage WebSocket connections for real-time operations stream."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self.message_queue: asyncio.Queue = asyncio.Queue()
        self.event_handlers: list[Callable] = []

    async def connect(self, websocket: WebSocket, subprotocol: str | None = None):
        """Accept and register a new WebSocket connection."""
        await websocket.accept(subprotocol=subprotocol)
        self.active_connections.append(websocket)
        print(f"WebSocket connected. Total connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            print(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        """Send a message to a specific client."""
        try:
            await websocket.send_json(message)
        except Exception:
            self.disconnect(websocket)

    async def broadcast(self, message: dict):
        """Broadcast a message to all connected clients."""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)

        # Clean up disconnected clients
        for conn in disconnected:
            self.disconnect(conn)

    async def broadcast_event(self, event: OperationEvent):
        """Broadcast an operation event."""
        await self.broadcast(event.model_dump())

    def add_event_handler(self, handler: Callable):
        """Add an event handler callback."""
        self.event_handlers.append(handler)

    async def emit_event(self, event_type: str, **kwargs):
        """Emit an event to all handlers and broadcast to WebSockets."""
        event = OperationEvent(type=event_type, **kwargs)

        # Call handlers
        for handler in self.event_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception:
                pass

        # Broadcast to WebSockets
        await self.broadcast_event(event)

    async def stream_logs(self, websocket: WebSocket, session_id: str | None = None):
        """Stream logs to a WebSocket client."""
        await self.connect(websocket)
        try:
            while True:
                # Keep connection alive and handle incoming messages
                data = await websocket.receive_text()
                try:
                    message = json.loads(data)
                    # Handle control messages
                    if message.get("action") == "ping":
                        await websocket.send_json({"type": "pong"})
                except json.JSONDecodeError:
                    pass
        except Exception:
            pass
        finally:
            self.disconnect(websocket)


# Singleton instance
websocket_manager = WebSocketManager()
