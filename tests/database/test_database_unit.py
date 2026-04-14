# *** TEST FILE - SAFE TO DELETE ***
"""
Unit tests for the TransitFlow Database module.

Tests cover ConnectionPool, DatabaseWriter, and BrokerHandler DB integration.
All database interactions are mocked -- no Docker or running DB required.

Run:  pytest tests/database/ -v --tb=short
"""

import json
import os
import sys
import time
from unittest.mock import MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# Path setup (mirrors conftest.py)
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
BACKEND_DIR = os.path.join(SRC_DIR, "Backend")

for p in (SRC_DIR, BACKEND_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)


# ===== ConnectionPool Tests ================================================

class TestConnectionPool:

    def test_open_creates_threaded_pool(self, mock_pg_pool):
        """open() creates a ThreadedConnectionPool with correct params."""
        from Database.connection import ConnectionPool
        from Database import config

        MockPoolClass, _mock_instance = mock_pg_pool

        pool = ConnectionPool(min_conn=2, max_conn=10)
        pool.open()

        MockPoolClass.assert_called_once_with(
            minconn=2,
            maxconn=10,
            host=config.DB_HOST,
            port=config.DB_PORT,
            dbname=config.DB_NAME,
            user=config.DB_USER,
            password=config.DB_PASSWORD,
        )

    def test_close_calls_closeall(self, mock_pg_pool):
        """close() calls closeall() on the internal pool and sets it to None."""
        from Database.connection import ConnectionPool

        _MockPoolClass, mock_instance = mock_pg_pool

        pool = ConnectionPool()
        pool.open()
        assert pool._pool is not None

        pool.close()
        mock_instance.closeall.assert_called_once()
        assert pool._pool is None

    def test_connection_gets_and_puts(self, open_pool):
        """connection() context manager gets a conn, yields it, then returns it."""
        pool, mock_conn, _mock_cursor = open_pool

        with pool.connection() as conn:
            assert conn is mock_conn

        pool._pool.getconn.assert_called_once()
        pool._pool.putconn.assert_called_once_with(mock_conn)

    def test_connection_rollback_on_exception(self, open_pool):
        """connection() calls conn.rollback() when the body raises."""
        pool, mock_conn, _mock_cursor = open_pool

        with pytest.raises(ValueError):
            with pool.connection() as conn:
                raise ValueError("boom")

        mock_conn.rollback.assert_called_once()
        pool._pool.putconn.assert_called_once_with(mock_conn)

    def test_connection_raises_when_not_open(self):
        """connection() raises RuntimeError when the pool is not open."""
        from Database.connection import ConnectionPool

        pool = ConnectionPool()
        with pytest.raises(RuntimeError, match="not open"):
            with pool.connection():
                pass


# ===== DatabaseWriter Tests ================================================

