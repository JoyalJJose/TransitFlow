"""Comprehensive unit tests for PredictionEngine, ThresholdEvaluator,
and EvaluatorRegistry.

All expected values are hand-calculated and documented in comments.
"""

import pytest

from PredictionEngine.engine import PredictionConfig, PredictionEngine
from PredictionEngine.evaluator import (
    Alert,
    EvaluatorRegistry,
    ThresholdEvaluator,
)
from PredictionEngine.snapshot import (
    RouteSnapshot,
    RoutePredictionResult,
    StopPrediction,
    StopState,
    VehiclePrediction,
    VehicleSnapshot,
)

from conftest import make_snapshot, make_stops, make_vehicle


# ==========================================================================
# PredictionEngine -- core simulation
# ==========================================================================


class TestSingleVehicleBasic:
    """Single vehicle, basic boarding + alighting simulation."""

    def test_load_increases_with_boarding(self, engine):
        # 5 stops, 10 people waiting each, vehicle at stop 1, capacity 75
        # Terminus is stop 5 -> walk covers stops 1-4
        # af=0.05, load starts at 0
        # Stop 1: alight=round(0*0.05)=0, board=min(10,75)=10, load=10
        # Stop 2: alight=round(10*0.05)=round(0.5)=0, board=min(10,75)=10, load=20
        # Stop 3: alight=round(20*0.05)=1, load=19, board=min(10,56)=10, load=29
        # Stop 4: alight=round(29*0.05)=round(1.45)=1, load=28, board=min(10,47)=10, load=38
        stops = make_stops(5, [10, 10, 10, 10, 0])
        vehicle = make_vehicle(current_stop_sequence=1, capacity=75)
        snap = make_snapshot(stops, (vehicle,))

        result = engine.predict_route(snap)

        assert len(result.vehicle_predictions) == 1
        vp = result.vehicle_predictions[0]
        assert len(vp.stops) == 4  # stops 1-4, terminus excluded

        loads = [sp.predicted_passengers for sp in vp.stops]
        assert loads == [10, 20, 29, 38]

    def test_alighting_before_boarding_frees_capacity(self, engine):
        # Vehicle starts with 73 passengers, capacity 75
        # Stop 1: 20 waiting
        # af=0.05 -> alight=round(73*0.05)=round(3.65)=4, load=69, board=min(20,6)=6, load=75
        stops = make_stops(2, [20, 0])
        vehicle = make_vehicle(
            current_stop_sequence=1, capacity=75, passenger_count=73,
        )
        snap = make_snapshot(stops, (vehicle,))

        result = engine.predict_route(snap)
        sp = result.vehicle_predictions[0].stops[0]

        assert sp.alighted == 4
        assert sp.boarded == 6
        assert sp.predicted_passengers == 75


class TestMultiVehicle:
    """Multiple vehicles interacting via the shared remaining[] array."""

    def test_vehicle_ahead_consumes_passengers(self, engine):
        # 3 stops: 10, 10, terminus=0.  Two vehicles, af=0.0 for simplicity.
        # Vehicle A at stop 1 (ahead), Vehicle B at stop 1 (behind, higher id)
        # Sorted: same stop_seq -> tiebreak ascending id -> A first, then B
        #
        # Vehicle A: stop1 board=min(10,75)=10 load=10; stop2 board=min(10,65)=10 load=20
        # remaining after A: [0, 0]
        # Vehicle B: stop1 board=min(0,75)=0 load=0; stop2 board=min(0,75)=0 load=0
        stops = make_stops(3, [10, 10, 0])
        vA = make_vehicle(vehicle_id="trip-A", current_stop_sequence=1)
        vB = make_vehicle(vehicle_id="trip-B", current_stop_sequence=1)
        snap = make_snapshot(stops, (vA, vB))

        result = engine.predict_route(snap, alighting_fraction=0.0)

        preds = {vp.vehicle_id: vp for vp in result.vehicle_predictions}
        assert [sp.predicted_passengers for sp in preds["trip-A"].stops] == [10, 20]
        assert [sp.predicted_passengers for sp in preds["trip-B"].stops] == [0, 0]

    def test_front_to_back_ordering(self, engine):
        # Vehicle A at stop 3 (ahead), Vehicle B at stop 1 (behind).
        # 5 stops, 10 waiting each, af=0.0
        # A processes stops 3-4 first, B processes stops 1-4.
        # A: stop3 board=10 load=10; stop4 board=10 load=20
        # remaining after A: [10, 10, 0, 0, 0]
        # B: stop1 board=10 load=10; stop2 board=10 load=20; stop3 board=0 load=20; stop4 board=0 load=20
        stops = make_stops(5, [10, 10, 10, 10, 0])
        vA = make_vehicle(vehicle_id="trip-A", current_stop_sequence=3)
        vB = make_vehicle(vehicle_id="trip-B", current_stop_sequence=1)
        snap = make_snapshot(stops, (vA, vB))

        result = engine.predict_route(snap, alighting_fraction=0.0)

        preds = {vp.vehicle_id: vp for vp in result.vehicle_predictions}
        assert [sp.predicted_passengers for sp in preds["trip-A"].stops] == [10, 20]
        assert [sp.predicted_passengers for sp in preds["trip-B"].stops] == [10, 20, 20, 20]

    def test_three_vehicles_with_stranded(self, engine):
        # 4 stops, 30 waiting each, capacity=20, af=0.0
        # Sorted by stop_seq desc: all at stop 1 -> tiebreak ascending id
        # A: stop1 board=min(30,20)=20 load=20; stop2 board=min(30,0)=0 load=20; stop3 board=0 load=20
        # remaining: [10, 30, 30]
        # B: stop1 board=min(10,20)=10 load=10; stop2 board=min(30,10)=10 load=20; stop3 board=0 load=20
        # remaining: [0, 20, 30]
        # C: stop1 board=0 load=0; stop2 board=min(20,20)=20 load=20; stop3 board=0 load=20
        # remaining: [0, 0, 30]
        # stranded: stop-3 (sequence=3) = 30  (all 3 vehicles full by stop 3)
        stops = make_stops(4, [30, 30, 30, 0])
        vehicles = tuple(
            make_vehicle(vehicle_id=f"trip-{c}", current_stop_sequence=1, capacity=20)
            for c in "ABC"
        )
        snap = make_snapshot(stops, vehicles)

        result = engine.predict_route(snap, alighting_fraction=0.0)
        assert result.stranded_at_stops == {"stop-3": 30}


