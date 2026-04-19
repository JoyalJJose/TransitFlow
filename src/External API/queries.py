"""Database queries for the External API.

One public function, :func:`query_stop_traffic_lights`, that gathers everything
needed for the single public endpoint. Kept deliberately small so the shape of
the returned dict mirrors the HTTP response exactly.
"""

from __future__ import annotations

from datetime import datetime, timezone

from traffic_light import occupancy_state, stop_state


def _route_display_name(short_name: str | None, transport_type: str | None) -> str:
    """Match the convention used by the dashboard API for consistency."""
    name = short_name or ""
    if transport_type == "luas":
        return f"LUAS {name} Line"
    return f"Route {name}"


def query_stop_traffic_lights(pool, stop_id: str) -> dict | None:
    """Return the traffic-light payload for ``stop_id``, or ``None`` if unknown.

    The returned dict is ready to be JSON-serialised by FastAPI.
    """
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT s.stop_id, s.stop_name, cc.count AS waiting_count
                FROM stops s
                LEFT JOIN current_counts cc ON cc.stop_id = s.stop_id
                WHERE s.stop_id = %s
                """,
                (stop_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            _, stop_name, waiting_count = row

            cur.execute(
                """
                WITH latest AS (
                    SELECT vehicle_id, MAX(time) AS t
                    FROM predictions
                    WHERE stop_id = %s
                    GROUP BY vehicle_id
                )
                SELECT p.vehicle_id,
                       p.route_id,
                       p.predicted_occupancy_pct,
                       r.route_short_name,
                       r.transport_type
                FROM predictions p
                JOIN latest l ON l.vehicle_id = p.vehicle_id AND l.t = p.time
                LEFT JOIN routes r ON r.route_id = p.route_id
                WHERE p.stop_id = %s
                ORDER BY p.predicted_occupancy_pct DESC NULLS LAST, p.vehicle_id
                """,
                (stop_id, stop_id),
            )
            vehicle_rows = cur.fetchall()

    vehicles = []
    for vehicle_id, route_id, occ_pct, short_name, transport_type in vehicle_rows:
        vehicles.append({
            "vehicle_id": vehicle_id,
            "route_id": route_id,
            "route_name": _route_display_name(short_name, transport_type),
            "occupancy_state": occupancy_state(occ_pct),
        })

    return {
        "stop_id": stop_id,
        "stop_name": stop_name,
        "stop_state": stop_state(waiting_count),
        "vehicles": vehicles,
        "as_of": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
