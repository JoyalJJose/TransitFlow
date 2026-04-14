import os

# NTA GTFS-Realtime API
GTFSR_API_URL = os.environ.get(
    "GTFSR_API_URL",
    "https://api.nationaltransport.ie/gtfsr/v2/gtfsr",
)
GTFSR_API_KEY = os.environ.get("GTFSR_API_KEY", "")

# Response format: "pb" (protobuf) or "json"
GTFSR_FORMAT = os.environ.get("GTFSR_FORMAT", "pb")

# NTA fair-usage policy: max one request per 60 s per API key.
_MIN_POLL_INTERVAL = 60
GTFSR_POLL_INTERVAL = max(
    _MIN_POLL_INTERVAL,
    int(os.environ.get("GTFSR_POLL_INTERVAL", "60")),
)

# HTTP request timeout in seconds
GTFSR_REQUEST_TIMEOUT = int(os.environ.get("GTFSR_REQUEST_TIMEOUT", "30"))

# Only keep trip updates whose route_id belongs to this agency.
# Default is Dublin Bus.  Set to "" to disable filtering.
GTFSR_AGENCY_FILTER = os.environ.get("GTFSR_AGENCY_FILTER", "7778019")

# Number of most-recent fetches to retain in gtfs_rt_trip_updates.
# Older rows are purged after each write to cap storage.
GTFSR_RETAIN_FETCHES = int(os.environ.get("GTFSR_RETAIN_FETCHES", "20"))