class TestDatabaseWriter:

    def test_write_crowd_count_inserts_and_upserts(self, writer_with_cache):
        """write_crowd_count executes 2 SQL statements and commits."""
        writer, mock_conn, mock_cursor = writer_with_cache

        ts = time.time()
        writer.write_crowd_count("dev-1", ts, 42, "zone-a")

        assert mock_cursor.execute.call_count == 2

        first_sql = mock_cursor.execute.call_args_list[0][0][0]
        assert "INSERT INTO crowd_count" in first_sql

        second_sql = mock_cursor.execute.call_args_list[1][0][0]
        assert "INSERT INTO current_counts" in second_sql
        assert "ON CONFLICT" in second_sql

        mock_conn.commit.assert_called_once()

    def test_write_crowd_count_skips_unknown_device(self, writer_with_cache):
        """write_crowd_count skips write when stop_id cannot be resolved."""
        writer, mock_conn, mock_cursor = writer_with_cache

        mock_cursor.execute.reset_mock()
        mock_cursor.fetchall.return_value = []

        writer.write_crowd_count("unknown-device", time.time(), 10, None)

        for c in mock_cursor.execute.call_args_list:
            sql = c[0][0]
            assert "INSERT INTO crowd_count" not in sql
            assert "INSERT INTO current_counts" not in sql
        mock_conn.commit.assert_not_called()

    def test_write_crowd_count_retries_cache(self, open_pool):
        """write_crowd_count reloads cache on miss before giving up."""
        from Database.writer import DatabaseWriter

        pool, mock_conn, mock_cursor = open_pool
        mock_cursor.fetchall.return_value = []

        with patch.object(DatabaseWriter, "_load_stop_id_cache") as mock_load:
            writer = DatabaseWriter(pool)
            mock_load.reset_mock()

            writer.write_crowd_count("unknown", time.time(), 5, None)

            mock_load.assert_called_once()

    def test_write_log_inserts(self, writer_with_cache):
        """write_log inserts into stop_logs with JSON-serialized extra."""
        writer, mock_conn, mock_cursor = writer_with_cache

        extra = {"code": 500}
        writer.write_log("dev-1", time.time(), "ERROR", "something failed", extra)

        mock_cursor.execute.assert_called_once()
        sql = mock_cursor.execute.call_args[0][0]
        params = mock_cursor.execute.call_args[0][1]

        assert "INSERT INTO stop_logs" in sql
        assert params[2] == "ERROR"
        assert params[3] == "something failed"
        assert json.loads(params[4]) == {"code": 500}
        mock_conn.commit.assert_called_once()

    def test_upsert_stop(self, writer_with_cache):
        """upsert_stop UPDATEs stops with is_online, last_seen, zone."""
        writer, mock_conn, mock_cursor = writer_with_cache

        writer.upsert_stop("dev-1", is_online=True, zone="zone-b")

        mock_cursor.execute.assert_called_once()
        sql = mock_cursor.execute.call_args[0][0]
        params = mock_cursor.execute.call_args[0][1]

        assert "UPDATE stops" in sql
        assert params[0] is True
        assert params[2] == "zone-b"
        assert params[3] == "dev-1"
        mock_conn.commit.assert_called_once()

    def test_update_pipeline_active(self, writer_with_cache):
        """update_pipeline_active UPDATEs stops.pipeline_active."""
        writer, mock_conn, mock_cursor = writer_with_cache

        writer.update_pipeline_active("dev-1", True)

        mock_cursor.execute.assert_called_once()
        sql = mock_cursor.execute.call_args[0][0]
        params = mock_cursor.execute.call_args[0][1]

        assert "pipeline_active" in sql
        assert params == (True, "dev-1")
        mock_conn.commit.assert_called_once()

    def test_log_admin_action(self, writer_with_cache):
        """log_admin_action inserts into admin_activity_log with JSON command."""
        writer, mock_conn, mock_cursor = writer_with_cache

        cmd = {"action": "restart", "delay": 5}
        writer.log_admin_action("dev-1", "restart", cmd, "admin-user")

        mock_cursor.execute.assert_called_once()
        sql = mock_cursor.execute.call_args[0][0]
        params = mock_cursor.execute.call_args[0][1]

        assert "INSERT INTO admin_activity_log" in sql
        assert params[0] == "dev-1"
        assert params[1] == "restart"
        assert json.loads(params[2]) == cmd
        assert params[3] == "admin-user"
        mock_conn.commit.assert_called_once()

    def test_register_model_version(self, writer_with_cache):
        """register_model_version inserts with ON CONFLICT DO NOTHING."""
        writer, mock_conn, mock_cursor = writer_with_cache

        writer.register_model_version("best.pt", "abc123", 1024, "/models/best.pt")

        mock_cursor.execute.assert_called_once()
        sql = mock_cursor.execute.call_args[0][0]
        params = mock_cursor.execute.call_args[0][1]

        assert "INSERT INTO model_versions" in sql
        assert "ON CONFLICT" in sql
        assert params == ("best.pt", "abc123", 1024, "/models/best.pt")
        mock_conn.commit.assert_called_once()

    def test_create_alert(self, writer_with_cache):
        """create_alert inserts into system_alerts."""
        writer, mock_conn, mock_cursor = writer_with_cache

        writer.create_alert("critical", "High crowd", source="threshold", device_id="dev-1")

        mock_cursor.execute.assert_called_once()
        sql = mock_cursor.execute.call_args[0][0]
        params = mock_cursor.execute.call_args[0][1]

        assert "INSERT INTO system_alerts" in sql
        assert params == ("critical", "High crowd", "threshold", "dev-1", None)
        mock_conn.commit.assert_called_once()

    def test_resolve_alert(self, writer_with_cache):
        """resolve_alert UPDATEs resolved_at on system_alerts."""
        writer, mock_conn, mock_cursor = writer_with_cache

        writer.resolve_alert(42)

        mock_cursor.execute.assert_called_once()
        sql = mock_cursor.execute.call_args[0][0]
        params = mock_cursor.execute.call_args[0][1]

        assert "UPDATE system_alerts" in sql
        assert "resolved_at" in sql
        assert params == (42,)
        mock_conn.commit.assert_called_once()

    def test_db_error_does_not_propagate(self, writer_with_cache):
        """A DB exception inside a write method is caught and logged, not raised."""
        writer, mock_conn, mock_cursor = writer_with_cache

        mock_cursor.execute.side_effect = Exception("DB connection lost")

        writer.write_log("dev-1", time.time(), "INFO", "test")

        mock_conn.commit.assert_not_called()

    def test_load_cache_failure_does_not_crash(self, open_pool):
        """If _load_stop_id_cache fails during __init__, writer still works."""
        from Database.writer import DatabaseWriter

        pool, mock_conn, mock_cursor = open_pool
        mock_cursor.execute.side_effect = Exception("DB not ready")

        writer = DatabaseWriter(pool)

        assert writer._stop_id_cache == {}


