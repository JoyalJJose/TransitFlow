# *** TEST FILE - SAFE TO DELETE ***
"""
End-to-end system integration tests for the 39A route.

Proves that the full pipeline works: DB seeding -> synthetic GTFS-RT ->
mock crowd counts -> SnapshotBuilder -> PredictionEngine -> Evaluator ->
results written to DB.

Requires Docker (TimescaleDB).
"""

import os
import sys

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
BACKEND_DIR = os.path.join(SRC_DIR, "Backend")

for p in (SRC_DIR, BACKEND_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from Database.writer import DatabaseWriter
from PredictionEngine import (
    PredictionEngine,
    RoutePredictionResult,
    ThresholdEvaluator,
    EvaluatorRegistry,
)
from PredictionEngine.snapshot_builder import SnapshotBuilder

pytestmark = pytest.mark.integration


# ===== SnapshotBuilder ======================================================

class TestSnapshotBuilder:

    def test_builds_route_with_correct_stops(
        self, seeded_db, route_39a_info, synthetic_vehicles, mock_crowd_counts,
    ):
        builder = SnapshotBuilder(seeded_db)
        snapshot = builder.build(
            route_39a_info["route_id"], route_39a_info["direction_id"],
        )

        assert snapshot is not None
        assert snapshot.route_id == route_39a_info["route_id"]
        assert snapshot.direction_id == route_39a_info["direction_id"]

        expected_stop_count = len(route_39a_info["stops"])
        assert len(snapshot.stops) == expected_stop_count

        sequences = [s.sequence for s in snapshot.stops]
        assert sequences == sorted(sequences), "Stops must be in sequence order"

    def test_crowd_counts_populated(
        self, seeded_db, route_39a_info, synthetic_vehicles, mock_crowd_counts,
    ):
        builder = SnapshotBuilder(seeded_db)
        snapshot = builder.build(
            route_39a_info["route_id"], route_39a_info["direction_id"],
        )

        with_data = [s for s in snapshot.stops if s.people_waiting is not None]
        without_data = [s for s in snapshot.stops if s.people_waiting is None]

        assert len(with_data) == len(mock_crowd_counts)
        assert len(without_data) > 0, "Some stops should have no edge device data"

        for s in with_data:
            assert s.people_waiting == mock_crowd_counts[s.stop_id]

    def test_vehicles_from_synthetic_data(
        self, seeded_db, route_39a_info, synthetic_vehicles, mock_crowd_counts,
    ):
        builder = SnapshotBuilder(seeded_db)
        snapshot = builder.build(
            route_39a_info["route_id"], route_39a_info["direction_id"],
        )

        assert len(snapshot.vehicles) == 3

        vehicle_ids = {v.vehicle_id for v in snapshot.vehicles}
        assert vehicle_ids == set(synthetic_vehicles)

        expected_positions = {"synth-trip-front": 10, "synth-trip-mid": 30, "synth-trip-rear": 55}
        for v in snapshot.vehicles:
            assert v.current_stop_sequence == expected_positions[v.vehicle_id]
            assert v.capacity == 80
            assert v.passenger_count == 0

    def test_returns_none_for_unknown_route(self, seeded_db):
        builder = SnapshotBuilder(seeded_db)
        result = builder.build("nonexistent_route", 0)
        assert result is None


# ===== PredictionEngine =====================================================

class TestPredictionEngineIntegration:

    def test_produces_results_for_all_vehicles(
        self, seeded_db, route_39a_info, synthetic_vehicles, mock_crowd_counts,
    ):
        builder = SnapshotBuilder(seeded_db)
        snapshot = builder.build(
            route_39a_info["route_id"], route_39a_info["direction_id"],
        )

        engine = PredictionEngine()
        result = engine.predict_route(snapshot)

        assert isinstance(result, RoutePredictionResult)
        assert result.route_id == route_39a_info["route_id"]
        assert result.direction_id == route_39a_info["direction_id"]
        assert len(result.vehicle_predictions) == 3

        for vp in result.vehicle_predictions:
            assert vp.vehicle_id in synthetic_vehicles
            assert len(vp.stops) > 0
            assert vp.peak_load >= 0
            assert 0.0 <= vp.peak_occupancy_pct
            assert 0.0 <= vp.confidence <= 1.0

    def test_front_vehicle_consumes_passengers_for_rear(
        self, seeded_db, route_39a_info, synthetic_vehicles, mock_crowd_counts,
    ):
        builder = SnapshotBuilder(seeded_db)
        snapshot = builder.build(
            route_39a_info["route_id"], route_39a_info["direction_id"],
        )

        engine = PredictionEngine()
        result = engine.predict_route(snapshot)

        vp_by_id = {vp.vehicle_id: vp for vp in result.vehicle_predictions}
        front = vp_by_id["synth-trip-front"]
        mid = vp_by_id["synth-trip-mid"]
        rear = vp_by_id["synth-trip-rear"]

        assert front.peak_load >= mid.peak_load or front.peak_load >= rear.peak_load, (
            "Front vehicle should generally board more (sees untouched passenger counts)"
        )

    def test_stranded_passengers_dict(
        self, seeded_db, route_39a_info, synthetic_vehicles, mock_crowd_counts,
    ):
        builder = SnapshotBuilder(seeded_db)
        snapshot = builder.build(
            route_39a_info["route_id"], route_39a_info["direction_id"],
        )

        engine = PredictionEngine()
        result = engine.predict_route(snapshot)

        assert isinstance(result.stranded_at_stops, dict)
        for stop_id, count in result.stranded_at_stops.items():
            assert isinstance(stop_id, str)
            assert count > 0


# ===== Evaluator ============================================================

class TestEvaluatorIntegration:

    def test_evaluator_runs_without_error(
        self, seeded_db, route_39a_info, synthetic_vehicles, mock_crowd_counts,
    ):
        builder = SnapshotBuilder(seeded_db)
        snapshot = builder.build(
            route_39a_info["route_id"], route_39a_info["direction_id"],
        )

        engine = PredictionEngine()
        result = engine.predict_route(snapshot)

        evaluator = ThresholdEvaluator()
        alert = evaluator.evaluate(result)

        if alert is not None:
            assert alert.route_id == route_39a_info["route_id"]
            assert alert.direction_id == route_39a_info["direction_id"]
            assert alert.vehicle_id in synthetic_vehicles
            assert alert.predicted_passengers >= 0
            assert alert.vehicle_capacity == 80
            assert len(alert.message) > 0

    def test_registry_dispatches_correctly(
        self, seeded_db, route_39a_info, synthetic_vehicles, mock_crowd_counts,
    ):
        builder = SnapshotBuilder(seeded_db)
        snapshot = builder.build(
            route_39a_info["route_id"], route_39a_info["direction_id"],
        )

        engine = PredictionEngine()
        result = engine.predict_route(snapshot)

        strict = ThresholdEvaluator(occupancy_threshold=0.5, min_stranded=1)
        lenient = ThresholdEvaluator(occupancy_threshold=1.0, min_stranded=9999)

        registry = EvaluatorRegistry(default=lenient)
        registry.register(route_39a_info["route_id"], strict)

        alert = registry.evaluate(result)
        if alert is not None:
            assert alert.route_id == route_39a_info["route_id"]


# ===== DatabaseWriter -- predictions ========================================

class TestWritePredictions:

    def test_predictions_written_to_db(
        self, seeded_db, route_39a_info, synthetic_vehicles, mock_crowd_counts,
    ):
        builder = SnapshotBuilder(seeded_db)
        snapshot = builder.build(
            route_39a_info["route_id"], route_39a_info["direction_id"],
        )

        engine = PredictionEngine()
        result = engine.predict_route(snapshot)

        writer = DatabaseWriter(seeded_db)
        writer.write_predictions(result)

        with seeded_db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM predictions WHERE route_id = %s",
                    (route_39a_info["route_id"],),
                )
                count = cur.fetchone()[0]

        expected = sum(len(vp.stops) for vp in result.vehicle_predictions)
        assert count >= expected, (
            f"Expected at least {expected} prediction rows, got {count}"
        )

    def test_prediction_fields_correct(
        self, seeded_db, route_39a_info, synthetic_vehicles, mock_crowd_counts,
    ):
        with seeded_db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT vehicle_id, route_id, direction_id, stop_id,
                           predicted_passengers, vehicle_capacity,
                           predicted_occupancy_pct, boarded, alighted,
                           has_data, confidence
                    FROM predictions
                    WHERE route_id = %s
                    LIMIT 10
                    """,
                    (route_39a_info["route_id"],),
                )
                rows = cur.fetchall()

        assert len(rows) > 0

        for row in rows:
            vehicle_id, route_id, direction_id, stop_id = row[:4]
            predicted_passengers, vehicle_capacity = row[4], row[5]
            occ_pct, boarded, alighted, has_data, confidence = row[6:]

            assert vehicle_id in synthetic_vehicles
            assert route_id == route_39a_info["route_id"]
            assert direction_id == route_39a_info["direction_id"]
            assert isinstance(stop_id, str) and len(stop_id) > 0
            assert predicted_passengers >= 0
            assert vehicle_capacity == 80
            assert occ_pct is not None
            assert boarded >= 0
            assert alighted >= 0
            assert isinstance(has_data, bool)
            assert 0.0 <= confidence <= 1.0


# ===== DatabaseWriter -- scheduler decisions ================================

class TestWriteSchedulerDecision:

    def test_decision_written_when_alert_exists(
        self, seeded_db, route_39a_info, synthetic_vehicles, mock_crowd_counts,
    ):
        builder = SnapshotBuilder(seeded_db)
        snapshot = builder.build(
            route_39a_info["route_id"], route_39a_info["direction_id"],
        )

        engine = PredictionEngine()
        result = engine.predict_route(snapshot)

        evaluator = ThresholdEvaluator(occupancy_threshold=0.5, min_stranded=1)
        alert = evaluator.evaluate(result)

        if alert is None:
            pytest.skip("No alert produced (thresholds not exceeded)")

        writer = DatabaseWriter(seeded_db)
        writer.write_scheduler_decision(alert)

        with seeded_db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT decision_type, route_id, direction_id,
                           trigger_vehicle_id, trigger_stop_id,
                           predicted_passengers, vehicle_capacity,
                           total_stranded, message
                    FROM scheduler_decisions
                    WHERE route_id = %s
                    ORDER BY decided_at DESC
                    LIMIT 1
                    """,
                    (route_39a_info["route_id"],),
                )
                row = cur.fetchone()

        assert row is not None, "Decision should have been written to DB"

        decision_type, route_id, direction_id = row[:3]
        trigger_vid, trigger_sid = row[3], row[4]
        pred_passengers, capacity, stranded, message = row[5:]

        assert decision_type == "deploy_vehicle"
        assert route_id == route_39a_info["route_id"]
        assert direction_id == route_39a_info["direction_id"]
        assert trigger_vid in synthetic_vehicles
        assert isinstance(trigger_sid, str) and len(trigger_sid) > 0
        assert pred_passengers >= 0
        assert capacity == 80
        assert stranded >= 0
        assert len(message) > 0


