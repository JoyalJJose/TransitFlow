"""Tests for Simulator.profiles – demand curves, weighting, multipliers."""

import math
import pytest
from Simulator import config
from Simulator.profiles import (
    time_of_day_multiplier,
    position_weight,
    build_route_multipliers,
    base_cap_for_stop,
)


# ── time_of_day_multiplier ──────────────────────────────────────────────

class TestTimeOfDayMultiplier:

    def test_night_is_low(self):
        assert time_of_day_multiplier(3.0) == pytest.approx(0.1)

    def test_am_peak(self):
        assert time_of_day_multiplier(8.5) == pytest.approx(1.0)

    def test_pm_peak(self):
        assert time_of_day_multiplier(17.5) == pytest.approx(1.0)

    def test_midday_lower_than_peak(self):
        mid = time_of_day_multiplier(11.0)
        peak = time_of_day_multiplier(8.5)
        assert mid < peak

    def test_smooth_interpolation(self):
        """Adjacent half-hours should not jump by more than 0.5."""
        for h in range(24):
            m1 = time_of_day_multiplier(h)
            m2 = time_of_day_multiplier(h + 0.5)
            assert abs(m2 - m1) <= 0.5

    def test_wraps_at_24(self):
        assert time_of_day_multiplier(25.0) == pytest.approx(
            time_of_day_multiplier(1.0),
        )

    def test_always_positive(self):
        for h_tenth in range(240):
            h = h_tenth / 10.0
            assert time_of_day_multiplier(h) > 0


# ── position_weight ─────────────────────────────────────────────────────

class TestPositionWeight:

    def test_terminus_low(self):
        w = position_weight(0, 50)
        assert 0.39 <= w <= 0.41

    def test_mid_route_high(self):
        w = position_weight(25, 50)
        assert w > 0.95

    def test_symmetric(self):
        w_start = position_weight(5, 50)
        w_end = position_weight(44, 50)
        assert w_start == pytest.approx(w_end, abs=0.01)

    def test_single_stop_returns_one(self):
        assert position_weight(0, 1) == 1.0


# ── build_route_multipliers ─────────────────────────────────────────────

class TestRouteMultipliers:

    def test_single_route_stops_get_one(self):
        routes = {"A": {"stop_ids": ["s1", "s2", "s3"]}}
        mults = build_route_multipliers(routes)
        assert mults["s1"] == pytest.approx(1.0)

    def test_shared_stop_boosted(self):
        routes = {
            "A": {"stop_ids": ["s1", "s2"]},
            "B": {"stop_ids": ["s2", "s3"]},
        }
        mults = build_route_multipliers(routes)
        assert mults["s1"] == pytest.approx(1.0)
        assert mults["s2"] == pytest.approx(1.3)
        assert mults["s3"] == pytest.approx(1.0)

    def test_triple_shared(self):
        routes = {
            "A": {"stop_ids": ["s1"]},
            "B": {"stop_ids": ["s1"]},
            "C": {"stop_ids": ["s1"]},
        }
        mults = build_route_multipliers(routes)
        assert mults["s1"] == pytest.approx(1.6)

    def test_real_config_has_shared_stops(self):
        mults = build_route_multipliers(config.ROUTES)
        boosted = {sid: m for sid, m in mults.items() if m > 1.05}
        assert len(boosted) > 0, "Expected shared stops in the real config"


# ── base_cap_for_stop ───────────────────────────────────────────────────

class TestBaseCap:

    def test_within_range(self):
        for sid in ["stop-001", "stop-999", "8220DB000315"]:
            cap = base_cap_for_stop(sid)
            assert config.BASE_CAP_MIN <= cap <= config.BASE_CAP_MAX

    def test_deterministic(self):
        a = base_cap_for_stop("8220DB000315")
        b = base_cap_for_stop("8220DB000315")
        assert a == b
