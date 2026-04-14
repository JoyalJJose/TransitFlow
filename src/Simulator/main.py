"""Entry point for the crowd-count simulator.

Usage (from ``src/``):
    python -m Simulator.main
    SIM_TIME_SCALE=5 SIM_RANDOM_SEED=42 python -m Simulator.main
"""

from __future__ import annotations

import json
import logging
import random
import signal
import ssl
import sys
import time

import paho.mqtt.client as mqtt
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties

from . import config
from .orchestrator import Orchestrator

logger = logging.getLogger(__name__)

_shutdown = False


def _on_signal(signum, frame):
    global _shutdown
    logger.info("Received signal %s – shutting down", signum)
    _shutdown = True


def _make_client() -> mqtt.Client:
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=config.CLIENT_ID,
        protocol=mqtt.MQTTv5,
    )
    client.tls_set(
        ca_certs=config.CA_CERT,
        certfile=config.CLIENT_CERT,
        keyfile=config.CLIENT_KEY,
        tls_version=ssl.PROTOCOL_TLS_CLIENT,
    )
    client.tls_insecure_set(True)

    def on_connect(client, userdata, flags, rc, properties=None):
        if rc.is_failure:
            logger.error("MQTT connect failed: %s", rc)
        else:
            logger.info("Connected to MQTT broker at %s:%d", config.BROKER_HOST, config.BROKER_PORT)

    def on_disconnect(client, userdata, flags, rc, properties=None):
        if rc.is_failure:
            logger.warning("Unexpected disconnect (%s), paho will auto-reconnect", rc)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    return client


def _publish_status(client: mqtt.Client, stop_ids: list[str], online: bool) -> None:
    payload = json.dumps({"online": online}).encode()
    for sid in stop_ids:
        client.publish(
            topic=f"edge/{sid}/status",
            payload=payload,
            qos=1,
            retain=True,
        )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    logger.info(
        "Starting crowd-count simulator  (time_scale=%.1f, seed=%s)",
        config.SIM_TIME_SCALE,
        config.SIM_RANDOM_SEED,
    )

    rng = random.Random(config.SIM_RANDOM_SEED)

    client = _make_client()
    conn_props = Properties(PacketTypes.CONNECT)
    conn_props.SessionExpiryInterval = 0
    client.connect(
        host=config.BROKER_HOST,
        port=config.BROKER_PORT,
        clean_start=True,
        properties=conn_props,
    )
    client.loop_start()

    # Allow the connection to establish
    time.sleep(1.0)

    orch = Orchestrator(client, rng)

    # Publish online status for all simulated stops
    logger.info("Publishing online status for %d stops …", len(orch.stop_ids))
    _publish_status(client, orch.stop_ids, online=True)

    # Backfill initial counts
    orch.backfill()

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    logger.info("Entering main loop (Ctrl+C to stop)")
    last_stats = time.monotonic()

    try:
        while not _shutdown:
            orch.run_once()

            now = time.monotonic()
            if now - last_stats >= config.STATS_LOG_INTERVAL:
                orch.log_stats()
                last_stats = now
    finally:
        logger.info("Shutting down – publishing offline status …")
        _publish_status(client, orch.stop_ids, online=False)
        time.sleep(0.5)
        client.loop_stop()
        client.disconnect()
        logger.info("Simulator stopped.")


if __name__ == "__main__":
    main()
