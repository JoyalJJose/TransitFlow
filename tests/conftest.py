# *** TEST FILE - SAFE TO DELETE ***
"""Top-level pytest configuration.

Auto-applies category markers based on the directory a test lives in so
we can filter by speed / dependency class::

    pytest -m unit                -- fast, no Docker / no network
    pytest -m integration         -- DB-backed (requires Docker)
    pytest -m e2e                 -- full MQTT + DB (requires Docker)

Individual files may still set their own ``pytestmark`` which will be
preserved by this hook.
"""

from __future__ import annotations

import os

_UNIT_DIRS = {"edge", "database", "prediction", "simulator", "api",
              "gtfs_rt", "supervisor"}
_INTEGRATION_DIRS = {"integration"}
_E2E_DIRS = {"mqtt"}


def pytest_collection_modifyitems(config, items):
    tests_root = os.path.dirname(__file__)
    for item in items:
        rel = os.path.relpath(str(item.fspath), tests_root)
        parts = rel.replace("\\", "/").split("/")
        if len(parts) < 2:
            continue
        top = parts[0]
        if top in _UNIT_DIRS:
            item.add_marker("unit")
        elif top in _INTEGRATION_DIRS:
            item.add_marker("integration")
        elif top in _E2E_DIRS:
            item.add_marker("e2e")
