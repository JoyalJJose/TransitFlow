"""Orchestrates all StopSimulator instances with staggered scheduling."""

from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from . import config
from . import profiles
from .generator import StopSimulator

if TYPE_CHECKING:
    import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)


@dataclass
class _StopEntry:
    sim: StopSimulator
    next_publish: float = 0.0
    interval: float = 17.5


class Orchestrator:
    """Manages stop simulators, staggered scheduling, and MQTT publishing."""

    def __init__(self, client: mqtt.Client, rng: random.Random):
        self._client = client
        self._rng = rng

        self._stops: list[_StopEntry] = []
        self._start_wall: float = 0.0
        self._start_hour: float = 0.0
        self._pub_count: int = 0

        self._build_stops()

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    def backfill(self) -> int:
        """Publish initial counts for every stop. Returns count published."""
        now = time.time()
        sim_hour = self._sim_hour()
        published = 0

        for entry in self._stops:
            count = entry.sim.seed_initial(sim_hour)
            self._publish_crowd_count(entry.sim.stop_id, count, now)
            published += 1
            time.sleep(config.BACKFILL_STAGGER)

        logger.info(
            "Backfill complete: %d stops seeded (sim_hour=%.1f)",
            published,
            sim_hour,
        )
        return published

    # ------------------------------------------------------------------
    # Main loop (called repeatedly by main.py)
    # ------------------------------------------------------------------

    def run_once(self) -> None:
        """Publish for all stops that are due, then sleep until the next one."""
        now_mono = time.monotonic()
        sim_hour = self._sim_hour()

        due = [e for e in self._stops if now_mono >= e.next_publish]
        for entry in due:
            count = entry.sim.tick(sim_hour)
            self._publish_crowd_count(
                entry.sim.stop_id, count, time.time(),
            )
            entry.next_publish = now_mono + entry.interval

        if not due:
            nearest = min(e.next_publish for e in self._stops)
            sleep_for = max(0.01, nearest - time.monotonic())
            time.sleep(sleep_for)

    def log_stats(self) -> None:
        """Log a one-line summary of current simulator state."""
        counts = [e.sim.count for e in self._stops]
        if not counts:
            return
        avg = sum(counts) / len(counts)
        hi_entry = max(self._stops, key=lambda e: e.sim.count)
        lo_entry = min(self._stops, key=lambda e: e.sim.count)
        logger.info(
            "stats | stops=%d  avg=%.1f  hi=%d (%s)  lo=%d (%s)  published=%d  sim_hour=%.1f",
            len(counts),
            avg,
            hi_entry.sim.count,
            hi_entry.sim.stop_id,
            lo_entry.sim.count,
            lo_entry.sim.stop_id,
            self._pub_count,
            self._sim_hour(),
        )

    @property
    def stop_ids(self) -> list[str]:
        return [e.sim.stop_id for e in self._stops]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_stops(self) -> None:
        route_mults = profiles.build_route_multipliers(config.ROUTES)
        seen: set[str] = set()

        all_entries: list[_StopEntry] = []
        for route_name, route_cfg in config.ROUTES.items():
            stop_ids = route_cfg["stop_ids"]
            headway_s = route_cfg["headway_minutes"] * 60.0
            n_stops = len(stop_ids)

            for idx, sid in enumerate(stop_ids):
                if sid in seen:
                    continue
                seen.add(sid)

                pw = profiles.position_weight(idx, n_stops)
                rm = route_mults.get(sid, 1.0)
                bc = profiles.base_cap_for_stop(sid)
                interval = self._rng.uniform(
                    config.PUBLISH_INTERVAL_MIN,
                    config.PUBLISH_INTERVAL_MAX,
                )

                sim = StopSimulator(
                    stop_id=sid,
                    position_weight=pw,
                    route_multiplier=rm,
                    base_cap=bc,
                    headway_seconds=headway_s,
                    rng=self._rng,
                )
                all_entries.append(_StopEntry(sim=sim, interval=interval))

        # Assign staggered initial offsets
        now_mono = time.monotonic()
        if all_entries:
            stagger_step = config.PUBLISH_INTERVAL_MIN / len(all_entries)
            for i, entry in enumerate(all_entries):
                entry.next_publish = now_mono + i * stagger_step

        self._stops = all_entries
        self._start_wall = time.time()
        self._start_hour = _wall_hour()

        logger.info(
            "Built %d unique stop simulators from %d routes",
            len(self._stops),
            len(config.ROUTES),
        )

    def _sim_hour(self) -> float:
        """Current simulated hour-of-day, respecting SIM_TIME_SCALE."""
        elapsed = time.time() - self._start_wall
        sim_elapsed_hours = (elapsed * config.SIM_TIME_SCALE) / 3600.0
        return (self._start_hour + sim_elapsed_hours) % 24.0

    def _publish_crowd_count(
        self, stop_id: str, count: int, ts: float,
    ) -> None:
        payload = json.dumps({
            "device_id": stop_id,
            "timestamp": ts,
            "count": count,
            "zone": "default",
        }).encode()

        self._client.publish(
            topic=f"edge/{stop_id}/crowdCount",
            payload=payload,
            qos=1,
        )
        self._pub_count += 1


def _wall_hour() -> float:
    """Current wall-clock hour as a float (e.g. 14.5 = 2:30 PM)."""
    t = time.localtime()
    return t.tm_hour + t.tm_min / 60.0 + t.tm_sec / 3600.0
