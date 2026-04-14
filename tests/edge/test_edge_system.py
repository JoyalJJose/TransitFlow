# *** TEST FILE - SAFE TO DELETE ***
"""
Unit tests for the TransitFlow Edge device system.

Tests cover: RuntimeSettings, FrameBuffer, MQTTLogHandler, ModelManager,
ModelReceiver callback, CrowdCounter pause/resume, ThermalCamera pipeline
control, and admin command dispatch.

All external dependencies (YOLO, torch, cv2) are mocked.

Run:  pytest tests/edge/ -v --tb=short
"""

import hashlib
import json
import logging
import os
import struct
import sys
import threading
import time
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Path setup (mirrors conftest.py)
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)


# ===== RuntimeSettings Tests ===============================================

class TestRuntimeSettings:

    def test_defaults(self, settings):
        """RuntimeSettings initialises with expected defaults."""
        assert settings.pipeline_active is True
        assert settings.capture_interval == 10.0
        assert settings.image_send_interval == 30.0
        assert settings.conf_threshold == 0.25
        assert settings.zone == "default"

    def test_property_setters(self, settings):
        """Each property can be set and read back correctly."""
        settings.pipeline_active = False
        assert settings.pipeline_active is False

        settings.capture_interval = 5.0
        assert settings.capture_interval == 5.0

        settings.image_send_interval = 15.0
        assert settings.image_send_interval == 15.0

        settings.conf_threshold = 0.5
        assert settings.conf_threshold == 0.5

        settings.zone = "platform-B"
        assert settings.zone == "platform-B"

    def test_update_applies_known_keys(self, settings):
        """update() applies known keys and returns what changed."""
        changed = settings.update({
            "capture_interval": 3,
            "conf_threshold": 0.8,
            "zone": "zone-X",
        })
        assert changed == {
            "capture_interval": 3.0,
            "conf_threshold": 0.8,
            "zone": "zone-X",
        }
        assert settings.capture_interval == 3.0
        assert settings.conf_threshold == 0.8
        assert settings.zone == "zone-X"

    def test_update_ignores_unknown_keys(self, settings):
        """update() silently ignores keys not in _KNOWN_KEYS."""
        changed = settings.update({"unknown_key": 999, "capture_interval": 7})
        assert "unknown_key" not in changed
        assert changed == {"capture_interval": 7.0}

    def test_update_skips_unchanged_values(self, settings):
        """update() does not report keys whose values didn't change."""
        settings.zone = "already-set"
        changed = settings.update({"zone": "already-set", "capture_interval": 2})
        assert "zone" not in changed
        assert changed == {"capture_interval": 2.0}

    def test_update_pipeline_active_as_bool(self, settings):
        """update() coerces pipeline_active to bool."""
        changed = settings.update({"pipeline_active": False})
        assert settings.pipeline_active is False
        assert changed == {"pipeline_active": False}

    def test_thread_safety(self, settings):
        """Concurrent reads and writes don't raise."""
        errors = []

        def writer():
            try:
                for i in range(200):
                    settings.capture_interval = float(i)
                    settings.zone = f"zone-{i}"
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(200):
                    _ = settings.capture_interval
                    _ = settings.zone
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread safety errors: {errors}"


# ===== FrameBuffer Tests ===================================================

class TestFrameBuffer:

    def test_put_get_single(self, frame_buffer):
        """put() then get() returns the frame path."""
        frame_buffer.put("/tmp/frame1.jpg")
        path = frame_buffer.get(timeout=1.0)
        assert path == "/tmp/frame1.jpg"

    def test_get_returns_none_on_timeout(self, frame_buffer):
        """get() returns None when no frame is available within timeout."""
        path = frame_buffer.get(timeout=0.05)
        assert path is None

    def test_overwrite_semantics(self, frame_buffer):
        """Multiple put() calls before get() -- only the latest frame is returned."""
        frame_buffer.put("/tmp/old.jpg")
        frame_buffer.put("/tmp/newer.jpg")
        frame_buffer.put("/tmp/latest.jpg")
        path = frame_buffer.get(timeout=1.0)
        assert path == "/tmp/latest.jpg"

    def test_consumed_after_get(self, frame_buffer):
        """After get(), the buffer is empty until another put()."""
        frame_buffer.put("/tmp/frame.jpg")
        frame_buffer.get(timeout=1.0)
        path = frame_buffer.get(timeout=0.05)
        assert path is None

    def test_producer_consumer_across_threads(self, frame_buffer):
        """Producer thread puts a frame, consumer thread gets it."""
        result = {}

        def consumer():
            result["path"] = frame_buffer.get(timeout=5.0)

        t = threading.Thread(target=consumer)
        t.start()
        time.sleep(0.05)
        frame_buffer.put("/tmp/threaded.jpg")
        t.join(timeout=5.0)

        assert result["path"] == "/tmp/threaded.jpg"


