# *** TEST FILE - SAFE TO DELETE ***
"""Unit tests for src/Backend/API/queries.py dashboard-payload helpers."""

import datetime as _dt

import pytest

from API import queries


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers --------------------------------------------------------------------
# ---------------------------------------------------------------------------

class TestHelpers:

    def test_rows_converts_cursor_to_dicts(self, make_pool):
        pool = make_pool([
            (("id", "name"), [(1, "alice"), (2, "bob")]),
        ])
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT ...")
                result = queries._rows(cur)

        assert result == [
            {"id": 1, "name": "alice"},
            {"id": 2, "name": "bob"},
        ]

    def test_hour_label_datetime(self):
        dt = _dt.datetime(2026, 4, 16, 7, 30, 0)
        assert queries._hour_label(dt) == "07:00"

    def test_hour_label_non_datetime_falls_back_to_str(self):
        assert queries._hour_label("foo") == "foo"

    def test_lerp(self):
        assert queries._lerp(0, 10, 0.5) == 5
        assert queries._lerp(0, 10, 0.0) == 0
        assert queries._lerp(0, 10, 1.0) == 10


# ---------------------------------------------------------------------------
# _query_routes, _query_stops, _query_stop_wait_counts ---------------------
# ---------------------------------------------------------------------------

class TestQueryRoutes:

    def test_bus_display_name(self, make_pool):
        pool = make_pool([
            (("route_id", "route_short_name", "route_long_name",
              "transport_type", "stop_ids"),
             [("r1", "39A", "Long", "bus", ["s1", "s2"])]),
        ])
        with pool.connection() as conn:
            with conn.cursor() as cur:
                result = queries._query_routes(cur)
        assert result == [{
            "id": "r1", "name": "Route 39A", "type": "bus",
            "stopIds": ["s1", "s2"],
        }]

    def test_luas_display_name(self, make_pool):
        pool = make_pool([
            (("route_id", "route_short_name", "route_long_name",
              "transport_type", "stop_ids"),
             [("r2", "Red", "Long", "luas", None)]),
        ])
        with pool.connection() as conn:
            with conn.cursor() as cur:
                result = queries._query_routes(cur)
        assert result[0]["name"] == "LUAS Red Line"
        assert result[0]["stopIds"] == []


class TestQueryStops:

    def test_maps_all_fields(self, make_pool):
        pool = make_pool([
            (("stop_id", "stop_name", "stop_lat", "stop_long", "transport_type",
              "device_id", "is_online", "pipeline_active", "last_seen"),
             [("s1", "Main St", 53.34, -6.26, "bus",
               "dev-1", True, True, _dt.datetime(2026, 4, 16, 10, 0))]),
        ])
        with pool.connection() as conn:
            with conn.cursor() as cur:
                result = queries._query_stops(cur)

        assert len(result) == 1
        r = result[0]
        assert r["id"] == "s1"
        assert r["name"] == "Main St"
        assert r["lat"] == 53.34
        assert r["lng"] == -6.26
        assert r["type"] == "bus"
        assert r["deviceId"] == "dev-1"
        assert r["isOnline"] is True
        assert r["pipelineActive"] is True
        assert r["lastSeen"].startswith("2026-04-16")

    def test_last_seen_none_passes_through(self, make_pool):
        pool = make_pool([
            (("stop_id", "stop_name", "stop_lat", "stop_long", "transport_type",
              "device_id", "is_online", "pipeline_active", "last_seen"),
             [("s1", "n", 0.0, 0.0, "bus", None, False, False, None)]),
        ])
        with pool.connection() as conn:
            with conn.cursor() as cur:
                result = queries._query_stops(cur)
        assert result[0]["lastSeen"] is None


class TestQueryStopWaitCounts:

    def test_returns_shape(self, make_pool):
        pool = make_pool([
            (("stop_id", "count"), [("s1", 7), ("s2", 3)]),
        ])
        with pool.connection() as conn:
            with conn.cursor() as cur:
                result = queries._query_stop_wait_counts(cur)
        assert result == [
            {"stopId": "s1", "count": 7},
            {"stopId": "s2", "count": 3},
        ]