class TestStrandedPassengers:
    """Verify stranded count computation."""

    def test_vehicle_fills_up_stranded_appear(self, engine):
        # 3 stops, 100 waiting each, capacity 50, af=0.0
        # Walk covers stops 1-2 (stop 3 is terminus)
        # Stop 1: board=min(100,50)=50, load=50. remaining[0]=50
        # Stop 2: board=min(100,0)=0, load=50. remaining[1]=100
        # stranded: stop-1=50, stop-2=100
        stops = make_stops(3, [100, 100, 0])
        vehicle = make_vehicle(current_stop_sequence=1, capacity=50)
        snap = make_snapshot(stops, (vehicle,))

        result = engine.predict_route(snap, alighting_fraction=0.0)

        assert result.stranded_at_stops == {"stop-1": 50, "stop-2": 100}


class TestEdgeCases:
    """Edge cases handled by the engine."""

    def test_vehicle_at_last_stop_no_predictions(self, engine):
        stops = make_stops(3, [10, 10, 0])
        vehicle = make_vehicle(current_stop_sequence=3)  # last stop
        snap = make_snapshot(stops, (vehicle,))

        result = engine.predict_route(snap)
        assert len(result.vehicle_predictions) == 0

    def test_empty_route(self, engine):
        snap = make_snapshot((), ())
        result = engine.predict_route(snap)
        assert result.vehicle_predictions == ()
        assert result.stranded_at_stops == {}

    def test_single_stop_route(self, engine):
        stops = make_stops(1, [10])
        vehicle = make_vehicle(current_stop_sequence=1)
        snap = make_snapshot(stops, (vehicle,))

        result = engine.predict_route(snap)
        assert result.vehicle_predictions == ()
        assert result.stranded_at_stops == {}

    def test_vehicle_stop_sequence_not_in_route(self, engine):
        stops = make_stops(3, [10, 10, 0])
        vehicle = make_vehicle(current_stop_sequence=99)
        snap = make_snapshot(stops, (vehicle,))

        result = engine.predict_route(snap)
        assert len(result.vehicle_predictions) == 0

    def test_none_crowd_data_treated_as_zero(self, engine):
        # Stops 1 and 2 have None, stop 3 has 10, stop 4 is terminus
        stops = make_stops(4, [None, None, 10, 0])
        vehicle = make_vehicle(current_stop_sequence=1)
        snap = make_snapshot(stops, (vehicle,))

        result = engine.predict_route(snap, alighting_fraction=0.0)
        vp = result.vehicle_predictions[0]

        assert vp.stops[0].boarded == 0  # None -> 0
        assert vp.stops[1].boarded == 0  # None -> 0
        assert vp.stops[2].boarded == 10
        assert not vp.stops[0].has_data
        assert not vp.stops[1].has_data
        assert vp.stops[2].has_data

    def test_none_crowd_data_degrades_confidence(self, engine):
        # 2/3 predicted stops have None data -> confidence = 1/3
        stops = make_stops(4, [None, None, 10, 0])
        vehicle = make_vehicle(current_stop_sequence=1)
        snap = make_snapshot(stops, (vehicle,))

        result = engine.predict_route(snap, alighting_fraction=0.0)
        vp = result.vehicle_predictions[0]
        assert vp.confidence == pytest.approx(1 / 3)

    def test_all_stops_none_confidence_zero(self, engine):
        stops = make_stops(3, [None, None, None])
        vehicle = make_vehicle(current_stop_sequence=1, passenger_count=5)
        snap = make_snapshot(stops, (vehicle,))

        result = engine.predict_route(snap)
        vp = result.vehicle_predictions[0]
        assert vp.confidence == 0.0
        assert result.stranded_at_stops == {}

    def test_zero_capacity_vehicle_skipped(self, engine):
        stops = make_stops(3, [10, 10, 0])
        vehicle = make_vehicle(capacity=0)
        snap = make_snapshot(stops, (vehicle,))

        result = engine.predict_route(snap)
        assert len(result.vehicle_predictions) == 0

    def test_passenger_count_exceeds_capacity(self, engine):
        # passenger_count=80 > capacity=75 -> board=max(0,75-80)=0, no boarding
        # alight=round(80*0.05)=4, load=76 after stop 1
        stops = make_stops(3, [10, 10, 0])
        vehicle = make_vehicle(capacity=75, passenger_count=80)
        snap = make_snapshot(stops, (vehicle,))

        result = engine.predict_route(snap)
        vp = result.vehicle_predictions[0]

        # Stop 1: alight=round(80*0.05)=4, load=76, board=max(0,75-76)=0 -> 0, load=76
        # Stop 2: alight=round(76*0.05)=round(3.8)=4, load=72, board=min(10,3)=3, load=75
        assert vp.stops[0].boarded == 0
        assert vp.stops[0].alighted == 4
        assert vp.stops[0].predicted_passengers == 76
        assert vp.stops[1].boarded == 3
        assert vp.stops[1].predicted_passengers == 75

    def test_same_stop_tiebreaker_by_vehicle_id(self, engine):
        # Two vehicles at same stop: "trip-A" (lower) processes first
        stops = make_stops(2, [5, 0])
        vA = make_vehicle(vehicle_id="trip-A", current_stop_sequence=1, capacity=10)
        vB = make_vehicle(vehicle_id="trip-B", current_stop_sequence=1, capacity=10)
        snap = make_snapshot(stops, (vB, vA))  # deliberately unsorted

        result = engine.predict_route(snap, alighting_fraction=0.0)
        preds = {vp.vehicle_id: vp for vp in result.vehicle_predictions}

        assert preds["trip-A"].stops[0].boarded == 5
        assert preds["trip-B"].stops[0].boarded == 0

    def test_non_zero_passenger_count_seeds_simulation(self, engine):
        # Vehicle starts with 20 passengers, af=0.05
        # Stop 1: alight=round(20*0.05)=1, load=19, board=min(10,56)=10, load=29
        stops = make_stops(2, [10, 0])
        vehicle = make_vehicle(passenger_count=20, capacity=75)
        snap = make_snapshot(stops, (vehicle,))

        result = engine.predict_route(snap)
        sp = result.vehicle_predictions[0].stops[0]
        assert sp.alighted == 1
        assert sp.boarded == 10
        assert sp.predicted_passengers == 29


