"""Pytest fixtures for PredictionEngine unit tests.

No external dependencies -- the prediction engine is pure computation on
frozen dataclasses.  These helpers build route snapshots quickly.
"""

import os
import sys

import pytest

# ---------------------------------------------------------------------------
# Path setup -- make PredictionEngine importable
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
BACKEND_DIR = os.path.join(SRC_DIR, "Backend")

for p in (SRC_DIR, BACKEND_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from PredictionEngine.snapshot import (
    RouteSnapshot,
    StopState,
    VehicleSnapshot,
)
from PredictionEngine.engine import PredictionEngine


# ---------------------------------------------------------------------------
# Builder helpers
# ---------------------------------------------------------------------------

def make_stops(
    count: int,
    people_waiting: list[int | None] | None = None,
    start_seq: int = 1,
) -> tuple[StopState, ...]:
    """Build an ordered tuple of StopStates.

    *people_waiting* defaults to 10 at every stop if not provided.
    """
    if people_waiting is None:
        people_waiting = [10] * count
    assert len(people_waiting) == count
    return tuple(
        StopState(
            stop_id=f"stop-{start_seq + i}",
            sequence=start_seq + i,
            people_waiting=people_waiting[i],
        )
        for i in range(count)
    )


def make_vehicle(
    vehicle_id: str = "trip-A",
    route_id: str = "route-1",
    capacity: int = 75,
    current_stop_sequence: int = 1,
    passenger_count: int = 0,
) -> VehicleSnapshot:
    return VehicleSnapshot(
        vehicle_id=vehicle_id,
        route_id=route_id,
        capacity=capacity,
        current_stop_sequence=current_stop_sequence,
        passenger_count=passenger_count,
    )


def make_snapshot(
    stops: tuple[StopState, ...],
    vehicles: tuple[VehicleSnapshot, ...],
    route_id: str = "route-1",
    direction_id: int = 0,
) -> RouteSnapshot:
    return RouteSnapshot(
        route_id=route_id,
        direction_id=direction_id,
        stops=stops,
        vehicles=vehicles,
    )


@pytest.fixture
def engine() -> PredictionEngine:
    return PredictionEngine()
