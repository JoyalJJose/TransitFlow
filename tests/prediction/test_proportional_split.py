# *** TEST FILE - SAFE TO DELETE ***
"""Unit tests for the proportional_split() pure function."""

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
BACKEND_DIR = os.path.join(SRC_DIR, "Backend")

for p in (SRC_DIR, BACKEND_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from PredictionEngine.snapshot_builder import proportional_split


class TestProportionalSplit:

    def test_two_routes_basic(self):
        """3 min vs 8 min example from the design doc."""
        etas = {("routeA", 0): 180, ("routeB", 0): 480}
        share_a = proportional_split(etas, "routeA", 0)
        share_b = proportional_split(etas, "routeB", 0)

        assert 0.70 < share_a < 0.75
        assert 0.25 < share_b < 0.30
        assert abs(share_a + share_b - 1.0) < 1e-9

    def test_equal_etas_equal_shares(self):
        etas = {("r1", 0): 300, ("r2", 0): 300}
        assert proportional_split(etas, "r1", 0) == 0.5
        assert proportional_split(etas, "r2", 0) == 0.5

    def test_three_routes(self):
        etas = {("r1", 0): 60, ("r2", 0): 120, ("r3", 0): 360}
        s1 = proportional_split(etas, "r1", 0)
        s2 = proportional_split(etas, "r2", 0)
        s3 = proportional_split(etas, "r3", 0)

        assert s1 > s2 > s3
        assert abs(s1 + s2 + s3 - 1.0) < 1e-9

    def test_target_not_in_etas_returns_one(self):
        etas = {("r1", 0): 180, ("r2", 0): 480}
        assert proportional_split(etas, "r_missing", 0) == 1.0

    def test_direction_matters(self):
        etas = {("r1", 0): 180, ("r1", 1): 480}
        share_d0 = proportional_split(etas, "r1", 0)
        share_d1 = proportional_split(etas, "r1", 1)
        assert share_d0 > share_d1

    def test_min_eta_clamp(self):
        """ETAs below min_eta are clamped, preventing division by tiny number."""
        etas = {("r1", 0): 5, ("r2", 0): 600}
        share = proportional_split(etas, "r1", 0, min_eta=30)
        # r1 clamped to 30s: w1 = 1/30, w2 = 1/600
        # share = (1/30) / (1/30 + 1/600) = 20/21 ≈ 0.952
        assert 0.94 < share < 0.96

    def test_single_route_gets_full_share(self):
        etas = {("r1", 0): 300}
        assert proportional_split(etas, "r1", 0) == 1.0

    def test_very_large_eta_gets_tiny_share(self):
        etas = {("r1", 0): 60, ("r2", 0): 36000}
        share_far = proportional_split(etas, "r2", 0)
        assert share_far < 0.01

    def test_many_routes_sum_to_one(self):
        etas = {(f"r{i}", 0): (i + 1) * 60 for i in range(10)}
        total = sum(
            proportional_split(etas, f"r{i}", 0)
            for i in range(10)
        )
        assert abs(total - 1.0) < 1e-9

    def test_empty_etas_returns_one(self):
        assert proportional_split({}, "r1", 0) == 1.0
