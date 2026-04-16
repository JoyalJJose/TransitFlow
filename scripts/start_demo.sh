#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
#  TransitFlow Demo – Start All Services
#
#  Run from the project root:
#    bash scripts/start_demo.sh
#
#  Optional env vars:
#    SIM_TIME_SCALE=10   – compress a full day into ~2.4 h
#    SIM_RANDOM_SEED=42  – reproducible demo data
# ─────────────────────────────────────────────────────────────────
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Export variables from .env so child processes (simulator, fetcher) inherit them.
# Shell-level vars (e.g. SIM_TIME_SCALE=3) still override via the command line.
if [ -f "$ROOT/.env" ]; then
    set -a
    source "$ROOT/.env"
    set +a
fi

LOGDIR="$ROOT/logs"
mkdir -p "$LOGDIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${CYAN}[demo]${NC} $*"; }
ok()   { echo -e "  ${GREEN}✓${NC} $*"; }
warn() { echo -e "  ${YELLOW}⚠${NC} $*"; }
fail() { echo -e "  ${RED}✗${NC} $*"; exit 1; }

# Track background PIDs for cleanup
PIDS=()
CLEANUP_DONE=0
cleanup() {
    if [ "$CLEANUP_DONE" -eq 1 ]; then
        return
    fi
    CLEANUP_DONE=1
    trap - EXIT INT TERM

    echo ""
    log "Shutting down…"
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null && kill $(jobs -p) 2>/dev/null || true
    done
    wait 2>/dev/null || true
    log "Logs saved to $LOGDIR/"
    log "Done. Run ${YELLOW}bash scripts/stop_demo.sh${NC} to also stop Docker."
}
trap cleanup EXIT INT TERM

wait_for_port() {
    local host=$1 port=$2 label=$3 max_wait=${4:-30}
    local elapsed=0
    while ! python -c "import socket; s=socket.create_connection(('$host',$port),timeout=1); s.close()" 2>/dev/null; do
        sleep 1
        elapsed=$((elapsed + 1))
        if [ "$elapsed" -ge "$max_wait" ]; then
            fail "$label not reachable on $host:$port after ${max_wait}s"
        fi
    done
    ok "$label listening on $host:$port"
}

# ── 0. Prerequisites ──────────────────────────────────────────────
log "Checking prerequisites…"

command -v docker >/dev/null 2>&1 || fail "docker not found"
ok "docker available"

command -v python >/dev/null 2>&1 || fail "python not found"
ok "python available"

if [ ! -d "$ROOT/.venv" ]; then
    fail ".venv not found – run: python -m venv .venv && pip install -r requirements"
fi
ok ".venv exists"

source "$ROOT/.venv/Scripts/activate" 2>/dev/null \
    || source "$ROOT/.venv/bin/activate" 2>/dev/null \
    || fail "Could not activate venv"
ok "venv activated"

if [ ! -f "$ROOT/docker/mosquitto/certs/ca.crt" ]; then
    fail "TLS certs missing – run: cd docker/mosquitto/certs && bash generate_certs.sh"
fi
ok "TLS certificates present"

# ── 1. Docker containers ─────────────────────────────────────────
log "Starting Docker containers…"
docker compose -f "$ROOT/docker/docker-compose.yml" up -d 2>&1 | sed 's/^/  /'

wait_for_port 127.0.0.1 8883 "Mosquitto"   15

log "Waiting for TimescaleDB to be healthy…"
for i in $(seq 1 60); do
    health=$(docker inspect --format='{{.State.Health.Status}}' transitflow-db 2>/dev/null)
    if [ "$health" = "healthy" ]; then
        ok "TimescaleDB healthy"
        break
    fi
    if [ "$i" -eq 60 ]; then fail "TimescaleDB not healthy after 60s"; fi
    sleep 1
done

# ── 2. Seed database (idempotent) ────────────────────────────────
log "Checking database…"
row_count=$(docker exec transitflow-db psql -U transitflow -d transitflow -tAc \
    "SELECT count(*) FROM stops;" 2>/dev/null || echo "0")

if [ "${row_count:-0}" -gt 0 ]; then
    ok "Database already seeded ($row_count stops) – skipping"
else
    log "Seeding database (this may take ~60s on first run)…"
    if (cd "$ROOT/src" && python -m Backend.Database.seed 2>&1 | sed 's/^/  /'); then
        ok "Database seeded"
    else
        fail "Database seeding FAILED (see output above)"
    fi
fi

# ── 2b. Seed demo data (vehicles, telemetry, alerts) ─────────────
vehicle_count=$(docker exec transitflow-db psql -U transitflow -d transitflow -tAc \
    "SELECT count(*) FROM vehicles;" 2>/dev/null || echo "0")

if [ "${vehicle_count:-0}" -gt 0 ]; then
    ok "Demo data already seeded ($vehicle_count vehicles) – skipping"
