"""Model lifecycle management.

Handles installing newly received models, backing up the current model,
and rolling back to the backup if the new model fails to load.
"""

import logging
import os
import shutil

logger = logging.getLogger(__name__)


class ModelManager:
    """Manages model files on disk and coordinates swaps with the inference engine.

    Uses ``notify_fn`` for operational logging to the backend instead of
    importing comms directly (callback-only wiring).
    """

    def __init__(
        self,
        current_dir: str,
        backup_dir: str,
        model_filename: str,
        crowd_counter,
        notify_fn,
    ):
        """
        Args:
            current_dir:    Directory holding the active model file.
            backup_dir:     Directory holding the backup model file.
            model_filename: Name of the model file (e.g. ``best.pt``).
            crowd_counter:  CrowdCounter instance (has pause/resume/reload_model).
            notify_fn:      callable(level, message, extra=None) for backend logging.
        """
        self._current_dir = current_dir
        self._backup_dir = backup_dir
        self._filename = model_filename
        self._counter = crowd_counter
        self._notify = notify_fn

        os.makedirs(current_dir, exist_ok=True)
        os.makedirs(backup_dir, exist_ok=True)

    # -- public API --------------------------------------------------------

    def get_current_model_path(self) -> str:
        return os.path.join(self._current_dir, self._filename)

    def get_backup_model_path(self) -> str:
        return os.path.join(self._backup_dir, self._filename)

    def install_new_model(self, new_model_path: str):
        """Install a newly received model, backing up the current one.

        Called by ModelReceiver (via callback) after successful assembly
        and SHA-256 verification.

        Steps:
            1. Pause inference
            2. Backup current model (overwrite previous backup)
            3. Move new model into current dir
            4. Try to reload the model in the CrowdCounter
            5. On success: resume inference
            6. On failure: rollback and resume
        """
        current_path = self.get_current_model_path()
        backup_path = self.get_backup_model_path()

        self._counter.pause()

        try:
            if os.path.isfile(current_path):
                shutil.copy2(current_path, backup_path)
                logger.info("Backed up current model to %s", backup_path)

            shutil.move(new_model_path, current_path)
            logger.info("New model placed at %s", current_path)

            self._counter.reload_model(current_path)
            self._notify("info", "Model swap successful", {
                "model": self._filename,
            })

        except Exception:
            logger.exception("Failed to load new model, rolling back")
            self.rollback()
            self._notify("error", "Model swap failed, rolled back to backup", {
                "model": self._filename,
            })

        finally:
            self._counter.resume()

    def rollback(self):
        """Restore the backup model to current and reload it."""
        current_path = self.get_current_model_path()
        backup_path = self.get_backup_model_path()

        if not os.path.isfile(backup_path):
            logger.error("No backup model available at %s", backup_path)
            return

        shutil.copy2(backup_path, current_path)
        logger.info("Restored backup model to %s", current_path)

        try:
            self._counter.reload_model(current_path)
        except Exception:
            logger.exception("Failed to reload backup model")
