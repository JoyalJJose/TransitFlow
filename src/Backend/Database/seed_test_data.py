"""Seed the TransitFlow database with realistic test data for dashboard testing.

Populates tables that are normally empty during a demo run:
  - vehicles
  - vehicle_telemetry  (24h of 15-min interval data)
  - predictions        (latest prediction per route/direction)
  - scheduler_decisions
  - gtfs_rt_service_alerts
  - model_versions
  - admin_activity_log
  - system_alerts
  - stop_logs

Idempotent: safe to run multiple times. Uses ON CONFLICT where possible
and deletes stale seeded rows for append-only tables.

Usage:
    source .venv/Scripts/activate
    PYTHONPATH=src python -m Backend.Database.seed_test_data

    # Re-anchor the 24h vehicle_telemetry window to "now" without
    # re-seeding anything else (used by scripts/start_demo.sh so the
    # Fleet Utilisation / Fullness / Occupancy charts always have data).
    PYTHONPATH=src python -m Backend.Database.seed_test_data --refresh-telemetry
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import logging
import math
import random
import sys

import psycopg2
from psycopg2.extras import execute_values

from . import config as db_config

logger = logging.getLogger(__name__)

SEED_TAG = "seed_test_data"

# Reuse the simulator's demand curve for realistic occupancy patterns
_DEMAND_CURVE: list[tuple[float, float]] = [
    (0.0, 0.10), (5.0, 0.10), (6.0, 0.20), (6.5, 0.20),
    (7.0, 0.60), (7.5, 1.00), (9.5, 1.00), (10.0, 0.50),
    (12.0, 0.50), (12.5, 0.60), (14.0, 0.60), (14.5, 0.50),
    (16.0, 0.50), (16.5, 1.00), (18.5, 1.00), (19.0, 0.40),
    (21.0, 0.40), (22.0, 0.10), (24.0, 0.10),
]

VEHICLE_STATES = ["STOPPED", "DEPARTING", "ARRIVING"]
BUS_CAPACITY = 80
LUAS_CAPACITY = 300


def _demand_mult(hour: float) -> float:
    hour = hour % 24.0
    for i in range(len(_DEMAND_CURVE) - 1):
        h0, m0 = _DEMAND_CURVE[i]
        h1, m1 = _DEMAND_CURVE[i + 1]
        if h0 <= hour < h1:
            t = (hour - h0) / (h1 - h0) if h1 != h0 else 0.0
            return m0 + t * (m1 - m0)
    return _DEMAND_CURVE[-1][1]


def _get_connection():
    return psycopg2.connect(
        host=db_config.DB_HOST,
        port=db_config.DB_PORT,
        dbname=db_config.DB_NAME,
        user=db_config.DB_USER,
        password=db_config.DB_PASSWORD,
    )


def _fetch_routes(cur) -> list[dict]:
    cur.execute("""
        SELECT r.route_id, r.route_short_name, r.transport_type,
               array_agg(DISTINCT rs.direction_id) AS directions
        FROM routes r
        JOIN route_stops rs ON rs.route_id = r.route_id
        GROUP BY r.route_id, r.route_short_name, r.transport_type
        ORDER BY r.transport_type, r.route_short_name
    """)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _fetch_route_stops(cur, route_id: str, direction_id: int) -> list[str]:
    cur.execute("""
        SELECT stop_id FROM route_stops
        WHERE route_id = %s AND direction_id = %s
        ORDER BY stop_sequence
    """, (route_id, direction_id))
    return [r[0] for r in cur.fetchall()]


def _fetch_route_stops_with_seq(cur, route_id: str, direction_id: int) -> list[tuple[str, int]]:
    cur.execute("""
        SELECT stop_id, stop_sequence FROM route_stops
        WHERE route_id = %s AND direction_id = %s
        ORDER BY stop_sequence
    """, (route_id, direction_id))
    return [(r[0], r[1]) for r in cur.fetchall()]


def _fetch_all_stops(cur) -> list[dict]:
    cur.execute("SELECT device_id, stop_id, stop_name, transport_type FROM stops")
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


# -----------------------------------------------------------------------
# 1. Vehicles
# -----------------------------------------------------------------------

def seed_vehicles(conn):
    """Create one vehicle per route+direction with realistic state."""
    rng = random.Random(42)
    with conn.cursor() as cur:
        routes = _fetch_routes(cur)
        rows = []
        for r in routes:
            cap = LUAS_CAPACITY if r["transport_type"] == "luas" else BUS_CAPACITY
            for d in sorted(set(r["directions"])):
                stops = _fetch_route_stops(cur, r["route_id"], d)
                if not stops:
                    continue
                vid = f"v-{r['route_short_name']}-d{d}"
                stop_idx = rng.randint(0, len(stops) - 1)
                pax = rng.randint(int(cap * 0.15), int(cap * 0.85))
                occ = round(pax / cap * 100, 1)
                state = rng.choice(VEHICLE_STATES)
                rows.append((
                    vid, r["route_id"], cap, stops[stop_idx],
                    state, pax, occ, True,
                    _dt.datetime.now(_dt.timezone.utc),
                ))

        if rows:
            execute_values(cur, """
                INSERT INTO vehicles
                    (vehicle_id, route_id, capacity, current_stop_id,
                     state, passenger_count, occupancy_percent,
                     is_active, last_updated)
                VALUES %s
                ON CONFLICT (vehicle_id) DO UPDATE SET
                    route_id          = EXCLUDED.route_id,
                    capacity          = EXCLUDED.capacity,
                    current_stop_id   = EXCLUDED.current_stop_id,
                    state             = EXCLUDED.state,
                    passenger_count   = EXCLUDED.passenger_count,
                    occupancy_percent = EXCLUDED.occupancy_percent,
                    is_active         = EXCLUDED.is_active,
                    last_updated      = EXCLUDED.last_updated
            """, rows)
    conn.commit()
    logger.info("Seeded %d vehicles", len(rows))
    return rows


# -----------------------------------------------------------------------
# 2. Vehicle telemetry (24h at 15-min intervals)
# -----------------------------------------------------------------------

def seed_vehicle_telemetry(conn, vehicle_rows):
    """Generate 24h of telemetry at 15-min intervals per vehicle."""
    rng = random.Random(43)
    now = _dt.datetime.now(_dt.timezone.utc)
    start = now - _dt.timedelta(hours=24)
    interval = _dt.timedelta(minutes=15)
    steps = int(24 * 60 / 15)  # 96 steps

    rows = []
    for v in vehicle_rows:
        vid, route_id, cap = v[0], v[1], v[2]
        stop_id = v[3]
        for i in range(steps):
            ts = start + interval * i
            hour = ts.hour + ts.minute / 60.0
            base_occ = _demand_mult(hour) * rng.uniform(0.3, 0.9)
            pax = max(0, min(cap, int(cap * base_occ + rng.gauss(0, cap * 0.05))))
            occ_pct = round(pax / cap * 100, 1)
            state = rng.choice(VEHICLE_STATES)
            rows.append((ts, vid, route_id, pax, occ_pct, stop_id, state))

    with conn.cursor() as cur:
        # Clear old seeded telemetry to avoid duplicates
        cur.execute("DELETE FROM vehicle_telemetry WHERE time >= %s", (start,))
        if rows:
            execute_values(cur, """
                INSERT INTO vehicle_telemetry
                    (time, vehicle_id, route_id, passenger_count,
                     occupancy_percent, current_stop_id, state)
                VALUES %s
            """, rows, page_size=2000)
    conn.commit()
    logger.info("Seeded %d vehicle_telemetry rows", len(rows))


# -----------------------------------------------------------------------
# 3. Predictions
# -----------------------------------------------------------------------

def seed_predictions(conn):
    """Generate prediction rows for each route+direction."""
    rng = random.Random(44)
    now = _dt.datetime.now(_dt.timezone.utc)

    with conn.cursor() as cur:
        routes = _fetch_routes(cur)
        rows = []
        for r in routes:
            cap = LUAS_CAPACITY if r["transport_type"] == "luas" else BUS_CAPACITY
            for d in sorted(set(r["directions"])):
                stops = _fetch_route_stops(cur, r["route_id"], d)
                if not stops:
                    continue
                vid = f"v-{r['route_short_name']}-d{d}"
                pax = rng.randint(int(cap * 0.2), int(cap * 0.5))
                confidence = round(rng.uniform(0.6, 0.95), 3)

                for seq, sid in enumerate(stops):
                    waiting = rng.randint(0, 25)
                    can_board = min(waiting, cap - pax)
                    boarded = rng.randint(0, max(1, can_board))
                    alighted = rng.randint(0, max(1, int(pax * 0.15)))
                    pax = max(0, pax + boarded - alighted)
                    occ = round(pax / cap, 4) if cap else 0.0
                    rows.append((
                        now, vid, r["route_id"], d, sid, seq,
                        pax, cap, occ, waiting,
                        boarded, alighted, True, confidence,
                    ))

        # Clear recent predictions so we don't accumulate stale runs
        cur.execute("DELETE FROM predictions WHERE time >= %s - INTERVAL '5 minutes'", (now,))
        if rows:
            execute_values(cur, """
                INSERT INTO predictions
                    (time, vehicle_id, route_id, direction_id, stop_id,
                     stop_sequence, predicted_passengers, vehicle_capacity,
                     predicted_occupancy_pct, waiting_at_stop,
                     boarded, alighted, has_data, confidence)
                VALUES %s
            """, rows, page_size=2000)
    conn.commit()
    logger.info("Seeded %d prediction rows", len(rows))


# -----------------------------------------------------------------------
# 4. Scheduler decisions
# -----------------------------------------------------------------------

def seed_scheduler_decisions(conn):
    rng = random.Random(45)
    now = _dt.datetime.now(_dt.timezone.utc)

    with conn.cursor() as cur:
        routes = _fetch_routes(cur)
        if not routes:
            return

        # Check for existing seeded decisions
        cur.execute("SELECT COUNT(*) FROM scheduler_decisions WHERE message LIKE %s",
                    (f"%[{SEED_TAG}]%",))
        if cur.fetchone()[0] > 0:
            logger.info("Scheduler decisions already seeded, skipping")
            return

        rows = []
        for i in range(8):
            r = rng.choice(routes)
            cap = LUAS_CAPACITY if r["transport_type"] == "luas" else BUS_CAPACITY
            dirs = sorted(set(r["directions"]))
            d = rng.choice(dirs)
            stops = _fetch_route_stops(cur, r["route_id"], d)
            trigger_stop = rng.choice(stops) if stops else None
            pax = rng.randint(int(cap * 0.8), cap)
            occ = round(pax / cap, 4)
            stranded = rng.randint(5, 30)
            ts = now - _dt.timedelta(minutes=rng.randint(5, 600))
            rows.append((
                ts, "deploy_vehicle", r["route_id"], d,
                f"v-{r['route_short_name']}-d{d}",
                trigger_stop, pax, occ, cap, stranded, 0.9,
                f"High occupancy at stop — {stranded} stranded [{SEED_TAG}]",
                "pending",
            ))

        if rows:
            execute_values(cur, """
                INSERT INTO scheduler_decisions
                    (decided_at, decision_type, route_id, direction_id,
                     trigger_vehicle_id, trigger_stop_id,
                     predicted_passengers, predicted_occupancy_pct,
                     vehicle_capacity, total_stranded, threshold,
                     message, status)
                VALUES %s
            """, rows)
    conn.commit()
    logger.info("Seeded %d scheduler decisions", len(rows))


# -----------------------------------------------------------------------
# 5. GTFS-RT service alerts
# -----------------------------------------------------------------------

def seed_service_alerts(conn):
    now = _dt.datetime.now(_dt.timezone.utc)

    sample_alerts = [
        ("CONSTRUCTION", "REDUCED_SERVICE",
         "Track work on Red Line", "Luas Red Line operating reduced service due to track maintenance near Smithfield.",
         "WARNING"),
        ("ACCIDENT", "DETOUR",
         "Route 39A diversion", "Dublin Bus route 39A diverted via N11 due to road traffic incident.",
         "SEVERE"),
        ("WEATHER", "SIGNIFICANT_DELAYS",
         "Storm warning delays", "Significant delays expected across all services due to Met Éireann Orange warning.",
         "SEVERE"),
        ("MAINTENANCE", "MODIFIED_SERVICE",
         "Green Line weekend schedule", "Luas Green Line operating weekend timetable for planned maintenance.",
         "INFO"),
        ("OTHER_CAUSE", "UNKNOWN_EFFECT",
         "Service update", "Minor scheduling adjustments on several bus routes.",
         "INFO"),
    ]

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM gtfs_rt_service_alerts WHERE header_text LIKE %s",
                    (f"%{SEED_TAG}%",))
        if cur.fetchone()[0] > 0:
            logger.info("Service alerts already seeded, skipping")
            return

        rows = []
        for i, (cause, effect, header, desc, severity) in enumerate(sample_alerts):
            ts = now - _dt.timedelta(hours=i * 3)
            end = ts + _dt.timedelta(hours=12) if severity != "INFO" else None
            rows.append((
                f"seed-alert-{i}", ts, cause, effect,
                f"{header}", desc, severity,
                ts, end,
            ))

        if rows:
            execute_values(cur, """
                INSERT INTO gtfs_rt_service_alerts
                    (alert_id, received_at, cause, effect,
                     header_text, description_text, severity,
                     active_period_start, active_period_end)
                VALUES %s
            """, rows)
    conn.commit()
    logger.info("Seeded %d service alerts", len(rows))


# -----------------------------------------------------------------------
# 6. Model versions
# -----------------------------------------------------------------------

def seed_model_versions(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM model_versions")
        if cur.fetchone()[0] > 0:
            logger.info("Model versions already exist, skipping")
            return

        now = _dt.datetime.now(_dt.timezone.utc)
        models = [
            ("yolov8n-crowd.pt", "1.0.0", True, now - _dt.timedelta(days=7), 6_800_000),
            ("yolov8n-crowd.pt", "0.9.0", False, now - _dt.timedelta(days=30), 6_750_000),
            ("yolov8n-crowd.pt", "0.8.0", False, now - _dt.timedelta(days=60), 6_700_000),
        ]

        rows = []
        for fname, ver, active, uploaded, size in models:
            sha = hashlib.sha256(f"{fname}-{ver}".encode()).hexdigest()
            rows.append((fname, ver, sha, size, f"models/{ver}/{fname}", uploaded, active))

        execute_values(cur, """
            INSERT INTO model_versions
                (filename, version, sha256, file_size, file_path, uploaded_at, is_active)
            VALUES %s
            ON CONFLICT (sha256) DO NOTHING
        """, rows)
    conn.commit()
    logger.info("Seeded %d model versions", len(rows))


# -----------------------------------------------------------------------
# 7. Admin activity log
# -----------------------------------------------------------------------

def seed_admin_log(conn):
    now = _dt.datetime.now(_dt.timezone.utc)

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM admin_activity_log WHERE action LIKE %s",
                    (f"%{SEED_TAG}%",))
        if cur.fetchone()[0] > 0:
            logger.info("Admin log already seeded, skipping")
            return

        stops = _fetch_all_stops(cur)
        sample_devices = [s["device_id"] for s in stops[:5]] if stops else ["device-1"]

        entries = [
            (now - _dt.timedelta(hours=2), sample_devices[0],
             f"update_config [{SEED_TAG}]",
             json.dumps({"capture_interval": 10, "conf_threshold": 0.3}),
             "ok", "operator"),
            (now - _dt.timedelta(hours=5), sample_devices[1 % len(sample_devices)],
             f"start_pipeline [{SEED_TAG}]",
             json.dumps({"action": "start_pipeline"}),
             "ok", "operator"),
            (now - _dt.timedelta(hours=10), None,
             f"update_evaluator [{SEED_TAG}]",
             json.dumps({"occupancy_threshold": 0.85, "min_stranded": 3}),
             "ok", "system"),
            (now - _dt.timedelta(hours=18), sample_devices[2 % len(sample_devices)],
             f"stop_pipeline [{SEED_TAG}]",
             json.dumps({"action": "stop_pipeline"}),
             "ok", "operator"),
        ]

        rows = [(ts, dev, act, cmd, res, by) for ts, dev, act, cmd, res, by in entries]
        execute_values(cur, """
            INSERT INTO admin_activity_log
                (occurred_at, target_device_id, action, command, result, initiated_by)
            VALUES %s
        """, rows)
    conn.commit()
    logger.info("Seeded %d admin log entries", len(rows))


# -----------------------------------------------------------------------
# 8. System alerts
# -----------------------------------------------------------------------

def seed_system_alerts(conn):
    now = _dt.datetime.now(_dt.timezone.utc)

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM system_alerts WHERE message LIKE %s",
                    (f"%[{SEED_TAG}]%",))
        if cur.fetchone()[0] > 0:
            logger.info("System alerts already seeded, skipping")
            return

        stops = _fetch_all_stops(cur)
        routes = _fetch_routes(cur)

        alerts = [
            ("critical", f"Edge device offline for >15 min [{SEED_TAG}]",
             "monitor", stops[0]["device_id"] if stops else None, None, None),
            ("warning", f"Prediction confidence below 0.3 for route [{SEED_TAG}]",
             "prediction_engine", None, routes[0]["route_id"] if routes else None, None),
            ("info", f"GTFS-RT feed recovered after 5 failures [{SEED_TAG}]",
             "gtfs_rt", None, None, None),
            ("warning", f"High crowd count at stop — 35 waiting [{SEED_TAG}]",
             "crowd_monitor", stops[1]["device_id"] if len(stops) > 1 else None, None,
             now - _dt.timedelta(hours=1)),
            ("critical", f"Database connection pool exhausted [{SEED_TAG}]",
             "system", None, None, now - _dt.timedelta(hours=3)),
        ]

        rows = []
        for i, (sev, msg, src, dev, route, resolved) in enumerate(alerts):
            ts = now - _dt.timedelta(hours=i * 2)
            rows.append((ts, sev, msg, src, dev, route, resolved))

        execute_values(cur, """
            INSERT INTO system_alerts
                (created_at, severity, message, source, device_id, route_id, resolved_at)
            VALUES %s
        """, rows)
    conn.commit()
    logger.info("Seeded %d system alerts", len(rows))


# -----------------------------------------------------------------------
# 9. Stop logs
# -----------------------------------------------------------------------

def seed_stop_logs(conn):
    rng = random.Random(46)
    now = _dt.datetime.now(_dt.timezone.utc)

    with conn.cursor() as cur:
        stops = _fetch_all_stops(cur)
        if not stops:
            logger.warning("No stops found; skipping stop_logs seed")
            return

        # Only seed a handful of stops with recent logs
        sample = stops[:min(8, len(stops))]

        rows = []
        levels = ["INFO", "INFO", "INFO", "WARNING", "ERROR"]
        messages = [
            ("INFO", "Pipeline started successfully"),
            ("INFO", "Crowd count published: {count}"),
            ("INFO", "Image sent to broker"),
            ("WARNING", "Camera frame drop detected"),
            ("WARNING", "High crowd count: {count} exceeds threshold"),
            ("ERROR", "Failed to connect to MQTT broker"),
            ("INFO", "Model loaded: yolov8n-crowd.pt v1.0.0"),
            ("INFO", "Settings updated via admin command"),
        ]

        for stop in sample:
            n_logs = rng.randint(5, 15)
            for j in range(n_logs):
                ts = now - _dt.timedelta(minutes=rng.randint(1, 1440))
                lvl, msg = rng.choice(messages)
                if "{count}" in msg:
                    msg = msg.format(count=rng.randint(1, 40))
                rows.append((ts, stop["device_id"], lvl, msg, "{}"))

        if rows:
            # Avoid unbounded growth: clear old seeded logs (>24h window overlap is fine)
            oldest = min(r[0] for r in rows)
            cur.execute("DELETE FROM stop_logs WHERE time >= %s", (oldest,))
            execute_values(cur, """
                INSERT INTO stop_logs (time, device_id, level, message, extra)
                VALUES %s
            """, rows)
    conn.commit()
    logger.info("Seeded %d stop_log entries across %d devices", len(rows), min(8, len(stops)))


# -----------------------------------------------------------------------
# 10. GTFS-RT trip updates (delay data for analytics)
# -----------------------------------------------------------------------

def seed_trip_updates(conn):
    """Generate 24h of trip update delay data for analytics charts."""
    rng = random.Random(47)
    now = _dt.datetime.now(_dt.timezone.utc)
    start = now - _dt.timedelta(hours=24)

    with conn.cursor() as cur:
        routes = _fetch_routes(cur)
        if not routes:
            return

        # Pick a subset of routes for delay data
        sample_routes = routes[:min(6, len(routes))]
        rows = []

        for r in sample_routes:
            dirs = sorted(set(r["directions"]))
            for d in dirs:
                stop_seqs = _fetch_route_stops_with_seq(cur, r["route_id"], d)
                if not stop_seqs:
                    continue
                for hour_offset in range(24):
                    ts = start + _dt.timedelta(hours=hour_offset, minutes=rng.randint(0, 30))
                    trip_id = f"seed-trip-{r['route_short_name']}-d{d}-h{hour_offset}"
                    for sid, seq in stop_seqs[:min(10, len(stop_seqs))]:
                        base_delay = rng.gauss(60, 120)
                        if 7.5 <= (ts.hour + ts.minute / 60) <= 9.5:
                            base_delay += rng.uniform(60, 300)
                        elif 16.5 <= (ts.hour + ts.minute / 60) <= 18.5:
                            base_delay += rng.uniform(30, 240)
                        arrival_delay = max(-60, int(base_delay))
                        departure_delay = arrival_delay + rng.randint(0, 30)
                        rows.append((
                            ts, trip_id, r["route_id"], d,
                            f"v-{r['route_short_name']}-d{d}",
                            sid, seq, arrival_delay, departure_delay,
                            "{}",
                        ))

        cur.execute("DELETE FROM gtfs_rt_trip_updates WHERE time >= %s AND trip_id LIKE 'seed-trip-%%'", (start,))
        if rows:
            execute_values(cur, """
                INSERT INTO gtfs_rt_trip_updates
                    (time, trip_id, route_id, direction_id, vehicle_id,
                     stop_id, stop_sequence, arrival_delay, departure_delay, raw)
                VALUES %s
            """, rows, page_size=2000)
    conn.commit()
    logger.info("Seeded %d trip update rows for delay analytics", len(rows))


# -----------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------

def _load_vehicle_rows(conn) -> list[tuple]:
    """Fetch existing vehicles shaped like the tuples seed_vehicles() returns.

    ``seed_vehicle_telemetry`` only uses positions 0-3 (vehicle_id, route_id,
    capacity, current_stop_id), so the trailing fields are padded with
    placeholders.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT vehicle_id, route_id, capacity, current_stop_id
            FROM vehicles
            WHERE is_active = true AND current_stop_id IS NOT NULL
        """)
        return [
            (row[0], row[1], row[2], row[3], None, 0, 0.0, True, None)
            for row in cur.fetchall()
        ]


def refresh_telemetry(conn) -> None:
    """Re-anchor the 24h vehicle_telemetry window to "now".

    The three charts (Home: Fleet Utilisation, Analytics: Vehicle Fullness
    Over Time and Fleet Occupancy Distribution) all query
    ``vehicle_telemetry WHERE time > NOW() - INTERVAL '24 hours'``.  The
    full seed is gated on whether ``vehicles`` already has rows, so on
    demo restarts the telemetry ages out and the charts go blank.  This
    repopulates only the time-windowed telemetry, without touching the
    reference ``vehicles`` rows.
    """
    vehicle_rows = _load_vehicle_rows(conn)
    if not vehicle_rows:
        logger.warning("No active vehicles found; skipping telemetry refresh")
        return
    seed_vehicle_telemetry(conn, vehicle_rows)


def main():
    parser = argparse.ArgumentParser(description="Seed TransitFlow test data")
    parser.add_argument(
        "--refresh-telemetry",
        action="store_true",
        help=(
            "Only re-seed the 24h vehicle_telemetry window (leaves every "
            "other seeded table untouched). Used on demo restarts to keep "
            "the fleet occupancy charts populated."
        ),
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
    )

    logger.info("Connecting to database...")
    conn = _get_connection()
    try:
        if args.refresh_telemetry:
            logger.info("--- Refreshing vehicle telemetry window ---")
            refresh_telemetry(conn)
            logger.info("=== Telemetry refresh complete ===")
            return

        logger.info("--- Seeding vehicles ---")
        vehicle_rows = seed_vehicles(conn)

        logger.info("--- Seeding vehicle telemetry ---")
        seed_vehicle_telemetry(conn, vehicle_rows)

        logger.info("--- Seeding predictions ---")
        seed_predictions(conn)

        logger.info("--- Seeding scheduler decisions ---")
        seed_scheduler_decisions(conn)

        logger.info("--- Seeding trip updates (delay data) ---")
        seed_trip_updates(conn)

        logger.info("--- Seeding service alerts ---")
        seed_service_alerts(conn)

        logger.info("--- Seeding model versions ---")
        seed_model_versions(conn)

        logger.info("--- Seeding admin activity log ---")
        seed_admin_log(conn)

        logger.info("--- Seeding system alerts ---")
        seed_system_alerts(conn)

        logger.info("--- Seeding stop logs ---")
        seed_stop_logs(conn)

        logger.info("=== Test data seeding complete ===")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
