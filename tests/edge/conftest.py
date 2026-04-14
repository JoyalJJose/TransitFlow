# *** TEST FILE - SAFE TO DELETE ***
"""
Pytest fixtures for Edge device unit tests.

All external dependencies (YOLO, torch, cv2) are mocked so these tests
run with just pytest + paho-mqtt installed.
"""

import os
import sys
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup -- make Edge importable
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

# ---------------------------------------------------------------------------
# Mock heavy dependencies that aren't installed in the test environment
# ---------------------------------------------------------------------------
if "cv2" not in sys.modules:
    sys.modules["cv2"] = MagicMock()
if "torch" not in sys.modules:
    sys.modules["torch"] = MagicMock()
if "ultralytics" not in sys.modules:
    sys.modules["ultralytics"] = MagicMock()


# ===== RuntimeSettings fixture =============================================

@pytest.fixture
def settings():
    """Fresh RuntimeSettings with defaults."""
    from Edge.config import RuntimeSettings
    return RuntimeSettings()


# ===== FrameBuffer fixture =================================================

@pytest.fixture
def frame_buffer():
    from Edge.camera import FrameBuffer
    return FrameBuffer()


# ===== Mock CrowdCounter ===================================================

class MockCrowdCounter:
    """Stand-in for CrowdCounter that doesn't need YOLO or torch."""

    def __init__(self):
        self._paused = threading.Event()
        self._paused.set()
        self.count_calls = []
        self.reload_calls = []
        self._count_value = 5

    def count(self, image_path: str) -> dict:
        self._paused.wait()
        self.count_calls.append(image_path)
        return {
            "device_id": "test-device",
            "timestamp": time.time(),
            "count": self._count_value,
            "zone": "test-zone",
        }

    def pause(self):
        self._paused.clear()

    def resume(self):
        self._paused.set()

    def reload_model(self, model_path: str):
        self.reload_calls.append(model_path)


class FailingCrowdCounter(MockCrowdCounter):
    """CrowdCounter that raises on reload_model (simulates corrupt model)."""

    def reload_model(self, model_path: str):
        self.reload_calls.append(model_path)
        raise RuntimeError("Simulated model load failure")


@pytest.fixture
def mock_counter():
    return MockCrowdCounter()


@pytest.fixture
def failing_counter():
    return FailingCrowdCounter()


# ===== Mock comms (send_log spy) ===========================================

class MockComms:
    """Minimal stand-in for MQTTComms that records send_log calls."""

    def __init__(self):
        self.logs = []
        self.crowd_counts = []
        self.images = []

    def send_log(self, level, message, extra=None):
        self.logs.append({"level": level, "message": message, "extra": extra})

    def send_crowd_count(self, data):
        self.crowd_counts.append(data)

    def send_image(self, image_path, metadata=None):
        self.images.append(image_path)

    def publish_raw(self, topic, payload, qos):
        pass


@pytest.fixture
def mock_comms():
    return MockComms()


# ===== Temp model files ====================================================

@pytest.fixture
def model_dirs(tmp_path):
    """Create temporary current/ and backup/ model directories with dummy .pt files."""
    current_dir = tmp_path / "current"
    backup_dir = tmp_path / "backup"
    current_dir.mkdir()
    backup_dir.mkdir()

    (current_dir / "best.pt").write_bytes(b"current-model-data-v1")
    (backup_dir / "best.pt").write_bytes(b"backup-model-data-v0")

    return {
        "current_dir": str(current_dir),
        "backup_dir": str(backup_dir),
        "model_filename": "best.pt",
    }
