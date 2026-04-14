# *** TEST FILE - SAFE TO DELETE ***
"""
Integration tests for the TransitFlow MQTT system.

Tests cover every message flow: connection, crowdCount, image, log,
admin commands, device status, and chunked model transfer.

Run:  pytest tests/mqtt/ -v --tb=short
"""

import hashlib
import json
import os
import struct
import sys
import threading
import time

import pytest

# ---------------------------------------------------------------------------
# Path setup (mirrors conftest.py)
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
BACKEND_DIR = os.path.join(SRC_DIR, "Backend")

for p in (SRC_DIR, BACKEND_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

MSG_TIMEOUT = 10  # seconds to wait for async MQTT delivery


# ===== Connection Tests ====================================================

class TestConnection:

    def test_edge_connects(self, edge_client):
        """EdgeClient connects via TLS and is running its network loop."""
        assert edge_client._client.is_connected()

    def test_backend_connects(self, broker_handler):
        """BrokerHandler connects via TLS and is running its network loop."""
        assert broker_handler._client.is_connected()


# ===== CrowdCount Flow =====================================================

class TestCrowdCount:

    def test_crowd_count_received_by_backend(self, edge_client, broker_handler):
        """Edge publishes crowdCount JSON -> backend handler receives it."""
        received = threading.Event()
        captured = {}

        original = broker_handler._handle_crowd_count

        def spy(device_id, msg):
            original(device_id, msg)
            try:
                captured["device_id"] = device_id
                captured["data"] = json.loads(msg.payload.decode())
            except Exception:
                pass
            received.set()

        broker_handler._handle_crowd_count = spy

        payload = {"count": 42, "zone": "test-zone", "timestamp": time.time()}
        edge_client.send_crowd_count(payload)

        assert received.wait(timeout=MSG_TIMEOUT), "Backend did not receive crowdCount"
        assert captured["data"]["count"] == 42
        assert captured["data"]["zone"] == "test-zone"

        broker_handler._handle_crowd_count = original


# ===== Image Transfer ======================================================

class TestImageTransfer:

    def test_image_received_and_saved(self, edge_client, broker_handler, dummy_image_file):
        """Edge sends a binary image -> backend receives header + bytes."""
        received = threading.Event()
        captured = {}

        original = broker_handler._handle_image

        def spy(device_id, msg):
            original(device_id, msg)
            captured["device_id"] = device_id
            captured["raw_len"] = len(msg.payload)
            received.set()

        broker_handler._handle_image = spy

        with open(dummy_image_file, "rb") as f:
            expected_bytes = f.read()

        edge_client.send_image(dummy_image_file, metadata={"test": True})

        assert received.wait(timeout=MSG_TIMEOUT), "Backend did not receive image"
        assert captured["device_id"] == edge_client._device_id

        # Verify the saved file exists and matches
        from Edge import config as edge_cfg
        from MQTTBroker import config as backend_cfg

        save_dir = os.path.join(backend_cfg.RECEIVED_IMAGES_DIR, edge_cfg.DEVICE_ID)
        assert os.path.isdir(save_dir), f"Image save directory not created: {save_dir}"

        saved_files = os.listdir(save_dir)
        assert len(saved_files) >= 1, "No image files saved"

        saved_path = os.path.join(save_dir, saved_files[-1])
        with open(saved_path, "rb") as f:
            saved_bytes = f.read()
        assert saved_bytes == expected_bytes, "Saved image bytes do not match original"

        broker_handler._handle_image = original

    def test_image_header_metadata_parsed(self, edge_client, broker_handler, dummy_image_file):
        """Backend correctly parses the image wire format header (device_id, filename)."""
        received = threading.Event()
        captured = {}

        original = broker_handler._handle_image

        def spy(device_id, msg):
            payload = msg.payload
            header_len = struct.unpack("!I", payload[:4])[0]
            captured["header"] = json.loads(payload[4 : 4 + header_len].decode())
            captured["image_len"] = len(payload) - 4 - header_len
            original(device_id, msg)
            received.set()

        broker_handler._handle_image = spy

        edge_client.send_image(dummy_image_file, metadata={"camera": "cam-01"})

        assert received.wait(timeout=MSG_TIMEOUT), "Backend did not receive image"

        header = captured["header"]
        assert header["device_id"] == edge_client._device_id
        assert header["filename"] == os.path.basename(dummy_image_file)
        assert "timestamp" in header
        assert header["metadata"]["camera"] == "cam-01"
        assert captured["image_len"] == os.path.getsize(dummy_image_file)

        broker_handler._handle_image = original


# ===== Log Flow ============================================================

class TestLogFlow:

    def test_log_received_by_backend(self, edge_client, broker_handler):
        """Edge sends a log entry -> backend receives it."""
        received = threading.Event()
        captured = {}

        original = broker_handler._handle_log

        def spy(device_id, msg):
            original(device_id, msg)
            try:
                captured["entry"] = json.loads(msg.payload.decode())
            except Exception:
                pass
            received.set()

        broker_handler._handle_log = spy

        edge_client.send_log("error", "Test error message", extra={"code": 500})

        assert received.wait(timeout=MSG_TIMEOUT), "Backend did not receive log"
        assert captured["entry"]["level"] == "error"
        assert captured["entry"]["message"] == "Test error message"
        assert captured["entry"]["extra"]["code"] == 500

        broker_handler._handle_log = original


# ===== Admin Command Flow ==================================================

class TestAdminCommand:

    def test_admin_received_by_edge(self, edge_client, broker_handler):
        """Backend sends admin command -> edge device receives it."""
        received = threading.Event()
        captured = {}

        def admin_callback(command):
            captured["command"] = command
            received.set()

        edge_client.set_admin_callback(admin_callback)

        command = {"action": "restart", "delay": 5}
        broker_handler.send_admin(edge_client._device_id, command)

        assert received.wait(timeout=MSG_TIMEOUT), "Edge did not receive admin command"
        assert captured["command"]["action"] == "restart"
        assert captured["command"]["delay"] == 5


# ===== Device Status =======================================================

class TestDeviceStatus:

    def test_online_status_tracked(self, edge_client, broker_handler):
        """Edge device connection publishes online status -> backend tracks it."""
        deadline = time.time() + MSG_TIMEOUT
        device_id = edge_client._device_id

        while time.time() < deadline:
            devices = broker_handler.get_devices()
            if device_id in devices and devices[device_id].get("online"):
                break
            time.sleep(0.5)

        devices = broker_handler.get_devices()
        assert device_id in devices, f"Device {device_id} not tracked by backend"
        assert devices[device_id]["online"] is True, "Device not reported as online"

    def test_offline_status_on_disconnect(self, edge_client, broker_handler):
        """Edge graceful disconnect publishes offline status -> backend tracks it."""
        device_id = edge_client._device_id

        # Wait for backend to see the device come online
        deadline = time.time() + MSG_TIMEOUT
        while time.time() < deadline:
            devices = broker_handler.get_devices()
            if device_id in devices and devices[device_id].get("online"):
                break
            time.sleep(0.5)
        assert broker_handler.get_devices().get(device_id, {}).get("online"), \
            "Device never came online"

        # Disconnect the edge client (publishes offline status)
        edge_client.disconnect()
        edge_client.loop_stop()
        edge_client._test_torn_down = True

        # Wait for backend to see the device go offline
        deadline = time.time() + MSG_TIMEOUT
        while time.time() < deadline:
            devices = broker_handler.get_devices()
            dev = devices.get(device_id, {})
            if dev and dev.get("online") is False:
                break
            time.sleep(0.5)

        devices = broker_handler.get_devices()
        assert devices[device_id]["online"] is False, "Device not reported as offline"


# ===== Model Transfer ======================================================

class TestModelTransfer:

    def test_model_delivered_and_verified(
        self, edge_client, broker_handler, model_distributor, dummy_model_file
    ):
        """Backend distributes a .pt model -> edge reassembles, verifies SHA256, ACKs success."""
        device_id = edge_client._device_id

        with open(dummy_model_file, "rb") as f:
            expected_sha256 = hashlib.sha256(f.read()).hexdigest()

        result = {"success": None}

        def run_distribute():
            result["success"] = model_distributor.distribute_model(
                device_id, dummy_model_file
            )

        dist_thread = threading.Thread(target=run_distribute, daemon=True)
        dist_thread.start()
        dist_thread.join(timeout=60)

        assert not dist_thread.is_alive(), "distribute_model did not complete within 60s"
        assert result["success"] is True, "Model distribution reported failure"

        from Edge import config as edge_cfg
        model_filename = os.path.basename(dummy_model_file)
        saved_path = os.path.join(edge_cfg.MODEL_SAVE_DIR, model_filename)
        assert os.path.isfile(saved_path), f"Model file not saved at {saved_path}"

        with open(saved_path, "rb") as f:
            actual_sha256 = hashlib.sha256(f.read()).hexdigest()
        assert actual_sha256 == expected_sha256, "Saved model SHA256 does not match original"

    def test_model_multi_chunk(
        self, edge_client, broker_handler, model_distributor, tmp_path
    ):
        """Model transfer with many chunks (1MB file / 256KB chunks = 4 chunks)."""
        device_id = edge_client._device_id

        model_path = tmp_path / "large_model.pt"
        model_data = os.urandom(1024 * 1024)
        model_path.write_bytes(model_data)
        expected_sha256 = hashlib.sha256(model_data).hexdigest()

        result = {"success": None}

        def run_distribute():
            result["success"] = model_distributor.distribute_model(
                device_id, str(model_path)
            )

        dist_thread = threading.Thread(target=run_distribute, daemon=True)
        dist_thread.start()
        dist_thread.join(timeout=60)

        assert not dist_thread.is_alive(), "distribute_model did not complete within 60s"
        assert result["success"] is True, "Multi-chunk model distribution failed"

        from Edge import config as edge_cfg
        saved_path = os.path.join(edge_cfg.MODEL_SAVE_DIR, "large_model.pt")
        assert os.path.isfile(saved_path), f"Model file not saved at {saved_path}"

        with open(saved_path, "rb") as f:
            actual_sha256 = hashlib.sha256(f.read()).hexdigest()
        assert actual_sha256 == expected_sha256, "Multi-chunk model SHA256 mismatch"
