"""Immutable data models for point-in-time route snapshots and prediction results.

The prediction engine operates on these frozen dataclasses, never on mutable
DB state directly.  A separate SnapshotBuilder (future) is responsible for
constructing snapshots from database queries.
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Input snapshot (what the world looks like right now)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StopState:
    """One stop along a route at a point in time."""

    stop_id: str
    sequence: int
    people_waiting: int | None  # None when no edge device / offline


@dataclass(frozen=True)
class VehicleSnapshot:
    """One active vehicle (trip) on a route at a point in time.

    ``vehicle_id`` is the *trip_id* from GTFS-RT (the reliable identifier).
    ``current_stop_sequence`` is the next stop the vehicle will reach.
    ``passenger_count`` defaults to 0 (no onboard counting); non-zero if data
    becomes available in the future.
    """

    vehicle_id: str
    route_id: str
    capacity: int
    current_stop_sequence: int
    passenger_count: int = 0


@dataclass(frozen=True)
class RouteSnapshot:
    """Complete snapshot for one route + direction."""

    route_id: str
    direction_id: int
    stops: tuple[StopState, ...]
    vehicles: tuple[VehicleSnapshot, ...]


# ---------------------------------------------------------------------------
# Prediction output
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StopPrediction:
    """Predicted state at one stop for one vehicle."""

    stop_id: str
    stop_sequence: int
    predicted_passengers: int   # estimated load after boarding (capped at capacity)
    boarded: int
    alighted: int
    people_waiting_at_stop: int | None
    has_data: bool              # True if this stop had edge device data


@dataclass(frozen=True)
class VehiclePrediction:
    """Aggregated prediction for one vehicle's remaining journey."""

    vehicle_id: str
    route_id: str
    vehicle_capacity: int
    stops: tuple[StopPrediction, ...]
    peak_load: int
    peak_occupancy_pct: float   # peak_load / capacity
    confidence: float           # fraction of predicted stops that had data


@dataclass(frozen=True)
class RoutePredictionResult:
    """Full prediction output for one route + direction."""

    route_id: str
    direction_id: int
    vehicle_predictions: tuple[VehiclePrediction, ...]
    stranded_at_stops: dict[str, int]  # stop_id -> passengers left behind
