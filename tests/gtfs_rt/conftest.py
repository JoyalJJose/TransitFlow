# *** TEST FILE - SAFE TO DELETE ***
"""Fixtures for GTFS-RT fetcher + main unit tests.

All tests here mock the network (``requests``) so no real NTA API call is made.
Real protobuf ``FeedMessage`` objects are used (the ``gtfs-realtime-bindings``
package is installed in src/Backend/GTFS_RT/requirements.txt).
"""

import os
import sys

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
BACKEND_DIR = os.path.join(SRC_DIR, "Backend")

for p in (SRC_DIR, BACKEND_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture
def make_feed():
    """Factory building a real ``FeedMessage`` protobuf for tests."""
    from google.transit import gtfs_realtime_pb2

    def _build(
        entities: list[dict] | None = None,
        timestamp: int = 1_700_000_000,
    ):
        """*entities* is a list of dicts describing TripUpdate entities::

            {
                "id": "entity-1",
                "trip_id": "trip-A",
                "route_id": "39A",
                "direction_id": 0,
                "vehicle_id": "v-1",
                "stop_time_updates": [
                    {"stop_id": "s1", "stop_sequence": 1,
                     "arrival_delay": 30, "departure_delay": 45},
                ],
            }

        Omit a key to drop the corresponding field.
        """
        feed = gtfs_realtime_pb2.FeedMessage()
        feed.header.gtfs_realtime_version = "2.0"
        feed.header.timestamp = timestamp

        for ent_cfg in entities or []:
            e = feed.entity.add()
            e.id = ent_cfg.get("id", "e")
            tu = e.trip_update

            if "trip_id" in ent_cfg:
                tu.trip.trip_id = ent_cfg["trip_id"]
            if "route_id" in ent_cfg:
                tu.trip.route_id = ent_cfg["route_id"]
            if "direction_id" in ent_cfg:
                tu.trip.direction_id = ent_cfg["direction_id"]
            if "vehicle_id" in ent_cfg:
                tu.vehicle.id = ent_cfg["vehicle_id"]

            for stu_cfg in ent_cfg.get("stop_time_updates", []):
                stu = tu.stop_time_update.add()
                if "stop_id" in stu_cfg:
                    stu.stop_id = stu_cfg["stop_id"]
                if "stop_sequence" in stu_cfg:
                    stu.stop_sequence = stu_cfg["stop_sequence"]
                if "arrival_delay" in stu_cfg:
                    stu.arrival.delay = stu_cfg["arrival_delay"]
                if "departure_delay" in stu_cfg:
                    stu.departure.delay = stu_cfg["departure_delay"]

        return feed

    return _build
