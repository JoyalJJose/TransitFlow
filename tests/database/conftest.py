# *** TEST FILE - SAFE TO DELETE ***
"""
Pytest fixtures for Database module unit tests.

All external dependencies (psycopg2 pool, real DB connections) are mocked
so these tests run with just pytest + psycopg2-binary installed.
No Docker or running database required.
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup -- make Database and MQTTBroker importable
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
BACKEND_DIR = os.path.join(SRC_DIR, "Backend")

for p in (SRC_DIR, BACKEND_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)


# ===== ConnectionPool fixtures =============================================

@pytest.fixture
def mock_pg_pool():
    """A mocked psycopg2 ThreadedConnectionPool.

    Returns the mock pool object so tests can inspect calls on it.
    """
    with patch("Database.connection.pool.ThreadedConnectionPool") as MockPoolClass:
        mock_pool_instance = MagicMock()
        MockPoolClass.return_value = mock_pool_instance
        yield MockPoolClass, mock_pool_instance


@pytest.fixture
def mock_conn_and_cursor():
    """A mock connection + cursor pair.

    The cursor supports use as a context manager (``with conn.cursor() as cur``).
    """
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return mock_conn, mock_cursor


@pytest.fixture
def open_pool(mock_pg_pool, mock_conn_and_cursor):
    """A ConnectionPool that is already open and yields a mocked connection.

    Returns (pool, mock_conn, mock_cursor) so tests can inspect DB calls.
    """
    from Database.connection import ConnectionPool

    MockPoolClass, mock_pool_instance = mock_pg_pool
    mock_conn, mock_cursor = mock_conn_and_cursor
    mock_pool_instance.getconn.return_value = mock_conn

    pool = ConnectionPool(min_conn=1, max_conn=5)
    pool.open()
    return pool, mock_conn, mock_cursor


# ===== DatabaseWriter fixtures =============================================

@pytest.fixture
def writer_with_cache(open_pool):
    """A DatabaseWriter backed by a mocked pool with a pre-populated cache.

    The ``_load_stop_id_cache`` call during ``__init__`` is patched so it
    doesn't try to execute SQL.  Instead, the cache is manually set to
    ``{"dev-1": "stop-1", "dev-2": "stop-2"}``.

    Returns (writer, mock_conn, mock_cursor).
    """
    from Database.writer import DatabaseWriter

    pool, mock_conn, mock_cursor = open_pool

    with patch.object(DatabaseWriter, "_load_stop_id_cache"):
        writer = DatabaseWriter(pool)

    writer._stop_id_cache = {"dev-1": "stop-1", "dev-2": "stop-2"}
    return writer, mock_conn, mock_cursor
