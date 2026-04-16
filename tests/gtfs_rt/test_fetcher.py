# *** TEST FILE - SAFE TO DELETE ***
"""Unit tests for GTFSRealtimeFetcher.

No live HTTP calls.  ``requests.get`` is patched and a real protobuf
``FeedMessage`` is serialised into the mock response content.
"""

from unittest.mock import MagicMock, patch

import pytest
import requests

from Backend.GTFS_RT.fetcher import GTFSRealtimeFetcher
from Backend.GTFS_RT import fetcher as fetcher_mod


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# fetch_feed() -------------------------------------------------------------
# ---------------------------------------------------------------------------

class TestFetchFeed:

    def test_successful_fetch_parses_protobuf(self, make_feed):
        feed = make_feed([{"id": "e1", "trip_id": "t1", "route_id": "39A"}])
        mock_resp = MagicMock()
        mock_resp.content = feed.SerializeToString()
        mock_resp.raise_for_status = MagicMock()

        f = GTFSRealtimeFetcher(
            api_url="http://fake", api_key="k", fmt="pb", timeout=5,
        )
        with patch.object(fetcher_mod.requests, "get", return_value=mock_resp) as mg:
            result = f.fetch_feed()

        assert result is not None
        assert len(result.entity) == 1
        assert result.entity[0].trip_update.trip.route_id == "39A"
        mg.assert_called_once()
        _, kwargs = mg.call_args
        assert kwargs["headers"] == {"x-api-key": "k"}
        assert kwargs["params"] == {"format": "pb"}
        assert kwargs["timeout"] == 5

    def test_http_error_returns_none(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("500")

        f = GTFSRealtimeFetcher(api_url="http://fake", api_key="k")
        with patch.object(fetcher_mod.requests, "get", return_value=mock_resp):
            assert f.fetch_feed() is None

    def test_connection_error_returns_none(self):
        f = GTFSRealtimeFetcher(api_url="http://fake", api_key="k")
        with patch.object(
            fetcher_mod.requests, "get",
            side_effect=requests.ConnectionError("boom"),
        ):
            assert f.fetch_feed() is None

    def test_parse_error_returns_none(self):
        mock_resp = MagicMock()
        mock_resp.content = b"\x00\x01not_a_protobuf\xff"
        mock_resp.raise_for_status = MagicMock()

        f = GTFSRealtimeFetcher(api_url="http://fake", api_key="k")
        with patch.object(fetcher_mod.requests, "get", return_value=mock_resp):
            assert f.fetch_feed() is None

    def test_rate_limit_guard_waits_on_rapid_recall(self, make_feed):
        """Second call within 60 s must sleep the remaining time."""
        feed = make_feed([])
        mock_resp = MagicMock()
        mock_resp.content = feed.SerializeToString()
        mock_resp.raise_for_status = MagicMock()

        f = GTFSRealtimeFetcher(api_url="http://fake", api_key="k")

        # fetch_feed() calls monotonic() twice per call (guard check + record).
        # Call 1: guard=1000 (elapsed=1000 but last_request_at=0 -> skip), record=1010
        # Call 2: guard=1015 (elapsed=5 -> wait 55 s), record=1075
        monotonic_values = iter([1000.0, 1010.0, 1015.0, 1075.0])
        slept: list[float] = []

        with patch.object(
            fetcher_mod._time, "monotonic",
            side_effect=lambda: next(monotonic_values),
        ), patch.object(
            fetcher_mod._time, "sleep", side_effect=lambda s: slept.append(s),
        ), patch.object(
            fetcher_mod.requests, "get", return_value=mock_resp,
        ):
            f.fetch_feed()
            f.fetch_feed()

        # Second call should have slept ~55 s (60 - 5)
        assert len(slept) == 1
        assert 54.0 <= slept[0] <= 56.0

    def test_first_call_does_not_rate_limit(self, make_feed):
        """Rate-limit guard should not trigger on the very first call."""
        feed = make_feed([])
        mock_resp = MagicMock()
        mock_resp.content = feed.SerializeToString()
        mock_resp.raise_for_status = MagicMock()

        f = GTFSRealtimeFetcher(api_url="http://fake", api_key="k")
        slept: list[float] = []

        with patch.object(
            fetcher_mod._time, "sleep", side_effect=lambda s: slept.append(s),
        ), patch.object(
            fetcher_mod.requests, "get", return_value=mock_resp,
        ):
            f.fetch_feed()

        assert slept == []


# ---------------------------------------------------------------------------
# parse_trip_updates() -----------------------------------------------------
# ---------------------------------------------------------------------------

class TestParseTripUpdates:

    def test_produces_one_row_per_stop_time_update(self, make_feed):
        feed = make_feed([
            {
                "id": "e1", "trip_id": "t1", "route_id": "r1",
                "direction_id": 0, "vehicle_id": "v1",
                "stop_time_updates": [
                    {"stop_id": "s1", "stop_sequence": 1,
                     "arrival_delay": 10, "departure_delay": 20},
                    {"stop_id": "s2", "stop_sequence": 2,
                     "arrival_delay": 30, "departure_delay": 40},
                ],
            },
        ])
        rows = GTFSRealtimeFetcher.parse_trip_updates(feed)
        assert len(rows) == 2

        r1, r2 = rows
        assert r1["trip_id"] == "t1"
        assert r1["route_id"] == "r1"
        assert r1["direction_id"] == 0
        assert r1["vehicle_id"] == "v1"
        assert r1["stop_id"] == "s1"
        assert r1["stop_sequence"] == 1
        assert r1["arrival_delay"] == 10
        assert r1["departure_delay"] == 20
        assert r2["stop_id"] == "s2"
        assert r2["arrival_delay"] == 30

    def test_filters_by_route_ids(self, make_feed):
        feed = make_feed([
            {"id": "e1", "trip_id": "t1", "route_id": "kept",
             "stop_time_updates": [{"stop_id": "s1", "stop_sequence": 1}]},
            {"id": "e2", "trip_id": "t2", "route_id": "dropped",
             "stop_time_updates": [{"stop_id": "s2", "stop_sequence": 1}]},
        ])
        rows = GTFSRealtimeFetcher.parse_trip_updates(feed, route_ids={"kept"})
        assert len(rows) == 1
        assert rows[0]["route_id"] == "kept"

    def test_empty_route_ids_keeps_nothing(self, make_feed):
        feed = make_feed([
            {"id": "e1", "trip_id": "t1", "route_id": "r1",
             "stop_time_updates": [{"stop_id": "s1", "stop_sequence": 1}]},
        ])
        rows = GTFSRealtimeFetcher.parse_trip_updates(feed, route_ids=set())
        assert rows == []

    def test_missing_arrival_departure_gives_none(self, make_feed):
        feed = make_feed([
            {"id": "e1", "trip_id": "t1", "route_id": "r1",
             "stop_time_updates": [
                 {"stop_id": "s1", "stop_sequence": 1},  # no delays
             ]},
        ])
        rows = GTFSRealtimeFetcher.parse_trip_updates(feed)
        assert rows[0]["arrival_delay"] is None
        assert rows[0]["departure_delay"] is None

    def test_skips_entities_without_trip_update(self, make_feed):
        from google.transit import gtfs_realtime_pb2

        feed = gtfs_realtime_pb2.FeedMessage()
        feed.header.gtfs_realtime_version = "2.0"
        feed.header.timestamp = 1_700_000_000

        e = feed.entity.add()
        e.id = "alert-only"
        e.alert.header_text.translation.add().text = "Delays"

        rows = GTFSRealtimeFetcher.parse_trip_updates(feed)
        assert rows == []

    def test_time_field_is_feed_timestamp_utc(self, make_feed):
        import datetime as _dt

        feed = make_feed(
            [{"id": "e1", "trip_id": "t1", "route_id": "r1",
              "stop_time_updates": [{"stop_id": "s1", "stop_sequence": 1}]}],
            timestamp=1_700_000_000,
        )
        rows = GTFSRealtimeFetcher.parse_trip_updates(feed)
        assert rows[0]["time"] == _dt.datetime.fromtimestamp(
            1_700_000_000, tz=_dt.timezone.utc,
        )

    def test_raw_payload_preserved_as_dict(self, make_feed):
        feed = make_feed([
            {"id": "e1", "trip_id": "t1", "route_id": "r1",
             "stop_time_updates": [{"stop_id": "s1", "stop_sequence": 1}]},
        ])
        rows = GTFSRealtimeFetcher.parse_trip_updates(feed)
        raw = rows[0]["raw"]
        assert isinstance(raw, dict)
        assert "tripUpdate" in raw
