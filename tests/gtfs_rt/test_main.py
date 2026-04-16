# *** TEST FILE - SAFE TO DELETE ***
"""Unit tests for the GTFS-RT fetcher entry point.

Covers the helper functions ``_load_route_filter`` and ``_fetch_cycle``.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from Backend.GTFS_RT import main as gtfs_main
from Backend.GTFS_RT import config as gtfs_config


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _Cursor:
    def __init__(self, rows):
        self._rows = rows
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchall(self):
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Pool:
    def __init__(self, rows=(), raise_on_cursor=False):
        self._rows = rows
        self._raise = raise_on_cursor

    @contextmanager
    def connection(self):
        if self._raise:
            raise RuntimeError("pool down")
        conn = MagicMock()
        conn.cursor.return_value = _Cursor(list(self._rows))
        yield conn


# ---------------------------------------------------------------------------
# _load_route_filter --------------------------------------------------------
# ---------------------------------------------------------------------------

class TestLoadRouteFilter:

    def test_returns_none_when_agency_filter_empty(self, monkeypatch):
        monkeypatch.setattr(gtfs_config, "GTFSR_AGENCY_FILTER", "")
        result = gtfs_main._load_route_filter(_Pool())
        assert result is None

    def test_returns_route_ids_for_agency(self, monkeypatch):
        monkeypatch.setattr(gtfs_config, "GTFSR_AGENCY_FILTER", "7778019")
        pool = _Pool(rows=[("r1",), ("r2",), ("r3",)])
        result = gtfs_main._load_route_filter(pool)
        assert result == {"r1", "r2", "r3"}

    def test_empty_routes_table_degrades_gracefully(self, monkeypatch):
        monkeypatch.setattr(gtfs_config, "GTFSR_AGENCY_FILTER", "7778019")
        pool = _Pool(rows=[])
        result = gtfs_main._load_route_filter(pool)
        assert result is None

    def test_db_error_returns_none(self, monkeypatch):
        monkeypatch.setattr(gtfs_config, "GTFSR_AGENCY_FILTER", "7778019")
        result = gtfs_main._load_route_filter(_Pool(raise_on_cursor=True))
        assert result is None


# ---------------------------------------------------------------------------
# _fetch_cycle --------------------------------------------------------------
# ---------------------------------------------------------------------------

class TestFetchCycle:

    def test_happy_path_writes_and_purges(self, monkeypatch):
        monkeypatch.setattr(gtfs_config, "GTFSR_RETAIN_FETCHES", 42)
        fetcher = MagicMock()
        fetcher.fetch_feed.return_value = object()
        fetcher.parse_trip_updates.return_value = [{"x": 1}, {"x": 2}]
        writer = MagicMock()

        count = gtfs_main._fetch_cycle(fetcher, writer, route_filter={"r1"})

        assert count == 2
        fetcher.parse_trip_updates.assert_called_once()
        args, kwargs = fetcher.parse_trip_updates.call_args
        assert kwargs["route_ids"] == {"r1"}
        writer.write_gtfs_trip_updates.assert_called_once_with([{"x": 1}, {"x": 2}])
        writer.purge_old_trip_updates.assert_called_once_with(retain=42)

    def test_returns_zero_when_feed_is_none(self):
        fetcher = MagicMock()
        fetcher.fetch_feed.return_value = None
        writer = MagicMock()

        count = gtfs_main._fetch_cycle(fetcher, writer, None)

        assert count == 0
        writer.write_gtfs_trip_updates.assert_not_called()
        writer.purge_old_trip_updates.assert_not_called()

    def test_empty_updates_still_purges(self):
        fetcher = MagicMock()
        fetcher.fetch_feed.return_value = object()
        fetcher.parse_trip_updates.return_value = []
        writer = MagicMock()

        count = gtfs_main._fetch_cycle(fetcher, writer, None)

        assert count == 0
        writer.write_gtfs_trip_updates.assert_called_once_with([])
        writer.purge_old_trip_updates.assert_called_once()
