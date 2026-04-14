"""Per-stop state machine that produces realistic crowd-count values."""

from __future__ import annotations

import random
import time

from . import config
from . import profiles


class StopSimulator:
    """Owns the mutable count state for a single bus stop.

    Each tick, :meth:`tick` returns a new count that drifts toward a
    demand-driven target with Gaussian noise, and periodically applies
    vehicle-arrival dips.
    """

    def __init__(
        self,
        stop_id: str,
        position_weight: float,
        route_multiplier: float,
        base_cap: int,
        headway_seconds: float,
        rng: random.Random,
    ):
        self.stop_id = stop_id
        self._pos_weight = position_weight
        self._route_mult = route_multiplier
        self._base_cap = base_cap
        self._headway = headway_seconds
        self._rng = rng

        self.count: int = 0
        self._next_dip: float = time.monotonic() + self._schedule_dip_delay()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def seed_initial(self, sim_hour: float) -> int:
        """Set an initial count based on the current time-of-day profile."""
        target = self._target(sim_hour)
        self.count = max(0, round(target + self._rng.gauss(0, 1)))
        return self.count

    def tick(self, sim_hour: float) -> int:
        """Advance the state by one step and return the new count."""
        now = time.monotonic()

        if now >= self._next_dip and self.count > 0:
            drop_frac = self._rng.uniform(
                config.DIP_DROP_MIN, config.DIP_DROP_MAX,
            )
            self.count = max(0, self.count - round(self.count * drop_frac))
            self._next_dip = now + self._schedule_dip_delay()

        target = self._target(sim_hour)
        bias = (target - self.count) * config.BIAS_STRENGTH
        delta = self._rng.gauss(bias, config.MAX_DELTA_STDDEV)
        hard_cap = round(self._base_cap * self._route_mult * 2.5)
        self.count = self._clamp(round(self.count + delta), 0, hard_cap)
        return self.count

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _target(self, sim_hour: float) -> float:
        tod = profiles.time_of_day_multiplier(sim_hour)
        return self._base_cap * tod * self._pos_weight * self._route_mult

    def _schedule_dip_delay(self) -> float:
        jitter = self._rng.uniform(-0.25, 0.25) * self._headway
        return max(30.0, self._headway + jitter)

    @staticmethod
    def _clamp(value: int, lo: int, hi: int) -> int:
        return max(lo, min(hi, value))
