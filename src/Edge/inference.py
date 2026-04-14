"""YOLO-based crowd counting for thermal images.

Ported from the InferProto prototype. Uses ultralytics YOLO and PyTorch.
"""

import logging
import threading
import time

import torch
from ultralytics import YOLO

from . import config

logger = logging.getLogger(__name__)


class CrowdCounter:
    """Counts people in thermal images using a YOLO model.

    Reads conf_threshold and zone from RuntimeSettings on every call so
    that admin config changes apply immediately.  Supports pause/resume
    for safe model hot-swapping.
    """

    def __init__(self, model_path: str, settings):
        """
        Args:
            model_path: Path to the .pt YOLO model file.
            settings: A RuntimeSettings instance (thread-safe).
        """
        self._settings = settings
        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        self._model_path = model_path
        self._model = YOLO(model_path)
        self._paused = threading.Event()
        self._paused.set()  # starts unpaused

        logger.info(
            "CrowdCounter initialised (model=%s, device=%s)",
            model_path, self._device,
        )

    # -- public API --------------------------------------------------------

    def count(self, image_path: str) -> dict:
        """Run inference on a single image and return a structured result.

        Blocks if the counter is paused (during a model swap).
        """
        self._paused.wait()

        results = self._model.predict(
            source=str(image_path),
            conf=self._settings.conf_threshold,
            device=self._device,
            verbose=False,
        )

        result = results[0]
        count = len(result.boxes)

        return {
            "device_id": config.DEVICE_ID,
            "timestamp": time.time(),
            "count": count,
            "zone": self._settings.zone,
        }

    def pause(self):
        """Pause inference -- count() will block until resume()."""
        self._paused.clear()
        logger.info("Inference paused")

    def resume(self):
        """Resume inference after a pause."""
        self._paused.set()
        logger.info("Inference resumed")

    def reload_model(self, model_path: str):
        """Load a new YOLO model from disk. Raises on failure."""
        new_model = YOLO(model_path)
        self._model = new_model
        self._model_path = model_path
        logger.info("Model reloaded from %s", model_path)