# ===== Proportional crowd splitting ==========================================

class TestCrowdSplitting:

    def test_shared_stop_crowd_is_split(
        self, seeded_db, route_39a_info, synthetic_vehicles,
        mock_crowd_counts, competing_route_at_shared_stop,
    ):
        """When a competing route also serves a stop, the crowd count
        should be split proportionally based on inverse-ETA weighting.
        """
        info = competing_route_at_shared_stop
        shared_stop = info["shared_stop_id"]
        raw_count = mock_crowd_counts.get(shared_stop)
        if raw_count is None or raw_count == 0:
            pytest.skip("Shared stop has no crowd count data")

        builder = SnapshotBuilder(seeded_db)
        snapshot = builder.build(
            route_39a_info["route_id"], route_39a_info["direction_id"],
        )

        stop_state = next(
            s for s in snapshot.stops if s.stop_id == shared_stop
        )

        assert stop_state.people_waiting is not None
        assert stop_state.people_waiting < raw_count, (
            f"Expected split crowd ({stop_state.people_waiting}) "
            f"to be less than raw count ({raw_count}) at shared stop"
        )
        assert stop_state.people_waiting > 0, (
            "Our route should still get a positive share"
        )

    def test_unshared_stop_gets_full_count(
        self, seeded_db, route_39a_info, synthetic_vehicles,
        mock_crowd_counts, competing_route_at_shared_stop,
    ):
        """Stops served only by 39A should keep their full crowd count."""
        info = competing_route_at_shared_stop
        shared_stop = info["shared_stop_id"]

        builder = SnapshotBuilder(seeded_db)
        snapshot = builder.build(
            route_39a_info["route_id"], route_39a_info["direction_id"],
        )

        for s in snapshot.stops:
            if s.stop_id == shared_stop:
                continue
            if s.people_waiting is not None and s.stop_id in mock_crowd_counts:
                assert s.people_waiting == mock_crowd_counts[s.stop_id], (
                    f"Stop {s.stop_id} should keep full count "
                    f"(expected {mock_crowd_counts[s.stop_id]}, "
                    f"got {s.people_waiting})"
                )


