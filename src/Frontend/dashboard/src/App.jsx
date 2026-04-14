import { useEffect, useState, useCallback, useMemo } from 'react';
import { subscribeToDashboard } from './services/dataService';
import HeaderBar from './components/HeaderBar';
import StationPanel from './components/StationPanel';
import MapView from './components/MapView';
import CenterCharts from './components/CenterCharts';
import FleetOverview from './components/FleetOverview';
import PerformanceMetrics from './components/PerformanceMetrics';
import RouteHealth from './components/RouteHealth';
import CrowdingHotspots from './components/CrowdingHotspots';
import AlertBar from './components/AlertBar';
import './App.css';

export default function App() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [theme, setTheme] = useState(() => localStorage.getItem('theme') || 'light');
  const [filter, setFilter] = useState('all');
  const [mapFullscreen, setMapFullscreen] = useState(false);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
  }, [theme]);

  const toggleTheme = useCallback(() => {
    setTheme((t) => (t === 'dark' ? 'light' : 'dark'));
  }, []);

  useEffect(() => {
    const unsubscribe = subscribeToDashboard(
      (payload) => {
        setData(payload);
        setError(null);
      },
      (err) => {
        console.error('Dashboard data error:', err);
        setError('Connection lost — retrying…');
      },
    );
    return unsubscribe;
  }, []);

  const filtered = useMemo(() => {
    if (!data) return null;
    if (filter === 'all') return data;

    const routes = data.routes.filter((r) => r.type === filter);
    const routeIds = new Set(routes.map((r) => r.id));
    const stopIdSet = new Set(routes.flatMap((r) => r.stopIds));
    const routeNames = new Set(routes.map((r) => r.name));

    return {
      ...data,
      routes,
      stops: data.stops.filter((s) => stopIdSet.has(s.id)),
      stopWaitCounts: data.stopWaitCounts.filter((s) => stopIdSet.has(s.stopId)),
      vehicles: data.vehicles.filter((v) => routeIds.has(v.routeId)),
      resourceEfficiency: data.resourceEfficiency.filter((e) => routeNames.has(e.route)),
      onTimeData: data.onTimeDataByType?.[filter] ?? data.onTimeData,
      fleetUtilization: data.fleetUtilByType?.[filter] ?? data.fleetUtilization,
      routeHealth: data.routeHealth.filter((r) => r.type === filter),
      crowdingHotspots: data.crowdingHotspots.filter((h) => stopIdSet.has(h.stopId)),
    };
  }, [data, filter]);

  if (!filtered) {
    return (
      <div className="loading">
        <p>Connecting to data source…</p>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <HeaderBar
        theme={theme}
        onToggleTheme={toggleTheme}
        filter={filter}
        onFilterChange={setFilter}
      />

      {error && <div className="error-strip">{error}</div>}

      <div className="dashboard-content">
        <main className={`dashboard-grid${mapFullscreen ? ' dashboard-grid--hidden' : ''}`}>
          <div className="left-column">
            <StationPanel stops={filtered.stops} stopWaitCounts={filtered.stopWaitCounts} />
            <RouteHealth routeHealth={filtered.routeHealth} />
            <CrowdingHotspots hotspots={filtered.crowdingHotspots} />
          </div>

          <div className="center-column">
            <div className="map-section">
              <MapView
                stops={filtered.stops}
                stopWaitCounts={filtered.stopWaitCounts}
                vehicles={filtered.vehicles}
                theme={theme}
                onToggleFullscreen={() => setMapFullscreen(true)}
              />
            </div>
            <CenterCharts
              resourceEfficiency={filtered.resourceEfficiency}
              onTimeData={filtered.onTimeData}
              theme={theme}
            />
          </div>

          <div className="right-column">
            <FleetOverview vehicles={filtered.vehicles} />
            <PerformanceMetrics fleetUtilization={filtered.fleetUtilization} theme={theme} />
          </div>
        </main>

        <div className={`map-fullscreen-overlay${mapFullscreen ? ' map-fullscreen-overlay--active' : ''}`}>
          <MapView
            stops={filtered.stops}
            stopWaitCounts={filtered.stopWaitCounts}
            vehicles={filtered.vehicles}
            theme={theme}
            isFullscreen={mapFullscreen}
            onToggleFullscreen={() => setMapFullscreen(false)}
          />
        </div>
      </div>

      <AlertBar alerts={filtered.alerts} />
    </div>
  );
}