class TestAlightingFraction:
    """Alighting fraction edge cases."""

    def test_zero_alighting_fraction(self, engine):
        # No alighting -> demand accumulates
        stops = make_stops(4, [10, 10, 10, 0])
        vehicle = make_vehicle(current_stop_sequence=1, capacity=100)
        snap = make_snapshot(stops, (vehicle,))

        result = engine.predict_route(snap, alighting_fraction=0.0)
        loads = [sp.predicted_passengers for sp in result.vehicle_predictions[0].stops]
        assert loads == [10, 20, 30]

    def test_low_load_alighting_rounds_to_zero(self, engine):
        # load=5, af=0.05 -> round(0.25) = 0
        stops = make_stops(2, [0, 0])
        vehicle = make_vehicle(passenger_count=5, capacity=75)
        snap = make_snapshot(stops, (vehicle,))

        result = engine.predict_route(snap)
        sp = result.vehicle_predictions[0].stops[0]
        assert sp.alighted == 0
        assert sp.predicted_passengers == 5


class TestRouteEdgeCases:
    """Route-level edge cases (2 stops, second-to-last stop)."""

    def test_two_stop_route(self, engine):
        # Only 1 real stop + terminus -> 1 prediction per vehicle
        stops = make_stops(2, [10, 0])
        vehicle = make_vehicle(current_stop_sequence=1)
        snap = make_snapshot(stops, (vehicle,))

        result = engine.predict_route(snap, alighting_fraction=0.0)
        vp = result.vehicle_predictions[0]
        assert len(vp.stops) == 1
        assert vp.stops[0].predicted_passengers == 10

    def test_vehicle_at_second_to_last_stop(self, engine):
        # Stop 4 is the second-to-last, stop 5 is terminus
        stops = make_stops(5, [10, 10, 10, 20, 0])
        vehicle = make_vehicle(current_stop_sequence=4)
        snap = make_snapshot(stops, (vehicle,))

        result = engine.predict_route(snap, alighting_fraction=0.0)
        vp = result.vehicle_predictions[0]
        assert len(vp.stops) == 1
        assert vp.stops[0].predicted_passengers == 20


class TestPeakLoadAndOccupancy:
    """Peak load and occupancy percentage computation."""

    def test_peak_load_and_occupancy(self, engine):
        # 4 stops, varying waiting, af=0.0, capacity=50
        # stop1: board=10 load=10; stop2: board=30 load=40; stop3: board=5 load=45
        # peak=45, pct=45/50=0.9
        stops = make_stops(4, [10, 30, 5, 0])
        vehicle = make_vehicle(current_stop_sequence=1, capacity=50)
        snap = make_snapshot(stops, (vehicle,))

        result = engine.predict_route(snap, alighting_fraction=0.0)
        vp = result.vehicle_predictions[0]
        assert vp.peak_load == 45
        assert vp.peak_occupancy_pct == pytest.approx(0.9)


# ==========================================================================
# ThresholdEvaluator
# ==========================================================================


def _make_vp(
    vehicle_id: str = "trip-A",
    capacity: int = 75,
    peak_load: int = 60,
    confidence: float = 1.0,
    stop_passengers: int | None = None,
) -> VehiclePrediction:
    """Helper to build a VehiclePrediction for evaluator tests."""
    passengers = stop_passengers if stop_passengers is not None else peak_load
    return VehiclePrediction(
        vehicle_id=vehicle_id,
        route_id="route-1",
        vehicle_capacity=capacity,
        stops=(
            StopPrediction(
                stop_id="stop-1",
                stop_sequence=1,
                predicted_passengers=passengers,
                boarded=passengers,
                alighted=0,
                people_waiting_at_stop=passengers,
                has_data=True,
            ),
        ),
        peak_load=peak_load,
        peak_occupancy_pct=peak_load / capacity,
        confidence=confidence,
    )


def _make_result(
    vehicle_predictions: tuple[VehiclePrediction, ...] = (),
    stranded: dict[str, int] | None = None,
    route_id: str = "route-1",
) -> RoutePredictionResult:
    return RoutePredictionResult(
        route_id=route_id,
        direction_id=0,
        vehicle_predictions=vehicle_predictions,
        stranded_at_stops=stranded or {},
    )


