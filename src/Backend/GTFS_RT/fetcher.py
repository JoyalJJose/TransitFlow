"""GTFS-Realtime feed fetcher for the NTA TripUpdates API.

Fetches protobuf-encoded FeedMessages from the NTA GTFS-R v2 endpoint,
parses TripUpdate entities, and returns them as flat dicts matching the
``gtfs_rt_trip_updates`` table schema.
"""

import datetime as _dt
import logging
import time as _time

import requests
from google.transit import gtfs_realtime_pb2

from . import config

logger = logging.getLogger(__name__)

_MIN_REQUEST_GAP = 60  # seconds -- NTA hard limit per API key


class GTFSRealtimeFetcher:
    """HTTP client + protobuf parser for the NTA GTFS-Realtime feed."""

    def __init__(
        self,
        api_url: str = config.GTFSR_API_URL,
        api_key: str = config.GTFSR_API_KEY,
        fmt: str = config.GTFSR_FORMAT,
        timeout: int = config.GTFSR_REQUEST_TIMEOUT,
    ):
        self._url = api_url
        self._api_key = api_key
        self._fmt = fmt
        self._timeout = timeout
        self._last_request_at: float = 0.0

    def fetch_feed(self) -> gtfs_realtime_pb2.FeedMessage | None:
        """GET the GTFS-R feed and parse the protobuf response.

        Enforces a minimum 60 s gap between HTTP requests regardless of how
        the caller schedules polls (NTA fair-usage policy).
        Returns the parsed ``FeedMessage`` or ``None`` on any failure.
        """
        elapsed = _time.monotonic() - self._last_request_at
        if self._last_request_at and elapsed < _MIN_REQUEST_GAP:
            wait = _MIN_REQUEST_GAP - elapsed
            logger.warning(
                "Rate-limit guard: waiting %.1fs before next API call", wait
            )
            _time.sleep(wait)

        params = {"format": self._fmt} if self._fmt else {}
        headers = {"x-api-key": self._api_key}

        self._last_request_at = _time.monotonic()
        try:
            resp = requests.get(
                self._url,
                headers=headers,
                params=params,
                timeout=self._timeout,
            )
            resp.raise_for_status()
        except requests.RequestException:
            logger.exception("Failed to fetch GTFS-R feed")
            return None

        feed = gtfs_realtime_pb2.FeedMessage()
        try:
            feed.ParseFromString(resp.content)
        except Exception:
            logger.exception("Failed to parse GTFS-R protobuf response")
            return None

        logger.debug(
            "Fetched GTFS-R feed: %d entities (timestamp %s)",
            len(feed.entity),
            _dt.datetime.fromtimestamp(
                feed.header.timestamp, tz=_dt.timezone.utc
            ).isoformat(),
        )
        return feed

    @staticmethod
    def parse_trip_updates(
        feed: gtfs_realtime_pb2.FeedMessage,
        route_ids: set[str] | None = None,
    ) -> list[dict]:
        """Extract TripUpdate entities into flat dicts for DB insertion.

        Each ``StopTimeUpdate`` within a ``TripUpdate`` produces one dict
        (one row in ``gtfs_rt_trip_updates``).  The full entity is preserved
        in the ``raw`` JSONB column via protobuf ``MessageToDict``.

        If *route_ids* is provided, only entities whose ``route_id`` is in the
        set are kept (used to restrict to Dublin Bus only).
        """
        from google.protobuf.json_format import MessageToDict

        feed_ts = _dt.datetime.fromtimestamp(
            feed.header.timestamp, tz=_dt.timezone.utc
        )
        rows: list[dict] = []
        total_trip_updates = 0
        skipped = 0

        for entity in feed.entity:
            if not entity.HasField("trip_update"):
                continue

            total_trip_updates += 1
            tu = entity.trip_update
            trip = tu.trip

            if route_ids is not None and trip.route_id not in route_ids:
                skipped += 1
                continue

            vehicle_id = tu.vehicle.id if tu.HasField("vehicle") else None
            direction_id = (
                trip.direction_id if trip.HasField("direction_id") else None
            )
            raw = MessageToDict(entity)

            for stu in tu.stop_time_update:
                rows.append(
                    {
                        "time": feed_ts,
                        "trip_id": trip.trip_id,
                        "route_id": trip.route_id or None,
                        "direction_id": direction_id,
                        "vehicle_id": vehicle_id,
                        "stop_id": stu.stop_id or None,
                        "stop_sequence": stu.stop_sequence or None,
                        "arrival_delay": (
                            stu.arrival.delay
                            if stu.HasField("arrival")
                            else None
                        ),
                        "departure_delay": (
                            stu.departure.delay
                            if stu.HasField("departure")
                            else None
                        ),
                        "raw": raw,
                    }
                )

        logger.debug(
            "Parsed %d rows from %d TripUpdates (%d skipped by route filter)",
            len(rows),
            total_trip_updates,
            skipped,
        )
        return rows
