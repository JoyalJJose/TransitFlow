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
               COALESCE(sub.stop_ids, '{}') AS stop_ids
        FROM routes r
        LEFT JOIN LATERAL (
            SELECT array_agg(rs.stop_id ORDER BY rs.stop_sequence) AS stop_ids
            FROM route_stops rs
            WHERE rs.route_id = r.route_id AND rs.direction_id = 0
        ) sub ON true
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
        SELECT stop_id, stop_name, stop_lat, stop_long, transport_type,
               device_id, is_online, pipeline_active, last_seen
        FROM stops
        ORDER BY stop_name
    """)
    return [
        {"id": r["stop_id"], "name": r["stop_name"],
         "lat": r["stop_lat"], "lng": r["stop_long"],
         "type": r["transport_type"],
         "deviceId": r["device_id"], "isOnline": r["is_online"],
         "pipelineActive": r["pipeline_active"],
         "lastSeen": str(r["last_seen"]) if r["last_seen"] else None}
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

    Joins through ``stops`` rather than ``routes`` because GTFS-RT
    trip-update route IDs may differ from the static GTFS route IDs,
    while stop IDs are consistent across both feeds.
    """
    cur.execute("""
        SELECT time_bucket('1 hour', tu.time) AS bucket,
               s.transport_type,
               COUNT(*) AS total,
               COUNT(*) FILTER (WHERE ABS(COALESCE(tu.arrival_delay, 0)) < 300) AS on_time
        FROM gtfs_rt_trip_updates tu
        JOIN stops s ON s.stop_id = tu.stop_id
        WHERE tu.time > NOW() - INTERVAL '24 hours'
        GROUP BY bucket, s.transport_type
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
# On-demand query functions (for REST endpoints)
# ---------------------------------------------------------------------------

def query_stop_history(pool, stop_id: str, hours: int = 24) -> list[dict]:
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT time, count, zone
                FROM crowd_count
                WHERE stop_id = %s AND time > NOW() - make_interval(hours => %s)
                ORDER BY time
            """, (stop_id, hours))
            return [{"time": str(r["time"]), "count": r["count"], "zone": r["zone"]} for r in _rows(cur)]


def query_vehicle_history(pool, hours: int = 24, route_id: str | None = None) -> list[dict]:
    with pool.connection() as conn:
        with conn.cursor() as cur:
            if route_id:
                cur.execute("""
                    SELECT time_bucket('15 minutes', vt.time) AS bucket,
                           AVG(vt.occupancy_percent) AS avg_occupancy
                    FROM vehicle_telemetry vt
                    JOIN vehicles v ON v.vehicle_id = vt.vehicle_id
                    WHERE vt.time > NOW() - make_interval(hours => %s)
                      AND v.route_id = %s
                    GROUP BY bucket ORDER BY bucket
                """, (hours, route_id))
            else:
                cur.execute("""
                    SELECT time_bucket('15 minutes', vt.time) AS bucket,
                           AVG(vt.occupancy_percent) AS avg_occupancy
                    FROM vehicle_telemetry vt
                    WHERE vt.time > NOW() - make_interval(hours => %s)
                    GROUP BY bucket ORDER BY bucket
                """, (hours,))
            return [{"time": str(r["bucket"]), "avg_occupancy": round(r["avg_occupancy"] or 0, 1)} for r in _rows(cur)]


