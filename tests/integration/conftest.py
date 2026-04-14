# *** TEST FILE - SAFE TO DELETE ***
"""
Pytest fixtures for system integration tests.

Session-scoped: Docker lifecycle, DB seeding, synthetic data insertion.
Requires Docker to be running.
"""

import datetime as _dt
import json
import os
import random
import subprocess
import sys
import time

import psycopg2
import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
BACKEND_DIR = os.path.join(SRC_DIR, "Backend")

for p in (SRC_DIR, BACKEND_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

DOCKER_DIR = os.path.join(PROJECT_ROOT, "docker")


# ===== helpers ==============================================================

def _wait_for_db(host="localhost", port=5432, timeout=60):
    """Poll until TimescaleDB accepts connections."""
    deadline = time.time() + timeout
    delay = 1.0
    while time.time() < deadline:
        try:
            conn = psycopg2.connect(
                host=host, port=port,
                dbname="transitflow", user="transitflow",
                password="transitflow_dev",
                connect_timeout=3,
            )
            conn.close()
            return True
        except psycopg2.OperationalError:
            time.sleep(delay)
            delay = min(delay * 1.5, 5.0)
    raise RuntimeError(f"TimescaleDB not ready after {timeout}s on {host}:{port}")


def _run_seed():
    """Run the GTFS seed script against the running DB."""
    subprocess.run(
        [sys.executable, "-m", "Backend.Database.seed"],
        check=True,
        cwd=SRC_DIR,
    )


# ===== session fixtures =====================================================

@pytest.fixture(scope="session")
def docker_db():
    """Start Docker containers and wait for TimescaleDB to be ready."""
    compose_file = os.path.join(DOCKER_DIR, "docker-compose.yml")

    print("\n[integration] Starting Docker containers...")
    subprocess.run(
        ["docker", "compose", "-f", compose_file, "up", "-d", "--wait"],
        check=True, cwd=PROJECT_ROOT,
    )

    print("[integration] Waiting for TimescaleDB to accept connections...")
    _wait_for_db()
    print("[integration] TimescaleDB is ready.")

    yield

    print("\n[integration] Stopping Docker containers and removing volumes...")
    subprocess.run(
        ["docker", "compose", "-f", compose_file, "down", "-v"],
        check=True, cwd=PROJECT_ROOT,
    )


@pytest.fixture(scope="session")
def seeded_db(docker_db):
    """Seed the DB with GTFS static data and return a ConnectionPool."""
    from Database.connection import ConnectionPool

    print("[integration] Running GTFS seed script...")
    _run_seed()
    print("[integration] Seeding complete.")

    pool = ConnectionPool()
    pool.open()
    yield pool
    pool.close()


@pytest.fixture(scope="session")
def route_39a_info(seeded_db):
    """Look up route 39A info from the seeded database.

    Returns a dict with route_id, direction_id, and ordered stop list.
    """
    with seeded_db.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT route_id FROM routes WHERE route_short_name = '39A'"
            )
            row = cur.fetchone()
            assert row is not None, "Route 39A not found in seeded routes table"
            route_id = row[0]

            cur.execute(
                """
                SELECT stop_id, stop_sequence
                FROM route_stops
                WHERE route_id = %s AND direction_id = 0
                ORDER BY stop_sequence
                """,
                (route_id,),
            )
            stops = cur.fetchall()
            assert len(stops) > 0, "No stops for 39A direction 0"

    print(f"[integration] Route 39A = {route_id}, direction 0: {len(stops)} stops")
    return {
        "route_id": route_id,
        "direction_id": 0,
        "stops": [(s[0], s[1]) for s in stops],  # (stop_id, stop_sequence)
    }


@pytest.fixture(scope="session")
def synthetic_vehicles(seeded_db, route_39a_info):
    """Insert synthetic GTFS-RT trip update rows for 3 vehicles on 39A.

    Each vehicle gets multiple rows (one per remaining stop from its
    position to the end of the route), matching real GTFS-RT data patterns.
    """
    from Database.writer import DatabaseWriter

    route_id = route_39a_info["route_id"]
    direction_id = route_39a_info["direction_id"]
    stops = route_39a_info["stops"]

    vehicle_positions = [
        ("synth-trip-front", 10),
        ("synth-trip-mid", 30),
        ("synth-trip-rear", 55),
    ]

    now = _dt.datetime.now(_dt.timezone.utc)
    rows = []
    for trip_id, current_seq in vehicle_positions:
        for stop_id, seq in stops:
            if seq >= current_seq:
                rows.append({
                    "time": now,
                    "trip_id": trip_id,
                    "route_id": route_id,
                    "direction_id": direction_id,
                    "vehicle_id": None,
                    "stop_id": stop_id,
                    "stop_sequence": seq,
                    "arrival_delay": random.randint(-30, 120),
                    "departure_delay": random.randint(-30, 120),
                    "raw": {"synthetic": True, "trip_id": trip_id},
                })

    writer = DatabaseWriter(seeded_db)
    writer.write_gtfs_trip_updates(rows)

    trip_ids = [t for t, _ in vehicle_positions]
    print(
        f"[integration] Inserted {len(rows)} synthetic GTFS-RT rows "
        f"for {len(trip_ids)} vehicles"
    )
    return trip_ids


