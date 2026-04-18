# TransitFlow

Real-time transit operations demo. Simulates stop-level crowding, ingests live/streamed data into TimescaleDB, runs predictions, and serves a live dashboard via FastAPI + WebSocket + React.

## Start

Requires Docker Desktop running.

```bash
docker compose -f docker/docker-compose.demo.yml up -d --build --wait
```

- Dashboard: http://127.0.0.1:5173
- API: http://127.0.0.1:8000/api/health

## Stop

```bash
docker compose -f docker/docker-compose.demo.yml down -v && docker rmi transitflow-demo/app:latest transitflow-demo/mosquitto:latest transitflow-demo/dashboard:latest
```

Removes this demo's containers, network, volumes, and only its three image tags. Nothing else on your Docker host is touched.

## API Keys (optional)

Without keys the system still boots, but two features degrade: live GTFS-Realtime trip updates are disabled (simulator, predictions, and the rest of the dashboard keep working), and the dashboard map tiles do not render (non-map dashboard data still works).

Create `.env` in the repo root and append:

```
GTFSR_API_KEY=your_nta_gtfsr_key
```

For map tiles, create `src/Frontend/dashboard/.env` and append:

```
VITE_MAPBOX_ACCESS_TOKEN=your_mapbox_token
```

Re-run the Start command to pick up new values.
