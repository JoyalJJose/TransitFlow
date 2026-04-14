"""Tests for Simulator.generator.StopSimulator."""

import random
import time
from unittest.mock import patch

import pytest
from Simulator.generator import StopSimulator


def _make_sim(
    stop_id: str = "test-stop",
    position_weight: float = 0.7,
    route_multiplier: float = 1.0,
    base_cap: int = 10,
    headway_seconds: float = 900.0,
    seed: int = 42,
) -> StopSimulator:
    return StopSimulator(
        stop_id=stop_id,
        position_weight=position_weight,
        route_multiplier=route_multiplier,
        base_cap=base_cap,
        headway_seconds=headway_seconds,
        rng=random.Random(seed),
    )


class TestSeedInitial:

    def test_returns_non_negative(self):
        sim = _make_sim()
        count = sim.seed_initial(sim_hour=8.5)
        assert count >= 0

    def test_peak_hour_higher_than_night(self):
        counts_peak = []
        counts_night = []
        for s in range(50):
            sim_p = _make_sim(seed=s)
            sim_n = _make_sim(seed=s)
            counts_peak.append(sim_p.seed_initial(8.5))
            counts_night.append(sim_n.seed_initial(3.0))
        assert sum(counts_peak) > sum(counts_night)


class TestTick:

    def test_temporal_coherence(self):
        """Consecutive ticks should not jump by more than ~10."""
        sim = _make_sim(base_cap=10)
        sim.seed_initial(8.5)
        prev = sim.count
        for _ in range(100):
            new = sim.tick(8.5)
            assert abs(new - prev) <= 15, (
                f"Jump too large: {prev} -> {new}"
            )
            prev = new

    def test_count_never_negative(self):
        sim = _make_sim(base_cap=3)
        sim.seed_initial(3.0)
        for _ in range(200):
            c = sim.tick(3.0)
            assert c >= 0

    def test_count_bounded_by_hard_cap(self):
        sim = _make_sim(base_cap=10, route_multiplier=1.3)
        sim.seed_initial(8.5)
        hard_cap = round(10 * 1.3 * 2.5)
        for _ in range(200):
            c = sim.tick(8.5)
            assert c <= hard_cap

    def test_drift_toward_target(self):
        """Over many ticks at peak, average count should be near the target."""
        sim = _make_sim(base_cap=10, position_weight=1.0, seed=99)
        sim.seed_initial(8.5)
        counts = []
        for _ in range(300):
            counts.append(sim.tick(8.5))
        avg = sum(counts) / len(counts)
        # target = 10 * 1.0 * 1.0 * 1.0 = 10 (peak, full weight, single route)
        assert 5 < avg < 15, f"Average {avg} too far from target ~10"


class TestVehicleDip:

    def test_dip_reduces_count(self):
        """When a dip fires, count should drop."""
        sim = _make_sim(base_cap=10, headway_seconds=0.01)
        sim.seed_initial(8.5)
        sim.count = 12
        # Force the dip to be in the past
        sim._next_dip = time.monotonic() - 1
        new = sim.tick(8.5)
        assert new < 12


class TestClamp:

    def test_clamps_low(self):
        assert StopSimulator._clamp(-5, 0, 100) == 0

    def test_clamps_high(self):
        assert StopSimulator._clamp(150, 0, 100) == 100

    def test_passes_through(self):
        assert StopSimulator._clamp(50, 0, 100) == 50
