"""SQL queries that assemble the full dashboard payload from TimescaleDB.

Every function takes a :class:`ConnectionPool` and returns plain dicts/lists
matching the shape the React dashboard expects.
"""

from __future__ import annotations

import logging
from typing import Any

logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rows(cur) -> list[dict]:
    """Convert cursor results to a list of dicts keyed by column name."""
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _hour_label(dt) -> str:
    """Format a datetime/timestamp as 'HH:00' for the frontend's shortTime()."""
    try:
        return f"{dt.hour:02d}:00"
    except AttributeError:
        return str(dt)


# ---------------------------------------------------------------------------
# Individual query functions
# ---------------------------------------------------------------------------

def _query_routes(cur) -> list[dict]:
    cur.execute("""
        SELECT r.route_id,
               r.route_short_name,
               r.route_long_name,
               r.transport_type,
               COALESCE(
                   array_agg(DISTINCT rs.stop_id) FILTER (WHERE rs.stop_id IS NOT NULL),
                   '{}'
               ) AS stop_ids
        FROM routes r
        LEFT JOIN route_stops rs ON rs.route_id = r.route_id
        GROUP BY r.route_id
        ORDER BY r.transport_type, r.route_short_name
    """)
    out = []
    for row in _rows(cur):
        name = row["route_short_name"] or ""
        t = row["transport_type"]
        if t == "luas":
            display = f"LUAS {name} Line"
        else:
            display = f"Route {name}"
        out.append({
            "id": row["route_id"],
            "name": display,
            "type": t,
            "stopIds": list(row["stop_ids"]) if row["stop_ids"] else [],
        })
    return out


def _query_stops(cur) -> list[dict]:
    cur.execute("""
        SELECT stop_id, stop_name, stop_lat, stop_long, transport_type
        FROM stops
        ORDER BY stop_name
    """)
    return [
        {"id": r["stop_id"], "name": r["stop_name"],
         "lat": r["stop_lat"], "lng": r["stop_long"],
         "type": r["transport_type"]}
        for r in _rows(cur)
    ]


def _query_stop_wait_counts(cur) -> list[dict]:
    cur.execute("SELECT stop_id, count FROM current_counts")
    return [{"stopId": r["stop_id"], "count": r["count"]} for r in _rows(cur)]


def _lerp(a: float, b: float, t: float) -> float:
    """Linear interpolation between *a* and *b* at fraction *t*."""
    return a + (b - a) * t


def _query_vehicles(cur) -> list[dict]:
    cur.execute("""
        SELECT DISTINCT ON (v.vehicle_id)
               v.vehicle_id,
               v.route_id,
               v.capacity,
               v.passenger_count,
               v.occupancy_percent,
               v.state,
               r.route_short_name,
               r.transport_type,
               s_cur.stop_name  AS current_stop_name,
               s_cur.stop_lat   AS cur_lat,
               s_cur.stop_long  AS cur_lng,
               s_next.stop_lat  AS next_lat,
               s_next.stop_long AS next_lng,
               s_prev.stop_lat  AS prev_lat,
               s_prev.stop_long AS prev_lng
        FROM vehicles v
        JOIN routes r       ON r.route_id  = v.route_id
        JOIN stops  s_cur   ON s_cur.stop_id = v.current_stop_id
        JOIN route_stops rs ON rs.route_id = v.route_id
                           AND rs.stop_id  = v.current_stop_id
        LEFT JOIN route_stops rs_next ON rs_next.route_id    = v.route_id
                                     AND rs_next.direction_id = rs.direction_id
                                     AND rs_next.stop_sequence = rs.stop_sequence + 1
        LEFT JOIN stops s_next ON s_next.stop_id = rs_next.stop_id
        LEFT JOIN route_stops rs_prev ON rs_prev.route_id    = v.route_id
                                     AND rs_prev.direction_id = rs.direction_id
                                     AND rs_prev.stop_sequence = rs.stop_sequence - 1
        LEFT JOIN stops s_prev ON s_prev.stop_id = rs_prev.stop_id
        WHERE v.is_active = true
          AND v.current_stop_id IS NOT NULL
        ORDER BY v.vehicle_id, rs.direction_id ASC
    """)
    out = []
    for r in _rows(cur):
        cur_lat = r["cur_lat"]
        cur_lng = r["cur_lng"]
        state = r["state"] or ""

        if state == "DEPARTING" and r["next_lat"] is not None:
            lat = _lerp(cur_lat, r["next_lat"], 0.25)
            lng = _lerp(cur_lng, r["next_lng"], 0.25)
        elif state == "ARRIVING" and r["prev_lat"] is not None:
            lat = _lerp(r["prev_lat"], cur_lat, 0.75)
            lng = _lerp(r["prev_lng"], cur_lng, 0.75)
        else:
            lat = cur_lat
            lng = cur_lng

        t = r["transport_type"]
        name = r["route_short_name"] or ""
        display = f"LUAS {name} Line" if t == "luas" else f"Route {name}"

        out.append({
            "id": r["vehicle_id"],
            "routeId": r["route_id"],
            "routeName": display,
            "type": t,
            "currentOccupancyPercent": round(r["occupancy_percent"] or 0),
            "capacity": r["capacity"],
            "passengerCount": r["passenger_count"],
            "state": state,
            "lat": round(lat, 6),
            "lng": round(lng, 6),
            "currentStopName": r["current_stop_name"],
        })
    return out


