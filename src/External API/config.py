"""Configuration for the External API service.

All values are read from environment variables with sensible defaults so the
service runs out of the box in development. Thresholds are the boundaries
between green/amber/red for the traffic-light mapping.
"""

from __future__ import annotations

import os


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


WAIT_AMBER: int = _int_env("WAIT_AMBER", 5)
WAIT_RED: int = _int_env("WAIT_RED", 15)

OCC_AMBER: int = _int_env("OCC_AMBER", 50)
OCC_RED: int = _int_env("OCC_RED", 80)

EXTERNAL_API_PORT: int = _int_env("EXTERNAL_API_PORT", 8100)
