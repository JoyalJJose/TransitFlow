"""Build RouteSnapshot objects from database queries.

Bridges the gap between the persistence layer (TimescaleDB) and the
PredictionEngine's pure-computation interface.  Queries three tables:

1. ``route_stops`` -- ordered stop sequence for a route + direction
2. ``current_counts`` -- crowd counts at each stop (from edge devices)
3. ``gtfs_rt_trip_updates`` -- active vehicle positions (from GTFS-RT)

When a stop serves multiple routes, the raw crowd count is split
proportionally among routes using inverse-ETA weighting (closer bus
gets a larger share of the waiting passengers).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from .snapshot import RouteSnapshot, StopState, VehicleSnapshot

if TYPE_CHECKING:
    from Database.connection import ConnectionPool

logger = logging.getLogger(__name__)

_SCHEDULE_TZ = ZoneInfo("Europe/Dublin")


# ------------------------------------------------------------------
# Pure helper -- testable without DB
# ------------------------------------------------------------------

def proportional_split(
    etas: dict[tuple[str, int], int],
    target_route: str,
    target_direction: int,
    min_eta: int = 30,
) -> float:
    """Compute inverse-ETA share for *(target_route, target_direction)*.

    Parameters
    ----------
    etas:
        ``{(route_id, direction_id): relative_eta_seconds}`` for every
        competing route at a single stop.  All values must be positive.
    target_route / target_direction:
        The route whose share we want.
    min_eta:
        Floor value (seconds) to clamp ETAs before inverting.  Prevents
        a near-zero ETA from dominating the entire weight.

    Returns
    -------
    float between 0.0 and 1.0 (inclusive).  Returns 1.0 if the target
    is absent from *etas* (defensive fallback).
    """
    target_key = (target_route, target_direction)
    if target_key not in etas:
        return 1.0

    weights: dict[tuple[str, int], float] = {}
    for key, eta in etas.items():
        weights[key] = 1.0 / max(eta, min_eta)

    total = sum(weights.values())
    if total == 0:
        return 1.0

    return weights[target_key] / total


def _seconds_from_midnight() -> int:
    """Current wall-clock time as seconds since midnight (Europe/Dublin).

    GTFS schedule times are in local time, so we must match that
    timezone.  Using UTC would introduce a 1-hour offset during Irish
    Summer Time and flatten the proportional weights.
    """
    now = datetime.now(_SCHEDULE_TZ)
    return now.hour * 3600 + now.minute * 60 + now.second


# ------------------------------------------------------------------
# Main class
# ------------------------------------------------------------------

class SnapshotBuilder:
    """Construct a :class:`RouteSnapshot` from live database state.

    Parameters
    ----------
    pool:
        Any object whose ``.connection()`` method returns a context manager
        yielding a DB-API 2.0 connection (duck-typed; no hard import of
        ``ConnectionPool``).
    default_capacity:
        Assumed vehicle capacity when no per-vehicle data is available.
        80 is typical for a Dublin Bus double-decker.
    """

    def __init__(self, pool: ConnectionPool, default_capacity: int = 80) -> None:
        self._pool = pool
        self._default_capacity = default_capacity

    def build(self, route_id: str, direction_id: int) -> RouteSnapshot | None:
        """Query the DB and assemble a snapshot for *route_id* + *direction_id*.

        Returns ``None`` if the route has no stops in ``route_stops``
        (i.e. the GTFS data has not been seeded for this route).
        """
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                stops = self._query_stops(cur, route_id, direction_id)
                if not stops:
                    logger.warning(
                        "No route_stops found for route=%s dir=%s",
                        route_id,
                        direction_id,
                    )
                    return None

                stop_ids = [s.stop_id for s in stops]
                crowd = self._query_crowd_counts(cur, stop_ids)
                vehicles = self._query_vehicles(
                    cur, route_id, direction_id,
                )
                shares = self._compute_crowd_shares(
                    cur, route_id, direction_id, stop_ids,
                )

        stops_with_counts = tuple(
            StopState(
                stop_id=s.stop_id,
                sequence=s.sequence,
                people_waiting=self._apply_share(
                    crowd.get(s.stop_id), shares.get(s.stop_id, 1.0),
                ),
            )
            for s in stops
        )

        return RouteSnapshot(
            route_id=route_id,
            direction_id=direction_id,
            stops=stops_with_counts,
            vehicles=tuple(vehicles),
        )

    # ------------------------------------------------------------------
    # Private query helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_share(raw_count: int | None, share: float) -> int | None:
        if raw_count is None:
            return None
        return round(raw_count * share)

    @staticmethod
    def _query_stops(cur, route_id: str, direction_id: int) -> list[StopState]:
        cur.execute(
            """
            SELECT rs.stop_id, rs.stop_sequence
            FROM route_stops rs
            WHERE rs.route_id = %s AND rs.direction_id = %s
            ORDER BY rs.stop_sequence
            """,
            (route_id, direction_id),
        )
        return [
            StopState(stop_id=row[0], sequence=row[1], people_waiting=None)
            for row in cur.fetchall()
        ]

    @staticmethod
    def _query_crowd_counts(cur, stop_ids: list[str]) -> dict[str, int]:
        if not stop_ids:
            return {}
        cur.execute(
            """
            SELECT cc.stop_id, cc.count
            FROM current_counts cc
            WHERE cc.stop_id = ANY(%s)
            """,
            (stop_ids,),
        )
        return {row[0]: row[1] for row in cur.fetchall()}

    def _query_vehicles(
        self, cur, route_id: str, direction_id: int,
    ) -> list[VehicleSnapshot]:
        cur.execute(
            """
            SELECT DISTINCT ON (trip_id)
                trip_id, route_id, stop_sequence AS current_stop_sequence
            FROM gtfs_rt_trip_updates
            WHERE route_id = %s
              AND direction_id = %s
              AND trip_id IS NOT NULL AND trip_id != ''
            ORDER BY trip_id, time DESC, stop_sequence ASC
            """,
            (route_id, direction_id),
        )
        return [
            VehicleSnapshot(
                vehicle_id=row[0],
                route_id=row[1],
                capacity=self._default_capacity,
                current_stop_sequence=row[2],
            )
            for row in cur.fetchall()
        ]

    # ------------------------------------------------------------------
    # Proportional crowd splitting
    # ------------------------------------------------------------------

    _ETA_QUERY = """
        WITH latest_per_trip AS (
            SELECT DISTINCT ON (g.trip_id, g.stop_id)
                g.trip_id, g.stop_id, g.route_id, g.direction_id,
                g.arrival_delay, g.stop_sequence
            FROM gtfs_rt_trip_updates g
            WHERE g.stop_id = ANY(%s)
              AND g.trip_id IS NOT NULL AND g.trip_id != ''
              AND g.time > NOW() - INTERVAL '30 minutes'
            ORDER BY g.trip_id, g.stop_id, g.time DESC
        ),
        soonest_per_route AS (
            SELECT DISTINCT ON (l.stop_id, l.route_id, l.direction_id)
                l.stop_id,
                l.route_id,
                l.direction_id,
                st.arrival_seconds + COALESCE(l.arrival_delay, 0)
                    AS abs_arrival
            FROM latest_per_trip l
            JOIN stop_times st
                ON st.trip_id = l.trip_id
               AND st.stop_sequence = l.stop_sequence
            ORDER BY l.stop_id, l.route_id, l.direction_id,
                     abs_arrival ASC
        )
        SELECT stop_id, route_id, direction_id, abs_arrival
        FROM soonest_per_route
    """

    def _compute_crowd_shares(
        self,
        cur,
        route_id: str,
        direction_id: int,
        stop_ids: list[str],
    ) -> dict[str, float]:
        """Return ``{stop_id: fraction}`` -- this route's share of the
        crowd at each stop, based on inverse-ETA weighting against
        competing routes.
        """
        if not stop_ids:
            return {}

        cur.execute(self._ETA_QUERY, (stop_ids,))
        rows = cur.fetchall()

        # Group: stop_id -> {(route_id, direction_id): abs_arrival}
        raw: dict[str, dict[tuple[str, int], int]] = {}
        for stop_id, rid, did, abs_arr in rows:
            raw.setdefault(stop_id, {})[(rid, did)] = abs_arr

        now_secs = _seconds_from_midnight()
        shares: dict[str, float] = {}

        for stop_id in stop_ids:
            entries = raw.get(stop_id)
            if not entries:
                shares[stop_id] = 1.0
                continue

            relative_etas: dict[tuple[str, int], int] = {}
            for key, abs_arr in entries.items():
                eta = abs_arr - now_secs
                if eta > 43200:
                    eta -= 86400
                if eta <= 0:
                    continue
                relative_etas[key] = eta

            target = (route_id, direction_id)
            if not relative_etas or target not in relative_etas:
                shares[stop_id] = 1.0
                continue
            if len(relative_etas) == 1:
                shares[stop_id] = 1.0
                continue

            shares[stop_id] = proportional_split(
                relative_etas, route_id, direction_id,
            )

        return shares