def _query_crowding_hotspots(cur) -> list[dict]:
    cur.execute("""
        SELECT cc.stop_id,
               s.stop_name,
               cc.count,
               cc.previous_count
        FROM current_counts cc
        JOIN stops s ON s.stop_id = cc.stop_id
        ORDER BY cc.count DESC
        LIMIT 10
    """)
    out = []
    for r in _rows(cur):
        prev = r["previous_count"]
        count = r["count"]
        if prev is None:
            delta = 0
            trend = "stable"
        else:
            delta = count - prev
            trend = "rising" if delta > 0 else ("falling" if delta < 0 else "stable")
        out.append({
            "stopId": r["stop_id"],
            "stopName": r["stop_name"],
            "count": count,
            "trend": trend,
            "delta": delta,
        })
    return out


def _query_route_health(cur) -> list[dict]:
    cur.execute("""
        WITH active_vehicles AS (
            SELECT route_id, COUNT(*) AS cnt
            FROM vehicles
            WHERE is_active = true
            GROUP BY route_id
        ),
        latest_delays AS (
            SELECT tu.route_id,
                   AVG(tu.arrival_delay) AS avg_delay
            FROM gtfs_rt_trip_updates tu
            WHERE tu.time > NOW() - INTERVAL '10 minutes'
              AND tu.arrival_delay IS NOT NULL
            GROUP BY tu.route_id
        )
        SELECT r.route_id,
               r.route_short_name,
               r.transport_type,
               r.metadata,
               COALESCE(av.cnt, 0)         AS active_vehicles,
               COALESCE(ld.avg_delay, 0)   AS avg_delay_s
        FROM routes r
        LEFT JOIN active_vehicles av ON av.route_id = r.route_id
        LEFT JOIN latest_delays   ld ON ld.route_id = r.route_id
        ORDER BY r.transport_type, r.route_short_name
    """)
    out = []
    for r in _rows(cur):
        delay_s = r["avg_delay_s"] or 0
        if delay_s >= 300:
            status = "disrupted"
        elif delay_s >= 120:
            status = "delayed"
        else:
            status = "on-time"

        meta = r["metadata"] if isinstance(r["metadata"], dict) else {}
        t = r["transport_type"]
        name = r["route_short_name"] or ""
        display = f"LUAS {name} Line" if t == "luas" else f"Route {name}"

        out.append({
            "routeId": r["route_id"],
            "routeName": display,
            "type": t,
            "status": status,
            "delayMin": round(delay_s / 60, 1),
            "currentHeadway": meta.get("current_headway", 0),
            "scheduledHeadway": meta.get("scheduled_headway", 0),
            "activeVehicles": r["active_vehicles"],
        })
    return out


def _query_on_time_data(cur) -> dict[str, Any]:
    """On-time performance bucketed by hour for last 24 h.

    Returns ``{"all": [...], "luas": [...], "bus": [...]}``.
    """
    cur.execute("""
        SELECT time_bucket('1 hour', tu.time) AS bucket,
               r.transport_type,
               COUNT(*) AS total,
               COUNT(*) FILTER (WHERE ABS(COALESCE(tu.arrival_delay, 0)) < 300) AS on_time
        FROM gtfs_rt_trip_updates tu
        JOIN routes r ON r.route_id = tu.route_id
        WHERE tu.time > NOW() - INTERVAL '24 hours'
        GROUP BY bucket, r.transport_type
        ORDER BY bucket
    """)
    rows = _rows(cur)

    buckets_all: dict[str, dict] = {}
    buckets_type: dict[str, dict[str, dict]] = {"luas": {}, "bus": {}}

    for r in rows:
        label = _hour_label(r["bucket"])
        total = r["total"] or 1
        pct = round(r["on_time"] / total * 100, 1)
        t = r["transport_type"]

        if label not in buckets_all:
            buckets_all[label] = {"time": label, "onTimePercent": 0, "_total": 0, "_on": 0}
        buckets_all[label]["_total"] += total
        buckets_all[label]["_on"] += r["on_time"]

        if t in buckets_type:
            buckets_type[t][label] = {"time": label, "onTimePercent": pct}

    all_list = []
    for b in buckets_all.values():
        b["onTimePercent"] = round(b["_on"] / max(b["_total"], 1) * 100, 1)
        all_list.append({"time": b["time"], "onTimePercent": b["onTimePercent"]})

    return {
        "all": all_list,
        "luas": list(buckets_type["luas"].values()),
        "bus": list(buckets_type["bus"].values()),
    }