class TestThresholdEvaluator:

    def test_no_alert_when_below_thresholds(self):
        evaluator = ThresholdEvaluator(occupancy_threshold=0.9, min_stranded=5)
        vp = _make_vp(peak_load=60, capacity=75)  # 0.8 < 0.9
        result = _make_result((vp,), stranded={"stop-2": 2})

        assert evaluator.evaluate(result) is None

    def test_alert_on_occupancy_threshold(self):
        evaluator = ThresholdEvaluator(occupancy_threshold=0.9, min_stranded=100)
        vp = _make_vp(peak_load=70, capacity=75)  # 0.933 > 0.9
        result = _make_result((vp,))

        alert = evaluator.evaluate(result)
        assert alert is not None
        assert alert.vehicle_id == "trip-A"
        assert alert.predicted_occupancy_pct == pytest.approx(70 / 75)
        assert alert.trigger_detail["trigger"] == "occupancy"

    def test_alert_on_stranded(self):
        evaluator = ThresholdEvaluator(occupancy_threshold=0.99, min_stranded=5)
        vp = _make_vp(peak_load=50, capacity=75)  # 0.667 < 0.99
        result = _make_result((vp,), stranded={"stop-2": 3, "stop-3": 4})

        alert = evaluator.evaluate(result)
        assert alert is not None
        assert alert.total_stranded == 7
        assert alert.trigger_detail["trigger"] == "stranded"

    def test_alert_on_both_triggers(self):
        evaluator = ThresholdEvaluator(occupancy_threshold=0.9, min_stranded=5)
        vp = _make_vp(peak_load=70, capacity=75)
        result = _make_result((vp,), stranded={"stop-2": 10})

        alert = evaluator.evaluate(result)
        assert alert is not None
        assert alert.trigger_detail["trigger"] == "occupancy_and_stranded"

    def test_empty_predictions_returns_none(self):
        evaluator = ThresholdEvaluator()
        result = _make_result()
        assert evaluator.evaluate(result) is None

    def test_low_confidence_excluded_from_occupancy_check(self):
        evaluator = ThresholdEvaluator(
            occupancy_threshold=0.9, min_stranded=100, min_confidence=0.3,
        )
        # Vehicle with high occupancy but low confidence -> no alert
        vp = _make_vp(peak_load=74, capacity=75, confidence=0.1)
        result = _make_result((vp,))

        assert evaluator.evaluate(result) is None

    def test_stranded_not_gated_by_confidence(self):
        evaluator = ThresholdEvaluator(
            occupancy_threshold=0.99, min_stranded=5, min_confidence=0.5,
        )
        vp = _make_vp(peak_load=50, capacity=75, confidence=0.1)
        result = _make_result((vp,), stranded={"stop-2": 10})

        alert = evaluator.evaluate(result)
        assert alert is not None
        assert alert.trigger_detail["trigger"] == "stranded"
        assert alert.total_stranded == 10

    def test_all_below_min_confidence_no_stranded(self):
        evaluator = ThresholdEvaluator(
            occupancy_threshold=0.5, min_stranded=100, min_confidence=0.5,
        )
        vp = _make_vp(peak_load=70, capacity=75, confidence=0.1)
        result = _make_result((vp,))

        assert evaluator.evaluate(result) is None

    def test_alert_message_populated(self):
        evaluator = ThresholdEvaluator(occupancy_threshold=0.9, min_stranded=5)
        vp = _make_vp(peak_load=70, capacity=75)
        result = _make_result((vp,), stranded={"stop-2": 10})

        alert = evaluator.evaluate(result)
        assert alert is not None
        assert "route-1" in alert.message
        assert "trip-A" in alert.message


# ==========================================================================
# EvaluatorRegistry
# ==========================================================================


class TestEvaluatorRegistry:

    def test_registered_route_uses_custom_evaluator(self):
        default = ThresholdEvaluator(occupancy_threshold=0.99, min_stranded=100)
        custom = ThresholdEvaluator(occupancy_threshold=0.5, min_stranded=1)

        registry = EvaluatorRegistry(default=default)
        registry.register("route-1", custom)

        # This would NOT trigger the default (0.667 < 0.99) but WILL trigger custom (0.667 > 0.5)
        vp = _make_vp(peak_load=50, capacity=75)
        result = _make_result((vp,), route_id="route-1")

        alert = registry.evaluate(result)
        assert alert is not None

    def test_unregistered_route_uses_default(self):
        default = ThresholdEvaluator(occupancy_threshold=0.5, min_stranded=1)
        registry = EvaluatorRegistry(default=default)

        vp = _make_vp(peak_load=50, capacity=75)
        result = _make_result((vp,), route_id="route-unknown")

        alert = registry.evaluate(result)
        assert alert is not None  # default triggers at 0.5

    def test_get_returns_correct_evaluator(self):
        default = ThresholdEvaluator(occupancy_threshold=0.9)
        custom = ThresholdEvaluator(occupancy_threshold=0.5)

        registry = EvaluatorRegistry(default=default)
        registry.register("route-X", custom)

        assert registry.get("route-X") is custom
        assert registry.get("route-Y") is default


# ==========================================================================
# End-to-end: engine -> evaluator pipeline
# ==========================================================================


