"""Lightweight backend runtime supervisor.

Launches and monitors all continuous backend services (excluding the
simulator, which is script-managed):

  - GTFS-RT fetcher  (subprocess, conditional on GTFSR_API_KEY)
  - MQTT BrokerHandler  (subprocess, service mode)
  - FastAPI / uvicorn  (subprocess)
  - Prediction loop  (embedded thread, reacts to DB NOTIFY)

If a subprocess exits unexpectedly it is restarted with capped backoff.
If the prediction thread crashes it is restarted in-process.

Usage::

    PYTHONPATH=src python -m Backend.runtime_supervisor
"""

from __future__ import annotations

import logging
import os
import select
import signal
import subprocess
import sys
import threading
import time

import psycopg2

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
LOGDIR = os.path.join(ROOT, "logs")

# Add src/Backend/ to path so Database / PredictionEngine are importable.
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from Database import ConnectionPool, DatabaseWriter  # noqa: E402
from Database import config as db_config  # noqa: E402
from PredictionEngine import (  # noqa: E402
    PredictionConfig,
    PredictionEngine,
    SnapshotBuilder,
    ThresholdEvaluator,
)

_shutdown = threading.Event()

# -- prediction config (env-configurable) ----------------------------------

PRED_DEBOUNCE_S = float(os.environ.get("PREDICTION_DEBOUNCE_S", "5.0"))
PRED_CYCLE_INTERVAL_S = float(os.environ.get("PREDICTION_CYCLE_INTERVAL_S", "120.0"))
PRED_ALIGHTING_FRACTION = float(os.environ.get("PREDICTION_ALIGHTING_FRACTION", "0.05"))
PRED_DEFAULT_CAPACITY = int(os.environ.get("PREDICTION_DEFAULT_CAPACITY", "80"))
PRED_OCCUPANCY_THRESHOLD = float(os.environ.get("PREDICTION_OCCUPANCY_THRESHOLD", "0.9"))
PRED_MIN_STRANDED = int(os.environ.get("PREDICTION_MIN_STRANDED", "5"))
PRED_MIN_CONFIDENCE = float(os.environ.get("PREDICTION_MIN_CONFIDENCE", "0.3"))
API_HOST = os.environ.get("API_HOST", "127.0.0.1")
API_PORT = os.environ.get("API_PORT", "8000")

_TRIGGER_PAYLOADS = frozenset({"crowd_count", "gtfs_trip_updates"})


# -- subprocess management -------------------------------------------------

def _open_log(name: str):
    """Open (append) a log file under LOGDIR."""
    os.makedirs(LOGDIR, exist_ok=True)
    return open(os.path.join(LOGDIR, name), "a")


class _Worker:
    """Thin wrapper around a managed subprocess."""

    def __init__(
        self,
        name: str,
        cmd: list[str],
        log_file: str,
        env_extra: dict[str, str] | None = None,
    ):
        self.name = name
        self.cmd = cmd
        self.log_file = log_file
        self.env_extra = env_extra or {}
        self.proc: subprocess.Popen | None = None
        self._backoff = 2.0
        self._max_backoff = 30.0
        self._log_fh = None

    def start(self):
        env = {**os.environ, **self.env_extra}
        self._log_fh = _open_log(self.log_file)
        self.proc = subprocess.Popen(
            self.cmd,
            stdout=self._log_fh,
            stderr=subprocess.STDOUT,
            cwd=ROOT,
            env=env,
        )
        logger.info("[%s] started (PID %d)", self.name, self.proc.pid)
        self._backoff = 2.0

    def is_alive(self) -> bool:
        if self.proc is None:
            return False
        return self.proc.poll() is None

    def restart_if_dead(self):
        """Restart the subprocess if it exited, with exponential backoff."""
        if self.is_alive():
            return
        if self.proc is not None:
            logger.warning(
                "[%s] exited (code %s), restarting in %.0fs",
                self.name, self.proc.returncode, self._backoff,
            )
        if self._log_fh:
            self._log_fh.close()
        if not _shutdown.wait(self._backoff):
            self.start()
            self._backoff = min(self._backoff * 2, self._max_backoff)

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            logger.info("[%s] stopped", self.name)
        if self._log_fh:
            self._log_fh.close()


# -- embedded prediction loop ---------------------------------------------

