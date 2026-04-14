# *** TEST FILE - SAFE TO DELETE ***
"""
Pytest fixtures for MQTT integration tests.

Session-scoped: TLS cert generation, Docker broker lifecycle.
Function-scoped: EdgeClient, BrokerHandler, ModelDistributor instances.
"""

import hashlib
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time

import pytest

# ---------------------------------------------------------------------------
# Path setup -- make Edge and MQTTBroker importable
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
BACKEND_DIR = os.path.join(SRC_DIR, "Backend")

for p in (SRC_DIR, BACKEND_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

CERTS_DIR = os.path.join(PROJECT_ROOT, "docker", "mosquitto", "certs")
DOCKER_DIR = os.path.join(PROJECT_ROOT, "docker")


# ===== helpers =============================================================

def _generate_certs():
    """Generate self-signed TLS certs using openssl subprocess calls."""
    os.makedirs(CERTS_DIR, exist_ok=True)

    ca_key = os.path.join(CERTS_DIR, "ca.key")
    ca_crt = os.path.join(CERTS_DIR, "ca.crt")
    srv_key = os.path.join(CERTS_DIR, "server.key")
    srv_crt = os.path.join(CERTS_DIR, "server.crt")
    cli_key = os.path.join(CERTS_DIR, "client.key")
    cli_crt = os.path.join(CERTS_DIR, "client.crt")

    days = "3650"

    subprocess.run(
        ["openssl", "genrsa", "-out", ca_key, "2048"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["openssl", "req", "-x509", "-new", "-nodes",
         "-key", ca_key, "-sha256", "-days", days,
         "-subj", "/CN=TransitFlow MQTT CA", "-out", ca_crt],
        check=True, capture_output=True,
    )

    srv_csr = os.path.join(CERTS_DIR, "server.csr")
    subprocess.run(
        ["openssl", "genrsa", "-out", srv_key, "2048"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["openssl", "req", "-new", "-key", srv_key,
         "-subj", "/CN=mosquitto", "-out", srv_csr],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["openssl", "x509", "-req", "-in", srv_csr,
         "-CA", ca_crt, "-CAkey", ca_key, "-CAcreateserial",
         "-days", days, "-sha256", "-out", srv_crt],
        check=True, capture_output=True,
    )
    _silent_remove(srv_csr)

    cli_csr = os.path.join(CERTS_DIR, "client.csr")
    subprocess.run(
        ["openssl", "genrsa", "-out", cli_key, "2048"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["openssl", "req", "-new", "-key", cli_key,
         "-subj", "/CN=mqtt-client", "-out", cli_csr],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["openssl", "x509", "-req", "-in", cli_csr,
         "-CA", ca_crt, "-CAkey", ca_key, "-CAcreateserial",
         "-days", days, "-sha256", "-out", cli_crt],
        check=True, capture_output=True,
    )
    _silent_remove(cli_csr)
    _silent_remove(os.path.join(CERTS_DIR, "ca.srl"))


def _silent_remove(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def _wait_for_broker(host="localhost", port=8883, timeout=30):
    """Poll until the broker accepts a TLS connection."""
    ca_crt = os.path.join(CERTS_DIR, "ca.crt")
    deadline = time.time() + timeout
    delay = 1.0

    while time.time() < deadline:
        try:
            ctx = ssl.create_default_context(cafile=ca_crt)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with socket.create_connection((host, port), timeout=5) as sock:
                with ctx.wrap_socket(sock, server_hostname=host):
                    return True
        except (ConnectionRefusedError, OSError, ssl.SSLError):
            time.sleep(delay)
            delay = min(delay * 1.5, 5.0)

    raise RuntimeError(f"Broker not ready after {timeout}s on {host}:{port}")


# ===== session fixture =====================================================

@pytest.fixture(scope="session", autouse=True)
def mqtt_broker():
    """Start Mosquitto Docker container for the entire test session."""

    # Generate certs if missing
    if not os.path.isfile(os.path.join(CERTS_DIR, "ca.crt")):
        print("\n[conftest] Generating TLS certificates...")
        _generate_certs()
    else:
        print("\n[conftest] TLS certificates already exist, skipping generation.")

    # Start the broker
    print("[conftest] Starting Mosquitto Docker container...")
    subprocess.run(
        ["docker", "compose", "-f", os.path.join(DOCKER_DIR, "docker-compose.yml"),
         "up", "-d", "--wait"],
        check=True, cwd=PROJECT_ROOT,
    )

    print("[conftest] Waiting for broker to accept TLS connections...")
    _wait_for_broker()
    print("[conftest] Broker is ready.")

    yield

    # Teardown (use -v to remove named volumes so init.sql re-runs on next start)
    print("\n[conftest] Stopping Docker containers and removing volumes...")
    subprocess.run(
        ["docker", "compose", "-f", os.path.join(DOCKER_DIR, "docker-compose.yml"),
         "down", "-v"],
        check=True, cwd=PROJECT_ROOT,
    )

    # Clean up test artifacts
    for d in ("received", "models"):
        artifact_dir = os.path.join(PROJECT_ROOT, d)
        if os.path.isdir(artifact_dir):
            shutil.rmtree(artifact_dir, ignore_errors=True)


# ===== function fixtures ===================================================

@pytest.fixture
def edge_client(mqtt_broker):
    """Create a connected EdgeClient with ModelReceiver."""
    from Edge.comms import EdgeClient
    from Edge.model_receiver import ModelReceiver

    client = EdgeClient()
    model_receiver = ModelReceiver(publish_fn=client.publish_raw)
    client._model_receiver = model_receiver
    client._test_torn_down = False
    client.connect()
    client.loop_start()

    time.sleep(1.5)

    yield client

    if not getattr(client, "_test_torn_down", False):
        try:
            client.disconnect()
        except Exception:
            pass
        client.loop_stop()


@pytest.fixture
def broker_handler(mqtt_broker):
    """Create a connected BrokerHandler."""
    from MQTTBroker.broker_handler import BrokerHandler

    handler = BrokerHandler()
    handler.connect()
    handler.loop_start()

    time.sleep(1.5)

    yield handler

    try:
        handler.disconnect()
    except Exception:
        pass
    handler.loop_stop()


@pytest.fixture
def model_distributor(broker_handler):
    """Create a ModelDistributor wired to the BrokerHandler."""
    from MQTTBroker.model_distributor import ModelDistributor

    dist = ModelDistributor(mqtt_client=broker_handler.client)
    broker_handler.set_model_ack_callback(dist.on_model_ack)

    yield dist


@pytest.fixture
def dummy_image_file(tmp_path):
    """Create a small dummy binary file to use as a test image."""
    img_path = tmp_path / "test_image.bin"
    img_path.write_bytes(os.urandom(1024))
    return str(img_path)


@pytest.fixture
def dummy_model_file(tmp_path):
    """Create a dummy .pt file (~500KB) to test chunked transfer."""
    model_path = tmp_path / "test_model.pt"
    model_path.write_bytes(os.urandom(500 * 1024))
    return str(model_path)