def query_predictions_latest(pool) -> dict:
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT ON (route_id, direction_id)
                       route_id, direction_id, time
                FROM predictions
                ORDER BY route_id, direction_id, time DESC
            """)
            route_dirs = _rows(cur)

            routes_out = []
            for rd in route_dirs:
                cur.execute("""
                    SELECT vehicle_id, stop_id, stop_sequence,
                           predicted_passengers, vehicle_capacity,
                           predicted_occupancy_pct, waiting_at_stop,
                           boarded, alighted, has_data, confidence
                    FROM predictions
                    WHERE route_id = %s AND direction_id = %s AND time = %s
                    ORDER BY vehicle_id, stop_sequence
                """, (rd["route_id"], rd["direction_id"], rd["time"]))
                rows = _rows(cur)

                vehicles = {}
                stop_waiting: dict[str, int] = {}
                stop_boarded: dict[str, int] = {}
                for r in rows:
                    vid = r["vehicle_id"]
                    if vid not in vehicles:
                        vehicles[vid] = {
                            "vehicle_id": vid,
                            "route_id": rd["route_id"],
                            "vehicle_capacity": r["vehicle_capacity"],
                            "confidence": r["confidence"],
                            "peak_occupancy_pct": 0,
                            "stops": [],
                        }
                    vp = vehicles[vid]
                    occ = r["predicted_occupancy_pct"] or 0
                    if occ > vp["peak_occupancy_pct"]:
                        vp["peak_occupancy_pct"] = occ
                    vp["stops"].append({
                        "stop_id": r["stop_id"],
                        "stop_sequence": r["stop_sequence"],
                        "predicted_passengers": r["predicted_passengers"],
                        "boarded": r["boarded"],
                        "alighted": r["alighted"],
                        "waiting_at_stop": r["waiting_at_stop"],
                        "has_data": r["has_data"],
                    })

                    sid = r["stop_id"]
                    waiting = r["waiting_at_stop"] or 0
                    boarded = r["boarded"] or 0
                    if sid not in stop_waiting:
                        stop_waiting[sid] = waiting
                    stop_boarded[sid] = stop_boarded.get(sid, 0) + boarded

                stranded = {
                    sid: max(0, stop_waiting[sid] - stop_boarded.get(sid, 0))
                    for sid in stop_waiting
                    if stop_waiting[sid] - stop_boarded.get(sid, 0) > 0
                }

                routes_out.append({
                    "route_id": rd["route_id"],
                    "direction_id": rd["direction_id"],
                    "time": str(rd["time"]),
                    "vehicle_predictions": list(vehicles.values()),
                    "stranded_at_stops": stranded,
                })
            return {"routes": routes_out}


def query_predictions_for_route(pool, route_id: str, direction_id: int = 0) -> dict:
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT ON (1) time
                FROM predictions
                WHERE route_id = %s AND direction_id = %s
                ORDER BY 1 DESC LIMIT 1
            """, (route_id, direction_id))
            row = _rows(cur)
            if not row:
                return {"vehicle_predictions": [], "stops": [], "stranded_at_stops": {}}
            ts = row[0]["time"]

            cur.execute("""
                SELECT vehicle_id, stop_id, stop_sequence,
                       predicted_passengers, vehicle_capacity,
                       predicted_occupancy_pct, waiting_at_stop,
                       boarded, alighted, has_data, confidence
                FROM predictions
                WHERE route_id = %s AND direction_id = %s AND time = %s
                ORDER BY vehicle_id, stop_sequence
            """, (route_id, direction_id, ts))
            rows = _rows(cur)

            vehicles = {}
            stop_set = {}
            stop_waiting: dict[str, int] = {}
            stop_boarded: dict[str, int] = {}
            for r in rows:
                vid = r["vehicle_id"]
                if vid not in vehicles:
                    vehicles[vid] = {
                        "vehicle_id": vid,
                        "vehicle_capacity": r["vehicle_capacity"],
                        "confidence": r["confidence"],
                        "peak_occupancy_pct": 0,
                        "stops": [],
                    }
                vp = vehicles[vid]
                occ = r["predicted_occupancy_pct"] or 0
                if occ > vp["peak_occupancy_pct"]:
                    vp["peak_occupancy_pct"] = occ
                vp["stops"].append({
                    "stop_id": r["stop_id"],
                    "stop_sequence": r["stop_sequence"],
                    "predicted_passengers": r["predicted_passengers"],
                    "boarded": r["boarded"],
                    "alighted": r["alighted"],
                    "has_data": r["has_data"],
                })
                sid = r["stop_id"]
                if sid not in stop_set:
                    stop_set[sid] = {
                        "stop_id": sid,
                        "stop_sequence": r["stop_sequence"],
                        "people_waiting": r["waiting_at_stop"],
                    }
                waiting = r["waiting_at_stop"] or 0
                boarded = r["boarded"] or 0
                if sid not in stop_waiting:
                    stop_waiting[sid] = waiting
                stop_boarded[sid] = stop_boarded.get(sid, 0) + boarded

            stranded = {
                sid: max(0, stop_waiting[sid] - stop_boarded.get(sid, 0))
                for sid in stop_waiting
                if stop_waiting[sid] - stop_boarded.get(sid, 0) > 0
            }

            return {
                "vehicle_predictions": list(vehicles.values()),
                "stops": sorted(stop_set.values(), key=lambda s: s["stop_sequence"]),
                "stranded_at_stops": stranded,
            }


