import json
import os
import struct
import time
import logging
import ssl
import threading
import sys

import paho.mqtt.client as mqtt
from paho.mqtt.properties import Properties
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.subscribeoptions import SubscribeOptions

from . import config

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from Database import ConnectionPool, DatabaseWriter

logger = logging.getLogger(__name__)

MODEL_TYPE_META = 0x01
MODEL_TYPE_CHUNK = 0x02
MODEL_TYPE_ACK = 0x03


class BrokerHandler:
    """Backend MQTT handler.

    Owns a single persistent MQTT v5 client that subscribes to all edge device
    topics (wildcard).  Receives crowd-count data, images, logs, device status,
    and model ACKs.  Exposes the MQTT client for ModelDistributor to publish on.
    """

    def __init__(self):
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=config.CLIENT_ID,
            protocol=mqtt.MQTTv5,
        )

        self._client.tls_set(
            ca_certs=config.CA_CERT,
            certfile=config.CLIENT_CERT,
            keyfile=config.CLIENT_KEY,
            tls_version=ssl.PROTOCOL_TLS_CLIENT,
        )
        self._client.tls_insecure_set(True)

        self._client.max_queued_messages_set(config.MAX_QUEUED_MESSAGES)
        self._client.max_inflight_messages_set(config.MAX_INFLIGHT_MESSAGES)

        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        self._devices: dict[str, dict] = {}
        self._devices_lock = threading.Lock()

        self._model_ack_callback = None

        self._db_pool = ConnectionPool()
        try:
            self._db_pool.open()
            self._db_writer = DatabaseWriter(self._db_pool)
            logger.info("DatabaseWriter initialised")
        except Exception:
            logger.warning(
                "Could not connect to database; DB writes will be disabled",
                exc_info=True,
            )
            self._db_writer = None

    @property
    def client(self) -> mqtt.Client:
        """Expose the MQTT client so ModelDistributor can publish."""
        return self._client

    # -- connection --------------------------------------------------------

    def connect(self):
        conn_props = Properties(PacketTypes.CONNECT)
        conn_props.SessionExpiryInterval = 0xFFFFFFFF

        self._client.connect(
            host=config.BROKER_HOST,
            port=config.BROKER_PORT,
            clean_start=False,
            properties=conn_props,
        )

    def loop_start(self):
        self._client.loop_start()

    def loop_stop(self):
        self._client.loop_stop()

    def loop_forever(self):
        self._client.loop_forever()

    def disconnect(self):
        self._client.disconnect()
        if self._db_pool:
            self._db_pool.close()

    # -- callbacks ---------------------------------------------------------

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code.is_failure:
            logger.error("Connection failed: %s", reason_code)
            return
        logger.info("Backend connected (session_present=%s)", flags.session_present)

        for name, pattern in config.TOPIC_PATTERNS.items():
            qos = config.QOS.get(name, 1)

            if name == "model":
                opts = SubscribeOptions(qos=qos, noLocal=True)
                client.subscribe(topic=pattern, options=opts)
            else:
                client.subscribe(topic=pattern, qos=qos)

        logger.info("Subscribed to all edge wildcard topics")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code.is_failure:
            logger.warning("Unexpected disconnect (%s), paho will auto-reconnect", reason_code)
        else:
            logger.info("Backend disconnected cleanly")

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        parts = topic.split("/")
        if len(parts) < 3 or parts[0] != "edge":
            logger.warning("Unexpected topic format: %s", topic)
            return

        device_id = parts[1]
        suffix = parts[2]

        if suffix == "crowdCount":
            self._handle_crowd_count(device_id, msg)
        elif suffix == "image":
            self._handle_image(device_id, msg)
        elif suffix == "log":
            self._handle_log(device_id, msg)
        elif suffix == "status":
            self._handle_status(device_id, msg)
        elif suffix == "model":
            self._handle_model(device_id, msg)
        else:
            logger.warning("Unknown topic suffix '%s' from device %s", suffix, device_id)

    # -- topic handlers ----------------------------------------------------

    def _handle_crowd_count(self, device_id: str, msg):
        try:
            data = json.loads(msg.payload.decode())
            logger.info("[%s] Crowd count: %s", device_id, data)

            if self._db_writer:
                try:
                    self._db_writer.write_crowd_count(
                        device_id=device_id,
                        timestamp=data.get("timestamp", time.time()),
                        count=data["count"],
                        zone=data.get("zone"),
                    )
                except Exception:
                    logger.exception("[%s] DB write failed for crowd count", device_id)
        except Exception:
            logger.exception("[%s] Failed to parse crowd count", device_id)

    def _handle_image(self, device_id: str, msg):
        payload = msg.payload
        if len(payload) < 4:
            logger.warning("[%s] Image payload too short", device_id)
            return

        header_len = struct.unpack("!I", payload[:4])[0]
        if len(payload) < 4 + header_len:
            logger.warning("[%s] Image payload truncated", device_id)
            return

        try:
            header = json.loads(payload[4 : 4 + header_len].decode())
        except Exception:
            logger.exception("[%s] Failed to parse image header", device_id)
            return

        image_bytes = payload[4 + header_len :]
        filename = header.get("filename", f"{device_id}_{time.time()}.bin")

        save_dir = os.path.join(config.RECEIVED_IMAGES_DIR, device_id)
        os.makedirs(save_dir, exist_ok=True)

        timestamp_str = str(header.get("timestamp", time.time())).replace(".", "_")
        save_path = os.path.join(save_dir, f"{timestamp_str}_{filename}")

        with open(save_path, "wb") as f:
            f.write(image_bytes)

        logger.info("[%s] Image saved: %s (%d bytes)", device_id, save_path, len(image_bytes))

    def _handle_log(self, device_id: str, msg):
        try:
            entry = json.loads(msg.payload.decode())
            level = entry.get("level", "info").upper()
            message = entry.get("message", "")
            logger.info("[%s] DEVICE LOG (%s): %s", device_id, level, message)

            if self._db_writer:
                try:
                    self._db_writer.write_log(
                        device_id=device_id,
                        timestamp=entry.get("timestamp", time.time()),
                        level=level,
                        message=message,
                        extra=entry.get("extra"),
                    )
                except Exception:
                    logger.exception("[%s] DB write failed for log", device_id)
        except Exception:
            logger.exception("[%s] Failed to parse log entry", device_id)

    def _handle_status(self, device_id: str, msg):
        try:
            status = json.loads(msg.payload.decode())
            online = status.get("online", False)
            with self._devices_lock:
                self._devices[device_id] = {
                    "online": online,
                    "last_seen": time.time(),
                }
            state = "ONLINE" if online else "OFFLINE"
            logger.info("[%s] Device %s", device_id, state)

            if self._db_writer:
                try:
                    self._db_writer.upsert_stop(
                        device_id=device_id,
                        is_online=online,
                        zone=status.get("zone"),
                    )
                except Exception:
                    logger.exception("[%s] DB write failed for status", device_id)
        except Exception:
            logger.exception("[%s] Failed to parse status", device_id)

    def _handle_model(self, device_id: str, msg):
        """Only ACK messages (0x03) arrive here thanks to no_local=True."""
        payload = msg.payload
        if len(payload) < 1:
            return

        msg_type = payload[0]
        if msg_type != MODEL_TYPE_ACK:
            return

        try:
            ack = json.loads(payload[1:].decode())
            logger.info("[%s] Model ACK: %s", device_id, ack)

            if self._db_writer and ack.get("status") == "ok":
                try:
                    self._db_writer.register_model_version(
                        filename=ack.get("filename", "unknown"),
                        sha256=ack.get("sha256", ""),
                        file_size=ack.get("file_size"),
                        file_path=ack.get("file_path", ""),
                    )
                except Exception:
                    logger.exception("[%s] DB write failed for model version", device_id)

            if self._model_ack_callback:
                self._model_ack_callback(device_id, ack)
        except Exception:
            logger.exception("[%s] Failed to parse model ACK", device_id)

    # -- public API --------------------------------------------------------

    def set_model_ack_callback(self, callback):
        """Register a callback for model ACK messages.

        Signature: callback(device_id: str, ack: dict)
        """
        self._model_ack_callback = callback

    def send_admin(self, device_id: str, command: dict):
        """Send an admin command to a specific edge device."""
        topic = f"edge/{device_id}/admin"
        payload = json.dumps(command).encode()
        info = self._client.publish(
            topic=topic,
            payload=payload,
            qos=config.QOS["admin"],
        )
        logger.info("Admin command sent to %s (mid=%s): %s", device_id, info.mid, command)

        if self._db_writer:
            try:
                action = command.get("action", "unknown")
                self._db_writer.log_admin_action(
                    target_device_id=device_id,
                    action=action,
                    command=command,
                    initiated_by=command.get("initiated_by", "system"),
                )
                if action in ("start_pipeline", "stop_pipeline"):
                    self._db_writer.update_pipeline_active(
                        device_id, active=(action == "start_pipeline"),
                    )
            except Exception:
                logger.exception("DB write failed for admin action to %s", device_id)

        return info

    def get_devices(self) -> dict[str, dict]:
        """Return a snapshot of known device statuses."""
        with self._devices_lock:
            return dict(self._devices)
