"""Tests for Simulator.orchestrator.Orchestrator."""

import json
import random
from unittest.mock import MagicMock, call

import pytest
from Simulator import config
from Simulator.orchestrator import Orchestrator


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.publish = MagicMock()
    return client


class TestOrchestratorBuild:

    def test_deduplicates_shared_stops(self, mock_client):
        orch = Orchestrator(mock_client, random.Random(42))
        # Total unique stops across 12 routes should be < sum of all route lengths
        total_route_stops = sum(
            len(r["stop_ids"]) for r in config.ROUTES.values()
        )
        unique_count = len(orch.stop_ids)
        assert unique_count < total_route_stops, (
            "Shared stops should be deduplicated"
        )

    def test_all_stop_ids_present(self, mock_client):
        orch = Orchestrator(mock_client, random.Random(42))
        all_expected = set()
        for route_cfg in config.ROUTES.values():
            all_expected.update(route_cfg["stop_ids"])
        assert set(orch.stop_ids) == all_expected

    def test_stagger_offsets_spread(self, mock_client):
        orch = Orchestrator(mock_client, random.Random(42))
        nexts = [e.next_publish for e in orch._stops]
        # All offsets should be distinct (no two stops fire at exactly the same time)
        assert len(set(nexts)) == len(nexts)


class TestBackfill:

    def test_publishes_for_every_stop(self, mock_client):
        orch = Orchestrator(mock_client, random.Random(42))
        count = orch.backfill()
        assert count == len(orch.stop_ids)
        assert mock_client.publish.call_count == count

    def test_payload_format(self, mock_client):
        orch = Orchestrator(mock_client, random.Random(42))
        orch.backfill()
        first_call = mock_client.publish.call_args_list[0]
        topic = first_call.kwargs.get("topic") or first_call[1].get("topic")
        payload_bytes = first_call.kwargs.get("payload") or first_call[1].get("payload")

        assert topic.startswith("edge/")
        assert topic.endswith("/crowdCount")

        data = json.loads(payload_bytes.decode())
        assert "device_id" in data
        assert "timestamp" in data
        assert "count" in data
        assert isinstance(data["count"], int)
        assert data["count"] >= 0
        assert data["zone"] == "default"


class TestLogStats:

    def test_does_not_raise(self, mock_client):
        orch = Orchestrator(mock_client, random.Random(42))
        orch.backfill()
        orch.log_stats()
