import datetime as _dt
import json
import logging

from .connection import ConnectionPool

logger = logging.getLogger(__name__)


class DatabaseWriter:
    """Persistence layer called by BrokerHandler.

    Each public method is a self-contained transaction.  All DB errors are
    caught and logged so that a database outage never crashes the MQTT handler.
    """

    def __init__(self, pool: ConnectionPool):
        self._pool = pool
        self._stop_id_cache: dict[str, str] = {}
        self._load_stop_id_cache()

    # -- cache -------------------------------------------------------------

    def _load_stop_id_cache(self):
        """Load the device_id -> stop_id mapping from the stops table."""
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT device_id, stop_id FROM stops")
                    self._stop_id_cache = {
                        row[0]: row[1] for row in cur.fetchall()
                    }
            logger.info(
                "Loaded device_id->stop_id cache (%d entries)",
                len(self._stop_id_cache),
            )
        except Exception:
            logger.warning(
                "Could not load stop_id cache (table may be empty); "
                "will retry on first write",
            )

    def _resolve_stop_id(self, device_id: str) -> str | None:
        """Resolve a device_id to its GTFS stop_id via the cached mapping."""
        stop_id = self._stop_id_cache.get(device_id)
        if stop_id is None:
            self._load_stop_id_cache()
            stop_id = self._stop_id_cache.get(device_id)
        return stop_id

    # -- active methods (called by BrokerHandler) --------------------------

    def write_crowd_count(
        self,
        device_id: str,
        timestamp: float,
        count: int,
        zone: str | None,
    ):
        """Insert into crowd_count hypertable and upsert current_counts."""
        stop_id = self._resolve_stop_id(device_id)
        if stop_id is None:
            logger.warning(
                "[%s] No stop_id mapping found; skipping crowd count write",
                device_id,
            )
            return

        ts = _dt.datetime.fromtimestamp(timestamp, tz=_dt.timezone.utc)
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO crowd_count (time, device_id, stop_id, count, zone)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (ts, device_id, stop_id, count, zone),
                    )
                    cur.execute(
                        """
                        INSERT INTO current_counts
                            (device_id, stop_id, count, previous_count, zone, updated_at)
                        VALUES (%s, %s, %s, NULL, %s, %s)
                        ON CONFLICT (device_id) DO UPDATE SET
                            previous_count = current_counts.count,
                            count          = EXCLUDED.count,
                            zone           = EXCLUDED.zone,
                            updated_at     = EXCLUDED.updated_at
                        """,
                        (device_id, stop_id, count, zone, ts),
                    )
                    cur.execute("NOTIFY dashboard_update, 'crowd_count'")
                conn.commit()
        except Exception:
            logger.exception("[%s] Failed to write crowd count", device_id)

    def write_log(
        self,
        device_id: str,
        timestamp: float,
        level: str,
        message: str,
        extra: dict | None = None,
    ):
        """Insert a log entry into stop_logs."""
        ts = _dt.datetime.fromtimestamp(timestamp, tz=_dt.timezone.utc)
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO stop_logs (time, device_id, level, message, extra)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (ts, device_id, level, message, json.dumps(extra or {})),
                    )
                conn.commit()
        except Exception:
            logger.exception("[%s] Failed to write log entry", device_id)

    def upsert_stop(
        self,
        device_id: str,
        is_online: bool,
        zone: str | None = None,
    ):
        """Update online status and last_seen for a stop/device."""
        now = _dt.datetime.now(_dt.timezone.utc)
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE stops
                        SET is_online = %s,
                            last_seen = %s,
                            zone      = COALESCE(%s, zone)
                        WHERE device_id = %s
                        """,
                        (is_online, now, zone, device_id),
                    )
                    cur.execute("NOTIFY dashboard_update, 'stop_status'")
                conn.commit()
        except Exception:
            logger.exception("[%s] Failed to upsert stop", device_id)

    def update_pipeline_active(self, device_id: str, active: bool):
        """Set pipeline_active on a stop (called on admin start/stop pipeline)."""
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE stops SET pipeline_active = %s WHERE device_id = %s",
                        (active, device_id),
                    )
                    cur.execute("NOTIFY dashboard_update, 'pipeline_active'")
                conn.commit()
        except Exception:
            logger.exception("[%s] Failed to update pipeline_active", device_id)

    def log_admin_action(
        self,
        target_device_id: str | None,
        action: str,
        command: dict,
        initiated_by: str = "system",
    ):
        """Record an admin command in the audit trail."""
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO admin_activity_log
                            (target_device_id, action, command, initiated_by)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (target_device_id, action, json.dumps(command), initiated_by),
                    )
                conn.commit()
        except Exception:
            logger.exception("Failed to log admin action: %s", action)

    def register_model_version(
        self,
        filename: str,
        sha256: str,
        file_size: int | None = None,
        file_path: str = "",
    ):
        """Insert a new model version after successful distribution."""
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO model_versions
                            (filename, sha256, file_size, file_path)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (sha256) DO NOTHING
                        """,
                        (filename, sha256, file_size, file_path),
                    )
                conn.commit()
        except Exception:
            logger.exception("Failed to register model version: %s", filename)

    def create_alert(
        self,
        severity: str,
        message: str,
        source: str | None = None,
        device_id: str | None = None,
        route_id: str | None = None,
    ):
        """Insert a system-generated alert."""
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO system_alerts
                            (severity, message, source, device_id, route_id)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (severity, message, source, device_id, route_id),
                    )
                    cur.execute("NOTIFY dashboard_update, 'alert'")
                conn.commit()
        except Exception:
            logger.exception("Failed to create alert: %s", message)

    # -- placeholder stubs (for future modules) ----------------------------

    def write_gtfs_trip_updates(self, updates: list[dict]):
        """Batch-insert parsed TripUpdate rows into gtfs_rt_trip_updates.

        Each dict must contain keys matching the table columns:
        time, trip_id, route_id, vehicle_id, stop_id, stop_sequence,
        arrival_delay, departure_delay, raw.

        Uses SAVEPOINTs so a single bad row only rolls back itself;
        all other rows in the batch are still committed.
        """
        if not updates:
            return

        inserted = 0
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    for i, row in enumerate(updates):
                        sp = f"sp_tu_{i}"
                        try:
                            cur.execute(f"SAVEPOINT {sp}")
                            cur.execute(
                                """
                                INSERT INTO gtfs_rt_trip_updates
                                    (time, trip_id, route_id, direction_id,
                                     vehicle_id, stop_id, stop_sequence,
                                     arrival_delay, departure_delay, raw)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                """,
                                (
                                    row["time"],
                                    row["trip_id"],
                                    row.get("route_id"),
                                    row.get("direction_id"),
                                    row.get("vehicle_id"),
                                    row.get("stop_id"),
                                    row.get("stop_sequence"),
                                    row.get("arrival_delay"),
                                    row.get("departure_delay"),
                                    json.dumps(row.get("raw", {})),
                                ),
                            )
                            cur.execute(f"RELEASE SAVEPOINT {sp}")
                            inserted += 1
                        except Exception:
                            logger.exception(
                                "Failed to insert trip update row (trip=%s, stop=%s)",
                                row.get("trip_id"),
                                row.get("stop_id"),
                            )
                            cur.execute(f"ROLLBACK TO SAVEPOINT {sp}")
                    if inserted:
                        cur.execute("NOTIFY dashboard_update, 'gtfs_trip_updates'")
                conn.commit()
            logger.debug("Inserted %d / %d trip update rows", inserted, len(updates))
        except Exception:
            logger.exception("Failed to write GTFS-RT trip updates batch")

    def purge_old_trip_updates(self, retain: int = 20):
        """Keep only the *retain* most-recent fetches in gtfs_rt_trip_updates.

        Each fetch shares a single ``time`` value (the feed header timestamp),
        so we find the Nth newest distinct timestamp and delete everything older.
        """
        if retain <= 0:
            return
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM gtfs_rt_trip_updates
                        WHERE time < (
                            SELECT min(t) FROM (
                                SELECT DISTINCT time AS t
                                FROM gtfs_rt_trip_updates
                                ORDER BY t DESC
                                LIMIT %s
                            ) recent
                        )
                        """,
                        (retain,),
                    )
                    deleted = cur.rowcount
                conn.commit()
            if deleted:
                logger.debug(
                    "Purged %d old trip-update rows (retaining last %d fetches)",
                    deleted, retain,
                )
        except Exception:
            logger.exception("Failed to purge old trip updates")

    def write_gtfs_vehicle_position(self, **kwargs):
        """Placeholder -- will be implemented with the GTFS-RT vehicle positions module."""
        raise NotImplementedError

    def upsert_vehicle(
        self,
        vehicle_id: str,
        route_id: str | None = None,
        capacity: int = 0,
        current_stop_id: str | None = None,
        state: str = "INACTIVE",
        passenger_count: int = 0,
        occupancy_percent: float = 0.0,
    ):
        """Insert or update a vehicle row in the ``vehicles`` table."""
        now = _dt.datetime.now(_dt.timezone.utc)
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO vehicles
                            (vehicle_id, route_id, capacity, current_stop_id,
                             state, passenger_count, occupancy_percent,
                             is_active, last_updated)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE, %s)
                        ON CONFLICT (vehicle_id) DO UPDATE SET
                            route_id          = EXCLUDED.route_id,
                            capacity          = EXCLUDED.capacity,
                            current_stop_id   = EXCLUDED.current_stop_id,
                            state             = EXCLUDED.state,
                            passenger_count   = EXCLUDED.passenger_count,
                            occupancy_percent = EXCLUDED.occupancy_percent,
                            is_active         = TRUE,
                            last_updated      = EXCLUDED.last_updated
                        """,
                        (vehicle_id, route_id, capacity, current_stop_id,
                         state, passenger_count, occupancy_percent, now),
                    )
                    cur.execute("NOTIFY dashboard_update, 'vehicle'")
                conn.commit()
        except Exception:
            logger.exception("[%s] Failed to upsert vehicle", vehicle_id)

    def write_vehicle_telemetry(
        self,
        vehicle_id: str,
        route_id: str | None = None,
        passenger_count: int = 0,
        occupancy_percent: float = 0.0,
        current_stop_id: str | None = None,
        state: str = "INACTIVE",
        time: _dt.datetime | None = None,
    ):
        """Insert a single row into the ``vehicle_telemetry`` hypertable."""
        ts = time or _dt.datetime.now(_dt.timezone.utc)
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO vehicle_telemetry
                            (time, vehicle_id, route_id, passenger_count,
                             occupancy_percent, current_stop_id, state)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (ts, vehicle_id, route_id, passenger_count,
                         occupancy_percent, current_stop_id, state),
                    )
                conn.commit()
        except Exception:
            logger.exception("[%s] Failed to write vehicle telemetry", vehicle_id)

    def write_predictions(self, result):
        """Persist a :class:`RoutePredictionResult` to the ``predictions`` hypertable.

        Writes one row per ``StopPrediction`` across all vehicles.  Parent
        fields (vehicle_id, route_id, direction_id, vehicle_capacity,
        confidence) are denormalized from the ``VehiclePrediction``.
        """
        now = _dt.datetime.now(_dt.timezone.utc)
        rows_inserted = 0
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    for vp in result.vehicle_predictions:
                        for sp in vp.stops:
                            occ_pct = (
                                sp.predicted_passengers / vp.vehicle_capacity
                                if vp.vehicle_capacity > 0
                                else 0.0
                            )
                            cur.execute(
                                """
                                INSERT INTO predictions
                                    (time, vehicle_id, route_id, direction_id,
                                     stop_id, stop_sequence,
                                     predicted_passengers, vehicle_capacity,
                                     predicted_occupancy_pct, waiting_at_stop,
                                     boarded, alighted, has_data, confidence)
                                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                                """,
                                (
                                    now,
                                    vp.vehicle_id,
                                    vp.route_id,
                                    result.direction_id,
                                    sp.stop_id,
                                    sp.stop_sequence,
                                    sp.predicted_passengers,
                                    vp.vehicle_capacity,
                                    round(occ_pct, 4),
                                    sp.people_waiting_at_stop,
                                    sp.boarded,
                                    sp.alighted,
                                    sp.has_data,
                                    round(vp.confidence, 4),
                                ),
                            )
                            rows_inserted += 1
                    if rows_inserted:
                        cur.execute("NOTIFY dashboard_update, 'predictions'")
                conn.commit()
            logger.debug(
                "Wrote %d prediction rows for route=%s dir=%s",
                rows_inserted,
                result.route_id,
                result.direction_id,
            )
        except Exception:
            logger.exception(
                "Failed to write predictions for route=%s", result.route_id,
            )

    def write_scheduler_decision(
        self,
        alert,
        decision_type: str = "deploy_vehicle",
    ):
        """Persist an :class:`Alert` as a row in ``scheduler_decisions``."""
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO scheduler_decisions
                            (decision_type, route_id, direction_id,
                             trigger_vehicle_id, trigger_stop_id,
                             predicted_passengers, predicted_occupancy_pct,
                             vehicle_capacity, total_stranded,
                             threshold, message, metadata)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        """,
                        (
                            decision_type,
                            alert.route_id,
                            alert.direction_id,
                            alert.vehicle_id,
                            alert.trigger_stop_id,
                            alert.predicted_passengers,
                            round(alert.predicted_occupancy_pct, 4),
                            alert.vehicle_capacity,
                            alert.total_stranded,
                            alert.trigger_detail.get("occupancy_threshold"),
                            alert.message,
                            json.dumps(alert.trigger_detail),
                        ),
                    )
                    cur.execute("NOTIFY dashboard_update, 'scheduler_decision'")
                conn.commit()
            logger.debug(
                "Wrote scheduler decision (%s) for route=%s dir=%s",
                decision_type,
                alert.route_id,
                alert.direction_id,
            )
        except Exception:
            logger.exception(
                "Failed to write scheduler decision for route=%s",
                alert.route_id,
            )

    def resolve_alert(self, alert_id: int):
        """Mark a system alert as resolved."""
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE system_alerts
                        SET resolved_at = NOW()
                        WHERE id = %s AND resolved_at IS NULL
                        """,
                        (alert_id,),
                    )
                    cur.execute("NOTIFY dashboard_update, 'alert_resolved'")
                conn.commit()
        except Exception:
            logger.exception("Failed to resolve alert %d", alert_id)