class TestEndToEnd:
    """Full pipeline tests: build snapshot, run engine, evaluate."""

    def test_overcrowded_route_triggers_alert(self, engine):
        # Realistic scenario: 6 stops, lots of people, small bus
        # Stops: 20, 25, 30, 15, 10, terminus=0.  Capacity=40, af=0.0
        # Single vehicle at stop 1:
        #   stop1: board=20 load=20
        #   stop2: board=min(25,20)=20 load=40
        #   stop3: board=min(30,0)=0 load=40
        #   stop4: board=min(15,0)=0 load=40
        #   stop5: board=min(10,0)=0 load=40
        # peak=40, pct=40/40=1.0
        # stranded: stop-2=5, stop-3=30, stop-4=15, stop-5=10 -> total=60
        stops = make_stops(6, [20, 25, 30, 15, 10, 0])
        vehicle = make_vehicle(current_stop_sequence=1, capacity=40)
        snap = make_snapshot(stops, (vehicle,))

        result = engine.predict_route(snap, alighting_fraction=0.0)

        evaluator = ThresholdEvaluator(
            occupancy_threshold=0.9, min_stranded=5, min_confidence=0.3,
        )
        alert = evaluator.evaluate(result)
        assert alert is not None
        assert alert.trigger_detail["trigger"] == "occupancy_and_stranded"
        assert alert.predicted_occupancy_pct == pytest.approx(1.0)
        assert alert.total_stranded == 60
        assert alert.route_id == "route-1"
        assert alert.direction_id == 0
        assert alert.vehicle_capacity == 40

    def test_healthy_route_no_alert(self, engine):
        # Low demand, big bus -> no alert
        stops = make_stops(5, [5, 3, 2, 1, 0])
        vehicle = make_vehicle(current_stop_sequence=1, capacity=75)
        snap = make_snapshot(stops, (vehicle,))

        result = engine.predict_route(snap, alighting_fraction=0.0)

        evaluator = ThresholdEvaluator(occupancy_threshold=0.9, min_stranded=5)
        assert evaluator.evaluate(result) is None

    def test_registry_end_to_end_dispatches_per_route(self, engine):
        # Route A: tight threshold, should alert
        # Route B: loose threshold, should not alert
        default = ThresholdEvaluator(occupancy_threshold=0.99, min_stranded=999)
        tight = ThresholdEvaluator(occupancy_threshold=0.5, min_stranded=1)

        registry = EvaluatorRegistry(default=default)
        registry.register("route-tight", tight)

        stops = make_stops(3, [40, 0, 0])
        vehicle = make_vehicle(current_stop_sequence=1, capacity=75, route_id="route-tight")
        snap = make_snapshot(stops, (vehicle,), route_id="route-tight")

        result = engine.predict_route(snap, alighting_fraction=0.0)
        alert = registry.evaluate(result)
        assert alert is not None  # tight evaluator fires

        # Same scenario but different route -> uses default (won't fire)
        snap2 = make_snapshot(stops, (vehicle,), route_id="route-default")
        result2 = engine.predict_route(snap2, alighting_fraction=0.0)
        assert registry.evaluate(result2) is None


# ==========================================================================
# Deeper field-level and structural assertions
# ==========================================================================


class TestFieldCorrectness:
    """Verify that all output fields are correctly propagated."""

    def test_route_id_and_direction_propagated(self, engine):
        stops = make_stops(3, [10, 10, 0])
        vehicle = make_vehicle(current_stop_sequence=1, route_id="route-X")
        snap = make_snapshot(stops, (vehicle,), route_id="route-X", direction_id=1)

        result = engine.predict_route(snap)
        assert result.route_id == "route-X"
        assert result.direction_id == 1
        assert result.vehicle_predictions[0].route_id == "route-X"

    def test_stop_prediction_people_waiting_matches_input(self, engine):
        stops = make_stops(4, [5, None, 20, 0])
        vehicle = make_vehicle(current_stop_sequence=1)
        snap = make_snapshot(stops, (vehicle,))

        result = engine.predict_route(snap, alighting_fraction=0.0)
        sp_list = result.vehicle_predictions[0].stops

        assert sp_list[0].people_waiting_at_stop == 5
        assert sp_list[1].people_waiting_at_stop is None
        assert sp_list[2].people_waiting_at_stop == 20

    def test_stop_prediction_sequences_match_route(self, engine):
        stops = make_stops(4, [10, 10, 10, 0], start_seq=10)
        vehicle = make_vehicle(current_stop_sequence=10)
        snap = make_snapshot(stops, (vehicle,))

        result = engine.predict_route(snap, alighting_fraction=0.0)
        sp_list = result.vehicle_predictions[0].stops

        assert [sp.stop_sequence for sp in sp_list] == [10, 11, 12]
        assert [sp.stop_id for sp in sp_list] == ["stop-10", "stop-11", "stop-12"]

    def test_vehicle_prediction_vehicle_capacity_correct(self, engine):
        stops = make_stops(3, [10, 10, 0])
        vehicle = make_vehicle(capacity=42)
        snap = make_snapshot(stops, (vehicle,))

        result = engine.predict_route(snap)
        assert result.vehicle_predictions[0].vehicle_capacity == 42

    def test_boarded_plus_alighted_consistency(self, engine):
        # For each stop: load_after = load_before - alighted + boarded
        stops = make_stops(6, [15, 20, 10, 25, 5, 0])
        vehicle = make_vehicle(current_stop_sequence=1, capacity=50, passenger_count=10)
        snap = make_snapshot(stops, (vehicle,))

        result = engine.predict_route(snap)
        vp = result.vehicle_predictions[0]

        load = 10  # initial passenger_count
        for sp in vp.stops:
            load = load - sp.alighted + sp.boarded
            assert sp.predicted_passengers == load

    def test_frozen_dataclasses_immutable(self):
        stop = StopState(stop_id="s1", sequence=1, people_waiting=10)
        with pytest.raises(AttributeError):
            stop.people_waiting = 5  # type: ignore[misc]

        vehicle = VehicleSnapshot(
            vehicle_id="v1", route_id="r1", capacity=75, current_stop_sequence=1,
        )
        with pytest.raises(AttributeError):
            vehicle.capacity = 100  # type: ignore[misc]


