# TransitFlow Testing Plan

## 1. Purpose and Scope

This plan summarises how the TransitFlow implementation is verified. The
goal of testing is not exhaustive correctness proof but to give confidence
that the major architectural components of a real-time public transport
decision-support system behave correctly in isolation and cooperate
correctly end-to-end. Testing exercises the edge sensing pipeline, the
MQTT transport layer, the backend ingestion and persistence layer, the
prediction and evaluation engine, the dashboard API, and the GTFS-Realtime
integration. Deliberately out of scope: physical camera hardware, live NTA
GTFS-RT production traffic, and load or stress testing beyond the
single-host demo deployment.

## 2. Test Strategy

Testing follows a three-layer model, each layer chosen to match the cost
and determinism of the component being exercised:

- **Unit layer.** Every component whose behaviour is deterministic enough
  to run without Docker is tested in isolation. Heavy dependencies
  (OpenCV, YOLO, `psycopg2`, `requests`, `asyncpg`, `subprocess`) are
  mocked. This layer forms the bulk of the suite and runs in well under a
  minute, so it is cheap to re-run during development.
- **Integration layer.** DB-backed flows (the SnapshotBuilder -> engine ->
  evaluator -> writer pipeline, and proportional crowd splitting across
  competing routes) are tested against a real TimescaleDB container seeded
  with GTFS-static data and synthetic GTFS-RT rows. This layer proves that
  the schema, SQL, and business logic agree.
- **End-to-end layer.** Full MQTT transport is exercised over a real
  Mosquitto broker with TLS, with both edge and backend clients connected,
  proving connectivity, subscriptions, QoS, message framing, and the
  model-transfer chunking and SHA256 verification loop.

Mocks are used for three purposes: to remove hardware (`cv2`, camera,
YOLO), to remove network (NTA API, MQTT socket), and to make
non-deterministic code (wall-clock, random) reproducible. No production
code has been modified purely to make it testable; where helpers were
added (for example the auto-marker `conftest.py`) they live in the test
tree.

## 3. Test Categories and Tooling

| Category     | Location                | Dependencies                    | Runtime    |
|--------------|-------------------------|---------------------------------|------------|
| Unit         | `tests/{edge,database,prediction,simulator,api,gtfs_rt,supervisor}` | `pytest`, `pytest-cov`          | ~90 s      |
| Integration  | `tests/integration`     | + Docker TimescaleDB            | ~45 s      |
| End-to-end   | `tests/mqtt`            | + Docker Mosquitto + TimescaleDB | ~35 s      |

Categories are applied automatically by `tests/conftest.py` based on the
containing directory so every test inherits the right marker, and runs
can be filtered with `pytest -m unit` (for example). Coverage is recorded
with `pytest-cov` in branch mode using the configuration in
`pyproject.toml`.

## 4. Traceability to Project Objectives

The eight objectives from `PROJECT_OVERVIEW.md` are verified as follows:

- **Obj 1 - reliable edge sensing.** `tests/edge` covers RuntimeSettings,
  FrameBuffer, ThermalCamera pipeline control, CrowdCounter pause/resume,
  and admin-dispatch routing.
- **Obj 2 - secure edge-to-backend communication.** `tests/mqtt` exercises
  TLS-protected MQTT flows including crowd counts, images, logs, admin
  commands, and online/offline status. `tests/edge` covers reconnect and
  the paho-mqtt Callback API v2 integration.
- **Obj 3 - time-series data layer.** `tests/database` covers the
  ConnectionPool lifecycle, the DatabaseWriter inserts and upserts, and
  the BrokerHandler-to-writer delegation.
- **Obj 4 - GTFS-RT integration.** `tests/gtfs_rt` covers the
  protobuf parser, the 60-second rate-limit guard, HTTP error handling,
  agency filtering, and the fetch-filter-write cycle.
- **Obj 5 - prediction and evaluation.** `tests/prediction` covers the
  sequential boarding/alighting simulation (65 tests), the proportional
  crowd-split at shared stops, and the SnapshotBuilder DB-to-engine
  bridge. `tests/integration` proves the full pipeline writes predictions
  and scheduler decisions to the DB.
- **Obj 6 - real-time dashboard delivery.** `tests/api` covers every
  dashboard payload helper in `queries.py`, the WebSocket
  ConnectionManager (including stale-client eviction), health endpoints,
  CORS, and on-demand REST routes.
- **Obj 7 - modular and extensible architecture.** Every production
  module is covered by at least one test suite, and unit tests use only
  duck-typed interfaces (pool, cursor, client) so they run without the
  real backing services.
- **Obj 8 - system suitability evaluation.** Coverage statistics (below)
  and the results summary give a measurable view of which parts of the
  system are exercised and which are acknowledged gaps.

