# Running the Demo

## Prerequisites

- Docker Desktop running
- TLS certs generated (`cd docker/mosquitto/certs && bash generate_certs.sh`) -- one-time only
- Python venv set up with dependencies installed
- **For GTFS-RT data:** Set `GTFSR_API_KEY` in `.env` (register at [NTA Developer Portal](https://developer.nationaltransport.ie)). Requires internet access. If not set, the demo runs without real-time vehicle/delay data -- the dashboard still works, just without on-time performance charts

## Start

```bash
bash scripts/start_demo.sh
```

The script starts everything in order, checks connectivity, and prints the dashboard URL when ready.

**Startup sequence:**

1. Docker containers (Mosquitto + TimescaleDB)
2. Database seed (idempotent -- skips if already seeded)
3. Process cleanup (kills leftover Python processes from previous runs)
4. Backend runtime supervisor -- one process that manages:
   - MQTT BrokerHandler (subprocess, service mode)
   - FastAPI API server (subprocess via uvicorn)
   - GTFS-RT fetcher (subprocess, conditional -- skipped if no API key)
   - Prediction loop (embedded thread, reacts to new crowd + GTFS data)
5. React dashboard (Vite dev server)
6. Crowd count simulator (backfills ~30s, then continuous updates)
7. Data-flow checks (crowd counts, GTFS-RT rows, predictions, WebSocket probe)
8. Firewall safety audit (verifies all ports are loopback-only)

The runtime supervisor automatically restarts any backend service that crashes.

**Options:**

```bash
SIM_TIME_SCALE=10 bash scripts/start_demo.sh    # fast-forward: full day in ~2.4 hours
SIM_RANDOM_SEED=42 bash scripts/start_demo.sh   # reproducible data
```

## Services and Ports

| Service | Address | Notes |
|---------|---------|-------|
| Dashboard | `http://localhost:5173` | React app (may fall back to 5174) |
| FastAPI | `http://127.0.0.1:8000` | WebSocket at `/ws/dashboard` |
| Mosquitto | `127.0.0.1:8883` | MQTTS (TLS) |
| TimescaleDB | `127.0.0.1:5432` | PostgreSQL + TimescaleDB |

All ports bind to `127.0.0.1` only -- no traffic leaves the machine, so local firewalls are not an issue.

## Environment Variables

Set these in `.env` at the project root (copy from `.env.example`):

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GTFSR_API_KEY` | For GTFS-RT | (none) | NTA API key for real-time vehicle data |
| `GTFSR_AGENCY_FILTER` | No | `7778019` | Agency ID for route filtering (empty = all agencies) |
| `SIM_TIME_SCALE` | No | `1` | Time compression factor (e.g., `10` = 10x faster) |
| `SIM_RANDOM_SEED` | No | (random) | Fixed seed for reproducible demo data |

## Stop

```bash
bash scripts/stop_demo.sh
```

To keep Docker running between restarts (faster -- database stays seeded):

```bash
bash scripts/stop_demo.sh --keep-docker
```

## Logs

Service logs are written to `logs/`:

| Log file | Service |
|----------|---------|
| `runtime_supervisor.log` | Runtime supervisor + prediction loop |
| `broker_handler.log` | MQTT BrokerHandler |
| `api_server.log` | FastAPI API |
| `dashboard.log` | React dev server |
| `simulator.log` | Crowd count simulator |
| `gtfsrt_fetcher.log` | GTFS-RT fetcher |
