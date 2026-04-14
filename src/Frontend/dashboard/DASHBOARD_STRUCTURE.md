# Dashboard Project — Structure & Code Guide

This document describes the structure, dependencies, and code organization of the **Transit Dashboard** frontend application.

---

## 1. Project Overview

The dashboard is a **real-time transit monitoring UI** for Dublin-area transport (LUAS tram and Dublin Bus). It displays:

- **Live station wait counts** and a **map** of stops with crowding indicators  
- **Route health** (delays, headways, active vehicles)  
- **Fleet overview** (occupancy, fill-level distribution, “most full” vehicles)  
- **Charts**: resource efficiency, on-time performance, fleet utilization  
- **Crowding hotspots** with trend (rising/falling/stable)  
- **Alerts** (dismissible bar at the bottom)  
- **Theme toggle** (light/dark) and **filter** (All / LUAS / Bus)

Data is either **mock** (timer-pushed payloads) or **live** via **WebSocket**, controlled by environment variables.

---

## 2. Technology Stack & Libraries

### 2.1 Runtime / Framework

| Package | Version | Purpose |
|--------|---------|--------|
| **react** | ^19.2.0 | UI framework and component model. |
| **react-dom** | ^19.2.0 | React renderer for the browser (used in `main.jsx` with `createRoot`). |

### 2.2 Mapping

| Package | Version | Purpose |
|--------|---------|--------|
| **mapbox-gl** | ^3.18.1 | Mapbox GL JS — renders the interactive map (tiles, markers, styles). Provides the base map and `mapbox-gl.css`. |
| **react-map-gl** | ^8.1.0 | React bindings for Mapbox GL. Used in `MapView.jsx`: `<Map>`, `<Marker>`, `<NavigationControl>` from `react-map-gl/mapbox`. Handles view state, markers for stops, and light/dark map styles. |

**Note:** Map requires `VITE_MAPBOX_ACCESS_TOKEN` in `.env`. Without it, a placeholder message is shown.

### 2.3 Charts

| Package | Version | Purpose |
|--------|---------|--------|
| **recharts** | ^3.7.0 | Declarative chart library. Used for: **BarChart** (Resource Efficiency in `CenterCharts.jsx`), **AreaChart** (On-Time Performance in `CenterCharts.jsx`, Fleet Utilization in `PerformanceMetrics.jsx`). Provides `XAxis`, `YAxis`, `CartesianGrid`, `Tooltip`, `ResponsiveContainer`, `Bar`, `Area`, `Cell`. |

### 2.4 Build & Dev Tooling

| Package | Version | Purpose |
|--------|---------|--------|
| **vite** | ^7.3.1 | Build tool and dev server. Entry: `index.html` → `/src/main.jsx`. |
| **@vitejs/plugin-react** | ^5.1.1 | Vite plugin for React (JSX, Fast Refresh). |
| **babel-plugin-react-compiler** | ^1.0.0 | Optional React Compiler plugin; configured in `vite.config.js` for automatic optimizations. |

### 2.5 Linting & Types

| Package | Version | Purpose |
|--------|---------|--------|
| **eslint** | ^9.39.1 | Linting. |
| **@eslint/js** | ^9.39.1 | ESLint JavaScript parser/config. |
| **eslint-plugin-react-hooks** | ^7.0.1 | Enforces Rules of Hooks. |
| **eslint-plugin-react-refresh** | ^0.4.24 | Prevents component state loss during HMR. |
| **globals** | ^16.5.0 | Global variables for ESLint env. |
| **@types/react** | ^19.2.7 | TypeScript types for React (dev). |
| **@types/react-dom** | ^19.2.3 | TypeScript types for React DOM (dev). |

**Summary:** No UI component library (e.g. MUI) is used; the UI is custom-built with CSS. Icons are inline SVG components in the code (e.g. in `HeaderBar.jsx`).

---

## 3. Project Structure