# ===== MQTTLogHandler Tests ================================================

class TestMQTTLogHandler:

    def test_forwards_warning_to_comms(self, mock_comms):
        """WARNING log records are forwarded via comms.send_log()."""
        from Edge.comms import MQTTLogHandler

        handler = MQTTLogHandler(mock_comms)
        handler.setLevel(logging.WARNING)

        test_logger = logging.getLogger("test.mqtt_handler")
        test_logger.addHandler(handler)
        test_logger.setLevel(logging.WARNING)

        test_logger.warning("Something went wrong")

        assert len(mock_comms.logs) == 1
        assert mock_comms.logs[0]["level"] == "warning"
        assert "Something went wrong" in mock_comms.logs[0]["message"]

        test_logger.removeHandler(handler)

    def test_forwards_error_to_comms(self, mock_comms):
        """ERROR log records are forwarded via comms.send_log()."""
        from Edge.comms import MQTTLogHandler

        handler = MQTTLogHandler(mock_comms)
        handler.setLevel(logging.WARNING)

        test_logger = logging.getLogger("test.mqtt_handler_err")
        test_logger.addHandler(handler)
        test_logger.setLevel(logging.WARNING)

        test_logger.error("Critical failure")

        assert len(mock_comms.logs) == 1
        assert mock_comms.logs[0]["level"] == "error"

        test_logger.removeHandler(handler)

    def test_reentrant_guard_prevents_recursion(self):
        """If send_log triggers a warning, the handler doesn't recurse."""
        from Edge.comms import MQTTLogHandler

        call_count = 0

        class RecursiveComms:
            def send_log(self, level, message, extra=None):
                nonlocal call_count
                call_count += 1
                logging.getLogger("recursive").warning("inner warning from send_log")

        comms = RecursiveComms()
        handler = MQTTLogHandler(comms)
        handler.setLevel(logging.WARNING)

        recursive_logger = logging.getLogger("recursive")
        recursive_logger.addHandler(handler)
        recursive_logger.setLevel(logging.WARNING)

        recursive_logger.warning("trigger")

        # Should be called once (the trigger), NOT again for the inner warning
        assert call_count == 1

        recursive_logger.removeHandler(handler)

    def test_info_not_forwarded(self, mock_comms):
        """INFO log records are NOT forwarded (handler level is WARNING)."""
        from Edge.comms import MQTTLogHandler

        handler = MQTTLogHandler(mock_comms)
        handler.setLevel(logging.WARNING)

        test_logger = logging.getLogger("test.mqtt_handler_info")
        test_logger.addHandler(handler)
        test_logger.setLevel(logging.INFO)

        test_logger.info("Just info")

        assert len(mock_comms.logs) == 0

        test_logger.removeHandler(handler)


# ===== ModelManager Tests ==================================================

