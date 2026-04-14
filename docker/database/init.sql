-- TransitFlow Database Schema
-- PostgreSQL + TimescaleDB
-- Auto-runs on first container start via /docker-entrypoint-initdb.d/

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- =========================================================================
-- Static / Reference tables (from GTFS)
-- =========================================================================

CREATE TABLE routes (
    route_id         TEXT PRIMARY KEY,
    agency_id        TEXT,
    route_short_name TEXT NOT NULL,
    route_long_name  TEXT,
    route_type       SMALLINT NOT NULL,
    transport_type   TEXT NOT NULL,
    metadata         JSONB DEFAULT '{}'
);

CREATE TABLE route_stops (
    route_id       TEXT NOT NULL REFERENCES routes(route_id),
    stop_id        TEXT NOT NULL,
    direction_id   SMALLINT NOT NULL DEFAULT 0,
    stop_sequence  INTEGER NOT NULL,
    PRIMARY KEY (route_id, direction_id, stop_sequence)
);

CREATE INDEX idx_route_stops_stop ON route_stops(stop_id);

CREATE TABLE stop_times (
    trip_id            TEXT NOT NULL,
    stop_sequence      INTEGER NOT NULL,
    stop_id            TEXT NOT NULL,
    arrival_seconds    INTEGER NOT NULL,
    departure_seconds  INTEGER NOT NULL,
    PRIMARY KEY (trip_id, stop_sequence)
);

CREATE INDEX idx_stop_times_trip_stop ON stop_times(trip_id, stop_id);

-- =========================================================================
-- Core tables (populated via MQTT + seed script)
-- =========================================================================

CREATE TABLE stops (
    device_id       TEXT PRIMARY KEY,
    stop_id         TEXT NOT NULL UNIQUE,
    stop_code       TEXT,
    stop_name       TEXT NOT NULL,
    stop_lat        DOUBLE PRECISION NOT NULL,
    stop_long       DOUBLE PRECISION NOT NULL,
    transport_type  TEXT NOT NULL,
    zone            TEXT,
    is_online       BOOLEAN DEFAULT FALSE,
    pipeline_active BOOLEAN DEFAULT FALSE,
    last_seen       TIMESTAMPTZ,
    registered_at   TIMESTAMPTZ DEFAULT NOW(),
    config          JSONB DEFAULT '{}'
);

CREATE TABLE crowd_count (
    time       TIMESTAMPTZ NOT NULL,
    device_id  TEXT NOT NULL,
    stop_id    TEXT NOT NULL,
    count      INTEGER NOT NULL,
    zone       TEXT
);

SELECT create_hypertable('crowd_count', 'time');

CREATE TABLE current_counts (
    device_id      TEXT PRIMARY KEY REFERENCES stops(device_id),
    stop_id        TEXT NOT NULL,
    count          INTEGER NOT NULL,
    previous_count INTEGER,
    zone           TEXT,
    updated_at     TIMESTAMPTZ NOT NULL
);

CREATE TABLE stop_logs (
    time       TIMESTAMPTZ NOT NULL,
    device_id  TEXT NOT NULL,
    level      TEXT NOT NULL,
    message    TEXT NOT NULL,
    extra      JSONB DEFAULT '{}'
);

SELECT create_hypertable('stop_logs', 'time');

CREATE TABLE model_versions (
    id          SERIAL PRIMARY KEY,
    filename    TEXT NOT NULL,
    version     TEXT,
    sha256      TEXT NOT NULL UNIQUE,
    file_size   BIGINT,
    file_path   TEXT NOT NULL,
    uploaded_at TIMESTAMPTZ DEFAULT NOW(),
    is_active   BOOLEAN DEFAULT FALSE,
    metadata    JSONB DEFAULT '{}'
);

CREATE TABLE admin_activity_log (
    id               BIGSERIAL PRIMARY KEY,
    occurred_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    target_device_id TEXT,
    action           TEXT NOT NULL,
    command          JSONB NOT NULL,
    result           TEXT,
    initiated_by     TEXT DEFAULT 'system'
);

CREATE TABLE system_alerts (
    id          BIGSERIAL PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    severity    TEXT NOT NULL,
    message     TEXT NOT NULL,
    source      TEXT,
    device_id   TEXT,
    route_id    TEXT,
    resolved_at TIMESTAMPTZ,
    metadata    JSONB DEFAULT '{}'
);

