"""Traffic-light mapping helpers.

Convert raw numbers (people waiting, predicted occupancy %) into a low-
granularity colour state so downstream apps don't have to re-implement
thresholds or explain raw values to users.
"""

from __future__ import annotations

import config


def stop_state(count: int | None) -> str:
    """Map a people-waiting count to green / amber / red / unknown."""
    if count is None:
        return "unknown"
    if count < config.WAIT_AMBER:
        return "green"
    if count < config.WAIT_RED:
        return "amber"
    return "red"


def occupancy_state(pct: float | None) -> str:
    """Map a predicted occupancy percentage to green / amber / red / unknown."""
    if pct is None:
        return "unknown"
    if pct < config.OCC_AMBER:
        return "green"
    if pct < config.OCC_RED:
        return "amber"
    return "red"