class TestModelManager:

    def test_install_new_model_success(self, model_dirs, mock_counter):
        """Successful model install: backup current, move new, reload, resume."""
        from Edge.model_manager import ModelManager

        notifications = []

        def notify_fn(level, msg, extra=None):
            notifications.append({"level": level, "message": msg, "extra": extra})

        manager = ModelManager(
            crowd_counter=mock_counter,
            notify_fn=notify_fn,
            **model_dirs,
        )

        new_model = os.path.join(model_dirs["current_dir"], "..", "new_model.pt")
        with open(new_model, "wb") as f:
            f.write(b"brand-new-model-v2")

        manager.install_new_model(new_model)

        # New model should now be at current path
        current_path = manager.get_current_model_path()
        with open(current_path, "rb") as f:
            assert f.read() == b"brand-new-model-v2"

        # Old current should now be the backup
        backup_path = manager.get_backup_model_path()
        with open(backup_path, "rb") as f:
            assert f.read() == b"current-model-data-v1"

        # reload_model was called with the current path
        assert len(mock_counter.reload_calls) == 1
        assert mock_counter.reload_calls[0] == current_path

        # Inference was resumed (event is set)
        assert mock_counter._paused.is_set()

        # Success notification sent
        assert any(n["level"] == "info" and "successful" in n["message"]
                   for n in notifications)

    def test_install_new_model_rollback_on_failure(self, model_dirs, failing_counter):
        """If reload fails, rollback restores the previous current model and resumes."""
        from Edge.model_manager import ModelManager

        notifications = []

        def notify_fn(level, msg, extra=None):
            notifications.append({"level": level, "message": msg, "extra": extra})

        manager = ModelManager(
            crowd_counter=failing_counter,
            notify_fn=notify_fn,
            **model_dirs,
        )

        new_model = os.path.join(model_dirs["current_dir"], "..", "bad_model.pt")
        with open(new_model, "wb") as f:
            f.write(b"corrupt-model-data")

        manager.install_new_model(new_model)

        # Rollback copies backup -> current.  Backup was overwritten with the
        # original current during the install step, so current should now hold
        # the original current model data.
        current_path = manager.get_current_model_path()
        with open(current_path, "rb") as f:
            assert f.read() == b"current-model-data-v1"

        # Inference was resumed despite failure
        assert failing_counter._paused.is_set()

        # Error notification sent
        assert any(n["level"] == "error" and "rolled back" in n["message"]
                   for n in notifications)

    def test_rollback_with_no_backup(self, tmp_path, mock_counter):
        """rollback() handles missing backup gracefully."""
        from Edge.model_manager import ModelManager

        current_dir = str(tmp_path / "current")
        backup_dir = str(tmp_path / "backup")

        manager = ModelManager(
            current_dir=current_dir,
            backup_dir=backup_dir,
            model_filename="best.pt",
            crowd_counter=mock_counter,
            notify_fn=lambda *a, **kw: None,
        )

        # No backup file exists -- should not raise
        manager.rollback()
        assert len(mock_counter.reload_calls) == 0

    def test_pause_resume_around_install(self, model_dirs, mock_counter):
        """Inference is paused before file ops and resumed after."""
        from Edge.model_manager import ModelManager

        pause_states = []

        original_pause = mock_counter.pause
        original_resume = mock_counter.resume

        def track_pause():
            original_pause()
            pause_states.append("paused")

        def track_resume():
            original_resume()
            pause_states.append("resumed")

        mock_counter.pause = track_pause
        mock_counter.resume = track_resume

        manager = ModelManager(
            crowd_counter=mock_counter,
            notify_fn=lambda *a, **kw: None,
            **model_dirs,
        )

        new_model = os.path.join(model_dirs["current_dir"], "..", "new.pt")
        with open(new_model, "wb") as f:
            f.write(b"data")

        manager.install_new_model(new_model)

        assert pause_states == ["paused", "resumed"]


# ===== ModelReceiver on_model_ready Tests ==================================

