"""FastAPI server that pushes live dashboard data via WebSocket.

Data flow:
    DatabaseWriter  ->  PG NOTIFY 'dashboard_update'
                    ->  asyncpg LISTEN loop (this module)
                    ->  queries.build_dashboard_payload()
                    ->  ConnectionManager.broadcast()
                    ->  React dashboard (WebSocket)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Allow importing the Database package from the Backend directory.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from Database import ConnectionPool
from Database import config as db_config

from .ws import router as ws_router, manager
from . import queries

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)

COALESCE_WINDOW_S = float(os.environ.get("DASHBOARD_COALESCE_MS", "500")) / 1000

# Module-level state initialised in lifespan.
_pool: ConnectionPool | None = None
_pg_conn: asyncpg.Connection | None = None
_listener_task: asyncio.Task | None = None

# Cached payload to avoid redundant queries on rapid connects.
_cached_payload: str | None = None


async def build_and_cache_payload() -> str:
    """Build the full dashboard JSON and cache it."""
    global _cached_payload
    payload = await asyncio.get_event_loop().run_in_executor(
        None, queries.build_dashboard_payload, _pool,
    )
    _cached_payload = json.dumps(payload, default=str)
    return _cached_payload


async def _listen_loop():
    """Background task: LISTEN on PG channel, coalesce, build + broadcast."""
    global _pg_conn

    dsn = (
        f"postgresql://{db_config.DB_USER}:{db_config.DB_PASSWORD}"
        f"@{db_config.DB_HOST}:{db_config.DB_PORT}/{db_config.DB_NAME}"
    )

    while True:
        try:
            _pg_conn = await asyncpg.connect(dsn)
            logger.info("LISTEN connection established")
            await _pg_conn.add_listener("dashboard_update", _on_notify)

            # Keep alive until the connection drops.
            while True:
                await asyncio.sleep(60)
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("LISTEN connection lost; reconnecting in 3 s")
            await asyncio.sleep(3)
        finally:
            if _pg_conn and not _pg_conn.is_closed():
                try:
                    await _pg_conn.close()
                except Exception:
                    pass


_coalesce_handle: asyncio.TimerHandle | None = None


def _on_notify(conn, pid, channel, payload):
    """Called by asyncpg when a NOTIFY arrives. Starts the coalesce timer."""
    global _coalesce_handle
    loop = asyncio.get_event_loop()

    if _coalesce_handle is not None:
        _coalesce_handle.cancel()

    _coalesce_handle = loop.call_later(COALESCE_WINDOW_S, _schedule_broadcast)


def _schedule_broadcast():
    """Fire the actual build+broadcast as an asyncio task."""
    asyncio.ensure_future(_do_broadcast())


async def _do_broadcast():
    """Build the full payload from DB and push to all connected clients."""
    global _coalesce_handle
    _coalesce_handle = None

    if manager.client_count == 0:
        return

    try:
        payload_json = await build_and_cache_payload()
        await manager.broadcast(payload_json)
        logger.debug("Broadcast to %d client(s)", manager.client_count)
    except Exception:
        logger.exception("Broadcast failed")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _pool, _listener_task

    # 1. Open sync connection pool for queries.
    _pool = ConnectionPool()
    _pool.open()

    # 2. Start async LISTEN loop.
    _listener_task = asyncio.create_task(_listen_loop())

    logger.info("API server started")
    yield

    # Shutdown
    if _listener_task:
        _listener_task.cancel()
        try:
            await _listener_task
        except asyncio.CancelledError:
            pass

    if _pool:
        _pool.close()

    logger.info("API server stopped")


app = FastAPI(title="TransitFlow Dashboard API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ws_router)


@app.get("/api/health")
async def health():
    db_ok = _pool is not None
    try:
        if _pool:
            with _pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
    except Exception:
        db_ok = False

    pg_listen_ok = _pg_conn is not None and not _pg_conn.is_closed() if _pg_conn else False

    mqtt_status = os.environ.get("MQTT_STATUS", "ok" if db_ok else "unknown")
    gtfs_rt_status = os.environ.get("GTFS_RT_STATUS", "ok" if db_ok else "unknown")

    return {
        "status": "ok" if db_ok else "degraded",
        "db": db_ok,
        "connected_clients": manager.client_count,
        "pg_listen": "ok" if pg_listen_ok else "down",
        "coalesce_ms": int(COALESCE_WINDOW_S * 1000),
        "mqtt": mqtt_status,
        "gtfs_rt": gtfs_rt_status,
        "gtfs_rt_last_fetch": os.environ.get("GTFS_RT_LAST_FETCH"),
        "gtfs_rt_entities": int(os.environ.get("GTFS_RT_ENTITIES", "0")) or None,
        "gtfs_rt_errors": int(os.environ.get("GTFS_RT_ERRORS", "0")),
        "gtfs_rt_poll_interval": int(os.environ.get("GTFSR_POLL_INTERVAL", "60")),
        "gtfs_rt_retain": int(os.environ.get("GTFSR_RETAIN_FETCHES", "20")),
        "gtfs_rt_timeout": int(os.environ.get("GTFSR_REQUEST_TIMEOUT", "30")),
    }


# ---------------------------------------------------------------------------
# REST endpoints for on-demand queries
# ---------------------------------------------------------------------------

@app.get("/api/stops/{stop_id}/history")
async def stop_history(stop_id: str, hours: int = 24):
    return await asyncio.get_event_loop().run_in_executor(
        None, queries.query_stop_history, _pool, stop_id, hours)


@app.get("/api/vehicles/history")
async def vehicle_history(hours: int = 24, route_id: str | None = None):
    return await asyncio.get_event_loop().run_in_executor(
        None, queries.query_vehicle_history, _pool, hours, route_id)


@app.get("/api/predictions/latest")
async def predictions_latest():
    return await asyncio.get_event_loop().run_in_executor(
        None, queries.query_predictions_latest, _pool)


@app.get("/api/predictions/{route_id}")
async def predictions_for_route(route_id: str, direction_id: int = 0):
    return await asyncio.get_event_loop().run_in_executor(
        None, queries.query_predictions_for_route, _pool, route_id, direction_id)


@app.get("/api/scheduler/decisions")
async def scheduler_decisions(limit: int = 50):
    return await asyncio.get_event_loop().run_in_executor(
        None, queries.query_scheduler_decisions, _pool, limit)


@app.get("/api/analytics/on-time")
async def analytics_on_time(route_id: str | None = None, hours: int = 24):
    return await asyncio.get_event_loop().run_in_executor(
        None, queries.query_on_time, _pool, route_id, hours)


@app.get("/api/analytics/delays")
async def analytics_delays(route_id: str | None = None, hours: int = 24):
    return await asyncio.get_event_loop().run_in_executor(
        None, queries.query_delay_data, _pool, route_id, hours)


@app.get("/api/analytics/service-alerts")
async def analytics_service_alerts():
    return await asyncio.get_event_loop().run_in_executor(
        None, queries.query_service_alerts, _pool)


@app.get("/api/analytics/gtfs-rt-freshness")
async def gtfs_rt_freshness():
    return await asyncio.get_event_loop().run_in_executor(
        None, queries.query_gtfs_rt_freshness, _pool)


@app.get("/api/devices")
async def devices():
    return await asyncio.get_event_loop().run_in_executor(
        None, queries.query_devices, _pool)


@app.get("/api/devices/{device_id}/logs")
async def device_logs(device_id: str, limit: int = 100):
    return await asyncio.get_event_loop().run_in_executor(
        None, queries.query_device_logs, _pool, device_id, limit)


@app.get("/api/models")
async def models():
    return await asyncio.get_event_loop().run_in_executor(
        None, queries.query_models, _pool)


@app.get("/api/alerts")
async def all_alerts():
    return await asyncio.get_event_loop().run_in_executor(
        None, queries.query_all_alerts, _pool)


@app.get("/api/admin/log")
async def admin_log(limit: int = 100):
    return await asyncio.get_event_loop().run_in_executor(
        None, queries.query_admin_log, _pool, limit)


@app.post("/api/alerts/{alert_id}/resolve")
async def resolve_alert(alert_id: int):
    await asyncio.get_event_loop().run_in_executor(
        None, queries.resolve_alert, _pool, alert_id)
    return {"ok": True}


@app.post("/api/admin/command")
async def admin_command(body: dict):
    """Forward an admin command to an edge device via MQTT.

    Requires the broker_handler to be accessible. For now this is a stub
    that logs the command -- full integration requires sharing the
    BrokerHandler instance with this process.
    """
    logger.info("Admin command received: %s", body)
    device_id = body.get("device_id")
    if not device_id:
        return {"error": "device_id required"}
    return {"ok": True, "device_id": device_id, "command": body}


@app.get("/api/config/prediction")
async def get_prediction_config():
    return {"alighting_fraction": 0.05, "default_capacity": 80}


@app.put("/api/config/prediction")
async def update_prediction_config(body: dict):
    logger.info("Prediction config update: %s", body)
    return {"ok": True, **body}


@app.get("/api/config/evaluator")
async def get_evaluator_config(route_id: str | None = None):
    return {"occupancy_threshold": 0.9, "min_stranded": 5, "min_confidence": 0.3}


@app.put("/api/config/evaluator")
async def update_evaluator_config(body: dict):
    logger.info("Evaluator config update: %s", body)
    return {"ok": True, **body}