# ==========================================================================
# Realistic Dublin Bus scenario
# ==========================================================================


class TestRealisticScenario:
    """Simulate a realistic Dublin Bus route with multiple vehicles."""

    def test_multi_vehicle_realistic_route(self, engine):
        # 10-stop route, 3 vehicles at different positions
        # Capacity 75 (double-decker), af=0.05
        # Stops: 8, None, 15, 12, None, 20, 5, 10, 3, terminus=0
        #
        # Vehicle A at stop 7 (ahead), B at stop 4 (middle), C at stop 1 (behind)
        waiting = [8, None, 15, 12, None, 20, 5, 10, 3, 0]
        stops = make_stops(10, waiting)

        vA = make_vehicle(vehicle_id="trip-100", current_stop_sequence=7, capacity=75, passenger_count=0)
        vB = make_vehicle(vehicle_id="trip-200", current_stop_sequence=4, capacity=75, passenger_count=0)
        vC = make_vehicle(vehicle_id="trip-300", current_stop_sequence=1, capacity=75, passenger_count=0)
        snap = make_snapshot(stops, (vC, vA, vB))  # deliberately unordered

        result = engine.predict_route(snap)

        assert result.route_id == "route-1"
        assert len(result.vehicle_predictions) == 3

        preds = {vp.vehicle_id: vp for vp in result.vehicle_predictions}

        # Vehicle A processes first (highest stop_seq=7): walks stops 7,8,9 -> predictions for 7,8
        # But wait, stop 9 is terminus (index 9), so walk is indices 6..8 (stops 7,8,9-1=8)
        # Index 6 (stop-7): waiting=5.  Index 7 (stop-8): waiting=10.  Index 8 (stop-9): waiting=3
        # A: stop7 alight=0 board=5 load=5; stop8 alight=round(5*0.05)=round(0.25)=0 board=10 load=15; stop9 (index 8) alight=round(15*0.05)=round(0.75)=1 load=14 board=3 load=17
        # Wait, end_idx = len(stops)-1 = 9, so range(6,9) = [6,7,8]
        assert len(preds["trip-100"].stops) == 3

        # Vehicle B next (stop_seq=4): walks indices 3..8
        assert len(preds["trip-200"].stops) == 6

        # Vehicle C last (stop_seq=1): walks indices 0..8
        assert len(preds["trip-300"].stops) == 9

        # Vehicles B and C traverse None stops -> confidence < 1.0
        # Vehicle A only visits stops 7-9 (all have data) -> confidence = 1.0
        assert preds["trip-100"].confidence == 1.0
        assert 0.0 < preds["trip-200"].confidence < 1.0
        assert 0.0 < preds["trip-300"].confidence < 1.0

        # Peak loads should be reasonable (not exceeding capacity for this light demand)
        for vp in result.vehicle_predictions:
            assert vp.peak_load <= 75

    def test_rush_hour_overcrowding(self):
        # Rush hour: heavy demand, 2 buses, capacity 75, af=0.05
        # 8 stops with 40 people waiting at most, then terminus
        waiting = [40, 35, 30, 25, 20, 15, 10, 5, 0]
        stops = make_stops(9, waiting)

        vA = make_vehicle(vehicle_id="trip-early", current_stop_sequence=5, capacity=75)
        vB = make_vehicle(vehicle_id="trip-late", current_stop_sequence=1, capacity=75)
        snap = make_snapshot(stops, (vA, vB))

        engine = PredictionEngine()
        result = engine.predict_route(snap)

        preds = {vp.vehicle_id: vp for vp in result.vehicle_predictions}

        # Vehicle "trip-early" starts at stop 5, walks 5-8 (4 predictions)
        assert len(preds["trip-early"].stops) == 4

        # Vehicle "trip-late" starts at stop 1, walks 1-8 (8 predictions)
        assert len(preds["trip-late"].stops) == 8

        # With 180 total waiting and 150 combined capacity, stranded likely > 0
        total_demand = sum(w for w in waiting if w)
        total_boarded = sum(
            sp.boarded for vp in result.vehicle_predictions for sp in vp.stops
        )
        total_stranded = sum(result.stranded_at_stops.values())
        assert total_boarded + total_stranded == total_demand


# ==========================================================================
# Alighting model behaviour
# ==========================================================================