def _query_fleet_utilization(cur) -> dict[str, Any]:
    """Fleet utilisation bucketed by hour for the last 24 h.

    Returns ``{"all": [...], "luas": [...], "bus": [...]}``.
    """
    cur.execute("""
        SELECT time_bucket('1 hour', vt.time) AS bucket,
               r.transport_type,
               AVG(vt.occupancy_percent) AS avg_occ
        FROM vehicle_telemetry vt
        JOIN vehicles v ON v.vehicle_id = vt.vehicle_id
        JOIN routes   r ON r.route_id   = v.route_id
        WHERE vt.time > NOW() - INTERVAL '24 hours'
        GROUP BY bucket, r.transport_type
        ORDER BY bucket
    """)
    rows = _rows(cur)

    buckets_all: dict[str, dict] = {}
    buckets_type: dict[str, dict[str, dict]] = {"luas": {}, "bus": {}}

    for r in rows:
        label = _hour_label(r["bucket"])
        avg = round(r["avg_occ"] or 0, 1)
        t = r["transport_type"]

        if label not in buckets_all:
            buckets_all[label] = {"time": label, "_sum": 0, "_n": 0}
        buckets_all[label]["_sum"] += (r["avg_occ"] or 0)
        buckets_all[label]["_n"] += 1

        if t in buckets_type:
            buckets_type[t][label] = {"time": label, "avgOccupancy": avg}

    all_list = []
    for b in buckets_all.values():
        avg = round(b["_sum"] / max(b["_n"], 1), 1)
        all_list.append({"time": b["time"], "avgOccupancy": avg})

    return {
        "all": all_list,
        "luas": list(buckets_type["luas"].values()),
        "bus": list(buckets_type["bus"].values()),
    }


def _query_resource_efficiency(cur) -> list[dict]:
    cur.execute("""
        SELECT r.route_short_name,
               r.transport_type,
               ROUND(AVG(v.occupancy_percent)::numeric) AS efficiency
        FROM vehicles v
        JOIN routes r ON r.route_id = v.route_id
        WHERE v.is_active = true
        GROUP BY r.route_id, r.route_short_name, r.transport_type
        ORDER BY r.transport_type, r.route_short_name
    """)
    out = []
    for r in _rows(cur):
        t = r["transport_type"]
        name = r["route_short_name"] or ""
        display = f"LUAS {name} Line" if t == "luas" else f"Route {name}"
        out.append({
            "route": display,
            "efficiency": int(r["efficiency"] or 0),
        })
    return out


def _query_alerts(cur) -> list[dict]:
    cur.execute("""
        SELECT id, severity, message
        FROM system_alerts
        WHERE resolved_at IS NULL
        ORDER BY created_at DESC
    """)
    return [
        {"id": r["id"], "severity": r["severity"], "message": r["message"]}
        for r in _rows(cur)
    ]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def build_dashboard_payload(pool) -> dict:
    """Query all tables and return the complete dashboard payload dict."""
    with pool.connection() as conn:
        with conn.cursor() as cur:
            routes = _query_routes(cur)
            stops = _query_stops(cur)
            stop_wait_counts = _query_stop_wait_counts(cur)
            vehicles = _query_vehicles(cur)
            crowding_hotspots = _query_crowding_hotspots(cur)
            route_health = _query_route_health(cur)
            on_time = _query_on_time_data(cur)
            fleet_util = _query_fleet_utilization(cur)
            resource_eff = _query_resource_efficiency(cur)
            alerts = _query_alerts(cur)

    return {
        "routes": routes,
        "stops": stops,
        "stopWaitCounts": stop_wait_counts,
        "vehicles": vehicles,
        "crowdingHotspots": crowding_hotspots,
        "routeHealth": route_health,
        "onTimeData": on_time["all"],
        "onTimeDataByType": {"luas": on_time["luas"], "bus": on_time["bus"]},
        "fleetUtilization": fleet_util["all"],
        "fleetUtilByType": {"luas": fleet_util["luas"], "bus": fleet_util["bus"]},
        "resourceEfficiency": resource_eff,
        "alerts": alerts,
    }
