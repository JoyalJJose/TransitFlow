import logging
from contextlib import contextmanager

import psycopg2
from psycopg2 import pool

from . import config

logger = logging.getLogger(__name__)


class ConnectionPool:
    """Thread-safe PostgreSQL connection pool.

    Wraps psycopg2's ThreadedConnectionPool so that MQTT callback threads
    can safely acquire and release connections concurrently.
    """

    def __init__(
        self,
        min_conn: int | None = None,
        max_conn: int | None = None,
    ):
        self._min = min_conn or config.MIN_POOL_CONNECTIONS
        self._max = max_conn or config.MAX_POOL_CONNECTIONS
        self._pool: pool.ThreadedConnectionPool | None = None

    def open(self):
        """Create the underlying connection pool."""
        self._pool = pool.ThreadedConnectionPool(
            minconn=self._min,
            maxconn=self._max,
            host=config.DB_HOST,
            port=config.DB_PORT,
            dbname=config.DB_NAME,
            user=config.DB_USER,
            password=config.DB_PASSWORD,
        )
        logger.info(
            "Database pool opened (%s:%s/%s, min=%d, max=%d)",
            config.DB_HOST, config.DB_PORT, config.DB_NAME,
            self._min, self._max,
        )

    def close(self):
        """Close all pooled connections."""
        if self._pool:
            self._pool.closeall()
            self._pool = None
            logger.info("Database pool closed")

    @contextmanager
    def connection(self):
        """Context manager that checks out a connection and returns it on exit.

        Usage::

            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(...)
                conn.commit()
        """
        if not self._pool:
            raise RuntimeError("Connection pool is not open")

        conn = self._pool.getconn()
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise
        finally:
            self._pool.putconn(conn)