# ---------------------------------------------------------------------------
# _query_crowding_hotspots --------------------------------------------------
# ---------------------------------------------------------------------------

class TestCrowdingHotspots:

    def test_trend_rising(self, make_pool):
        pool = make_pool([
            (("stop_id", "stop_name", "count", "previous_count"),
             [("s1", "Main", 10, 5)]),
        ])
        with pool.connection() as conn:
            with conn.cursor() as cur:
                out = queries._query_crowding_hotspots(cur)
        assert out[0]["trend"] == "rising"
        assert out[0]["delta"] == 5

    def test_trend_falling(self, make_pool):
        pool = make_pool([
            (("stop_id", "stop_name", "count", "previous_count"),
             [("s1", "Main", 5, 10)]),
        ])
        with pool.connection() as conn:
            with conn.cursor() as cur:
                out = queries._query_crowding_hotspots(cur)
        assert out[0]["trend"] == "falling"
        assert out[0]["delta"] == -5

    def test_trend_stable_with_none_prev(self, make_pool):
        pool = make_pool([
            (("stop_id", "stop_name", "count", "previous_count"),
             [("s1", "Main", 5, None)]),
        ])
        with pool.connection() as conn:
            with conn.cursor() as cur:
                out = queries._query_crowding_hotspots(cur)
        assert out[0]["trend"] == "stable"
        assert out[0]["delta"] == 0


# ---------------------------------------------------------------------------
# _query_route_health -------------------------------------------------------
# ---------------------------------------------------------------------------

class TestRouteHealth:

    def test_status_buckets(self, make_pool):
        pool = make_pool([
            (("route_id", "route_short_name", "transport_type", "metadata",
              "active_vehicles", "avg_delay_s"),
             [
                 ("r1", "39A", "bus", {}, 3, 30),     # on-time
                 ("r2", "46A", "bus", {}, 1, 180),    # delayed
                 ("r3", "16",  "bus", {}, 0, 500),    # disrupted
             ]),
        ])
        with pool.connection() as conn:
            with conn.cursor() as cur:
                out = queries._query_route_health(cur)
        assert out[0]["status"] == "on-time"
        assert out[1]["status"] == "delayed"
        assert out[2]["status"] == "disrupted"
        assert out[0]["delayMin"] == 0.5
        assert out[0]["activeVehicles"] == 3


# ---------------------------------------------------------------------------
# _query_vehicles -----------------------------------------------------------
# ---------------------------------------------------------------------------

class TestQueryVehicles:

    def test_stationary_uses_current_position(self, make_pool):
        pool = make_pool([
            (("vehicle_id", "route_id", "capacity", "passenger_count",
              "occupancy_percent", "state", "route_short_name", "transport_type",
              "current_stop_name", "cur_lat", "cur_lng", "next_lat", "next_lng",
              "prev_lat", "prev_lng"),
             [("v1", "r1", 80, 10, 12.5, "STATIONARY", "39A", "bus",
               "Main", 53.0, -6.0, None, None, None, None)]),
        ])
        with pool.connection() as conn:
            with conn.cursor() as cur:
                out = queries._query_vehicles(cur)
        v = out[0]
        assert v["id"] == "v1"
        assert v["lat"] == 53.0
        assert v["lng"] == -6.0
        assert v["routeName"] == "Route 39A"
        # Python's banker's rounding: round(12.5) -> 12, round(13.5) -> 14.
        assert v["currentOccupancyPercent"] in (12, 13)

    def test_departing_interpolates_toward_next(self, make_pool):
        pool = make_pool([
            (("vehicle_id", "route_id", "capacity", "passenger_count",
              "occupancy_percent", "state", "route_short_name", "transport_type",
              "current_stop_name", "cur_lat", "cur_lng", "next_lat", "next_lng",
              "prev_lat", "prev_lng"),
             [("v1", "r1", 80, 0, 0, "DEPARTING", "39A", "bus",
               "Main", 0.0, 0.0, 4.0, 8.0, None, None)]),
        ])
        with pool.connection() as conn:
            with conn.cursor() as cur:
                out = queries._query_vehicles(cur)
        # lerp 0.25 => lat=1.0, lng=2.0
        assert out[0]["lat"] == 1.0
        assert out[0]["lng"] == 2.0

    def test_arriving_interpolates_toward_current(self, make_pool):
        pool = make_pool([
            (("vehicle_id", "route_id", "capacity", "passenger_count",
              "occupancy_percent", "state", "route_short_name", "transport_type",
              "current_stop_name", "cur_lat", "cur_lng", "next_lat", "next_lng",
              "prev_lat", "prev_lng"),
             [("v1", "r1", 80, 0, 0, "ARRIVING", "39A", "bus",
               "Main", 4.0, 8.0, None, None, 0.0, 0.0)]),
        ])
        with pool.connection() as conn:
            with conn.cursor() as cur:
                out = queries._query_vehicles(cur)
        # lerp(prev, cur, 0.75) => 3.0, 6.0
        assert out[0]["lat"] == 3.0
        assert out[0]["lng"] == 6.0