class TestModelReceiverCallback:

    def _simulate_transfer(self, receiver, data: bytes, filename: str = "test.pt"):
        """Helper: simulate a complete chunked model transfer."""
        chunk_size = 256
        file_hash = hashlib.sha256(data).hexdigest()
        total_chunks = (len(data) + chunk_size - 1) // chunk_size

        meta = json.dumps({
            "filename": filename,
            "total_chunks": total_chunks,
            "total_size": len(data),
            "sha256": file_hash,
            "chunk_size": chunk_size,
        }).encode()
        receiver.handle_meta(meta)

        for i in range(total_chunks):
            start = i * chunk_size
            end = min(start + chunk_size, len(data))
            chunk_data = data[start:end]
            chunk_hash = hashlib.sha256(chunk_data).digest()
            payload = struct.pack("!I", i) + chunk_hash + chunk_data
            receiver.handle_chunk(payload)

    def test_on_model_ready_called_after_successful_transfer(self):
        """After all chunks arrive and SHA-256 matches, on_model_ready is called."""
        from Edge.model_receiver import ModelReceiver

        callback_paths = []

        def on_ready(path):
            callback_paths.append(path)

        receiver = ModelReceiver(publish_fn=lambda *a: None)
        receiver.on_model_ready = on_ready

        model_data = os.urandom(1024)
        self._simulate_transfer(receiver, model_data)

        assert len(callback_paths) == 1
        assert os.path.isfile(callback_paths[0])

        with open(callback_paths[0], "rb") as f:
            assert f.read() == model_data

        # Cleanup
        os.remove(callback_paths[0])

    def test_on_model_ready_not_called_when_none(self):
        """If on_model_ready is None, transfer completes without error."""
        from Edge.model_receiver import ModelReceiver

        receiver = ModelReceiver(publish_fn=lambda *a: None)
        assert receiver.on_model_ready is None

        model_data = os.urandom(512)
        self._simulate_transfer(receiver, model_data)
        # No exception raised

    def test_ack_published_on_success(self):
        """A success ACK is published after verified assembly."""
        from Edge.model_receiver import ModelReceiver

        published = []

        def capture_publish(topic, payload, qos):
            published.append({"topic": topic, "payload": payload, "qos": qos})

        receiver = ModelReceiver(publish_fn=capture_publish)
        model_data = os.urandom(512)
        self._simulate_transfer(receiver, model_data)

        assert len(published) >= 1
        ack_payload = published[-1]["payload"]
        assert ack_payload[0] == 0x03  # MODEL_TYPE_ACK
        ack_json = json.loads(ack_payload[1:].decode())
        assert ack_json["status"] == "success"
        assert ack_json["sha256_verified"] is True


# ===== CrowdCounter Pause/Resume Tests ====================================

class TestCrowdCounterPauseResume:

    def test_pause_blocks_count(self, mock_counter):
        """When paused, count() blocks until resume() is called."""
        mock_counter.pause()

        result = {}

        def call_count():
            result["value"] = mock_counter.count("/tmp/test.jpg")

        t = threading.Thread(target=call_count)
        t.start()

        time.sleep(0.1)
        assert "value" not in result, "count() should be blocked while paused"

        mock_counter.resume()
        t.join(timeout=5.0)
        assert "value" in result
        assert result["value"]["count"] == 5

    def test_resume_unblocks_count(self, mock_counter):
        """resume() after pause lets count() proceed."""
        mock_counter.pause()
        mock_counter.resume()
        result = mock_counter.count("/tmp/test.jpg")
        assert result["count"] == 5


# ===== ThermalCamera Pipeline Control Tests ================================

class TestThermalCameraPipelineControl:

    def test_pipeline_inactive_skips_capture(self, settings, frame_buffer):
        """When pipeline_active is False, camera loop does not produce frames."""
        import Edge.camera as cam_mod

        settings.pipeline_active = False
        settings.capture_interval = 0.05

        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.read.return_value = (True, MagicMock())
        cam_mod.cv2.VideoCapture.return_value = mock_cap

        camera = cam_mod.ThermalCamera(
            device_index=0, settings=settings, frame_buffer=frame_buffer,
        )
        camera.start()
        time.sleep(0.3)
        camera.stop()

        path = frame_buffer.get(timeout=0.05)
        assert path is None

    def test_pipeline_active_produces_frames(self, settings, frame_buffer):
        """When pipeline_active is True, camera loop produces frames."""
        import Edge.camera as cam_mod

        settings.pipeline_active = True
        settings.capture_interval = 0.05

        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.read.return_value = (True, MagicMock())
        cam_mod.cv2.VideoCapture.return_value = mock_cap
        cam_mod.cv2.imwrite.return_value = True

        camera = cam_mod.ThermalCamera(
            device_index=0, settings=settings, frame_buffer=frame_buffer,
        )
        camera.start()
        time.sleep(0.3)
        camera.stop()

        path = frame_buffer.get(timeout=0.05)
        assert path is not None
        if path and os.path.exists(path):
            os.remove(path)

    def test_stop_terminates_thread(self, settings, frame_buffer):
        """stop() cleanly terminates the camera thread."""
        import Edge.camera as cam_mod

        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.read.return_value = (False, None)
        cam_mod.cv2.VideoCapture.return_value = mock_cap

        camera = cam_mod.ThermalCamera(
            device_index=0, settings=settings, frame_buffer=frame_buffer,
        )
        camera.start()
        assert camera._thread is not None
        assert camera._thread.is_alive()

        camera.stop()
        assert camera._thread is None
        mock_cap.release.assert_called_once()


