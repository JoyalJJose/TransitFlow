"""Chunked model file receiver over MQTT.

Reassembles a .pt model from individually transmitted chunks, verifies
integrity via SHA-256, then hands the assembled file to a registered
callback (``on_model_ready``) for the model manager to handle placement.
"""

import hashlib
import json
import os
import shutil
import struct
import tempfile
import threading
import logging

from . import config

logger = logging.getLogger(__name__)

MODEL_TYPE_ACK = 0x03


class ModelReceiver:
    """Reassembles a chunked .pt model file received over MQTT.

    Chunks are written to a temp directory on disk. Once all chunks arrive,
    the file is reassembled, its SHA-256 is verified, and the assembled file
    is passed to the ``on_model_ready`` callback.
    """

    def __init__(self, publish_fn):
        """
        Args:
            publish_fn: callable(topic, payload, qos) -- bound to MQTTComms.publish_raw
        """
        self._publish_fn = publish_fn
        self._lock = threading.Lock()
        self._reset_state()

        self.on_model_ready = None

    def _reset_state(self):
        self._filename = None
        self._total_chunks = 0
        self._total_size = 0
        self._expected_sha256 = None
        self._chunk_size = 0
        self._received_chunks: set[int] = set()
        self._temp_dir: str | None = None

    # -- public handlers called by MQTTComms -------------------------------

    def handle_meta(self, data: bytes):
        """Process a type-0x01 meta message (JSON)."""
        with self._lock:
            try:
                meta = json.loads(data.decode())
            except Exception:
                logger.exception("Failed to decode model meta JSON")
                return

            self._filename = meta["filename"]
            self._total_chunks = meta["total_chunks"]
            self._total_size = meta["total_size"]
            self._expected_sha256 = meta["sha256"]
            self._chunk_size = meta["chunk_size"]
            self._received_chunks = set()

            self._temp_dir = tempfile.mkdtemp(prefix="model_recv_")

            logger.info(
                "Model transfer started: %s (%d chunks, %d bytes)",
                self._filename,
                self._total_chunks,
                self._total_size,
            )

    def handle_chunk(self, data: bytes):
        """Process a type-0x02 chunk message (binary).

        Payload layout: [4B chunk_index][32B chunk_sha256][chunk_data]
        """
        if len(data) < 36:
            logger.warning("Chunk message too short (%d bytes)", len(data))
            return

        chunk_index = struct.unpack("!I", data[:4])[0]
        expected_hash = data[4:36]
        chunk_data = data[36:]

        actual_hash = hashlib.sha256(chunk_data).digest()
        if actual_hash != expected_hash:
            logger.warning(
                "Chunk %d SHA-256 mismatch (expected=%s, got=%s)",
                chunk_index,
                expected_hash.hex(),
                actual_hash.hex(),
            )
            return

        with self._lock:
            if self._temp_dir is None:
                logger.warning("Chunk %d received but no active transfer", chunk_index)
                return

            chunk_path = os.path.join(self._temp_dir, f"{chunk_index:08d}.chunk")
            with open(chunk_path, "wb") as f:
                f.write(chunk_data)

            self._received_chunks.add(chunk_index)

            logger.debug(
                "Chunk %d/%d received (%d bytes)",
                chunk_index + 1,
                self._total_chunks,
                len(chunk_data),
            )

            if len(self._received_chunks) == self._total_chunks:
                self._assemble_and_verify()

    # -- assembly ----------------------------------------------------------

    def _assemble_and_verify(self):
        """Reassemble chunks, verify full-file SHA-256, publish ACK.

        MUST be called while holding self._lock.
        """
        fd, assembled_path = tempfile.mkstemp(
            suffix=".pt", prefix=f"model_{self._filename}_",
        )
        os.close(fd)

        sha256 = hashlib.sha256()
        try:
            with open(assembled_path, "wb") as out:
                for i in range(self._total_chunks):
                    chunk_path = os.path.join(self._temp_dir, f"{i:08d}.chunk")
                    with open(chunk_path, "rb") as chunk_file:
                        chunk_data = chunk_file.read()
                        out.write(chunk_data)
                        sha256.update(chunk_data)
        except FileNotFoundError as exc:
            logger.error("Missing chunk file during assembly: %s", exc)
            self._send_error_ack(f"Missing chunk file: {exc}")
            self._safe_remove(assembled_path)
            return

        file_hash = sha256.hexdigest()

        if file_hash != self._expected_sha256:
            logger.error(
                "Full-file SHA-256 mismatch (expected=%s, got=%s)",
                self._expected_sha256,
                file_hash,
            )
            self._safe_remove(assembled_path)
            self._send_error_ack(
                f"SHA256 mismatch: expected {self._expected_sha256}, got {file_hash}",
            )
            return

        logger.info(
            "Model %s received and verified (%s)", self._filename, assembled_path,
        )
        self._send_success_ack()
        self._cleanup_temp()

        if self.on_model_ready:
            try:
                self.on_model_ready(assembled_path)
            except Exception:
                logger.exception("on_model_ready callback failed")

    # -- ACK helpers -------------------------------------------------------

    def _send_success_ack(self):
        ack = {
            "filename": self._filename,
            "status": "success",
            "sha256_verified": True,
        }
        self._publish_ack(ack)

    def _send_error_ack(self, message: str):
        missing = sorted(set(range(self._total_chunks)) - self._received_chunks)
        ack = {
            "filename": self._filename,
            "status": "error",
            "missing_chunks": missing,
            "message": message,
        }
        self._publish_ack(ack)

    def _publish_ack(self, ack_dict: dict):
        payload = bytes([MODEL_TYPE_ACK]) + json.dumps(ack_dict).encode()
        topic = f"{config.TOPIC_PREFIX}/model"
        qos = config.QOS["model"]
        try:
            self._publish_fn(topic, payload, qos)
            logger.info("Model ACK published: %s", ack_dict.get("status"))
        except Exception:
            logger.exception("Failed to publish model ACK")

    # -- cleanup -----------------------------------------------------------

    def _cleanup_temp(self):
        if self._temp_dir and os.path.isdir(self._temp_dir):
            shutil.rmtree(self._temp_dir, ignore_errors=True)
        self._reset_state()

    @staticmethod
    def _safe_remove(path):
        try:
            os.remove(path)
        except OSError:
            pass