def query_scheduler_decisions(pool, limit: int = 50) -> list[dict]:
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, decided_at, decision_type, route_id, direction_id,
                       trigger_vehicle_id, trigger_stop_id,
                       predicted_passengers, predicted_occupancy_pct,
                       vehicle_capacity, total_stranded, threshold,
                       message, status, executed_at
                FROM scheduler_decisions
                ORDER BY decided_at DESC LIMIT %s
            """, (limit,))
            return [
                {**r, "decided_at": str(r["decided_at"]),
                 "executed_at": str(r["executed_at"]) if r["executed_at"] else None}
                for r in _rows(cur)
            ]


def query_delay_data(pool, route_id: str | None = None, hours: int = 24) -> list[dict]:
    with pool.connection() as conn:
        with conn.cursor() as cur:
            if route_id:
                # Filter by stops that belong to the selected route via
                # route_stops, because GTFS-RT trip-update route IDs may
                # differ from the static GTFS route IDs.
                cur.execute("""
                    SELECT tu.stop_id, s.stop_name,
                           EXTRACT(HOUR FROM tu.time)::int AS hour,
                           AVG(tu.arrival_delay) AS avg_delay
                    FROM gtfs_rt_trip_updates tu
                    JOIN stops s ON s.stop_id = tu.stop_id
                    WHERE tu.stop_id IN (
                              SELECT rs.stop_id FROM route_stops rs
                              WHERE rs.route_id = %s
                          )
                      AND tu.time > NOW() - make_interval(hours => %s)
                      AND tu.arrival_delay IS NOT NULL
                    GROUP BY tu.stop_id, s.stop_name, hour
                    ORDER BY tu.stop_id, hour
                """, (route_id, hours))
            else:
                cur.execute("""
                    SELECT tu.stop_id, s.stop_name,
                           AVG(tu.arrival_delay) AS avg_delay
                    FROM gtfs_rt_trip_updates tu
                    JOIN stops s ON s.stop_id = tu.stop_id
                    WHERE tu.time > NOW() - make_interval(hours => %s)
                      AND tu.arrival_delay IS NOT NULL
                    GROUP BY tu.stop_id, s.stop_name
                    ORDER BY avg_delay DESC
                    LIMIT 15
                """, (hours,))

            rows = _rows(cur)

            if route_id:
                stop_map = {}
                for r in rows:
                    sid = r["stop_id"]
                    if sid not in stop_map:
                        stop_map[sid] = {"stop_id": sid, "stop_name": r["stop_name"], "hours": []}
                    stop_map[sid]["hours"].append({"hour": r["hour"], "avg_delay": round(r["avg_delay"] or 0, 1)})
                return list(stop_map.values())
            else:
                return [
                    {"stop_id": r["stop_id"], "stop_name": r["stop_name"],
                     "avg_delay": round(r["avg_delay"] or 0, 1)}
                    for r in rows
                ]


def query_on_time(pool, route_id: str | None = None, hours: int = 24) -> list[dict]:
    """Hourly on-time percentage, optionally scoped to a route's stops."""
    with pool.connection() as conn:
        with conn.cursor() as cur:
            if route_id:
                cur.execute("""
                    SELECT time_bucket('1 hour', tu.time) AS bucket,
                           COUNT(*) AS total,
                           COUNT(*) FILTER (
                               WHERE ABS(COALESCE(tu.arrival_delay, 0)) < 300
                           ) AS on_time
                    FROM gtfs_rt_trip_updates tu
                    WHERE tu.stop_id IN (
                              SELECT rs.stop_id FROM route_stops rs
                              WHERE rs.route_id = %s
                          )
                      AND tu.time > NOW() - make_interval(hours => %s)
                    GROUP BY bucket
                    ORDER BY bucket
                """, (route_id, hours))
            else:
                cur.execute("""
                    SELECT time_bucket('1 hour', tu.time) AS bucket,
                           COUNT(*) AS total,
                           COUNT(*) FILTER (
                               WHERE ABS(COALESCE(tu.arrival_delay, 0)) < 300
                           ) AS on_time
                    FROM gtfs_rt_trip_updates tu
                    WHERE tu.time > NOW() - make_interval(hours => %s)
                    GROUP BY bucket
                    ORDER BY bucket
                """, (hours,))

            return [
                {
                    "time": _hour_label(r["bucket"]),
                    "onTimePercent": round(
                        r["on_time"] / max(r["total"], 1) * 100, 1
                    ),
                }
                for r in _rows(cur)
            ]