def _prediction_thread():
    """Reactive prediction loop: LISTEN for DB changes, debounce, predict."""
    while not _shutdown.is_set():
        pool = None
        listen_conn = None
        try:
            pool = ConnectionPool()
            pool.open()
            writer = DatabaseWriter(pool)
            builder = SnapshotBuilder(pool, default_capacity=PRED_DEFAULT_CAPACITY)
            engine = PredictionEngine(
                PredictionConfig(alighting_fraction=PRED_ALIGHTING_FRACTION),
            )
            evaluator = ThresholdEvaluator(
                occupancy_threshold=PRED_OCCUPANCY_THRESHOLD,
                min_stranded=PRED_MIN_STRANDED,
                min_confidence=PRED_MIN_CONFIDENCE,
            )

            # Open dedicated LISTEN connection
            listen_conn = psycopg2.connect(
                host=db_config.DB_HOST, port=db_config.DB_PORT,
                dbname=db_config.DB_NAME, user=db_config.DB_USER,
                password=db_config.DB_PASSWORD,
            )
            listen_conn.set_isolation_level(
                psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT,
            )
            with listen_conn.cursor() as cur:
                cur.execute("LISTEN dashboard_update;")

            # Load route-direction pairs
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT DISTINCT route_id, direction_id
                        FROM route_stops ORDER BY route_id, direction_id
                    """)
                    route_dirs = [(r[0], r[1]) for r in cur.fetchall()]

            logger.info(
                "Prediction loop started — %d route-directions, "
                "debounce=%.1fs, interval=%.0fs",
                len(route_dirs), PRED_DEBOUNCE_S, PRED_CYCLE_INTERVAL_S,
            )

            def _run_cycle():
                t0 = time.monotonic()
                written, skipped, alerts = 0, 0, 0
                for rid, did in route_dirs:
                    try:
                        snap = builder.build(rid, did)
                        if snap is None:
                            skipped += 1
                            continue
                        result = engine.predict_route(snap)
                        if not result.vehicle_predictions:
                            skipped += 1
                            continue
                        writer.write_predictions(result)
                        written += 1
                        alert = evaluator.evaluate(result)
                        if alert is not None:
                            writer.write_scheduler_decision(alert)
                            alerts += 1
                    except Exception:
                        logger.exception("Prediction failed for route=%s dir=%d", rid, did)
                logger.info(
                    "Cycle complete: %d predicted, %d skipped, %d alerts in %.2fs",
                    written, skipped, alerts, time.monotonic() - t0,
                )

            # Initial cycle
            _run_cycle()

            last_cycle = time.monotonic()
            pending = False
            debounce_deadline: float | None = None

            while not _shutdown.is_set():
                now = time.monotonic()
                candidates = [1.0]
                if debounce_deadline is not None:
                    candidates.append(max(0.0, debounce_deadline - now))
                candidates.append(max(0.0, last_cycle + PRED_CYCLE_INTERVAL_S - now))
                timeout = min(candidates)

                # Poll for NOTIFY
                try:
                    ready, _, _ = select.select([listen_conn], [], [], timeout)
                except (OSError, ValueError):
                    ready = []

                if ready:
                    listen_conn.poll()
                    while listen_conn.notifies:
                        n = listen_conn.notifies.pop(0)
                        if n.payload in _TRIGGER_PAYLOADS:
                            pending = True
                            debounce_deadline = time.monotonic() + PRED_DEBOUNCE_S

                now = time.monotonic()
                if pending and debounce_deadline is not None and now >= debounce_deadline:
                    _run_cycle()
                    last_cycle = time.monotonic()
                    pending = False
                    debounce_deadline = None
                    continue
                if now - last_cycle >= PRED_CYCLE_INTERVAL_S:
                    _run_cycle()
                    last_cycle = time.monotonic()
                    pending = False
                    debounce_deadline = None

        except Exception:
            logger.exception("[predictions] crashed — restarting in 5s")
            if not _shutdown.wait(5):
                continue
        finally:
            if listen_conn and not listen_conn.closed:
                listen_conn.close()
            if pool:
                try:
                    pool.close()
                except Exception:
                    pass
        break  # clean exit on shutdown

    logger.info("Prediction loop shut down")


# -- main ------------------------------------------------------------------

def main():
    python = sys.executable

    workers: list[_Worker] = [
        _Worker(
            "mqtt",
            [python, "-m", "Backend.MQTTBroker.main"],
            "broker_handler.log",
            env_extra={"MQTT_SERVICE_MODE": "1", "PYTHONPATH": "src"},
        ),
        _Worker(
            "api",
            [python, "-m", "uvicorn", "Backend.API.main:app",
             "--host", API_HOST, "--port", API_PORT],
            "api_server.log",
            env_extra={
                "PYTHONPATH": "src",
                "GTFS_RT_STATUS": "enabled" if os.environ.get("GTFSR_API_KEY", "") else "disabled",
            },
        ),
    ]

    if os.environ.get("GTFSR_API_KEY", ""):
        workers.append(_Worker(
            "gtfs_rt",
            [python, "-m", "Backend.GTFS_RT"],
            "gtfsrt_fetcher.log",
            env_extra={"PYTHONPATH": "src"},
        ))
        logger.info("GTFS-RT fetcher enabled (API key present)")
    else:
        logger.info("GTFS-RT fetcher disabled (no GTFSR_API_KEY)")

    def _handle_signal(sig, _frame):
        logger.info("Received signal %s — shutting down", sig)
        _shutdown.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    for w in workers:
        w.start()

    pred_thread = threading.Thread(
        target=_prediction_thread, name="predictions", daemon=True,
    )
    pred_thread.start()

    logger.info(
        "Runtime supervisor ready — %d subprocess(es) + prediction thread",
        len(workers),
    )

    while not _shutdown.is_set():
        _shutdown.wait(2)
        for w in workers:
            if not _shutdown.is_set():
                w.restart_if_dead()
        if not pred_thread.is_alive() and not _shutdown.is_set():
            logger.warning("[predictions] thread died — restarting")
            pred_thread = threading.Thread(
                target=_prediction_thread, name="predictions", daemon=True,
            )
            pred_thread.start()

    logger.info("Shutting down all workers…")
    for w in workers:
        w.stop()
    pred_thread.join(timeout=10)
    logger.info("Runtime supervisor exited")


if __name__ == "__main__":
    main()