class TestAlightingModel:
    """Deeper tests for alighting fraction behaviour."""

    def test_high_alighting_fraction_drains_bus(self):
        # af=0.5: half the load alights each stop
        # Vehicle starts with 64 passengers, no waiting at any stop
        # Stop 1: alight=round(64*0.5)=32, load=32, board=0
        # Stop 2: alight=round(32*0.5)=16, load=16, board=0
        # Stop 3: alight=round(16*0.5)=8, load=8, board=0
        # Stop 4: alight=round(8*0.5)=4, load=4, board=0
        stops = make_stops(5, [0, 0, 0, 0, 0])
        vehicle = make_vehicle(passenger_count=64, capacity=100)
        snap = make_snapshot(stops, (vehicle,))

        engine = PredictionEngine()
        result = engine.predict_route(snap, alighting_fraction=0.5)
        loads = [sp.predicted_passengers for sp in result.vehicle_predictions[0].stops]
        assert loads == [32, 16, 8, 4]

    def test_alighting_clamp_never_negative_load(self):
        # Even with af=1.0 (extreme), load should never go negative
        stops = make_stops(4, [10, 10, 10, 0])
        vehicle = make_vehicle(passenger_count=5, capacity=50)
        snap = make_snapshot(stops, (vehicle,))

        engine = PredictionEngine()
        result = engine.predict_route(snap, alighting_fraction=1.0)
        for sp in result.vehicle_predictions[0].stops:
            assert sp.predicted_passengers >= 0
            assert sp.alighted >= 0

    def test_alighting_frees_capacity_mid_route(self, engine):
        # Bus fills up at stop 1, some alight at stop 2 allowing more boarding
        # capacity=20, stop1 has 25 waiting, stop2 has 15 waiting, af=0.05
        # stop1: alight=0, board=min(25,20)=20, load=20. remaining[0]=5
        # stop2: alight=round(20*0.05)=1, load=19, board=min(15,1)=1, load=20. remaining[1]=14
        stops = make_stops(3, [25, 15, 0])
        vehicle = make_vehicle(current_stop_sequence=1, capacity=20)
        snap = make_snapshot(stops, (vehicle,))

        result = engine.predict_route(snap)
        sp2 = result.vehicle_predictions[0].stops[1]

        assert sp2.alighted == 1
        assert sp2.boarded == 1
        assert sp2.predicted_passengers == 20

    def test_config_alighting_fraction_used(self):
        config = PredictionConfig(alighting_fraction=0.2)
        engine = PredictionEngine(config=config)

        # load=50, af=0.2 -> alight=round(50*0.2)=10
        stops = make_stops(2, [0, 0])
        vehicle = make_vehicle(passenger_count=50, capacity=75)
        snap = make_snapshot(stops, (vehicle,))

        result = engine.predict_route(snap)
        assert result.vehicle_predictions[0].stops[0].alighted == 10

    def test_per_call_alighting_overrides_config(self):
        config = PredictionConfig(alighting_fraction=0.2)
        engine = PredictionEngine(config=config)

        stops = make_stops(2, [0, 0])
        vehicle = make_vehicle(passenger_count=50, capacity=75)
        snap = make_snapshot(stops, (vehicle,))

        # Override with 0.0 -> no alighting
        result = engine.predict_route(snap, alighting_fraction=0.0)
        assert result.vehicle_predictions[0].stops[0].alighted == 0


# ==========================================================================
# Conservation of passengers (invariant)
# ==========================================================================


class TestConservationInvariant:
    """The total demand must equal total boarded + total stranded."""

    def _check_conservation(self, result, total_demand):
        total_boarded = sum(
            sp.boarded for vp in result.vehicle_predictions for sp in vp.stops
        )
        total_stranded = sum(result.stranded_at_stops.values())
        assert total_boarded + total_stranded == total_demand

    def test_conservation_single_vehicle(self, engine):
        waiting = [10, 20, 15, 5, 0]
        stops = make_stops(5, waiting)
        vehicle = make_vehicle(current_stop_sequence=1, capacity=100)
        snap = make_snapshot(stops, (vehicle,))

        result = engine.predict_route(snap, alighting_fraction=0.0)
        self._check_conservation(result, sum(w for w in waiting if w))

    def test_conservation_multiple_vehicles(self, engine):
        waiting = [30, 25, 20, 15, 10, 0]
        stops = make_stops(6, waiting)
        vehicles = (
            make_vehicle(vehicle_id="trip-A", current_stop_sequence=1, capacity=30),
            make_vehicle(vehicle_id="trip-B", current_stop_sequence=3, capacity=30),
        )
        snap = make_snapshot(stops, vehicles)

        result = engine.predict_route(snap, alighting_fraction=0.0)
        self._check_conservation(result, sum(w for w in waiting if w))

    def test_conservation_with_alighting(self, engine):
        # With alighting, the invariant still holds because alighting doesn't
        # create or destroy waiting passengers -- it only affects onboard load.
        waiting = [20, 15, 10, 5, 0]
        stops = make_stops(5, waiting)
        vehicle = make_vehicle(current_stop_sequence=1, capacity=50)
        snap = make_snapshot(stops, (vehicle,))

        result = engine.predict_route(snap, alighting_fraction=0.1)
        self._check_conservation(result, sum(w for w in waiting if w))

    def test_conservation_with_none_stops(self, engine):
        # None stops contribute 0 to demand
        waiting = [10, None, 20, None, 0]
        stops = make_stops(5, waiting)
        vehicle = make_vehicle(current_stop_sequence=1, capacity=100)
        snap = make_snapshot(stops, (vehicle,))

        result = engine.predict_route(snap, alighting_fraction=0.0)
        total_demand = sum(w for w in waiting if w is not None and w > 0)
        self._check_conservation(result, total_demand)


# ==========================================================================
# Non-sequential stop sequences
# ==========================================================================


class TestNonSequentialStops:
    """Route stops may have non-contiguous sequence numbers (e.g., 10, 20, 30)."""

    def test_gaps_in_stop_sequences(self, engine):
        # Stop sequences: 10, 20, 30, 40 (with gaps)
        stops = (
            StopState(stop_id="A", sequence=10, people_waiting=5),
            StopState(stop_id="B", sequence=20, people_waiting=8),
            StopState(stop_id="C", sequence=30, people_waiting=3),
            StopState(stop_id="D", sequence=40, people_waiting=0),  # terminus
        )
        vehicle = VehicleSnapshot(
            vehicle_id="v1", route_id="r1", capacity=75, current_stop_sequence=10,
        )
        snap = RouteSnapshot(route_id="r1", direction_id=0, stops=stops, vehicles=(vehicle,))

        result = engine.predict_route(snap, alighting_fraction=0.0)
        vp = result.vehicle_predictions[0]

        assert len(vp.stops) == 3  # A, B, C (D is terminus)
        assert [sp.stop_id for sp in vp.stops] == ["A", "B", "C"]
        assert [sp.boarded for sp in vp.stops] == [5, 8, 3]

    def test_vehicle_mid_route_with_gaps(self, engine):
        stops = (
            StopState(stop_id="A", sequence=10, people_waiting=5),
            StopState(stop_id="B", sequence=20, people_waiting=8),
            StopState(stop_id="C", sequence=30, people_waiting=3),
            StopState(stop_id="D", sequence=40, people_waiting=0),
        )
        vehicle = VehicleSnapshot(
            vehicle_id="v1", route_id="r1", capacity=75, current_stop_sequence=20,
        )
        snap = RouteSnapshot(route_id="r1", direction_id=0, stops=stops, vehicles=(vehicle,))

        result = engine.predict_route(snap, alighting_fraction=0.0)
        vp = result.vehicle_predictions[0]

        assert len(vp.stops) == 2  # B, C
        assert [sp.stop_id for sp in vp.stops] == ["B", "C"]