# ===== Admin Command Dispatch Tests ========================================

class TestAdminDispatch:

    def _make_handle_admin(self, settings, comms):
        """Build the handle_admin function the same way main.py does."""
        def handle_admin(command: dict):
            action = command.get("action")

            if action == "update_config":
                changed = settings.update(command.get("settings", {}))
                comms.send_log("info", "Config updated", changed)
            elif action == "stop_pipeline":
                settings.pipeline_active = False
                comms.send_log("info", "Pipeline stopped by admin")
            elif action == "start_pipeline":
                settings.pipeline_active = True
                comms.send_log("info", "Pipeline started by admin")
            elif action == "restart":
                pass
            elif action == "status":
                pass
            else:
                comms.send_log("warning", f"Unknown admin action: {action}")

        return handle_admin

    def test_stop_pipeline(self, settings, mock_comms):
        """stop_pipeline sets pipeline_active to False and logs."""
        handle = self._make_handle_admin(settings, mock_comms)
        assert settings.pipeline_active is True

        handle({"action": "stop_pipeline"})

        assert settings.pipeline_active is False
        assert any("stopped" in log["message"].lower() for log in mock_comms.logs)

    def test_start_pipeline(self, settings, mock_comms):
        """start_pipeline sets pipeline_active to True and logs."""
        handle = self._make_handle_admin(settings, mock_comms)
        settings.pipeline_active = False

        handle({"action": "start_pipeline"})

        assert settings.pipeline_active is True
        assert any("started" in log["message"].lower() for log in mock_comms.logs)

    def test_update_config(self, settings, mock_comms):
        """update_config applies settings and logs what changed."""
        handle = self._make_handle_admin(settings, mock_comms)

        handle({"action": "update_config", "settings": {
            "capture_interval": 3,
            "conf_threshold": 0.6,
        }})

        assert settings.capture_interval == 3.0
        assert settings.conf_threshold == 0.6
        assert any("Config updated" in log["message"] for log in mock_comms.logs)

    def test_unknown_action_logs_warning(self, settings, mock_comms):
        """Unknown admin action sends a warning log."""
        handle = self._make_handle_admin(settings, mock_comms)

        handle({"action": "self_destruct"})

        assert any(log["level"] == "warning" for log in mock_comms.logs)

    def test_stop_then_start_round_trip(self, settings, mock_comms):
        """stop then start pipeline restores pipeline_active to True."""
        handle = self._make_handle_admin(settings, mock_comms)

        handle({"action": "stop_pipeline"})
        assert settings.pipeline_active is False

        handle({"action": "start_pipeline"})
        assert settings.pipeline_active is True


# ===== Backward Compatibility Tests ========================================

class TestBackwardCompat:

    def test_edge_client_alias(self):
        """EdgeClient is an alias for MQTTComms for backward compat."""
        from Edge.comms import EdgeClient, MQTTComms
        assert EdgeClient is MQTTComms

    def test_model_receiver_has_on_model_ready(self):
        """ModelReceiver exposes on_model_ready attribute."""
        from Edge.model_receiver import ModelReceiver
        r = ModelReceiver(publish_fn=lambda *a: None)
        assert hasattr(r, "on_model_ready")
        assert r.on_model_ready is None
