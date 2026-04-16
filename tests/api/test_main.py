# *** TEST FILE - SAFE TO DELETE ***
"""Unit tests for FastAPI routes in src/Backend/API/main.py.

The lifespan context is replaced with a no-op so no real DB pool is opened.
Query functions are monkeypatched to return canned data.
"""

from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


pytestmark = pytest.mark.unit


@asynccontextmanager
async def _noop_lifespan(app):
    yield


@pytest.fixture
def client(monkeypatch):
    """Yield a TestClient with a dummy pool injected and DB lifespan stubbed."""
    from API import main as api_main

    # Replace the lifespan so startup/shutdown don't touch a real DB.
    monkeypatch.setattr(api_main.app.router, "lifespan_context", _noop_lifespan)

    dummy_pool = MagicMock()
    monkeypatch.setattr(api_main, "_pool", dummy_pool)
    monkeypatch.setattr(api_main, "_pg_conn", None)

    with TestClient(api_main.app) as c:
        yield c, dummy_pool


# ---------------------------------------------------------------------------
# /api/health --------------------------------------------------------------
# ---------------------------------------------------------------------------

class TestHealth:

    def test_health_ok_when_db_reachable(self, client):
        c, pool = client
        # pool.connection() is a context manager returning a connection whose
        # cursor().execute() works -- by default the MagicMock supports this.
        resp = c.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["db"] is True
        assert body["connected_clients"] == 0

    def test_health_degraded_when_db_fails(self, client):
        c, pool = client
        pool.connection.side_effect = RuntimeError("DB down")
        resp = c.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "degraded"
        assert body["db"] is False


# ---------------------------------------------------------------------------
# /api/stops/{id}/history --------------------------------------------------
# ---------------------------------------------------------------------------

class TestStopHistory:

    def test_forwards_to_query_function(self, client):
        from API import main as api_main

        c, _ = client
        with patch.object(
            api_main.queries, "query_stop_history",
            return_value=[{"time": "2026-04-16 10:00:00", "count": 5, "zone": None}],
        ) as mock_q:
            resp = c.get("/api/stops/s1/history?hours=12")

        assert resp.status_code == 200
        assert resp.json() == [
            {"time": "2026-04-16 10:00:00", "count": 5, "zone": None},
        ]
        mock_q.assert_called_once()
        call_args = mock_q.call_args.args
        assert call_args[1] == "s1"
        assert call_args[2] == 12


# ---------------------------------------------------------------------------
# CORS ----------------------------------------------------------------------
# ---------------------------------------------------------------------------

class TestCors:

    def test_cors_allows_cross_origin(self, client):
        c, _ = client
        resp = c.get(
            "/api/health",
            headers={"Origin": "http://example.com"},
        )
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "*"


# ---------------------------------------------------------------------------
# /api/admin/command + predictions config routes ---------------------------
# ---------------------------------------------------------------------------

class TestAdminAndConfig:

    def test_admin_command_requires_device_id(self, client):
        c, _ = client
        resp = c.post("/api/admin/command", json={"action": "restart"})
        assert resp.status_code == 200
        assert resp.json() == {"error": "device_id required"}

    def test_admin_command_echoes_body(self, client):
        c, _ = client
        resp = c.post(
            "/api/admin/command",
            json={"device_id": "dev-1", "action": "restart"},
        )
        body = resp.json()
        assert body["ok"] is True
        assert body["device_id"] == "dev-1"

    def test_get_prediction_config_defaults(self, client):
        c, _ = client
        resp = c.get("/api/config/prediction")
        assert resp.status_code == 200
        body = resp.json()
        assert "alighting_fraction" in body
        assert "default_capacity" in body
