# *** TEST FILE - SAFE TO DELETE ***
"""Fixtures for API unit tests.

All DB access is mocked. No Docker / no running backend required.
"""

import os
import sys
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
BACKEND_DIR = os.path.join(SRC_DIR, "Backend")

for p in (SRC_DIR, BACKEND_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)


class QueueCursor:
    """Cursor that returns queued (description, rows) per execute() call.

    ``queries._rows()`` uses ``cursor.description`` + ``cursor.fetchall()``
    to build dicts keyed by column name. This fake honours that contract.
    """

    def __init__(self, responses):
        # responses: list of (columns_tuple, rows_list)
        self._responses = list(responses)
        self.description = None
        self._rows = []
        self.executed_sqls = []

    def execute(self, sql, params=None):
        self.executed_sqls.append((sql, params))
        if self._responses:
            cols, rows = self._responses.pop(0)
            self.description = tuple((c,) for c in cols)
            self._rows = rows
        else:
            self.description = tuple()
            self._rows = []

    def fetchall(self):
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakePool:
    """Mimics ``Database.ConnectionPool`` for tests. Uses a QueueCursor."""

    def __init__(self, responses):
        self.cursor_obj = QueueCursor(responses)

    @contextmanager
    def connection(self):
        conn = MagicMock()
        conn.cursor.return_value = self.cursor_obj
        yield conn


@pytest.fixture
def make_pool():
    def _make(responses):
        return FakePool(responses)
    return _make
