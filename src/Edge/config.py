import os
import threading

# ---------------------------------------------------------------------------
# Static config (read once at startup, from environment variables)
# ---------------------------------------------------------------------------

BROKER_HOST = os.environ.get("MQTT_BROKER_HOST", "localhost")
BROKER_PORT = int(os.environ.get("MQTT_BROKER_PORT", "8883"))

DEVICE_ID = os.environ.get("EDGE_DEVICE_ID", "edge-001")

# TLS certificate paths (relative to project root or absolute)
CA_CERT = os.environ.get("MQTT_CA_CERT", "docker/mosquitto/certs/ca.crt")
CLIENT_CERT = os.environ.get("MQTT_CLIENT_CERT", "docker/mosquitto/certs/client.crt")
CLIENT_KEY = os.environ.get("MQTT_CLIENT_KEY", "docker/mosquitto/certs/client.key")

# Topic prefix derived from device ID
TOPIC_PREFIX = f"edge/{DEVICE_ID}"

# Per-topic QoS levels
QOS = {
    "crowdCount": 1,
    "image": 2,
    "log": 1,
    "admin": 2,
    "model": 2,
    "status": 1,
}

# paho-mqtt queue settings
MAX_QUEUED_MESSAGES = 0       # 0 = unlimited
MAX_INFLIGHT_MESSAGES = 100

# Reconnect backoff (seconds)
RECONNECT_MIN_DELAY = 1
RECONNECT_MAX_DELAY = 120

# Model directory paths (relative to this package)
_EDGE_DIR = os.path.dirname(os.path.abspath(__file__))
CURRENT_MODEL_DIR = os.environ.get(
    "CURRENT_MODEL_DIR", os.path.join(_EDGE_DIR, "models", "current"),
)
BACKUP_MODEL_DIR = os.environ.get(
    "BACKUP_MODEL_DIR", os.path.join(_EDGE_DIR, "models", "backup"),
)
MODEL_FILENAME = os.environ.get("MODEL_FILENAME", "best.pt")
CURRENT_MODEL_PATH = os.path.join(CURRENT_MODEL_DIR, MODEL_FILENAME)

# Kept for backward-compat with model_receiver temp assembly path
MODEL_SAVE_DIR = os.environ.get("MODEL_SAVE_DIR", os.path.join(_EDGE_DIR, "models"))

# Camera
CAMERA_DEVICE_INDEX = os.environ.get("CAMERA_DEVICE_INDEX", "0")


# ---------------------------------------------------------------------------
# RuntimeSettings -- thread-safe, mutable at runtime via admin commands
# ---------------------------------------------------------------------------

class RuntimeSettings:
    """Thread-safe mutable settings that can be changed by admin commands."""

    def __init__(self):
        self._lock = threading.Lock()
        self._pipeline_active = True
        self._capture_interval = float(os.environ.get("CAPTURE_INTERVAL", "10"))
        self._image_send_interval = float(os.environ.get("IMAGE_SEND_INTERVAL", "30"))
        self._conf_threshold = float(os.environ.get("CONF_THRESHOLD", "0.25"))
        self._zone = os.environ.get("ZONE", "default")

    # -- properties with lock -----------------------------------------------

    @property
    def pipeline_active(self) -> bool:
        with self._lock:
            return self._pipeline_active

    @pipeline_active.setter
    def pipeline_active(self, value: bool):
        with self._lock:
            self._pipeline_active = bool(value)

    @property
    def capture_interval(self) -> float:
        with self._lock:
            return self._capture_interval

    @capture_interval.setter
    def capture_interval(self, value: float):
        with self._lock:
            self._capture_interval = float(value)

    @property
    def image_send_interval(self) -> float:
        with self._lock:
            return self._image_send_interval

    @image_send_interval.setter
    def image_send_interval(self, value: float):
        with self._lock:
            self._image_send_interval = float(value)

    @property
    def conf_threshold(self) -> float:
        with self._lock:
            return self._conf_threshold

    @conf_threshold.setter
    def conf_threshold(self, value: float):
        with self._lock:
            self._conf_threshold = float(value)

    @property
    def zone(self) -> str:
        with self._lock:
            return self._zone

    @zone.setter
    def zone(self, value: str):
        with self._lock:
            self._zone = str(value)

    # -- bulk update --------------------------------------------------------

    _KNOWN_KEYS = {
        "pipeline_active", "capture_interval", "image_send_interval",
        "conf_threshold", "zone",
    }

    def update(self, changes: dict) -> dict:
        """Apply a dict of setting changes atomically. Returns dict of what changed."""
        applied = {}
        with self._lock:
            for key, value in changes.items():
                if key not in self._KNOWN_KEYS:
                    continue
                attr = f"_{key}"
                old = getattr(self, attr)
                if key == "pipeline_active":
                    value = bool(value)
                elif key == "zone":
                    value = str(value)
                else:
                    value = float(value)
                if old != value:
                    setattr(self, attr, value)
                    applied[key] = value
        return applied
