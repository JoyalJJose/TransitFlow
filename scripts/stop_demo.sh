#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
#  TransitFlow Demo – Stop All Services
#
#  Run from the project root:
#    bash scripts/stop_demo.sh
#
#  Options:
#    --keep-docker   Stop app services but leave Docker containers running
#                    (faster restart next time, DB stays seeded)
# ─────────────────────────────────────────────────────────────────
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${CYAN}[demo]${NC} $*"; }
ok()   { echo -e "  ${GREEN}✓${NC} $*"; }
warn() { echo -e "  ${YELLOW}⚠${NC} $*"; }

KEEP_DOCKER=false
for arg in "$@"; do
    case "$arg" in
        --keep-docker) KEEP_DOCKER=true ;;
    esac
done

# ── 1. Kill processes on known ports ─────────────────────────────
log "Stopping application services…"

for port in 8000 5173 5174; do
    pid=$(netstat -aon 2>/dev/null | grep ":${port}.*LISTENING" | awk '{print $5}' | head -1)
    if [ -n "$pid" ] && [ "$pid" != "0" ]; then
        taskkill //PID "$pid" //F >/dev/null 2>&1 || true
        ok "Stopped process on port $port (PID $pid)"
    fi
done

# ── 2. Kill Python processes for our modules (PowerShell – reliable on Windows)
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
        ok "Stopped Python process (PID $pid)"
    done <<< "$killed"
else
    ok "No leftover Python demo processes found"
fi

ok "Application services stopped"

# ── 3. Docker containers ─────────────────────────────────────────
if [ "$KEEP_DOCKER" = true ]; then
    warn "Docker containers left running (--keep-docker)"
else
    log "Stopping Docker containers…"
    docker compose -f "$ROOT/docker/docker-compose.yml" down 2>&1 | sed 's/^/  /'
    ok "Docker containers stopped"
fi

# ── 4. Verify nothing is listening ────────────────────────────────
echo ""
remaining=0
for port in 8883 5432 8000 5173 5174; do
    if python -c "import socket; s=socket.create_connection(('127.0.0.1',$port),timeout=0.5); s.close()" 2>/dev/null; then
        if [ "$KEEP_DOCKER" = true ] && ([ "$port" = "8883" ] || [ "$port" = "5432" ]); then
            continue
        fi
        warn "Port $port still in use"
        remaining=1
    fi
done

if [ "$remaining" -eq 0 ]; then
    echo -e "${GREEN}All services stopped cleanly.${NC}"
else
    echo -e "${YELLOW}Some ports still in use – processes may take a moment to exit.${NC}"
fi
echo ""
echo -e "To restart:  ${CYAN}bash scripts/start_demo.sh${NC}"
