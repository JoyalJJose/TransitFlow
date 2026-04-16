# *** TEST FILE - SAFE TO DELETE ***
"""Unit tests for the WebSocket ConnectionManager."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from API.ws import ConnectionManager


pytestmark = pytest.mark.unit


class TestConnectionManager:

    def _make_ws(self):
        """Return an AsyncMock with accept / send_text / close methods."""
        ws = AsyncMock()
        ws.accept = AsyncMock()
        ws.send_text = AsyncMock()
        return ws

    def test_connect_accepts_and_appends(self):
        mgr = ConnectionManager()
        ws = self._make_ws()
        asyncio.run(mgr.connect(ws))

        ws.accept.assert_awaited_once()
        assert mgr.client_count == 1

    def test_disconnect_removes(self):
        mgr = ConnectionManager()
        ws = self._make_ws()
        asyncio.run(mgr.connect(ws))
        mgr.disconnect(ws)
        assert mgr.client_count == 0

    def test_broadcast_sends_to_all_clients(self):
        mgr = ConnectionManager()
        ws1, ws2, ws3 = self._make_ws(), self._make_ws(), self._make_ws()

        async def go():
            await mgr.connect(ws1)
            await mgr.connect(ws2)
            await mgr.connect(ws3)
            await mgr.broadcast('{"ok":true}')

        asyncio.run(go())
        ws1.send_text.assert_awaited_with('{"ok":true}')
        ws2.send_text.assert_awaited_with('{"ok":true}')
        ws3.send_text.assert_awaited_with('{"ok":true}')
        assert mgr.client_count == 3

    def test_broadcast_drops_stale_clients(self):
        mgr = ConnectionManager()
        good, bad = self._make_ws(), self._make_ws()
        bad.send_text.side_effect = RuntimeError("socket closed")

        async def go():
            await mgr.connect(good)
            await mgr.connect(bad)
            await mgr.broadcast("x")

        asyncio.run(go())
        assert mgr.client_count == 1
        # Second broadcast: should only hit the remaining good client.
        good.send_text.reset_mock()
        asyncio.run(mgr.broadcast("y"))
        good.send_text.assert_awaited_with("y")
