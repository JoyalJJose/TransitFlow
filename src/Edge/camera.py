"""Thermal camera capture and frame buffer.

Captures frames from a video device at a configurable interval and
places them in a size-1 overwrite buffer for the inference thread to
consume.
"""

import logging
import os
import tempfile
import threading

import cv2

logger = logging.getLogger(__name__)


class FrameBuffer:
    """Size-1 buffer that always holds the latest frame.

    The camera thread calls put() to deposit the newest frame path,
    overwriting any unconsumed frame.  The inference thread calls get()
    to retrieve it, blocking until one is available.
    """

    def __init__(self):
        self._cond = threading.Condition()
        self._path: str | None = None

    def put(self, image_path: str):
        """Deposit a new frame, overwriting any stale one."""
        with self._cond:
            self._path = image_path
            self._cond.notify()

    def get(self, timeout: float | None = None) -> str | None:
        """Block until a frame is available, then return its path.

        Returns None on timeout.
        """
        with self._cond:
            if self._path is None:
                self._cond.wait(timeout=timeout)
            path = self._path
            self._path = None
            return path


class ThermalCamera:
    """Captures frames from a thermal camera at a configurable interval.

    Runs a background thread that reads ``settings.pipeline_active`` and
    ``settings.capture_interval`` every tick so that admin changes take
    effect immediately.
    """

    def __init__(self, device_index, settings, frame_buffer: FrameBuffer):
        """
        Args:
            device_index: OpenCV VideoCapture device index or path.
            settings:     RuntimeSettings instance (thread-safe).
            frame_buffer: FrameBuffer to write captured frames into.
        """
        self._device_index = device_index
        self._settings = settings
        self._frame_buffer = frame_buffer
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._cap: cv2.VideoCapture | None = None

    # -- public API --------------------------------------------------------

    def start(self):
        """Open the camera and start the capture loop in a background thread."""
        try:
            idx = int(self._device_index)
        except (ValueError, TypeError):
            idx = self._device_index

        self._cap = cv2.VideoCapture(idx)
        if not self._cap.isOpened():
            logger.error("Failed to open camera device: %s", self._device_index)
            return

        logger.info("Camera opened (device=%s)", self._device_index)
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._capture_loop, name="camera-thread", daemon=True,
        )
        self._thread.start()

    def stop(self):
        """Signal the capture loop to stop and wait for it."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        logger.info("Camera stopped")

    # -- internal ----------------------------------------------------------

    def _capture_loop(self):
        while not self._stop_event.is_set():
            if not self._settings.pipeline_active:
                self._stop_event.wait(timeout=0.5)
                continue

            ret, frame = self._cap.read()
            if not ret:
                logger.warning("Camera read failed, skipping frame")
                self._stop_event.wait(timeout=1.0)
                continue

            fd, path = tempfile.mkstemp(suffix=".jpg", prefix="frame_")
            os.close(fd)
            cv2.imwrite(path, frame)
            self._frame_buffer.put(path)

            self._stop_event.wait(timeout=self._settings.capture_interval)