```
dashboard/
├── index.html                 # Single-page app entry; mounts #root, loads /src/main.jsx
├── package.json               # Dependencies and scripts (dev, build, lint, preview)
├── vite.config.js             # Vite config: React plugin + Babel React Compiler
├── .env                        # Env vars (e.g. VITE_MAPBOX_ACCESS_TOKEN, VITE_WS_URL)
├── .gitignore
├── README.md
├── DASHBOARD_STRUCTURE.md      # This file
│
├── src/
│   ├── main.jsx                # App entry: StrictMode, index.css, renders <App />
│   ├── App.jsx                 # Root component: data subscription, filter, layout, theme
│   ├── App.css                 # All dashboard layout and component styles
│   ├── index.css               # Global reset and CSS variables (light/dark themes)
│   │
│   ├── config/
│   │   └── api.js              # API/WS and mock flags from env (API_BASE_URL, WS_URL, USE_MOCK_DATA, MOCK_PUSH_INTERVAL_MS)
│   │
│   ├── services/
│   │   └── dataService.js      # subscribeToDashboard(onMessage, onError) — mock timer or WebSocket
│   │
│   ├── data/
│   │   └── mockTransportData.js # ROUTES, STOPS (Dublin GTFS), generateMockTransportPayload()
│   │
│   ├── components/             # All presentational/container UI components
│   │   ├── HeaderBar.jsx       # Top bar: menu, home, title, filter pill, search
│   │   ├── StationPanel.jsx    # Live station list + wait counts
│   │   ├── MapView.jsx         # Mapbox map + stop markers (size/color by wait count)
│   │   ├── CenterCharts.jsx     # Resource Efficiency bar chart + On-Time area chart
│   │   ├── FleetOverview.jsx    # Fleet stats, fill distribution, “most full” bars
│   │   ├── PerformanceMetrics.jsx # Fleet utilization area chart
│   │   ├── RouteHealth.jsx     # Route list with status, delay, headway, vehicles
│   │   ├── CrowdingHotspots.jsx # Top crowding stops with trend
│   │   ├── AlertBar.jsx         # Bottom alert strip (dismiss, acknowledge, details)
│   │   ├── DashboardCharts.jsx  # (Present in repo; not imported in App.jsx — legacy/unused)
│   │   └── SummaryCards.jsx    # (Present in repo; not imported in App.jsx — legacy/unused)
│   │
│   └── assets/                 # Static assets
│       ├── dublin-bus.svg
│       └── luas.svg
│
├── dist/                       # Production build output (vite build)
└── node_modules/               # Installed dependencies
```

---

## 4. Entry Points & Data Flow

### 4.1 Entry

1. **index.html** loads `/src/main.jsx`.
2. **main.jsx** imports `index.css` and `App.jsx`, then renders `<App />` inside `StrictMode` into `#root`.

### 4.2 Data Subscription (App.jsx)

- **subscribeToDashboard(onMessage, onError)** (from `services/dataService.js`):
  - **Mock mode** (when `USE_MOCK_DATA` is true or `VITE_WS_URL` is unset): uses `setInterval` to push `generateMockTransportPayload()` every `MOCK_PUSH_INTERVAL_MS` (4s).
  - **Live mode**: opens a WebSocket to `WS_URL`, parses JSON messages, calls `onMessage(payload)`, and on error/close calls `onError` and reconnects after a delay.

- **App** keeps:
  - `data` — latest full payload (or `null` before first message).
  - `error` — connection/error message shown in an error strip.
  - `theme` — `'light' | 'dark'` (synced to `document.documentElement.setAttribute('data-theme', theme)` and `localStorage`).
  - `filter` — `'all' | 'luas' | 'bus'`.

- **Filtering:** A `useMemo` derives `filtered` from `data` and `filter`: it filters `routes`, `stops`, `stopWaitCounts`, `vehicles`, `resourceEfficiency`, `onTimeData`/`onTimeDataByType`, `fleetUtilization`/`fleetUtilByType`, `routeHealth`, and `crowdingHotspots` so panels only show data for the selected mode.

- **Loading:** If `filtered` is null, App renders a “Connecting to data source…” loading view. Otherwise it renders the full dashboard layout and passes `filtered.*` and `theme` into the child components.

### 4.3 Dashboard Payload Shape (from mock or WebSocket)

The object passed to `onMessage` is expected to have this structure (as produced by `generateMockTransportPayload()`):

- **lastUpdated** — ISO timestamp string  
- **routes** — `Array<{ id, name, type, stopIds }>`  
- **stops** — `Array<{ id, name, lat, lng }>`  
- **stopWaitCounts** — `Array<{ stopId, count }>`  
- **vehicles** — `Array<{ id, routeId, currentOccupancyPercent, expectedAtStops? }>`  
- **onTimeData** — `Array<{ time, onTimePercent }>`  
- **onTimeDataByType** — `{ luas: [...], bus: [...] }` (same shape)  
- **fleetUtilization** — `Array<{ time, avgOccupancy }>`  
- **fleetUtilByType** — `{ luas: [...], bus: [...] }`  
- **resourceEfficiency** — `Array<{ route, efficiency }>`  
- **routeHealth** — `Array<{ routeId, routeName, type, status, delayMin, scheduledHeadway, currentHeadway, activeVehicles }>`  
- **crowdingHotspots** — `Array<{ stopId, stopName, count, trend, delta }>`  
- **alerts** — `Array<{ id, message, severity, timestamp }>`

---

## 5. Component Overview

### 5.1 App.jsx

- Subscribes to dashboard data (mock or WebSocket).
- Manages theme and filter state; applies theme to the document and localStorage.
- Computes filtered dataset and renders:
  - **HeaderBar** (theme toggle, filter, search, menu).
  - Error strip when `error` is set.
  - Three-column **dashboard-grid**: left (StationPanel, RouteHealth, CrowdingHotspots), center (MapView, CenterCharts), right (FleetOverview, PerformanceMetrics).
  - **AlertBar** with `filtered.alerts`.

### 5.2 HeaderBar.jsx

