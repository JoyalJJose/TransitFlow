"""GTFS-Realtime fetcher entry point.

Polls the NTA GTFS-R TripUpdates API every POLL_INTERVAL seconds and
writes parsed rows into the ``gtfs_rt_trip_updates`` hypertable.

Usage::

    # Continuous poll loop (production) — run from project root
    PYTHONPATH=src python -m Backend.GTFS_RT

    # Single fetch-filter-write cycle (testing / one-shot)
    PYTHONPATH=src python -m Backend.GTFS_RT --once
"""

import argparse
import logging
import os
import signal
import sys
import time

from dotenv import load_dotenv

load_dotenv()  # reads .env from project root before config is imported

# Sibling-package import (same technique as MQTTBroker/broker_handler.py)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from Database import ConnectionPool, DatabaseWriter  # noqa: E402

from . import config  # noqa: E402
from .fetcher import GTFSRealtimeFetcher  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)


def _load_route_filter(pool: ConnectionPool) -> set[str] | None:
    """Load the set of route_ids for the configured agency from the DB.

    Returns ``None`` (no filtering) when GTFSR_AGENCY_FILTER is empty or
    the routes table has not been seeded yet.
    """
    agency = config.GTFSR_AGENCY_FILTER
    if not agency:
        logger.info("Route filter disabled (GTFSR_AGENCY_FILTER is empty)")
        return None

    try:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT route_id FROM routes WHERE agency_id = %s",
                    (agency,),
                )
                route_ids = {row[0] for row in cur.fetchall()}
    except Exception:
        logger.warning(
            "Could not load route filter from DB (routes table may be empty); "
            "all trip updates will be kept"
        )
        return None

    if not route_ids:
        logger.warning(
            "No routes found for agency_id=%s; route filter disabled", agency
        )
        return None

    logger.info(
        "Route filter loaded: %d routes for agency_id=%s", len(route_ids), agency
    )
    return route_ids


def _fetch_cycle(fetcher, writer, route_filter):
    """Execute one fetch -> filter -> write -> purge cycle.  Returns the row count."""
    feed = fetcher.fetch_feed()
    if feed is None:
        return 0
    updates = fetcher.parse_trip_updates(feed, route_ids=route_filter)
    writer.write_gtfs_trip_updates(updates)
    writer.purge_old_trip_updates(retain=config.GTFSR_RETAIN_FETCHES)
    return len(updates)


def main():
    parser = argparse.ArgumentParser(description="GTFS-R TripUpdates fetcher")
    parser.add_argument(
        "--once", action="store_true",
        help="Run a single fetch-filter-write cycle and exit",
    )
    args = parser.parse_args()

    if not config.GTFSR_API_KEY:
        logger.error(
            "GTFSR_API_KEY is not set. "
            "Register at https://developer.nationaltransport.ie and set the env var."
        )
        sys.exit(1)

    fetcher = GTFSRealtimeFetcher()

    pool = ConnectionPool()
    try:
        pool.open()
    except Exception:
        logger.exception("Failed to open database connection pool")
        sys.exit(1)

    writer = DatabaseWriter(pool)
    route_filter = _load_route_filter(pool)

    if args.once:
        logger.info("Running single fetch cycle (--once)")
        try:
            count = _fetch_cycle(fetcher, writer, route_filter)
            logger.info("Done — %d rows written", count)
        except Exception:
            logger.exception("Fetch cycle failed")
        finally:
            pool.close()
        return

    # --- continuous poll loop ---
    shutdown = False

    def handle_signal(sig, frame):
        nonlocal shutdown
        shutdown = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    logger.info(
        "GTFS-R fetcher started (poll every %ds)", config.GTFSR_POLL_INTERVAL
    )

    consecutive_empty = 0
    _TRACEBACK_THRESHOLD = 3

    while not shutdown:
        try:
            count = _fetch_cycle(fetcher, writer, route_filter)
            if count > 0:
                if consecutive_empty > 0:
                    logger.info(
                        "GTFS-RT recovered after %d empty cycle(s)",
                        consecutive_empty,
                    )
                consecutive_empty = 0
            else:
                consecutive_empty += 1
                if consecutive_empty >= _TRACEBACK_THRESHOLD:
                    logger.warning(
                        "GTFS-RT: %d consecutive cycle(s) with no data",
                        consecutive_empty,
                    )
        except Exception:
            consecutive_empty += 1
            if consecutive_empty <= _TRACEBACK_THRESHOLD:
                logger.exception("Unhandled error in poll loop")
            else:
                logger.warning(
                    "GTFS-RT: %d consecutive failures (suppressing traceback)",
                    consecutive_empty,
                )

        deadline = time.monotonic() + config.GTFSR_POLL_INTERVAL
        while not shutdown and time.monotonic() < deadline:
            time.sleep(1)

    logger.info("Shutting down GTFS-R fetcher...")
    pool.close()


if __name__ == "__main__":
    main()