CREATE TABLE vehicles (
    vehicle_id        TEXT PRIMARY KEY,
    route_id          TEXT REFERENCES routes(route_id),
    capacity          INTEGER NOT NULL,
    current_stop_id   TEXT,
    state             TEXT DEFAULT 'INACTIVE',
    passenger_count   INTEGER DEFAULT 0,
    occupancy_percent REAL DEFAULT 0.0,
    is_active         BOOLEAN DEFAULT TRUE,
    last_updated      TIMESTAMPTZ DEFAULT NOW(),
    metadata          JSONB DEFAULT '{}'
);

CREATE TABLE vehicle_telemetry (
    time              TIMESTAMPTZ NOT NULL,
    vehicle_id        TEXT NOT NULL,
    route_id          TEXT,
    passenger_count   INTEGER,
    occupancy_percent REAL,
    current_stop_id   TEXT,
    state             TEXT
);

SELECT create_hypertable('vehicle_telemetry', 'time');

-- =========================================================================
-- Placeholder tables (future components)
-- =========================================================================

CREATE TABLE gtfs_rt_vehicle_positions (
    time                  TIMESTAMPTZ NOT NULL,
    vehicle_id            TEXT NOT NULL,
    route_id              TEXT,
    trip_id               TEXT,
    latitude              DOUBLE PRECISION,
    longitude             DOUBLE PRECISION,
    bearing               REAL,
    speed                 REAL,
    current_stop_sequence INTEGER,
    stop_id               TEXT,
    current_status        TEXT,
    raw                   JSONB
);

SELECT create_hypertable('gtfs_rt_vehicle_positions', 'time');

CREATE TABLE gtfs_rt_trip_updates (
    time            TIMESTAMPTZ NOT NULL,
    trip_id         TEXT NOT NULL,
    route_id        TEXT,
    direction_id    SMALLINT,
    vehicle_id      TEXT,
    stop_id         TEXT,
    stop_sequence   INTEGER,
    arrival_delay   INTEGER,
    departure_delay INTEGER,
    raw             JSONB
);

SELECT create_hypertable('gtfs_rt_trip_updates', 'time');

CREATE INDEX idx_gtfs_rt_stop ON gtfs_rt_trip_updates(stop_id);

CREATE TABLE gtfs_rt_service_alerts (
    id                  BIGSERIAL PRIMARY KEY,
    alert_id            TEXT,
    received_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    cause               TEXT,
    effect              TEXT,
    header_text         TEXT,
    description_text    TEXT,
    severity            TEXT,
    active_period_start TIMESTAMPTZ,
    active_period_end   TIMESTAMPTZ,
    raw                 JSONB
);

CREATE TABLE predictions (
    time                       TIMESTAMPTZ NOT NULL,
    vehicle_id                 TEXT NOT NULL,
    route_id                   TEXT NOT NULL,
    direction_id               SMALLINT,
    stop_id                    TEXT NOT NULL,
    stop_sequence              INTEGER,
    predicted_passengers       INTEGER NOT NULL,
    predicted_passengers_after INTEGER,
    vehicle_capacity           INTEGER NOT NULL,
    predicted_occupancy_pct    REAL,
    waiting_at_stop            INTEGER,
    boarded                    INTEGER,
    alighted                   INTEGER,
    has_data                   BOOLEAN,
    model_version              TEXT,
    confidence                 REAL,
    metadata                   JSONB DEFAULT '{}'
);

SELECT create_hypertable('predictions', 'time');

CREATE TABLE scheduler_decisions (
    id                      BIGSERIAL PRIMARY KEY,
    decided_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    decision_type           TEXT NOT NULL,
    route_id                TEXT,
    direction_id            SMALLINT,
    vehicle_id              TEXT,
    trigger_vehicle_id      TEXT,
    trigger_stop_id         TEXT,
    predicted_passengers    INTEGER,
    predicted_occupancy_pct REAL,
    vehicle_capacity        INTEGER,
    total_stranded          INTEGER,
    threshold               REAL,
    message                 TEXT,
    status                  TEXT DEFAULT 'pending',
    executed_at             TIMESTAMPTZ,
    result                  JSONB,
    metadata                JSONB DEFAULT '{}'
);