else
    log "Seeding demo data (vehicles, telemetry, alerts)…"
    if (cd "$ROOT/src" && python -m Backend.Database.seed_test_data 2>&1 | sed 's/^/  /'); then
        ok "Demo data seeded"
        docker exec transitflow-db psql -U transitflow -d transitflow \
            -c "NOTIFY dashboard_update, 'seed_complete'" >/dev/null 2>&1 || true
    else
        warn "Demo data seeding failed (non-critical)"
    fi
fi

# ── 3. Kill any leftover demo processes ───────────────────────────
log "Cleaning up leftover processes…"
for port in 8000 5173 5174; do
    existing_pid=$(netstat -aon 2>/dev/null | grep ":${port}.*LISTENING" | awk '{print $5}' | head -1)
    if [ -n "$existing_pid" ] && [ "$existing_pid" != "0" ]; then
        taskkill //PID "$existing_pid" //F >/dev/null 2>&1 || true
        warn "Killed existing process on port $port (PID $existing_pid)"
    fi
done

# Kill leftover Python processes for our modules (prevents MQTT client_id collision)
killed=$(powershell -Command "
    \$pattern = 'Simulator\.main|Backend\.MQTTBroker\.main|Backend\.API\.main|Backend\.GTFS_RT|Backend\.runtime_supervisor|uvicorn Backend\.API'
    Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" 2>\$null |
        Where-Object { \$_.CommandLine -match \$pattern } |
        ForEach-Object {
            Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue
            Write-Host \$_.ProcessId
        }
" 2>/dev/null || true)

if [ -n "$killed" ]; then
    while IFS= read -r pid; do
        warn "Killed leftover Python process (PID $pid)"
    done <<< "$killed"
fi

# ── 4. Backend runtime supervisor ─────────────────────────────────
# One process supervises MQTT broker, API, GTFS-RT (if key set), and
# an embedded prediction loop.  Each service logs to its own file.
log "Starting backend runtime supervisor…"

GTFSRT_RUNNING=false
if [ -n "${GTFSR_API_KEY:-}" ]; then
    GTFSRT_RUNNING=true
fi

(cd "$ROOT" && PYTHONPATH=src python -m Backend.runtime_supervisor \
) >"$LOGDIR/runtime_supervisor.log" 2>&1 &
PIDS+=($!)

# Wait for API to come up (started by supervisor)
wait_for_port 127.0.0.1 8000 "FastAPI (via supervisor)" 20

# Quick verification of sub-services
sleep 3
if grep -q "Subscribed to all edge" "$LOGDIR/broker_handler.log" 2>/dev/null; then
    ok "MQTT BrokerHandler connected (log: logs/broker_handler.log)"
elif grep -q "Backend connected" "$LOGDIR/broker_handler.log" 2>/dev/null; then
    ok "MQTT BrokerHandler connected (log: logs/broker_handler.log)"
else
    warn "MQTT BrokerHandler may still be connecting (check logs/broker_handler.log)"
fi

if [ "$GTFSRT_RUNNING" = true ]; then
    if grep -q "Fetched GTFS-R feed\|fetcher started" "$LOGDIR/gtfsrt_fetcher.log" 2>/dev/null; then
        ok "GTFS-RT fetcher active (log: logs/gtfsrt_fetcher.log)"
    else
        warn "GTFS-RT fetcher may still be starting (check logs/gtfsrt_fetcher.log)"
    fi
fi

if grep -q "Cycle complete\|Prediction loop started" "$LOGDIR/runtime_supervisor.log" 2>/dev/null; then
    ok "Prediction loop running (log: logs/runtime_supervisor.log)"
else
    warn "Prediction loop may still be starting (check logs/runtime_supervisor.log)"
fi

# ── 5. Frontend dashboard ─────────────────────────────────────────
log "Starting React dashboard…"
(cd "$ROOT/src/Frontend/dashboard" && npm run dev) >"$LOGDIR/dashboard.log" 2>&1 &
PIDS+=($!)
sleep 4

DASHBOARD_PORT="?"
if python -c "import socket; s=socket.create_connection(('127.0.0.1',5173),timeout=1); s.close()" 2>/dev/null; then
    DASHBOARD_PORT=5173
elif python -c "import socket; s=socket.create_connection(('127.0.0.1',5174),timeout=1); s.close()" 2>/dev/null; then
    DASHBOARD_PORT=5174
fi
ok "Dashboard running on http://localhost:$DASHBOARD_PORT/ (log: logs/dashboard.log)"

# ── 6. Crowd-count simulator ─────────────────────────────────────
log "Starting crowd-count simulator…"
(cd "$ROOT" && \
    SIM_TIME_SCALE="${SIM_TIME_SCALE:-1}" \
    SIM_RANDOM_SEED="${SIM_RANDOM_SEED:-}" \
    PYTHONPATH=src python -m Simulator.main \
) >"$LOGDIR/simulator.log" 2>&1 &
PIDS+=($!)

# Wait for the simulator to finish backfill
log "Waiting for simulator backfill (587 stops × 0.05s ≈ 30s)…"
for i in $(seq 1 60); do
    if grep -q "Entering main loop" "$LOGDIR/simulator.log" 2>/dev/null; then
        ok "Simulator backfill complete – entering main loop"
        break
    fi
    if grep -q "Error\|Traceback\|error" "$LOGDIR/simulator.log" 2>/dev/null; then
        fail "Simulator error – check logs/simulator.log"
    fi
    if [ "$i" -eq 60 ]; then warn "Simulator still backfilling (check logs/simulator.log)"; fi
    sleep 1
done

# ── 7. Final connectivity / data-flow check ──────────────────────
log "Running final connectivity check…"
sleep 3

# Crowd data reached DB (via simulator → MQTT → broker → writer)
db_rows=$(docker exec transitflow-db psql -U transitflow -d transitflow -tAc \
    "SELECT count(*) FROM current_counts WHERE count >= 0;" 2>/dev/null || echo "0")
if [ "${db_rows:-0}" -gt 0 ]; then
    ok "Crowd data: $db_rows stops with live counts"
else
    warn "No crowd data in current_counts yet"
fi

# GTFS-RT data reached DB (if fetcher is active)
if [ "$GTFSRT_RUNNING" = true ]; then
    gtfs_rows=$(docker exec transitflow-db psql -U transitflow -d transitflow -tAc \
        "SELECT count(*) FROM gtfs_rt_trip_updates;" 2>/dev/null || echo "0")
    if [ "${gtfs_rows:-0}" -gt 0 ]; then
        ok "GTFS-RT data: $gtfs_rows trip update rows"
    else
        warn "No GTFS-RT trip updates yet (may take up to 60s)"
    fi
fi

# Predictions written by embedded prediction loop
pred_rows=$(docker exec transitflow-db psql -U transitflow -d transitflow -tAc \
    "SELECT count(*) FROM predictions;" 2>/dev/null || echo "0")
if [ "${pred_rows:-0}" -gt 0 ]; then
    ok "Predictions: $pred_rows rows"
else
    warn "No predictions yet (first cycle may still be running)"
fi

# WebSocket payload check
ws_ok=$(python -c "
import asyncio, websockets, json
async def check():
    async with websockets.connect('ws://127.0.0.1:8000/ws/dashboard') as ws:
        msg = await asyncio.wait_for(ws.recv(), timeout=10)
        data = json.loads(msg)
        swc = len(data.get('stopWaitCounts', []))
        hs = len(data.get('crowdingHotspots', []))
        print(f'{swc} stopWaitCounts, {hs} crowdingHotspots')
asyncio.run(check())
" 2>&1 || echo "FAILED")

if echo "$ws_ok" | grep -q "FAILED"; then
    warn "WebSocket check failed – dashboard may not show live data"
else
    ok "WebSocket payload: $ws_ok"
fi

# ── 8. Firewall safety audit ─────────────────────────────────────
log "Firewall safety check…"
unsafe=0
for port in 5432 8883 8000; do
    binding=$(netstat -an 2>/dev/null | grep ":${port}.*LISTENING" | head -1)
    if echo "$binding" | grep -q "0\.0\.0\.0:${port}"; then
        warn "Port $port bound to 0.0.0.0 (exposed to network)"
        unsafe=1
    elif echo "$binding" | grep -q "127\.0\.0\.1:${port}"; then
        ok "Port $port bound to 127.0.0.1 only (firewall-safe)"
    fi
done

if [ "$unsafe" -eq 0 ]; then
    ok "All service ports are loopback-only – no firewall issues"
else
    warn "Some ports exposed externally – may be blocked by firewall"
fi

# ── Summary ───────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  TransitFlow Demo is LIVE${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  Dashboard:   ${CYAN}http://localhost:${DASHBOARD_PORT}/${NC}"
echo -e "  API:         ${CYAN}http://127.0.0.1:8000${NC}"
echo -e "  MQTT:        ${CYAN}127.0.0.1:8883${NC} (TLS)"
echo -e "  Database:    ${CYAN}127.0.0.1:5432${NC}"
echo -e "  Time scale:  ${CYAN}${SIM_TIME_SCALE:-1}x${NC}"
if [ "$GTFSRT_RUNNING" = true ]; then
    echo -e "  GTFS-RT:     ${GREEN}active${NC} (NTA API — requires internet)"
else
    echo -e "  GTFS-RT:     ${YELLOW}inactive${NC} (no API key or failed to start)"
fi
echo ""
echo -e "  Logs:        ${CYAN}logs/${NC} (runtime_supervisor, broker_handler, api_server, dashboard, simulator, gtfsrt_fetcher)"
echo ""
echo -e "  Press ${YELLOW}Ctrl+C${NC} to stop all services"
echo ""

# Keep the script alive – tail supervisor + simulator logs for live feedback
tail -f "$LOGDIR/runtime_supervisor.log" "$LOGDIR/simulator.log" 2>/dev/null &
PIDS+=($!)
wait "${PIDS[@]}" 2>/dev/null || true
