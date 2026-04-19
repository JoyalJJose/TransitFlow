"""External API service.

Public, read-only HTTP API that exposes traffic-light states for a stop:

- ``GET /v1/stops/{stop_id}`` -- one state for the stop (people waiting) and
  one state per arriving vehicle (predicted occupancy).
- ``GET /healthz`` -- simple liveness probe.

Designed to be embedded by user-facing apps (TFI Live, Google Maps, etc.) that
want low-granularity guidance without reimplementing thresholds.

Run with::

    uvicorn main:app --app-dir "src/External API" --host 0.0.0.0 --port 8100
"""

from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# Reuse the shared Database package without making the External API a
# subpackage of src/Backend. This mirrors the pattern used by src/Backend/API.
_BACKEND_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "Backend")
)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from Database import ConnectionPool  # noqa: E402

import queries  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("external_api")

_pool: ConnectionPool | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _pool
    _pool = ConnectionPool()
    _pool.open()
    logger.info("External API started")
    try:
        yield
    finally:
        if _pool:
            _pool.close()
        logger.info("External API stopped")


app = FastAPI(
    title="TransitFlow External API",
    description=(
        "Congestion of public transport stops and vehicles at a particular "
        "stop. One state for the stop itself (people waiting) and one state "
        "per arriving vehicle (predicted occupancy)."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/v1/stops/{stop_id}")
async def get_stop(stop_id: str):
    import asyncio

    payload = await asyncio.get_event_loop().run_in_executor(
        None, queries.query_stop_traffic_lights, _pool, stop_id,
    )
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Unknown stop_id: {stop_id}")
    return payload