def query_gtfs_rt_freshness(pool) -> dict:
    """Return the timestamp of the most recent GTFS-RT trip update row."""
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(time) AS latest FROM gtfs_rt_trip_updates")
            row = _rows(cur)
            ts = row[0]["latest"] if row else None
            return {"latest": str(ts) if ts else None}


def query_service_alerts(pool) -> list[dict]:
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, alert_id, received_at, cause, effect,
                       header_text, description_text, severity,
                       active_period_start, active_period_end
                FROM gtfs_rt_service_alerts
                ORDER BY received_at DESC LIMIT 50
            """)
            return [{**r, "received_at": str(r["received_at"]),
                     "active_period_start": str(r["active_period_start"]) if r["active_period_start"] else None,
                     "active_period_end": str(r["active_period_end"]) if r["active_period_end"] else None}
                    for r in _rows(cur)]


def query_devices(pool) -> list[dict]:
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT device_id, stop_id, stop_name, stop_lat, stop_long,
                       transport_type, zone, is_online, pipeline_active,
                       last_seen, config
                FROM stops
                ORDER BY stop_name
            """)
            return [{**r, "last_seen": str(r["last_seen"]) if r["last_seen"] else None}
                    for r in _rows(cur)]


def query_device_logs(pool, device_id: str, limit: int = 100) -> list[dict]:
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT time, level, message, extra
                FROM stop_logs
                WHERE device_id = %s
                ORDER BY time DESC LIMIT %s
            """, (device_id, limit))
            return [{"time": str(r["time"]), "level": r["level"], "message": r["message"]}
                    for r in _rows(cur)]


def query_models(pool) -> list[dict]:
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, filename, sha256, file_size, uploaded_at, is_active
                FROM model_versions
                ORDER BY uploaded_at DESC
            """)
            return [{**r, "uploaded_at": str(r["uploaded_at"]) if r["uploaded_at"] else None}
                    for r in _rows(cur)]


def query_all_alerts(pool) -> list[dict]:
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, severity, message, source, device_id, route_id,
                       created_at, resolved_at
                FROM system_alerts
                ORDER BY created_at DESC LIMIT 100
            """)
            return [{**r, "created_at": str(r["created_at"]),
                     "resolved_at": str(r["resolved_at"]) if r["resolved_at"] else None}
                    for r in _rows(cur)]


def query_admin_log(pool, limit: int = 100) -> list[dict]:
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, occurred_at, target_device_id, action, command,
                       result, initiated_by
                FROM admin_activity_log
                ORDER BY occurred_at DESC LIMIT %s
            """, (limit,))
            return [{**r, "occurred_at": str(r["occurred_at"])} for r in _rows(cur)]


def resolve_alert(pool, alert_id: int):
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE system_alerts SET resolved_at = NOW()
                WHERE id = %s AND resolved_at IS NULL
            """, (alert_id,))
            cur.execute("NOTIFY dashboard_update, 'alert_resolved'")
        conn.commit()


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