- **Props:** `theme`, `onToggleTheme`, `filter`, `onFilterChange`.
- Inline SVG icons: Menu, Home, Settings, Bell, Help, Export, Search, Grid, Luas, Dublin Bus.
- **Menu:** Hover/click to open dropdown with Dark Mode toggle, Notifications, Export, Settings, Help (handlers are placeholders).
- **Home:** Resets filter to `'all'`.
- **Filter pill:** Segmented control — All / LUAS / Bus; calls `onFilterChange('all'|'luas'|'bus')`.
- **Search:** Expandable search bar; submit shows “Search not yet implemented” (placeholder).

### 5.3 StationPanel.jsx

- **Props:** `stops`, `stopWaitCounts`.
- Builds a `waitMap` from `stopWaitCounts`, sorts stops by wait count (highest first), shows total waiting.
- Renders a list of stations with a colored dot (green/amber/red by count) and count.

### 5.4 MapView.jsx

- **Props:** `stops`, `stopWaitCounts`, `theme`.
- Uses **react-map-gl** (Mapbox): `Map`, `Marker`, `NavigationControl`.
- Center is computed from `stops` (or default Dublin).
- Map style: `mapbox/dark-v11` or `mapbox/light-v11` based on `theme`.
- Each stop is a circular `Marker`; radius and color depend on wait count (e.g. purple → pink → red).

### 5.5 CenterCharts.jsx

- **Props:** `resourceEfficiency`, `onTimeData`, `theme`.
- **Recharts:** First card — BarChart (resource efficiency by route, color by %). Second card — AreaChart (on-time % over time). Uses theme-aware grid/tick/tooltip styles.

### 5.6 FleetOverview.jsx

- **Props:** `vehicles`.
- Computes total deployed, average occupancy, and fill-level buckets (Low/Medium/High/Critical). Renders a stacked “fill distribution” bar and legend.
- “Most full” section: top N vehicles by occupancy with animated bars (requestAnimationFrame, slot-based animation).

### 5.7 PerformanceMetrics.jsx

- **Props:** `fleetUtilization`, `theme`.
- **Recharts:** Single AreaChart for fleet utilization (avgOccupancy over time), theme-aware.

### 5.8 RouteHealth.jsx

- **Props:** `routeHealth`.
- List of routes with status dot (green/amber/red), name, delay (+Xm), headway (current/scheduled), and active vehicle count.

### 5.9 CrowdingHotspots.jsx

- **Props:** `hotspots`.
- List of stops with name, count, trend arrow (↑/↓/—), and delta. Color by trend (e.g. danger/success/muted).

### 5.10 AlertBar.jsx

- **Props:** `alerts`.
- Local state: `dismissed` (Set of alert ids). Shows first non-dismissed alert; “+N more” if several.
- Severity classes: info, warning, critical. Buttons: Acknowledge, Details (placeholders), Dismiss (adds current id to `dismissed`).

---

## 6. Configuration & Environment

- **config/api.js** reads:
  - `VITE_API_BASE_URL`
  - `VITE_WS_URL`
  - `VITE_USE_MOCK_DATA` (if `'true'` or `VITE_WS_URL` is empty, mock mode is used)
  - `MOCK_PUSH_INTERVAL_MS` is hardcoded (4000).

- **MapView** uses `import.meta.env.VITE_MAPBOX_ACCESS_TOKEN`; if missing, the map is not rendered and a placeholder is shown.

- **.env** (not committed) typically contains:
  - `VITE_MAPBOX_ACCESS_TOKEN=...`
  - `VITE_WS_URL=ws://...` (optional; when set and not using mock, WebSocket is used)
  - `VITE_USE_MOCK_DATA=true` (optional override)

---

## 7. Styling

- **index.css:** Global reset, `:root` CSS variables for light theme (e.g. `--bg`, `--surface`, `--accent`, `--danger`, `--warning`, `--success`). `[data-theme='dark']` overrides for dark mode. Font: Inter, system fallbacks.
- **App.css:** Layout (app-shell, full viewport), header, filter pill, search, menu dropdown, panels, station list, map section, charts, fleet panel, route health, hotspots, alert bar. No separate CSS modules; all component styles live in this file.
- Theming is consistent: components use `var(--…)` or theme props (e.g. charts use `theme` for grid/tick/tooltip colors).

---

## 8. Scripts (package.json)

- **npm run dev** — Start Vite dev server.
- **npm run build** — Production build to `dist/`.
- **npm run preview** — Serve `dist/` locally.
- **npm run lint** — Run ESLint.

---

## 9. Unused / Legacy Files

- **src/components/DashboardCharts.jsx** and **src/components/SummaryCards.jsx** exist in the repo but are **not imported** in `App.jsx`. They can be treated as legacy or future use; the active chart UI is in `CenterCharts.jsx` and `PerformanceMetrics.jsx`.

---

This file is the single source of truth for the dashboard’s structure, libraries, and code organization. Update it when adding dependencies, new components, or changing the data contract.
