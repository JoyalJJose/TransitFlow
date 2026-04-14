"""Pluggable condition evaluation for prediction results.

Defines the ``Evaluator`` protocol (any object with an ``evaluate`` method),
a concrete ``ThresholdEvaluator`` with dual triggers (occupancy + stranded),
and an ``EvaluatorRegistry`` that dispatches to per-route evaluator instances.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .snapshot import RoutePredictionResult


# ---------------------------------------------------------------------------
# Alert dataclass (evaluator-agnostic output)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Alert:
    """Scheduling alert emitted when a route needs attention."""

    route_id: str
    direction_id: int
    vehicle_id: str               # worst-case vehicle
    trigger_stop_id: str          # worst-case stop
    predicted_passengers: int
    vehicle_capacity: int
    predicted_occupancy_pct: float
    total_stranded: int           # sum of stranded across the route
    trigger_detail: dict = field(default_factory=dict)
    message: str = ""


# ---------------------------------------------------------------------------
# Evaluator protocol
# ---------------------------------------------------------------------------

class Evaluator(Protocol):
    """Any object satisfying this protocol can evaluate prediction results."""

    def evaluate(self, result: RoutePredictionResult) -> Alert | None: ...


# ---------------------------------------------------------------------------
# ThresholdEvaluator
# ---------------------------------------------------------------------------

class ThresholdEvaluator:
    """Alert when any vehicle's peak load exceeds a capacity threshold,
    OR when total stranded passengers exceed a minimum count.

    Vehicles with ``confidence`` below *min_confidence* are excluded from
    the occupancy check (too little data to trust).  The stranded check is
    **not** gated by confidence because stranded counts are inherently
    conservative (unknown stops contribute 0 passengers).
    """

    def __init__(
        self,
        occupancy_threshold: float = 0.9,
        min_stranded: int = 5,
        min_confidence: float = 0.3,
    ) -> None:
        self._occupancy_threshold = occupancy_threshold
        self._min_stranded = min_stranded
        self._min_confidence = min_confidence

    def evaluate(self, result: RoutePredictionResult) -> Alert | None:
        if not result.vehicle_predictions:
            return None

        # --- Check 1: occupancy (confidence-gated) --------------------------
        qualifying = [
            vp for vp in result.vehicle_predictions
            if vp.confidence >= self._min_confidence
        ]

        worst_occupancy_vp = None
        if qualifying:
            worst_occupancy_vp = max(qualifying, key=lambda vp: vp.peak_occupancy_pct)
            if worst_occupancy_vp.peak_occupancy_pct < self._occupancy_threshold:
                worst_occupancy_vp = None

        # --- Check 2: stranded (not gated by confidence) ---------------------
        total_stranded = sum(result.stranded_at_stops.values())
        stranded_triggered = total_stranded >= self._min_stranded

        if worst_occupancy_vp is None and not stranded_triggered:
            return None

        # --- Build alert for the worst case ----------------------------------
        trigger: str
        if worst_occupancy_vp is not None and stranded_triggered:
            trigger = "occupancy_and_stranded"
        elif worst_occupancy_vp is not None:
            trigger = "occupancy"
        else:
            trigger = "stranded"

        # Pick the vehicle with the highest peak occupancy for the alert.
        # If no vehicle qualified on occupancy, fall back to the overall worst.
        if worst_occupancy_vp is not None:
            alert_vp = worst_occupancy_vp
        else:
            alert_vp = max(
                result.vehicle_predictions,
                key=lambda vp: vp.peak_occupancy_pct,
            )

        # Find the stop where this vehicle's load is highest
        worst_stop = max(alert_vp.stops, key=lambda sp: sp.predicted_passengers)

        return Alert(
            route_id=result.route_id,
            direction_id=result.direction_id,
            vehicle_id=alert_vp.vehicle_id,
            trigger_stop_id=worst_stop.stop_id,
            predicted_passengers=worst_stop.predicted_passengers,
            vehicle_capacity=alert_vp.vehicle_capacity,
            predicted_occupancy_pct=alert_vp.peak_occupancy_pct,
            total_stranded=total_stranded,
            trigger_detail={
                "trigger": trigger,
                "occupancy_threshold": self._occupancy_threshold,
                "peak_occupancy": alert_vp.peak_occupancy_pct,
                "total_stranded": total_stranded,
                "min_confidence": self._min_confidence,
            },
            message=(
                f"Route {result.route_id} dir {result.direction_id}: "
                f"{trigger} alert — vehicle {alert_vp.vehicle_id} peak "
                f"{alert_vp.peak_occupancy_pct:.0%} occupancy, "
                f"{total_stranded} stranded"
            ),
        )


# ---------------------------------------------------------------------------
# EvaluatorRegistry (per-route dispatch)
# ---------------------------------------------------------------------------

class EvaluatorRegistry:
    """Route-level evaluator dispatch.

    Each route can have its own ``Evaluator`` instance (or share one).
    Routes without a specific assignment use the *default*.
    """

    def __init__(self, default: Evaluator) -> None:
        self._default = default
        self._by_route: dict[str, Evaluator] = {}

    def register(self, route_id: str, evaluator: Evaluator) -> None:
        self._by_route[route_id] = evaluator

    def get(self, route_id: str) -> Evaluator:
        return self._by_route.get(route_id, self._default)

    def evaluate(self, result: RoutePredictionResult) -> Alert | None:
        return self.get(result.route_id).evaluate(result)
