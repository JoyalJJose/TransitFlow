import { useEffect, useState, useCallback, useMemo } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { subscribeToDashboard } from './services/dataService';
import HeaderBar from './components/HeaderBar';
import AlertBar from './components/AlertBar';
import HomePage from './pages/HomePage';
import AnalyticsPage from './pages/AnalyticsPage';
import SchedulingPage from './pages/SchedulingPage';
import CommandPanelPage from './pages/CommandPanelPage';
import './App.css';

function AppShell() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [theme, setTheme] = useState(() => localStorage.getItem('theme') || 'light');
  const [filter, setFilter] = useState('all');

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
        <Routes>
          <Route path="/" element={<HomePage data={filtered} theme={theme} />} />
          <Route path="/analytics" element={<AnalyticsPage data={filtered} theme={theme} />} />
          <Route path="/scheduling" element={<SchedulingPage data={filtered} theme={theme} />} />
          <Route path="/controls" element={<CommandPanelPage data={filtered} theme={theme} />} />
        </Routes>
      </div>

      <AlertBar alerts={filtered.alerts} />
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AppShell />
    </BrowserRouter>
  );
}
