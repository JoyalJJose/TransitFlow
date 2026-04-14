import hashlib
import json
import math
import struct
import time
import threading
import logging

from . import config

logger = logging.getLogger(__name__)

MODEL_TYPE_META = 0x01
MODEL_TYPE_CHUNK = 0x02


class ModelDistributor:
    """Distributes large .pt model files to edge devices over MQTT.

    Uses the BrokerHandler's MQTT client for publishing (no own connection).
    Receives ACK events via a callback registered with BrokerHandler.
    """

    def __init__(self, mqtt_client):
        """
        Args:
            mqtt_client: paho.mqtt.client.Client -- BrokerHandler's shared client.
        """
        self._client = mqtt_client

        self._ack_event = threading.Event()
        self._ack_data: dict | None = None
        self._ack_lock = threading.Lock()

    def on_model_ack(self, device_id: str, ack: dict):
        """Callback to register with BrokerHandler.set_model_ack_callback().

        Sets the threading.Event so distribute_model() can proceed.
        """
        with self._ack_lock:
            self._ack_data = {"device_id": device_id, "ack": ack}
        self._ack_event.set()

    def distribute_model(self, device_id: str, model_path: str) -> bool:
        """Send a .pt file to a specific edge device in chunks.

        Returns True on successful delivery, False on failure/timeout.
        """
        logger.info("Starting model distribution to %s: %s", device_id, model_path)
        topic = f"edge/{device_id}/model"
        qos = config.QOS["model"]
        chunk_size = config.MODEL_CHUNK_SIZE

        with open(model_path, "rb") as f:
            file_data = f.read()

        total_size = len(file_data)
        total_chunks = math.ceil(total_size / chunk_size)
        file_sha256 = hashlib.sha256(file_data).hexdigest()
        filename = model_path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]

        # Clear ACK state before publishing anything to avoid race condition
        self._ack_event.clear()
        with self._ack_lock:
            self._ack_data = None

        # 1. Publish meta message (0x01)
        meta = {
            "filename": filename,
            "total_chunks": total_chunks,
            "total_size": total_size,
            "sha256": file_sha256,
            "chunk_size": chunk_size,
        }
        meta_payload = bytes([MODEL_TYPE_META]) + json.dumps(meta).encode()
        self._client.publish(topic=topic, payload=meta_payload, qos=qos)
        logger.info(
            "Meta published: %s (%d chunks, %d bytes, sha256=%s)",
            filename,
            total_chunks,
            total_size,
            file_sha256[:16] + "...",
        )

        # 2. Publish chunks (0x02)
        for i in range(total_chunks):
            offset = i * chunk_size
            chunk_data = file_data[offset : offset + chunk_size]
            chunk_sha256 = hashlib.sha256(chunk_data).digest()

            chunk_payload = (
                bytes([MODEL_TYPE_CHUNK])
                + struct.pack("!I", i)
                + chunk_sha256
                + chunk_data
            )
            self._client.publish(topic=topic, payload=chunk_payload, qos=qos)

            if (i + 1) % 100 == 0 or (i + 1) == total_chunks:
                logger.info("Chunks published: %d/%d", i + 1, total_chunks)

            time.sleep(config.INTER_CHUNK_DELAY)

        logger.info("All %d chunks published, waiting for ACK...", total_chunks)

        # 3. Wait for ACK (event was cleared before publishing started)
        if not self._ack_event.wait(timeout=config.MODEL_ACK_TIMEOUT):
            logger.error("ACK timeout after %ds for %s", config.MODEL_ACK_TIMEOUT, filename)
            return False

        with self._ack_lock:
            ack = self._ack_data

        if ack is None:
            logger.error("ACK data missing for %s", filename)
            return False

        ack_body = ack["ack"]
        status = ack_body.get("status")

        if status == "success":
            logger.info("Model %s delivered successfully to %s", filename, device_id)
            return True

        missing = ack_body.get("missing_chunks", [])
        message = ack_body.get("message", "")
        logger.warning(
            "Model delivery failed for %s: %s (missing chunks: %s)",
            filename,
            message,
            missing,
        )

        if missing:
            return self._retry_chunks(
                topic, qos, file_data, chunk_size, missing, device_id, filename
            )

        return False

    def _retry_chunks(
        self,
        topic: str,
        qos: int,
        file_data: bytes,
        chunk_size: int,
        missing_indices: list[int],
        device_id: str,
        filename: str,
    ) -> bool:
        """Re-send only the missing/failed chunks and wait for another ACK."""
        logger.info("Retrying %d missing chunks for %s", len(missing_indices), filename)

        for i in missing_indices:
            offset = i * chunk_size
            chunk_data = file_data[offset : offset + chunk_size]
            chunk_sha256 = hashlib.sha256(chunk_data).digest()

            chunk_payload = (
                bytes([MODEL_TYPE_CHUNK])
                + struct.pack("!I", i)
                + chunk_sha256
                + chunk_data
            )
            self._client.publish(topic=topic, payload=chunk_payload, qos=qos)
            time.sleep(config.INTER_CHUNK_DELAY)

        logger.info("Retry chunks published, waiting for ACK...")

        self._ack_event.clear()
        with self._ack_lock:
            self._ack_data = None

        if not self._ack_event.wait(timeout=config.MODEL_ACK_TIMEOUT):
            logger.error("ACK timeout during retry for %s", filename)
            return False

        with self._ack_lock:
            ack = self._ack_data

        if ack and ack["ack"].get("status") == "success":
            logger.info("Model %s delivered after retry to %s", filename, device_id)
            return True

        logger.error("Model delivery still failed after retry for %s", filename)
        return False