@pytest.fixture(scope="session")
def mock_crowd_counts(seeded_db, route_39a_info):
    """Insert synthetic crowd counts for most 39A direction 0 stops.

    Distribution: suburban stops (early/late in route) get 0-3 people,
    city-centre stops (middle third) get 8-15.  A few stops are skipped
    to simulate missing edge devices (StopState.people_waiting = None).
    """
    stops = route_39a_info["stops"]
    total = len(stops)
    third = total // 3

    rng = random.Random(42)
    now = _dt.datetime.now(_dt.timezone.utc)
    inserted = {}

    skip_indices = {5, 15, 45, 60}

    with seeded_db.connection() as conn:
        with conn.cursor() as cur:
            for i, (stop_id, seq) in enumerate(stops):
                if i in skip_indices:
                    continue

                if i < third or i >= 2 * third:
                    count = rng.randint(0, 3)
                else:
                    count = rng.randint(8, 15)

                device_id = stop_id
                cur.execute(
                    """
                    INSERT INTO current_counts
                        (device_id, stop_id, count, previous_count, zone, updated_at)
                    VALUES (%s, %s, %s, NULL, NULL, %s)
                    ON CONFLICT (device_id) DO UPDATE SET
                        count = EXCLUDED.count,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (device_id, stop_id, count, now),
                )
                inserted[stop_id] = count
        conn.commit()

    print(
        f"[integration] Inserted crowd counts for {len(inserted)}/{total} stops "
        f"({total - len(inserted)} have no data)"
    )
    return inserted


@pytest.fixture(scope="session")
def competing_route_at_shared_stop(seeded_db, route_39a_info, synthetic_vehicles):
    """Set up a competing route at a stop shared with 39A.

    Inserts stop_times rows for the 39A synthetic trips AND a competing
    route trip, plus GTFS-RT data for the competitor.  Returns a dict
    with info needed by the crowd-splitting test.
    """
    route_id = route_39a_info["route_id"]
    stops = route_39a_info["stops"]

    # Pick a stop in the middle of the route for the test
    shared_stop_id, shared_seq = stops[35]

    # Find a real competing route that also serves this stop
    with seeded_db.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT rs.route_id, rs.direction_id, rs.stop_sequence
                FROM route_stops rs
                WHERE rs.stop_id = %s
                  AND rs.route_id != %s
                LIMIT 1
                """,
                (shared_stop_id, route_id),
            )
            row = cur.fetchone()

    if row is None:
        pytest.skip(f"No competing route found at stop {shared_stop_id}")

    competitor_route_id, competitor_dir, competitor_seq = row

    # Compute scheduled arrival for the shared stop as "now + 8 minutes"
    # so the test has a deterministic relative ETA.
    from zoneinfo import ZoneInfo
    dublin = ZoneInfo("Europe/Dublin")
    now_local = _dt.datetime.now(dublin)
    now_secs = now_local.hour * 3600 + now_local.minute * 60 + now_local.second

    our_arrival = now_secs + 180      # 39A arrives in 3 min
    competitor_arrival = now_secs + 480  # competitor arrives in 8 min

    now_utc = _dt.datetime.now(_dt.timezone.utc)

    with seeded_db.connection() as conn:
        with conn.cursor() as cur:
            # Insert stop_times for the 39A synth-trip-mid at the shared stop
            cur.execute(
                """
                INSERT INTO stop_times
                    (trip_id, stop_sequence, stop_id, arrival_seconds, departure_seconds)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (trip_id, stop_sequence) DO UPDATE SET
                    arrival_seconds = EXCLUDED.arrival_seconds
                """,
                ("synth-trip-mid", shared_seq, shared_stop_id,
                 our_arrival, our_arrival),
            )

            # Insert stop_times for the competitor trip
            competitor_trip = "competitor-trip-1"
            cur.execute(
                """
                INSERT INTO stop_times
                    (trip_id, stop_sequence, stop_id, arrival_seconds, departure_seconds)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (trip_id, stop_sequence) DO UPDATE SET
                    arrival_seconds = EXCLUDED.arrival_seconds
                """,
                (competitor_trip, competitor_seq, shared_stop_id,
                 competitor_arrival, competitor_arrival),
            )

            # Insert GTFS-RT row for the competitor trip at the shared stop
            cur.execute(
                """
                INSERT INTO gtfs_rt_trip_updates
                    (time, trip_id, route_id, direction_id, vehicle_id,
                     stop_id, stop_sequence, arrival_delay, departure_delay, raw)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (now_utc, competitor_trip, competitor_route_id, competitor_dir,
                 None, shared_stop_id, competitor_seq, 0, 0,
                 json.dumps({"synthetic": True, "competitor": True})),
            )

            # Also insert a GTFS-RT row for synth-trip-mid at the shared stop
            # with delay=0 (so ETA = our_arrival exactly)
            cur.execute(
                """
                INSERT INTO gtfs_rt_trip_updates
                    (time, trip_id, route_id, direction_id, vehicle_id,
                     stop_id, stop_sequence, arrival_delay, departure_delay, raw)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (now_utc, "synth-trip-mid", route_id, 0,
                 None, shared_stop_id, shared_seq, 0, 0,
                 json.dumps({"synthetic": True, "eta_test": True})),
            )
        conn.commit()

    print(
        f"[integration] Set up competing route {competitor_route_id} "
        f"at shared stop {shared_stop_id}"
    )
    return {
        "shared_stop_id": shared_stop_id,
        "shared_seq": shared_seq,
        "competitor_route_id": competitor_route_id,
        "competitor_direction": competitor_dir,
        "our_arrival_secs": our_arrival,
        "competitor_arrival_secs": competitor_arrival,
    }
