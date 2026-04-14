"""Seed the TransitFlow database with static GTFS data.

Usage:
    python -m Backend.Database.seed [--data-dir DATA_DIR]

Loads routes, stops, and route_stops from the GTFS files located in
``data/Transport Data/`` (Dublin Bus and LUAS).  The script is idempotent --
running it again will upsert existing rows and insert new ones.
"""

import argparse
import csv
import logging
import os
import sys

import psycopg2
from psycopg2.extras import execute_values

from . import config as db_config

logger = logging.getLogger(__name__)

TRANSPORT_TYPES = {
    "Dublin Bus": "bus",
    "LUAS": "luas",
}

DEFAULT_DATA_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "data", "Transport Data",
)


def _read_csv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _get_connection():
    return psycopg2.connect(
        host=db_config.DB_HOST,
        port=db_config.DB_PORT,
        dbname=db_config.DB_NAME,
        user=db_config.DB_USER,
        password=db_config.DB_PASSWORD,
    )


def seed_routes(conn, data_dir: str):
    """Upsert all routes from each GTFS source."""
    rows = []
    for folder, transport_type in TRANSPORT_TYPES.items():
        path = os.path.join(data_dir, folder, "routes.txt")
        if not os.path.exists(path):
            logger.warning("Missing %s, skipping", path)
            continue
        for r in _read_csv(path):
            rows.append((
                r["route_id"],
                r.get("agency_id", ""),
                r["route_short_name"],
                r.get("route_long_name", ""),
                int(r.get("route_type", 3)),
                transport_type,
            ))

    if not rows:
        return

    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO routes
                (route_id, agency_id, route_short_name, route_long_name,
                 route_type, transport_type)
            VALUES %s
            ON CONFLICT (route_id) DO UPDATE SET
                agency_id        = EXCLUDED.agency_id,
                route_short_name = EXCLUDED.route_short_name,
                route_long_name  = EXCLUDED.route_long_name,
                route_type       = EXCLUDED.route_type,
                transport_type   = EXCLUDED.transport_type
            """,
            rows,
        )
    conn.commit()
    logger.info("Upserted %d routes", len(rows))


def seed_stops(conn, data_dir: str):
    """Upsert all stops from each GTFS source.

    ``device_id`` is set to ``stop_id`` since each edge device corresponds
    to a single GTFS stop.
    """
    rows = []
    for folder, transport_type in TRANSPORT_TYPES.items():
        path = os.path.join(data_dir, folder, "stops.txt")
        if not os.path.exists(path):
            logger.warning("Missing %s, skipping", path)
            continue
        for s in _read_csv(path):
            stop_id = s["stop_id"]
            rows.append((
                stop_id,            # device_id = stop_id
                stop_id,
                s.get("stop_code", ""),
                s["stop_name"],
                float(s["stop_lat"]),
                float(s["stop_lon"]),
                transport_type,
                s.get("zone_id") or None,
            ))

    if not rows:
        return

    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO stops
                (device_id, stop_id, stop_code, stop_name, stop_lat,
                 stop_long, transport_type, zone)
            VALUES %s
            ON CONFLICT (device_id) DO UPDATE SET
                stop_id        = EXCLUDED.stop_id,
                stop_code      = EXCLUDED.stop_code,
                stop_name      = EXCLUDED.stop_name,
                stop_lat       = EXCLUDED.stop_lat,
                stop_long      = EXCLUDED.stop_long,
                transport_type = EXCLUDED.transport_type,
                zone           = EXCLUDED.zone
            """,
            rows,
        )
    conn.commit()
    logger.info("Upserted %d stops", len(rows))


