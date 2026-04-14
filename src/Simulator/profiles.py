"""Demand profiles and stop-level weighting functions.

All functions are pure (no side effects) and operate on wall-clock time
that has already been scaled by ``SIM_TIME_SCALE``.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import TYPE_CHECKING

from . import config

if TYPE_CHECKING:
    from collections.abc import Mapping

# ---------------------------------------------------------------------------
# Time-of-day demand curve
# ---------------------------------------------------------------------------

# (hour_start, multiplier) breakpoints – linearly interpolated between them.
_DEMAND_CURVE: list[tuple[float, float]] = [
    (0.0, 0.10),
    (5.0, 0.10),
    (6.0, 0.20),
    (6.5, 0.20),
    (7.0, 0.60),
    (7.5, 1.00),
    (9.5, 1.00),
    (10.0, 0.50),
    (12.0, 0.50),
    (12.5, 0.60),
    (14.0, 0.60),
    (14.5, 0.50),
    (16.0, 0.50),
    (16.5, 1.00),
    (18.5, 1.00),
    (19.0, 0.40),
    (21.0, 0.40),
    (22.0, 0.10),
    (24.0, 0.10),
]


def time_of_day_multiplier(hour: float) -> float:
    """Return the demand multiplier for *hour* (0.0–24.0), interpolated."""
    hour = hour % 24.0
    for i in range(len(_DEMAND_CURVE) - 1):
        h0, m0 = _DEMAND_CURVE[i]
        h1, m1 = _DEMAND_CURVE[i + 1]
        if h0 <= hour < h1:
            t = (hour - h0) / (h1 - h0) if h1 != h0 else 0.0
            return m0 + t * (m1 - m0)
    return _DEMAND_CURVE[-1][1]


# ---------------------------------------------------------------------------
# Stop-position weighting (bell-curve along route)
# ---------------------------------------------------------------------------

def position_weight(index: int, total_stops: int) -> float:
    """Busier near the middle of the route, quieter at termini.

    Returns a value in [0.4, 1.0].
    """
    if total_stops <= 1:
        return 1.0
    return 0.4 + 0.6 * math.sin(math.pi * index / (total_stops - 1))


# ---------------------------------------------------------------------------
# Multi-route stop multiplier
# ---------------------------------------------------------------------------

def build_route_multipliers(
    routes: Mapping[str, dict],
) -> dict[str, float]:
    """Return ``{stop_id: multiplier}`` based on how many routes each stop serves."""
    stop_counts: Counter[str] = Counter()
    for route_cfg in routes.values():
        for sid in route_cfg["stop_ids"]:
            stop_counts[sid] += 1
    return {
        sid: 1.0 + 0.3 * (cnt - 1) for sid, cnt in stop_counts.items()
    }


# ---------------------------------------------------------------------------
# Base capacity assignment (deterministic per stop_id)
# ---------------------------------------------------------------------------

def base_cap_for_stop(stop_id: str) -> int:
    """Deterministic base capacity in [BASE_CAP_MIN, BASE_CAP_MAX].

    Uses a hash so the same stop always gets the same cap across restarts
    (unless ``SIM_RANDOM_SEED`` changes the global RNG, which is separate).
    """
    h = hash(stop_id) & 0xFFFFFFFF
    span = config.BASE_CAP_MAX - config.BASE_CAP_MIN
    return config.BASE_CAP_MIN + (h % (span + 1))