# ==========================================================================
# Multiple vehicles at different capacities
# ==========================================================================


class TestMixedCapacities:
    """Vehicles with different capacities on the same route."""

    def test_small_and_large_bus(self, engine):
        # Small bus (cap=20) and large bus (cap=75) at same stop
        # 50 people waiting. af=0.0
        # trip-A (lower id) processes first: boards 20. remaining=30
        # trip-B: boards 30. remaining=0. No stranded.
        stops = make_stops(2, [50, 0])
        vA = make_vehicle(vehicle_id="trip-A", capacity=20, current_stop_sequence=1)
        vB = make_vehicle(vehicle_id="trip-B", capacity=75, current_stop_sequence=1)
        snap = make_snapshot(stops, (vA, vB))

        result = engine.predict_route(snap, alighting_fraction=0.0)
        preds = {vp.vehicle_id: vp for vp in result.vehicle_predictions}

        assert preds["trip-A"].stops[0].boarded == 20
        assert preds["trip-B"].stops[0].boarded == 30
        assert result.stranded_at_stops == {}


# ==========================================================================
# ThresholdEvaluator -- additional edge cases
# ==========================================================================


class TestThresholdEvaluatorAdditional:

    def test_exactly_at_threshold_triggers(self):
        # peak_occupancy_pct == occupancy_threshold exactly -> should trigger
        evaluator = ThresholdEvaluator(occupancy_threshold=0.8, min_stranded=999)
        vp = _make_vp(peak_load=60, capacity=75)  # 60/75 = 0.8 exactly
        result = _make_result((vp,))

        alert = evaluator.evaluate(result)
        assert alert is not None
        assert alert.trigger_detail["trigger"] == "occupancy"

    def test_exactly_at_stranded_threshold_triggers(self):
        evaluator = ThresholdEvaluator(occupancy_threshold=0.99, min_stranded=5)
        vp = _make_vp(peak_load=10, capacity=75)
        result = _make_result((vp,), stranded={"s1": 3, "s2": 2})  # total=5 exactly

        alert = evaluator.evaluate(result)
        assert alert is not None
        assert alert.trigger_detail["trigger"] == "stranded"

    def test_multiple_vehicles_worst_selected(self):
        evaluator = ThresholdEvaluator(occupancy_threshold=0.8, min_stranded=999)
        vp1 = _make_vp(vehicle_id="trip-low", peak_load=50, capacity=75)   # 0.667
        vp2 = _make_vp(vehicle_id="trip-high", peak_load=70, capacity=75)  # 0.933
        result = _make_result((vp1, vp2))

        alert = evaluator.evaluate(result)
        assert alert is not None
        assert alert.vehicle_id == "trip-high"

    def test_alert_trigger_detail_completeness(self):
        evaluator = ThresholdEvaluator(
            occupancy_threshold=0.9, min_stranded=5, min_confidence=0.3,
        )
        vp = _make_vp(peak_load=70, capacity=75)
        result = _make_result((vp,), stranded={"s1": 10})

        alert = evaluator.evaluate(result)
        assert alert is not None

        detail = alert.trigger_detail
        assert "trigger" in detail
        assert "occupancy_threshold" in detail
        assert "peak_occupancy" in detail
        assert "total_stranded" in detail
        assert "min_confidence" in detail
        assert detail["occupancy_threshold"] == 0.9
        assert detail["min_confidence"] == 0.3

    def test_alert_direction_id_propagated(self):
        evaluator = ThresholdEvaluator(occupancy_threshold=0.5, min_stranded=1)
        vp = _make_vp(peak_load=50, capacity=75)
        result = RoutePredictionResult(
            route_id="route-1",
            direction_id=1,
            vehicle_predictions=(vp,),
            stranded_at_stops={},
        )

        alert = evaluator.evaluate(result)
        assert alert is not None
        assert alert.direction_id == 1


# ==========================================================================
# No vehicles on route
# ==========================================================================


class TestNoVehicles:

    def test_no_vehicles_stranded_equals_waiting(self, engine):
        # If there are no vehicles, everyone is stranded
        stops = make_stops(4, [10, 20, 15, 0])
        snap = make_snapshot(stops, ())

        result = engine.predict_route(snap)
        assert result.vehicle_predictions == ()
        assert result.stranded_at_stops == {"stop-1": 10, "stop-2": 20, "stop-3": 15}

    def test_no_vehicles_no_waiting_no_stranded(self, engine):
        stops = make_stops(3, [0, 0, 0])
        snap = make_snapshot(stops, ())

        result = engine.predict_route(snap)
        assert result.stranded_at_stops == {}


# ==========================================================================
# Negative capacity
# ==========================================================================


class TestNegativeCapacity:

    def test_negative_capacity_vehicle_skipped(self, engine):
        stops = make_stops(3, [10, 10, 0])
        vehicle = make_vehicle(capacity=-5)
        snap = make_snapshot(stops, (vehicle,))

        result = engine.predict_route(snap)
        assert len(result.vehicle_predictions) == 0
