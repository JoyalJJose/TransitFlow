# *** TEST FILE - SAFE TO DELETE ***
"""Unit tests for Backend/runtime_supervisor.py.

Covers the ``_Worker`` class and the runtime constants that drive the
prediction loop. No real subprocesses, no real DB connection.
"""

from unittest.mock import MagicMock, patch

import pytest

from Backend import runtime_supervisor as sup


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# _Worker lifecycle --------------------------------------------------------
# ---------------------------------------------------------------------------

@pytest.fixture
def patched_worker_env(tmp_path, monkeypatch):
    """Redirect log writes to a temp dir and stub subprocess.Popen."""
    monkeypatch.setattr(sup, "LOGDIR", str(tmp_path))

    mock_proc = MagicMock()
    mock_proc.pid = 4321
    mock_proc.returncode = None
    mock_proc.poll.return_value = None  # alive by default

    popen_patch = patch.object(sup.subprocess, "Popen", return_value=mock_proc)
    with popen_patch as popen_mock:
        yield mock_proc, popen_mock


class TestWorkerStart:

    def test_start_launches_subprocess_and_opens_log(self, patched_worker_env):
        proc, popen_mock = patched_worker_env
        w = sup._Worker(
            "mqtt",
            ["python", "-m", "Backend.MQTTBroker.main"],
            "broker.log",
            env_extra={"MQTT_SERVICE_MODE": "1"},
        )
        w.start()

        assert w.proc is proc
        popen_mock.assert_called_once()
        _, kwargs = popen_mock.call_args
        assert "stdout" in kwargs
        assert kwargs["stderr"] == sup.subprocess.STDOUT
        # env_extra merged into environment
        assert kwargs["env"]["MQTT_SERVICE_MODE"] == "1"

    def test_start_resets_backoff(self, patched_worker_env):
        w = sup._Worker("x", ["cmd"], "x.log")
        w._backoff = 16.0
        w.start()
        assert w._backoff == 2.0


class TestWorkerLifecycle:

    def test_is_alive_reflects_poll(self, patched_worker_env):
        proc, _ = patched_worker_env
        w = sup._Worker("x", ["cmd"], "x.log")
        assert w.is_alive() is False
        w.start()
        proc.poll.return_value = None
        assert w.is_alive() is True
        proc.poll.return_value = 1
        assert w.is_alive() is False

    def test_restart_if_dead_noop_when_alive(self, patched_worker_env):
        proc, popen_mock = patched_worker_env
        w = sup._Worker("x", ["cmd"], "x.log")
        w.start()
        proc.poll.return_value = None

        w.restart_if_dead()
        # No second Popen call when the worker is alive.
        assert popen_mock.call_count == 1

    def test_restart_if_dead_launches_new_subprocess(self, patched_worker_env, monkeypatch):
        # Neutralise the backoff sleep in _shutdown.wait().
        monkeypatch.setattr(sup._shutdown, "wait", lambda s: False)

        proc, popen_mock = patched_worker_env
        w = sup._Worker("x", ["cmd"], "x.log")
        w.start()
        proc.poll.return_value = 1  # dead

        w.restart_if_dead()

        # A second Popen call means restart happened.
        assert popen_mock.call_count == 2
        # After a successful restart the backoff schedules the next retry
        # at 2 × 2 = 4 s (doubling, capped at _max_backoff).
        assert w._backoff == 4.0

    def test_restart_honours_shutdown_signal(self, patched_worker_env, monkeypatch):
        # If _shutdown.wait() returns True (shutdown requested) the worker
        # must NOT be restarted.
        monkeypatch.setattr(sup._shutdown, "wait", lambda s: True)
        proc, popen_mock = patched_worker_env
        w = sup._Worker("x", ["cmd"], "x.log")
        w.start()
        proc.poll.return_value = 1

        w.restart_if_dead()
        assert popen_mock.call_count == 1  # no restart

    def test_stop_terminates_gracefully(self, patched_worker_env):
        proc, _ = patched_worker_env
        w = sup._Worker("x", ["cmd"], "x.log")
        w.start()
        proc.poll.return_value = None
        w.stop()
        proc.terminate.assert_called_once()
        proc.wait.assert_called_once()

    def test_stop_kills_on_timeout(self, patched_worker_env):
        proc, _ = patched_worker_env
        proc.wait.side_effect = sup.subprocess.TimeoutExpired(cmd="cmd", timeout=5)
        w = sup._Worker("x", ["cmd"], "x.log")
        w.start()
        proc.poll.return_value = None
        w.stop()
        proc.kill.assert_called_once()


# ---------------------------------------------------------------------------
# Runtime constants / payload filter ---------------------------------------
# ---------------------------------------------------------------------------

class TestTriggerPayloads:

    def test_recognised_payloads(self):
        assert "crowd_count" in sup._TRIGGER_PAYLOADS
        assert "gtfs_trip_updates" in sup._TRIGGER_PAYLOADS

    def test_unknown_payload_rejected(self):
        assert "alert_resolved" not in sup._TRIGGER_PAYLOADS
        assert "" not in sup._TRIGGER_PAYLOADS

    def test_trigger_payloads_is_frozenset(self):
        assert isinstance(sup._TRIGGER_PAYLOADS, frozenset)


# ---------------------------------------------------------------------------
# _open_log helper ----------------------------------------------------------
# ---------------------------------------------------------------------------

class TestOpenLog:

    def test_creates_logdir(self, tmp_path, monkeypatch):
        target = tmp_path / "newlogs"
        monkeypatch.setattr(sup, "LOGDIR", str(target))
        fh = sup._open_log("foo.log")
        try:
            assert target.exists()
            assert fh.mode == "a"
        finally:
            fh.close()