# ---------------------------------------------------------------------------
# _query_alerts + build_dashboard_payload -----------------------------------
# ---------------------------------------------------------------------------

class TestAlerts:

    def test_query_alerts_shape(self, make_pool):
        pool = make_pool([
            (("id", "severity", "message"),
             [(1, "warning", "Bus delayed"), (2, "info", "Stop reopened")]),
        ])
        with pool.connection() as conn:
            with conn.cursor() as cur:
                out = queries._query_alerts(cur)
        assert out == [
            {"id": 1, "severity": "warning", "message": "Bus delayed"},
            {"id": 2, "severity": "info", "message": "Stop reopened"},
        ]


class TestBuildDashboardPayload:

    def test_empty_payload_has_all_top_level_keys(self, make_pool):
        # Ten empty result sets, one per sub-query.
        empty_desc = (("x",), [])
        pool = make_pool([empty_desc] * 10)

        payload = queries.build_dashboard_payload(pool)

        for key in [
            "routes", "stops", "stopWaitCounts", "vehicles",
            "crowdingHotspots", "routeHealth",
            "onTimeData", "onTimeDataByType",
            "fleetUtilization", "fleetUtilByType",
            "resourceEfficiency", "alerts",
        ]:
            assert key in payload


# ---------------------------------------------------------------------------
# On-demand query functions -------------------------------------------------
# ---------------------------------------------------------------------------

class TestOnDemandQueries:

    def test_query_stop_history(self, make_pool):
        pool = make_pool([
            (("time", "count", "zone"),
             [(_dt.datetime(2026, 4, 16, 10, 0), 5, "zone-a")]),
        ])
        result = queries.query_stop_history(pool, "s1", 24)
        assert result == [{
            "time": "2026-04-16 10:00:00", "count": 5, "zone": "zone-a",
        }]

    def test_query_vehicle_history_route_scoped(self, make_pool):
        pool = make_pool([
            (("bucket", "avg_occupancy"),
             [(_dt.datetime(2026, 4, 16, 10, 0), 42.456)]),
        ])
        result = queries.query_vehicle_history(pool, 24, "r1")
        assert len(result) == 1
        assert result[0]["avg_occupancy"] == 42.5

    def test_query_gtfs_rt_freshness_none_when_empty(self, make_pool):
        pool = make_pool([(("latest",), [(None,)])])
        result = queries.query_gtfs_rt_freshness(pool)
        assert result == {"latest": None}

    def test_query_gtfs_rt_freshness_with_timestamp(self, make_pool):
        ts = _dt.datetime(2026, 4, 16, 10, 0)
        pool = make_pool([(("latest",), [(ts,)])])
        result = queries.query_gtfs_rt_freshness(pool)
        assert result == {"latest": "2026-04-16 10:00:00"}