# ===== Full pipeline end-to-end =============================================

class TestFullPipeline:

    def test_end_to_end(
        self, seeded_db, route_39a_info, synthetic_vehicles, mock_crowd_counts,
    ):
        """Run the entire pipeline in sequence and verify DB state."""
        route_id = route_39a_info["route_id"]
        direction_id = route_39a_info["direction_id"]

        # 1. Build snapshot from DB
        builder = SnapshotBuilder(seeded_db)
        snapshot = builder.build(route_id, direction_id)
        assert snapshot is not None
        assert len(snapshot.stops) > 0
        assert len(snapshot.vehicles) == 3

        # 2. Run predictions
        engine = PredictionEngine()
        result = engine.predict_route(snapshot)
        assert len(result.vehicle_predictions) == 3

        # 3. Evaluate
        evaluator = ThresholdEvaluator()
        alert = evaluator.evaluate(result)

        # 4. Write predictions to DB
        writer = DatabaseWriter(seeded_db)
        writer.write_predictions(result)

        # 5. Write decision if alert was triggered
        if alert is not None:
            writer.write_scheduler_decision(alert)

        # 6. Verify predictions in DB
        with seeded_db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM predictions WHERE route_id = %s",
                    (route_id,),
                )
                pred_count = cur.fetchone()[0]
                assert pred_count > 0

                cur.execute(
                    """
                    SELECT DISTINCT vehicle_id FROM predictions
                    WHERE route_id = %s
                    """,
                    (route_id,),
                )
                db_vehicles = {row[0] for row in cur.fetchall()}
                assert db_vehicles == set(synthetic_vehicles)

                if alert is not None:
                    cur.execute(
                        "SELECT COUNT(*) FROM scheduler_decisions WHERE route_id = %s",
                        (route_id,),
                    )
                    decision_count = cur.fetchone()[0]
                    assert decision_count > 0

        print(
            f"\n[e2e] Pipeline complete: {pred_count} prediction rows, "
            f"alert={'YES' if alert else 'NO'}"
        )