def seed_route_stops(conn, data_dir: str):
    """Derive route_stops by joining trips.txt and stop_times.txt.

    For each (route_id, direction_id) pair we pick one representative trip
    and record its stop sequence.
    """
    rows = []
    for folder, _transport_type in TRANSPORT_TYPES.items():
        trips_path = os.path.join(data_dir, folder, "trips.txt")
        stop_times_path = os.path.join(data_dir, folder, "stop_times.txt")
        if not os.path.exists(trips_path) or not os.path.exists(stop_times_path):
            logger.warning("Missing trips/stop_times in %s, skipping", folder)
            continue

        trip_to_route: dict[str, tuple[str, int]] = {}
        for t in _read_csv(trips_path):
            trip_id = t["trip_id"]
            route_id = t["route_id"]
            direction = int(t.get("direction_id", 0))
            trip_to_route[trip_id] = (route_id, direction)

        # Pick one trip per (route_id, direction_id) and collect its stop seq
        seen_combos: dict[tuple[str, int], str] = {}
        for trip_id, (route_id, direction) in trip_to_route.items():
            key = (route_id, direction)
            if key not in seen_combos:
                seen_combos[key] = trip_id

        representative_trips = set(seen_combos.values())

        for st in _read_csv(stop_times_path):
            trip_id = st["trip_id"]
            if trip_id not in representative_trips:
                continue
            route_id, direction = trip_to_route[trip_id]
            rows.append((
                route_id,
                st["stop_id"],
                direction,
                int(st["stop_sequence"]),
            ))

    if not rows:
        return

    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO route_stops
                (route_id, stop_id, direction_id, stop_sequence)
            VALUES %s
            ON CONFLICT (route_id, direction_id, stop_sequence) DO UPDATE SET
                stop_id = EXCLUDED.stop_id
            """,
            rows,
        )
    conn.commit()
    logger.info("Upserted %d route_stop entries", len(rows))


def _parse_gtfs_time(text: str) -> int:
    """Convert GTFS time string (HH:MM:SS) to seconds from midnight.

    Handles values >24:00:00 used by GTFS for overnight trips
    (e.g. "25:30:00" -> 91800).
    """
    parts = text.strip().split(":")
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])


_SEED_BATCH = 10_000


def seed_stop_times(conn, data_dir: str):
    """Load scheduled arrival/departure times from stop_times.txt.

    Stores times as integer seconds from midnight so they can be combined
    with GTFS-RT ``arrival_delay`` to compute ETAs.
    """
    rows = []
    for folder in TRANSPORT_TYPES:
        path = os.path.join(data_dir, folder, "stop_times.txt")
        if not os.path.exists(path):
            logger.warning("Missing %s, skipping", path)
            continue
        for st in _read_csv(path):
            rows.append((
                st["trip_id"],
                int(st["stop_sequence"]),
                st["stop_id"],
                _parse_gtfs_time(st["arrival_time"]),
                _parse_gtfs_time(st["departure_time"]),
            ))

    if not rows:
        return

    sql = """
        INSERT INTO stop_times
            (trip_id, stop_sequence, stop_id, arrival_seconds, departure_seconds)
        VALUES %s
        ON CONFLICT (trip_id, stop_sequence) DO UPDATE SET
            stop_id           = EXCLUDED.stop_id,
            arrival_seconds   = EXCLUDED.arrival_seconds,
            departure_seconds = EXCLUDED.departure_seconds
    """
    with conn.cursor() as cur:
        for i in range(0, len(rows), _SEED_BATCH):
            execute_values(cur, sql, rows[i:i + _SEED_BATCH])
    conn.commit()
    logger.info("Upserted %d stop_time entries", len(rows))


def main():
    parser = argparse.ArgumentParser(description="Seed TransitFlow DB with GTFS data")
    parser.add_argument(
        "--data-dir",
        default=os.path.normpath(DEFAULT_DATA_DIR),
        help="Path to the 'Transport Data' directory",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if not os.path.isdir(args.data_dir):
        logger.error("Data directory not found: %s", args.data_dir)
        sys.exit(1)

    conn = _get_connection()
    try:
        seed_routes(conn, args.data_dir)
        seed_stops(conn, args.data_dir)
        seed_route_stops(conn, args.data_dir)
        seed_stop_times(conn, args.data_dir)
        logger.info("Seeding complete")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