## 5. Risk-based Coverage

The highest-risk behaviours are explicitly targeted:

- **MQTT reconnect and callback-API drift** - verified by `tests/mqtt`
  (real broker reconnect) and `tests/edge` (callback signatures). Testing
  caught a live bug here: paho-mqtt 2.1 requires Callback API v2 and the
  original edge and backend clients were still using v1 signatures.
- **Model OTA install and rollback** - `tests/edge` covers successful
  install, rollback on corrupt model reload, rollback with no backup, and
  pause/resume ordering around install.
- **Proportional crowd splitting at shared stops** - unit tested against
  the pure `proportional_split` function and against the builder
  call-site, and integration tested with two real routes at a shared
  stop.
- **GTFS-RT rate-limit compliance** - unit tested with a mocked
  monotonic clock showing the second call within 60 s sleeps the correct
  remainder; important for compliance with NTA fair-usage.
- **Privacy-aware counting** - the edge pipeline stores and transmits
  only integer counts and derived logs; no image-level tests assert on
  PII because no PII is ever produced. Image transport tests in
  `tests/mqtt` verify only that bytes are preserved, not their content.

## 6. Metrics and Acceptance Criteria

- All unit tests pass from a clean venv created from
  `requirements-dev.txt`.
- Unit line coverage averages at least 80 percent across pure-logic
  modules (Prediction engine, evaluator, snapshot builder, simulator
  components, database pool).
- Branch coverage is enabled; any conditional that is not exercised is
  visible in the terminal and HTML reports.
- Orchestration modules (`runtime_supervisor`, API lifespan,
  `GTFS_RT/main` poll loop) do not need full coverage: their steady-state
  loops are deliberately left to integration runs because mocking an
  entire process tree adds no useful evidence.
- Full unit run completes in under two minutes on a typical developer
  machine; full run with Docker under three minutes.

## 7. Results Summary

Latest run (unit layer only, branch coverage enabled):

- **Tests:** 242 passed, 0 failed, 0 skipped.
- **Runtime:** ~92 seconds.
- **Overall line coverage:** 60.1 percent across `src/`.
- **Overall branch coverage:** captured and included in the HTML report
  at `htmlcov/index.html`.

Per-module line coverage highlights:

- `PredictionEngine/engine.py`: 100 percent
- `PredictionEngine/snapshot.py`: 100 percent
- `PredictionEngine/evaluator.py`: 98.6 percent
- `PredictionEngine/snapshot_builder.py`: 93.3 percent
- `GTFS_RT/fetcher.py`: 100 percent
- `Database/connection.py`: 97.1 percent
- `Edge/model_manager.py`: 98.0 percent
- `Edge/camera.py`: 91.2 percent
- `Simulator/generator.py`: 100 percent
- `Simulator/profiles.py`: 94.9 percent
- `Simulator/orchestrator.py`: 84.3 percent
- `API/ws.py`: 71.9 percent
- `Edge/model_receiver.py`: 74.8 percent

Modules whose unit coverage is intentionally lower because they are
primarily exercised at the integration or e2e layer:

- `Database/writer.py`: 48 percent unit (most methods also hit by
  `tests/mqtt` and `tests/integration`).
- `API/queries.py`: 48 percent unit (remaining helpers exercised via
  `tests/integration`).
- `Edge/comms.py`, `MQTTBroker/broker_handler.py`: around 30-35 percent
  unit; the full wire-level flow is covered end-to-end by
  `tests/mqtt` (11 tests with a real broker).

Notable bugs found by testing: paho-mqtt Callback API v2 signature
mismatch in both `src/Edge/comms.py` and
`src/Backend/MQTTBroker/broker_handler.py`. Fixing this required changing
the `mqtt.Client()` constructor, the `on_connect` signature, and the
`on_disconnect` signature. Documented in `TESTING.md`.

## 8. Outstanding Risks and Future Work

What is not automatically tested:

- Physical thermal-camera hardware. The YOLO inference module
  (`src/Edge/inference.py`) is mocked entirely at the unit layer; field
  testing is required to validate model accuracy on real thermal frames.
- The live NTA GTFS-RT production feed. The fetcher is validated against
  locally-constructed protobuf fixtures only.
- TLS certificate rotation in production deployments. The MQTT suite
  uses certs generated once at session setup.
- Load and stress behaviour under many concurrent edge devices. The
  current tests prove functional correctness rather than throughput
  limits.

These would be the natural next steps if the project moved from
prototype to production deployment. For the scope of this final-year
implementation they are acknowledged risks rather than gaps that block
the acceptance criteria in Section 6.
