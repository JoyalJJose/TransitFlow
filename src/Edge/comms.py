import json
import logging
import ssl
import struct
import time

import paho.mqtt.client as mqtt
from paho.mqtt.properties import Properties
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.subscribeoptions import SubscribeOptions

from . import config

logger = logging.getLogger(__name__)

MODEL_TYPE_META = 0x01
MODEL_TYPE_CHUNK = 0x02
MODEL_TYPE_ACK = 0x03


class MQTTComms:
    """MQTT v5 client for an edge device.

    Sole owner of the MQTT connection. Publishes crowd-count data, images,
    and log entries to the backend.  Receives admin commands and model file
    chunks from the backend and dispatches them via registered callbacks.
    """

    def __init__(self, model_receiver=None):
        self._device_id = config.DEVICE_ID
        self._prefix = config.TOPIC_PREFIX
        self._qos = config.QOS
        self._model_receiver = model_receiver

        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"edge-{self._device_id}",
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

        lwt_payload = json.dumps({"online": False}).encode()
        self._client.will_set(
            topic=f"{self._prefix}/status",
            payload=lwt_payload,
            qos=self._qos["status"],
            retain=True,
        )

        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        self._admin_callback = None

    # -- connection --------------------------------------------------------

    @property
    def client(self):
        return self._client

    def connect(self):
        """Connect to the MQTT broker with a persistent session."""
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
        self._client.publish(
            topic=f"{self._prefix}/status",
            payload=json.dumps({"online": False}).encode(),
            qos=self._qos["status"],
            retain=True,
        )
        self._client.disconnect()

    # -- callbacks ---------------------------------------------------------

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code.is_failure:
            logger.error("Connection failed: %s", reason_code)
            return
        logger.info("Connected to broker (session_present=%s)", flags.session_present)

        client.publish(
            topic=f"{self._prefix}/status",
            payload=json.dumps({"online": True}).encode(),
            qos=self._qos["status"],
            retain=True,
        )

        client.subscribe(
            topic=f"{self._prefix}/admin",
            qos=self._qos["admin"],
        )

        model_opts = SubscribeOptions(
            qos=self._qos["model"],
            noLocal=True,
        )
        client.subscribe(
            topic=f"{self._prefix}/model",
            options=model_opts,
        )

        logger.info("Subscribed to admin and model topics")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code.is_failure:
            logger.warning(
                "Unexpected disconnect (%s), paho will auto-reconnect", reason_code,
            )
        else:
            logger.info("Disconnected cleanly")

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        suffix = topic[len(self._prefix) + 1:]

        if suffix == "admin":
            self._handle_admin(msg)
        elif suffix == "model":
            self._handle_model(msg)
        else:
            logger.warning("Message on unexpected topic: %s", topic)

    # -- admin handling ----------------------------------------------------

    def set_admin_callback(self, callback):
        """Register a function to call when an admin command arrives.

        Signature: callback(command: dict)
        """
        self._admin_callback = callback

    def _handle_admin(self, msg):
        try:
            command = json.loads(msg.payload.decode())
            logger.info("Admin command received: %s", command)
            if self._admin_callback:
                self._admin_callback(command)
        except Exception:
            logger.exception("Failed to process admin message")

    # -- model handling ----------------------------------------------------

    def set_model_receiver(self, model_receiver):
        """Attach a ModelReceiver to handle incoming model messages."""
        self._model_receiver = model_receiver

    def _handle_model(self, msg):
        if not self._model_receiver:
            logger.warning("Model message received but no ModelReceiver configured")
            return

        payload = msg.payload
        if len(payload) < 1:
            logger.warning("Empty model message received")
            return

        msg_type = payload[0]
        data = payload[1:]

        if msg_type == MODEL_TYPE_META:
            self._model_receiver.handle_meta(data)
        elif msg_type == MODEL_TYPE_CHUNK:
            self._model_receiver.handle_chunk(data)
        else:
            logger.debug(
                "Ignoring model message type 0x%02x (likely self-echo)", msg_type,
            )

    # -- publish methods ---------------------------------------------------

    def send_crowd_count(self, data: dict):
        """Publish crowd count JSON data."""
        payload = json.dumps(data).encode()
        info = self._client.publish(
            topic=f"{self._prefix}/crowdCount",
            payload=payload,
            qos=self._qos["crowdCount"],
        )
        logger.debug("Crowd count published (mid=%s)", info.mid)
        return info

    def send_image(self, image_path: str, metadata: dict | None = None):
        """Publish a raw image file with a JSON metadata header.

        Wire format: [4B header_length][JSON header bytes][raw image bytes]
        """
        with open(image_path, "rb") as f:
            image_bytes = f.read()

        header = {
            "device_id": self._device_id,
            "timestamp": time.time(),
            "filename": image_path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1],
        }
        if metadata:
            header["metadata"] = metadata

        header_bytes = json.dumps(header).encode()
        header_length = struct.pack("!I", len(header_bytes))
        payload = header_length + header_bytes + image_bytes

        info = self._client.publish(
            topic=f"{self._prefix}/image",
            payload=payload,
            qos=self._qos["image"],
        )
        logger.debug("Image published (mid=%s, size=%d)", info.mid, len(payload))
        return info

    def send_log(self, level: str, message: str, extra: dict | None = None):
        """Publish a log entry to the backend."""
        entry = {
            "level": level,
            "message": message,
            "timestamp": time.time(),
        }
        if extra:
            entry["extra"] = extra

        payload = json.dumps(entry).encode()
        info = self._client.publish(
            topic=f"{self._prefix}/log",
            payload=payload,
            qos=self._qos["log"],
        )
        logger.debug("Log published (mid=%s, level=%s)", info.mid, level)
        return info

    def publish_raw(self, topic: str, payload: bytes, qos: int):
        """Low-level publish used by ModelReceiver for ACKs."""
        return self._client.publish(topic=topic, payload=payload, qos=qos)


# Backward-compat alias so existing tests importing EdgeClient still work.
EdgeClient = MQTTComms


class MQTTLogHandler(logging.Handler):
    """Forwards WARNING+ log records to the backend via MQTT.

    Attach to the root logger so that any module using logger.warning() or
    logger.error() automatically gets the message sent to the backend.
    """

    def __init__(self, comms: MQTTComms):
        super().__init__()
        self._comms = comms
        self._reentrant = False

    def emit(self, record: logging.LogRecord):
        if self._reentrant:
            return
        self._reentrant = True
        try:
            level = record.levelname.lower()
            self._comms.send_log(level, self.format(record))
        except Exception:
            self.handleError(record)
        finally:
            self._reentrant = False
