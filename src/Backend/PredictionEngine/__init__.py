"""PredictionEngine -- sequential route simulation and pluggable evaluation."""

from .snapshot import (
    StopState,
    VehicleSnapshot,
    RouteSnapshot,
    StopPrediction,
    VehiclePrediction,
    RoutePredictionResult,
)
from .engine import PredictionConfig, PredictionEngine
from .evaluator import Alert, Evaluator, ThresholdEvaluator, EvaluatorRegistry
from .snapshot_builder import SnapshotBuilder

__all__ = [
    # Snapshot models
    "StopState",
    "VehicleSnapshot",
    "RouteSnapshot",
    "StopPrediction",
    "VehiclePrediction",
    "RoutePredictionResult",
    # Engine
    "PredictionConfig",
    "PredictionEngine",
    # Evaluator
    "Alert",
    "Evaluator",
    "ThresholdEvaluator",
    "EvaluatorRegistry",
    # Snapshot builder
    "SnapshotBuilder",
]
