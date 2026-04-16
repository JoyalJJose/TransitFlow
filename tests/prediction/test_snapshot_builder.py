# *** TEST FILE - SAFE TO DELETE ***
"""Unit tests for SnapshotBuilder with a fully mocked ConnectionPool.

Runs without Docker. These tests complement the Docker-backed
integration tests in tests/integration/test_system_integration.py.
"""

import os
import sys
import datetime as _dt
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
BACKEND_DIR = os.path.join(SRC_DIR, "Backend")

for p in (SRC_DIR, BACKEND_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from PredictionEngine import SnapshotBuilder
from PredictionEngine.snapshot import StopState, VehicleSnapshot
from PredictionEngine import snapshot_builder as sb_mod


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeCursor:
    """Cursor that returns queued rows per execute() call, in FIFO order."""

    def __init__(self, responses):
        self._responses = list(responses)
        self._last_rows = []
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if self._responses:
            self._last_rows = self._responses.pop(0)
        else:
            self._last_rows = []

    def fetchall(self):
        return self._last_rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakePool:
    """Pool whose ``connection()`` context yields a connection whose
    ``cursor()`` returns a single ``FakeCursor`` primed with responses.
    """

    def __init__(self, responses):
        self.cursor = FakeCursor(responses)

    @contextmanager
    def connection(self):
        conn = MagicMock()
        conn.cursor.return_value = self.cursor
        yield conn


# ---------------------------------------------------------------------------
# build() ------------------------------------------------------------------
# ---------------------------------------------------------------------------

class TestBuild:

    def test_returns_none_when_no_stops(self):
        pool = FakePool([[]])  # _query_stops -> empty
        builder = SnapshotBuilder(pool)
        result = builder.build("unknown_route", 0)
        assert result is None

    def test_stops_ordered_by_sequence(self):
        pool = FakePool([
            [("s1", 1), ("s2", 2), ("s3", 3)],  # _query_stops
            [],                                  # _query_crowd_counts
            [],                                  # _query_vehicles
            [],                                  # _compute_crowd_shares (ETA)
        ])
        builder = SnapshotBuilder(pool)
        snap = builder.build("r1", 0)

        assert snap is not None
        assert snap.route_id == "r1"
        assert snap.direction_id == 0
        assert [s.sequence for s in snap.stops] == [1, 2, 3]
        assert [s.stop_id for s in snap.stops] == ["s1", "s2", "s3"]

    def test_crowd_counts_populated_by_stop_id(self):
        pool = FakePool([
            [("s1", 1), ("s2", 2), ("s3", 3)],
            [("s1", 7), ("s3", 4)],  # s2 has no data
            [],
            [],
        ])
        builder = SnapshotBuilder(pool)
        snap = builder.build("r1", 0)

        by_id = {s.stop_id: s.people_waiting for s in snap.stops}
        assert by_id["s1"] == 7
        assert by_id["s2"] is None
        assert by_id["s3"] == 4

    def test_stops_without_data_get_none(self):
        pool = FakePool([
            [("s1", 1), ("s2", 2)],
            [],  # no crowd rows at all
            [],
            [],
        ])
        builder = SnapshotBuilder(pool)
        snap = builder.build("r1", 0)
        assert all(s.people_waiting is None for s in snap.stops)

    def test_vehicles_mapped_from_gtfs_rt_rows(self):
        pool = FakePool([
            [("s1", 1), ("s2", 2)],
            [],
            [  # _query_vehicles returns (trip_id, route_id, current_stop_sequence)
                ("trip-A", "r1", 1),
                ("trip-B", "r1", 2),
            ],
            [],
        ])
        builder = SnapshotBuilder(pool, default_capacity=80)
        snap = builder.build("r1", 0)

        assert len(snap.vehicles) == 2
        assert snap.vehicles[0].vehicle_id == "trip-A"
        assert snap.vehicles[0].capacity == 80
        assert snap.vehicles[0].current_stop_sequence == 1
        assert snap.vehicles[1].vehicle_id == "trip-B"

    def test_default_capacity_is_applied(self):
        pool = FakePool([
            [("s1", 1)],
            [],
            [("trip-A", "r1", 1)],
            [],
        ])
        builder = SnapshotBuilder(pool, default_capacity=123)
        snap = builder.build("r1", 0)
        assert snap.vehicles[0].capacity == 123

    def test_apply_share_none_crowd_stays_none(self):
        assert SnapshotBuilder._apply_share(None, 0.5) is None

    def test_apply_share_rounds_to_int(self):
        assert SnapshotBuilder._apply_share(10, 0.5) == 5
        assert SnapshotBuilder._apply_share(10, 0.25) == 2  # round-half-even


# ---------------------------------------------------------------------------
# Crowd split call-site ----------------------------------------------------
# ---------------------------------------------------------------------------

class TestCrowdSplit:

    def test_single_route_stop_keeps_full_count(self, monkeypatch):
        # Only one route arriving at the stop -> share must be 1.0
        monkeypatch.setattr(sb_mod, "_seconds_from_midnight", lambda: 0)
        pool = FakePool([
            [("s1", 1)],
            [("s1", 20)],
            [],
            [("s1", "r1", 0, 180)],  # only our route in soonest_per_route
        ])
        builder = SnapshotBuilder(pool)
        snap = builder.build("r1", 0)
        assert snap.stops[0].people_waiting == 20

    def test_two_routes_split_proportional(self, monkeypatch):
        # Our route arrives in 180 s, competitor in 480 s. Share ~= 0.727.
        monkeypatch.setattr(sb_mod, "_seconds_from_midnight", lambda: 0)
        pool = FakePool([
            [("s1", 1)],
            [("s1", 20)],
            [],
            [
                ("s1", "r1", 0, 180),   # ours
                ("s1", "r2", 0, 480),   # competitor
            ],
        ])
        builder = SnapshotBuilder(pool)
        snap = builder.build("r1", 0)

        # round(20 * 480/(180+480)) = round(14.545) = 15
        assert snap.stops[0].people_waiting == 15

    def test_expired_eta_dropped(self, monkeypatch):
        # Our "ETA" is already in the past (abs_arrival < now) -> dropped,
        # leaving no target entry -> share defaults to 1.0.
        monkeypatch.setattr(sb_mod, "_seconds_from_midnight", lambda: 500)
        pool = FakePool([
            [("s1", 1)],
            [("s1", 10)],
            [],
            [
                ("s1", "r1", 0, 100),   # negative ETA => dropped
                ("s1", "r2", 0, 800),   # positive ETA for competitor
            ],
        ])
        builder = SnapshotBuilder(pool)
        snap = builder.build("r1", 0)
        assert snap.stops[0].people_waiting == 10


# ---------------------------------------------------------------------------
# _seconds_from_midnight ---------------------------------------------------
# ---------------------------------------------------------------------------

class TestSecondsFromMidnight:

    def test_uses_dublin_timezone(self, monkeypatch):
        captured: dict = {}

        class _FakeDT(_dt.datetime):
            @classmethod
            def now(cls, tz=None):
                captured["tz"] = tz
                # 07:30:45 local
                return _dt.datetime(2026, 4, 16, 7, 30, 45, tzinfo=tz)

        monkeypatch.setattr(sb_mod, "datetime", _FakeDT)

        result = sb_mod._seconds_from_midnight()

        assert captured["tz"] is not None
        assert str(captured["tz"]) == "Europe/Dublin"
        assert result == 7 * 3600 + 30 * 60 + 45
