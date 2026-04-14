"""Core prediction algorithm -- sequential route simulation.

Processes vehicles from front to back along a route over a shared mutable
array of waiting passengers.  Each vehicle alights first, then boards up to
remaining capacity, naturally handling multi-vehicle interactions without
explicit "vehicles ahead" lookups.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .snapshot import (
    RouteSnapshot,
    RoutePredictionResult,
    StopPrediction,
    VehiclePrediction,
)

logger = logging.getLogger(__name__)

_DEFAULT_ALIGHTING_FRACTION = 0.05


@dataclass(frozen=True)
class PredictionConfig:
    """Tuneable knobs for the prediction simulation."""

    alighting_fraction: float = _DEFAULT_ALIGHTING_FRACTION


class PredictionEngine:
    """Simulates vehicle journeys along a route to estimate passenger load."""

    def __init__(self, config: PredictionConfig | None = None) -> None:
        self._config = config or PredictionConfig()

    def predict_route(
        self,
        snapshot: RouteSnapshot,
        alighting_fraction: float | None = None,
    ) -> RoutePredictionResult:
        """Run the sequential simulation for every vehicle on *snapshot*.

        Returns a :class:`RoutePredictionResult` with per-vehicle predictions
        and a mapping of stranded passengers at each stop.
        """
        af = (
            alighting_fraction
            if alighting_fraction is not None
            else self._config.alighting_fraction
        )

        stops = snapshot.stops

        if len(stops) <= 1:
            return RoutePredictionResult(
                route_id=snapshot.route_id,
                direction_id=snapshot.direction_id,
                vehicle_predictions=(),
                stranded_at_stops={},
            )

        # Step 1 -- build index: stop_sequence -> array index
        seq_to_idx: dict[int, int] = {}
        remaining: list[int] = []
        has_data: list[bool] = []

        for idx, stop in enumerate(stops):
            seq_to_idx[stop.sequence] = idx
            remaining.append(stop.people_waiting if stop.people_waiting is not None else 0)
            has_data.append(stop.people_waiting is not None)

        # Step 2 -- sort vehicles: furthest-ahead first, tiebreak by vehicle_id ascending
        sorted_vehicles = sorted(
            snapshot.vehicles,
            key=lambda v: (-v.current_stop_sequence, v.vehicle_id),
        )

        # Step 3 -- simulate each vehicle
        vehicle_predictions: list[VehiclePrediction] = []

        for vehicle in sorted_vehicles:
            start_idx = seq_to_idx.get(vehicle.current_stop_sequence)

            if start_idx is None:
                logger.warning(
                    "Vehicle %s has current_stop_sequence=%d which is not in "
                    "the route's stop list for route=%s direction=%d; skipping",
                    vehicle.vehicle_id,
                    vehicle.current_stop_sequence,
                    snapshot.route_id,
                    snapshot.direction_id,
                )
                continue

            if vehicle.capacity <= 0:
                logger.warning(
                    "Vehicle %s has capacity=%d; skipping",
                    vehicle.vehicle_id,
                    vehicle.capacity,
                )
                continue

            load = vehicle.passenger_count
            stop_preds: list[StopPrediction] = []
            stops_with_data = 0
            total_stops_predicted = 0

            # Walk from current stop to second-to-last (terminus excluded)
            end_idx = len(stops) - 1  # exclusive -- terminus index
            for i in range(start_idx, end_idx):
                # 3c-i: alight
                alight = round(load * af)
                alight = min(alight, load)
                load -= alight

                # 3c-ii: board
                board = min(remaining[i], max(0, vehicle.capacity - load))
                load += board
                remaining[i] -= board

                # 3c-iii: emit StopPrediction
                stop = stops[i]
                stop_preds.append(
                    StopPrediction(
                        stop_id=stop.stop_id,
                        stop_sequence=stop.sequence,
                        predicted_passengers=load,
                        boarded=board,
                        alighted=alight,
                        people_waiting_at_stop=stop.people_waiting,
                        has_data=has_data[i],
                    )
                )

                total_stops_predicted += 1
                if has_data[i]:
                    stops_with_data += 1

            if not stop_preds:
                continue

            peak_load = max(sp.predicted_passengers for sp in stop_preds)
            confidence = (
                stops_with_data / total_stops_predicted
                if total_stops_predicted > 0
                else 0.0
            )

            vehicle_predictions.append(
                VehiclePrediction(
                    vehicle_id=vehicle.vehicle_id,
                    route_id=vehicle.route_id,
                    vehicle_capacity=vehicle.capacity,
                    stops=tuple(stop_preds),
                    peak_load=peak_load,
                    peak_occupancy_pct=peak_load / vehicle.capacity,
                    confidence=confidence,
                )
            )

        # Step 4 -- stranded passengers
        stranded: dict[str, int] = {}
        for i, count in enumerate(remaining):
            if count > 0:
                stranded[stops[i].stop_id] = count

        return RoutePredictionResult(
            route_id=snapshot.route_id,
            direction_id=snapshot.direction_id,
            vehicle_predictions=tuple(vehicle_predictions),
            stranded_at_stops=stranded,
        )
