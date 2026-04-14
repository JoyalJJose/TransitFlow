import os

BROKER_HOST = os.environ.get("MQTT_BROKER_HOST", "localhost")
BROKER_PORT = int(os.environ.get("MQTT_BROKER_PORT", "8883"))

CLIENT_ID = "backend-handler"

# TLS certificate paths
CA_CERT = os.environ.get("MQTT_CA_CERT", "docker/mosquitto/certs/ca.crt")
CLIENT_CERT = os.environ.get("MQTT_CLIENT_CERT", "docker/mosquitto/certs/client.crt")
CLIENT_KEY = os.environ.get("MQTT_CLIENT_KEY", "docker/mosquitto/certs/client.key")

# Wildcard subscription topic patterns
TOPIC_PATTERNS = {
    "crowdCount": "edge/+/crowdCount",
    "image": "edge/+/image",
    "log": "edge/+/log",
    "status": "edge/+/status",
    "model": "edge/+/model",
}

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
MAX_QUEUED_MESSAGES = 0
MAX_INFLIGHT_MESSAGES = 100

# Storage directories
RECEIVED_IMAGES_DIR = os.environ.get("RECEIVED_IMAGES_DIR", "received/images")
RECEIVED_DATA_DIR = os.environ.get("RECEIVED_DATA_DIR", "received/data")

# Model distribution settings
MODEL_CHUNK_SIZE = int(os.environ.get("MODEL_CHUNK_SIZE", str(256 * 1024)))  # 256 KB
MODEL_ACK_TIMEOUT = int(os.environ.get("MODEL_ACK_TIMEOUT", "300"))  # seconds
INTER_CHUNK_DELAY = float(os.environ.get("INTER_CHUNK_DELAY", "0.01"))  # seconds