# ===== BrokerHandler DB Integration Tests ==================================

class TestBrokerHandlerDB:

    @patch("MQTTBroker.broker_handler.DatabaseWriter")
    @patch("MQTTBroker.broker_handler.ConnectionPool")
    @patch("MQTTBroker.broker_handler.mqtt.Client")
    def test_init_with_db_available(self, MockMqttClient, MockPool, MockWriter):
        """When DB is available, _db_writer is set to a DatabaseWriter."""
        from MQTTBroker.broker_handler import BrokerHandler

        handler = BrokerHandler()

        MockPool.return_value.open.assert_called_once()
        MockWriter.assert_called_once_with(MockPool.return_value)
        assert handler._db_writer is MockWriter.return_value

    @patch("MQTTBroker.broker_handler.DatabaseWriter")
    @patch("MQTTBroker.broker_handler.ConnectionPool")
    @patch("MQTTBroker.broker_handler.mqtt.Client")
    def test_init_with_db_unavailable(self, MockMqttClient, MockPool, MockWriter):
        """When DB is unavailable, _db_writer is None and handler still works."""
        from MQTTBroker.broker_handler import BrokerHandler

        MockPool.return_value.open.side_effect = Exception("connection refused")

        handler = BrokerHandler()

        assert handler._db_writer is None

    @patch("MQTTBroker.broker_handler.DatabaseWriter")
    @patch("MQTTBroker.broker_handler.ConnectionPool")
    @patch("MQTTBroker.broker_handler.mqtt.Client")
    def test_handle_crowd_count_calls_writer(self, MockMqttClient, MockPool, MockWriter):
        """_handle_crowd_count delegates to writer.write_crowd_count."""
        from MQTTBroker.broker_handler import BrokerHandler

        handler = BrokerHandler()

        mock_msg = MagicMock()
        payload = {"count": 15, "zone": "z1", "timestamp": 1700000000.0}
        mock_msg.payload = json.dumps(payload).encode()

        handler._handle_crowd_count("dev-1", mock_msg)

        handler._db_writer.write_crowd_count.assert_called_once_with(
            device_id="dev-1",
            timestamp=1700000000.0,
            count=15,
            zone="z1",
        )

    @patch("MQTTBroker.broker_handler.DatabaseWriter")
    @patch("MQTTBroker.broker_handler.ConnectionPool")
    @patch("MQTTBroker.broker_handler.mqtt.Client")
    def test_send_admin_start_pipeline(self, MockMqttClient, MockPool, MockWriter):
        """send_admin with start_pipeline calls log_admin_action AND update_pipeline_active."""
        from MQTTBroker.broker_handler import BrokerHandler

        handler = BrokerHandler()

        cmd = {"action": "start_pipeline", "initiated_by": "admin"}
        handler.send_admin("dev-1", cmd)

        handler._db_writer.log_admin_action.assert_called_once_with(
            target_device_id="dev-1",
            action="start_pipeline",
            command=cmd,
            initiated_by="admin",
        )
        handler._db_writer.update_pipeline_active.assert_called_once_with(
            "dev-1", active=True,
        )

    @patch("MQTTBroker.broker_handler.DatabaseWriter")
    @patch("MQTTBroker.broker_handler.ConnectionPool")
    @patch("MQTTBroker.broker_handler.mqtt.Client")
    def test_disconnect_closes_pool(self, MockMqttClient, MockPool, MockWriter):
        """disconnect() closes the DB pool."""
        from MQTTBroker.broker_handler import BrokerHandler

        handler = BrokerHandler()
        handler.disconnect()

        MockPool.return_value.close.assert_called_once()
