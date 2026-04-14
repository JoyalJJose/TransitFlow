"""WebSocket endpoint and connection manager for dashboard push."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()
logger = logging.getLogger(__name__)


class ConnectionManager:
    """Track connected dashboard WebSocket clients and broadcast to all."""

    def __init__(self):
        self._clients: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._clients.append(ws)
        logger.info("Dashboard client connected (%d total)", len(self._clients))

    def disconnect(self, ws: WebSocket):
        self._clients.remove(ws)
        logger.info("Dashboard client disconnected (%d remaining)", len(self._clients))

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def broadcast(self, payload_json: str):
        """Send pre-serialised JSON to every connected client."""
        stale: list[WebSocket] = []
        for ws in self._clients:
            try:
                await ws.send_text(payload_json)
            except Exception:
                stale.append(ws)
        for ws in stale:
            try:
                self._clients.remove(ws)
            except ValueError:
                pass
        if stale:
            logger.info("Removed %d stale client(s)", len(stale))


manager = ConnectionManager()


@router.websocket("/ws/dashboard")
async def dashboard_ws(ws: WebSocket):
    """Persistent WebSocket that pushes full dashboard payloads."""
    await manager.connect(ws)

    # Send an immediate full payload so the UI doesn't start empty.
    from .main import build_and_cache_payload  # deferred to avoid circular import

    try:
        payload_json = await build_and_cache_payload()
        await ws.send_text(payload_json)
    except Exception:
        logger.exception("Failed to send initial payload")

    try:
        while True:
            # Keep the connection alive by reading (handles pings/close).
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception:
        manager.disconnect(ws)
