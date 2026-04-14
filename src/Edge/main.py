"""Edge device entry point.

Wires together all modules (comms, inference, camera, model management)
and runs the continuous capture-inference pipeline.
"""

import logging
import os
import signal
import sys
import threading
import time

from . import config
from .config import RuntimeSettings
from .comms import MQTTComms, MQTTLogHandler
from .inference import CrowdCounter
from .camera import ThermalCamera, FrameBuffer
from .model_receiver import ModelReceiver
from .model_manager import ModelManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    settings = RuntimeSettings()
    shutdown_event = threading.Event()

    # ---- 1. MQTT connection (must be first so log handler can send) ------

    comms = MQTTComms()

    try:
        comms.connect()
    except Exception:
        logger.exception("Failed to connect to broker")
        sys.exit(1)

    comms.loop_start()

    # ---- 2. Attach MQTT log handler (WARNING+ auto-forwarded) ------------

    mqtt_handler = MQTTLogHandler(comms)
    mqtt_handler.setLevel(logging.WARNING)
    logging.getLogger().addHandler(mqtt_handler)

    # ---- 3. Inference engine ---------------------------------------------

    counter = CrowdCounter(
        model_path=config.CURRENT_MODEL_PATH,
        settings=settings,
    )

    # ---- 4. Frame buffer + camera ----------------------------------------

    frame_buffer = FrameBuffer()
    camera = ThermalCamera(
        device_index=config.CAMERA_DEVICE_INDEX,
        settings=settings,
        frame_buffer=frame_buffer,
    )

    # ---- 5. Model receiver + manager ------------------------------------

    model_receiver = ModelReceiver(publish_fn=comms.publish_raw)
    model_manager = ModelManager(
        current_dir=config.CURRENT_MODEL_DIR,
        backup_dir=config.BACKUP_MODEL_DIR,
        model_filename=config.MODEL_FILENAME,
        crowd_counter=counter,
        notify_fn=lambda level, msg, extra=None: comms.send_log(level, msg, extra),
    )

    # ---- 6. Admin command dispatch (defined before wiring) ---------------

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
            pass  # placeholder

        elif action == "status":
            pass  # placeholder

        else:
            comms.send_log("warning", f"Unknown admin action: {action}")

    # ---- 7. Wire callbacks -----------------------------------------------

    model_receiver.on_model_ready = model_manager.install_new_model
    comms.set_model_receiver(model_receiver)
    comms.set_admin_callback(handle_admin)

    # ---- 8. Inference loop (background thread) ---------------------------

    def inference_loop():
        image_send_tracker = time.time()
        while not shutdown_event.is_set():
            image_path = frame_buffer.get(timeout=1.0)
            if image_path is None:
                continue
            try:
                result = counter.count(image_path)
                comms.send_crowd_count(result)

                now = time.time()
                if now - image_send_tracker >= settings.image_send_interval:
                    comms.send_image(image_path)
                    image_send_tracker = now
            except Exception:
                logger.exception("Error in inference loop")
            finally:
                try:
                    os.remove(image_path)
                except OSError:
                    pass

    # ---- 9. Start pipeline -----------------------------------------------

    camera.start()
    infer_thread = threading.Thread(
        target=inference_loop, name="inference-thread", daemon=True,
    )
    infer_thread.start()

    comms.send_log("info", "Edge device started", {"device_id": config.DEVICE_ID})
    logger.info("Edge device '%s' running", config.DEVICE_ID)

    # ---- 10. Block until shutdown signal ---------------------------------

    signal.signal(signal.SIGINT, lambda *_: shutdown_event.set())
    signal.signal(signal.SIGTERM, lambda *_: shutdown_event.set())
    shutdown_event.wait()

    # ---- 11. Cleanup -----------------------------------------------------

    logger.info("Shutting down edge device...")
    camera.stop()
    infer_thread.join(timeout=5)
    comms.disconnect()
    comms.loop_stop()


if __name__ == "__main__":
    main()
