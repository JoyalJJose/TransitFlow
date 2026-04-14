import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  LineChart, Line, AreaChart, Area, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  Cell,
} from 'recharts';
import { apiGet } from '../services/apiService';

const TIME_RANGES = [
  { label: '1h', hours: 1 },
  { label: '6h', hours: 6 },
  { label: '24h', hours: 24 },
];

const FILL_COLORS = {
  low: '#9063ff',
  medium: '#d7a6b3',
  high: '#e5cdc8',
  critical: '#ef4444',
};

const BAR_PALETTE = ['#9063ff', '#7c5ce7', '#a78bfa', '#b8a0e8', '#d7a6b3', '#c497aa', '#d4b5c4', '#e5cdc8'];

function shortTime(t) {
  if (!t) return '';
  const d = new Date(t);
  if (isNaN(d)) {
    const n = parseInt(t.split(':')[0], 10);
    return isNaN(n) ? t : `${n}h`;
  }
  return `${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`;
}

function barColor(i, total) {
  return BAR_PALETTE[Math.min(i, BAR_PALETTE.length - 1)];
}

function effColor(pct) {
  if (pct >= 70) return '#9063ff';
  if (pct >= 50) return '#a78bfa';
  if (pct >= 30) return '#c4b5fd';
  return '#ddd6fe';
}

function delayColor(sec) {
  if (sec >= 600) return '#d7a6b3';
  if (sec >= 300) return '#a78bfa';
  return '#9063ff';
}

function relativeTime(ts) {
  if (!ts) return 'N/A';
  const diff = (Date.now() - new Date(ts).getTime()) / 1000;
  if (diff < 0) return 'just now';
  if (diff < 60) return `${Math.round(diff)}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  return `${Math.round(diff / 3600)}h ago`;
}

function freshnessColor(ts, thresholdSec) {
  if (!ts) return 'var(--text-muted)';
  const age = (Date.now() - new Date(ts).getTime()) / 1000;
  return age < thresholdSec ? 'var(--online)' : 'var(--warning)';
}

export default function AnalyticsPage({ data, theme }) {
  const dark = theme === 'dark';
  const grid = dark ? 'rgba(144,99,255,0.12)' : 'rgba(57,32,97,0.08)';
  const tick = { fill: dark ? 'rgba(229,205,200,0.65)' : 'rgba(57,32,97,0.45)', fontSize: 10 };
  const tooltipStyle = {
    background: dark ? '#2a2b44' : '#fff',
    border: `1px solid ${dark ? 'rgba(144,99,255,0.2)' : 'rgba(57,32,97,0.12)'}`,
    borderRadius: 6, fontSize: 12,
  };

  const [searchParams, setSearchParams] = useSearchParams();
  const [selectedRoute, setSelectedRoute] = useState(() => searchParams.get('route') || 'all');
  const [selectedStop, setSelectedStop] = useState(() => searchParams.get('stop') || 'all');
  const [timeRange, setTimeRange] = useState(24);

  useEffect(() => {
    const routeParam = searchParams.get('route');
    const stopParam = searchParams.get('stop');
    let changed = false;
    if (routeParam && routeParam !== selectedRoute) {
      setSelectedRoute(routeParam);
      changed = true;
    }
    if (stopParam && stopParam !== selectedStop) {
      setSelectedStop(stopParam);
      changed = true;
    }
    if (changed) setSearchParams({}, { replace: true });
  }, []);

  const [stopHistory, setStopHistory] = useState([]);
  const [vehicleHistory, setVehicleHistory] = useState([]);
  const [delayData, setDelayData] = useState([]);
  const [onTimeData, setOnTimeData] = useState([]);
  const [predictions, setPredictions] = useState(null);
  const [serviceAlerts, setServiceAlerts] = useState([]);
  const [gtfsRtLatest, setGtfsRtLatest] = useState(null);

  const lastWsTime = useRef(null);
  const [wsTimestamp, setWsTimestamp] = useState(null);

  useEffect(() => {
    if (data) {
      lastWsTime.current = new Date().toISOString();
      setWsTimestamp(lastWsTime.current);
    }
  }, [data]);

  useEffect(() => {
    const iv = setInterval(() => setWsTimestamp(lastWsTime.current), 5000);
    return () => clearInterval(iv);
  }, []);

  const routes = data?.routes ?? [];
  const stops = data?.stops ?? [];
  const vehicles = data?.vehicles ?? [];
  const stopWaitCounts = data?.stopWaitCounts ?? [];

  // --- Data-bearing route/stop sets ---
  const activeRouteIds = useMemo(() => {
    const ids = new Set();
    for (const v of vehicles) ids.add(v.routeId);
    if (predictions?.routes) {
      for (const r of predictions.routes) ids.add(r.route_id);
    }
    const routeStopMap = {};
    for (const r of routes) routeStopMap[r.id] = new Set(r.stopIds ?? []);
    const liveStopIds = new Set(stopWaitCounts.filter((s) => s.count > 0).map((s) => s.stopId));
    for (const [rid, sids] of Object.entries(routeStopMap)) {
      for (const sid of sids) {
        if (liveStopIds.has(sid)) { ids.add(rid); break; }
      }
    }
    return ids;
  }, [vehicles, predictions, routes, stopWaitCounts]);

  const dataRoutes = useMemo(
    () => routes.filter((r) => activeRouteIds.has(r.id)),
    [routes, activeRouteIds],
  );

  const liveStopIds = useMemo(
    () => new Set([
      ...stopWaitCounts.filter((s) => s.count > 0).map((s) => s.stopId),
      ...stops.filter((s) => s.isOnline).map((s) => s.id),
    ]),
    [stopWaitCounts, stops],
  );

  const filteredStops = useMemo(() => {
    let base = stops.filter((s) => liveStopIds.has(s.id));
    if (selectedRoute !== 'all') {
      const route = routes.find((r) => r.id === selectedRoute);
      if (route) {
        const sids = new Set(route.stopIds);
        base = base.filter((s) => sids.has(s.id));
      }
    }
    return base;
  }, [selectedRoute, routes, stops, liveStopIds]);

  // --- Context flags ---
  const hasRoute = selectedRoute !== 'all';
  const hasStop = selectedStop !== 'all';
  const showRouteCharts = hasRoute || !hasStop;

  // --- Data fetching (responds to route, stop, timeRange) ---
  const fetchData = useCallback(async () => {
    try {
      if (hasStop) {
        const sh = await apiGet(`/api/stops/${selectedStop}/history?hours=${timeRange}`);
        setStopHistory(sh ?? []);
      } else {
        setStopHistory([]);
      }

      const vh = await apiGet(`/api/vehicles/history?hours=${timeRange}${hasRoute ? `&route_id=${selectedRoute}` : ''}`);
      setVehicleHistory(vh ?? []);

      const delayUrl = hasRoute
        ? `/api/analytics/delays?route_id=${selectedRoute}&hours=${timeRange}`
        : `/api/analytics/delays?hours=${timeRange}`;
      const dd = await apiGet(delayUrl);
      setDelayData(dd ?? []);

      const onTimeUrl = hasRoute
        ? `/api/analytics/on-time?route_id=${selectedRoute}&hours=${timeRange}`
        : `/api/analytics/on-time?hours=${timeRange}`;
      const ot = await apiGet(onTimeUrl);
      setOnTimeData(ot ?? []);

      const pred = await apiGet('/api/predictions/latest');
      setPredictions(pred);

      const sa = await apiGet('/api/analytics/service-alerts');
      setServiceAlerts(sa ?? []);

      const gf = await apiGet('/api/analytics/gtfs-rt-freshness');
      setGtfsRtLatest(gf?.latest ?? null);
    } catch (e) {
      console.error('Analytics fetch error:', e);
    }
  }, [selectedStop, selectedRoute, timeRange, hasRoute, hasStop]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // --- Route-filtered WebSocket data for KPIs ---
  const routeStopIdSet = useMemo(() => {
    if (!hasRoute) return null;
    const route = routes.find((r) => r.id === selectedRoute);
    return route ? new Set(route.stopIds) : null;
  }, [hasRoute, selectedRoute, routes]);

  const filteredVehicles = useMemo(() => {
    if (!hasRoute) return vehicles;
    return vehicles.filter((v) => v.routeId === selectedRoute);
  }, [vehicles, hasRoute, selectedRoute]);

  const filteredWaitCounts = useMemo(() => {
    if (!routeStopIdSet) return stopWaitCounts;
    return stopWaitCounts.filter((s) => routeStopIdSet.has(s.stopId));
  }, [stopWaitCounts, routeStopIdSet]);

  // --- KPIs (reactive to route filter) ---
  const totalWaiting = useMemo(
    () => filteredWaitCounts.reduce((s, c) => s + c.count, 0),
    [filteredWaitCounts],
  );

  const avgOccupancy = useMemo(() => {
    if (!filteredVehicles.length) return 0;
    return Math.round(filteredVehicles.reduce((s, x) => s + x.currentOccupancyPercent, 0) / filteredVehicles.length);
  }, [filteredVehicles]);

  const onTimePct = useMemo(() => {
    if (!onTimeData.length) return 0;
    return Math.round(onTimeData.reduce((s, x) => s + x.onTimePercent, 0) / onTimeData.length);
  }, [onTimeData]);

  const activeVehicleCount = filteredVehicles.length;

  // --- Boarding vs Alighting (by route for 'all', by stop for specific route) ---
  const boardingAlighting = useMemo(() => {
    if (!predictions?.routes) return [];
    let targetRoutes = predictions.routes;
    if (hasRoute) {
      targetRoutes = targetRoutes.filter((r) => r.route_id === selectedRoute);
    }
    if (!hasRoute) {
      const routeMap = {};
      const nameMap = {};
      for (const r of routes) nameMap[r.id] = r.name;
      for (const route of targetRoutes) {
        const rid = route.route_id;
        if (!routeMap[rid]) routeMap[rid] = { name: nameMap[rid] || rid, boarded: 0, alighted: 0 };
        for (const vp of (route.vehicle_predictions ?? [])) {
          for (const sp of (vp.stops ?? [])) {
            routeMap[rid].boarded += sp.boarded ?? 0;
            routeMap[rid].alighted += sp.alighted ?? 0;
          }
        }
      }
      return Object.values(routeMap)
        .sort((a, b) => (b.boarded + b.alighted) - (a.boarded + a.alighted))
        .slice(0, 15);
    }
    const stopMap = {};
    for (const route of targetRoutes) {
      for (const vp of (route.vehicle_predictions ?? [])) {
        for (const sp of (vp.stops ?? [])) {
          if (!stopMap[sp.stop_id]) stopMap[sp.stop_id] = { stop: sp.stop_id, boarded: 0, alighted: 0 };
          stopMap[sp.stop_id].boarded += sp.boarded ?? 0;
          stopMap[sp.stop_id].alighted += sp.alighted ?? 0;
        }
      }
    }
    const nameMap = {};
    for (const s of stops) nameMap[s.id] = s.name;
    return Object.values(stopMap)
      .map((x) => ({ ...x, name: nameMap[x.stop] || x.stop }))
      .sort((a, b) => (b.boarded + b.alighted) - (a.boarded + a.alighted))
      .slice(0, 15);
  }, [predictions, selectedRoute, hasRoute, stops, routes]);

  // --- Stranded (filter to selected route if applicable) ---
  const strandedByRoute = useMemo(() => {
    if (!predictions?.routes) return [];
    let target = predictions.routes;
    if (hasRoute) target = target.filter((r) => r.route_id === selectedRoute);
    return target.map((r) => {
      const total = Object.values(r.stranded_at_stops ?? {}).reduce((s, v) => s + v, 0);
      const routeObj = routes.find((x) => x.id === r.route_id);
      return { route: routeObj?.name ?? r.route_id, stranded: total };
    }).filter((x) => x.stranded > 0).sort((a, b) => b.stranded - a.stranded).slice(0, 15);
  }, [predictions, routes, hasRoute, selectedRoute]);

  // --- Resource Efficiency ---
  const resourceEff = useMemo(() => {
    const eff = data?.resourceEfficiency ?? [];
    if (hasRoute) {
      const route = routes.find((r) => r.id === selectedRoute);
      if (route) return eff.filter((e) => e.route === route.name);
    }
    return eff.slice(0, 15);
  }, [data, hasRoute, selectedRoute, routes]);

  // --- Fleet Occupancy Distribution (uses fetched vehicleHistory — responds to route + time) ---
  const fleetDistOverTime = useMemo(() => {
    if (!vehicleHistory?.length) return [];
    const bucketMap = {};
    for (const entry of vehicleHistory) {
      const t = entry.time || entry.bucket;
      if (!bucketMap[t]) bucketMap[t] = { time: t, low: 0, medium: 0, high: 0, critical: 0, _total: 0 };
      const b = bucketMap[t];
      const occ = entry.avg_occupancy ?? entry.occupancy_percent ?? 0;
      if (occ >= 90) b.critical++;
      else if (occ >= 70) b.high++;
      else if (occ >= 40) b.medium++;
      else b.low++;
      b._total++;
    }
    return Object.values(bucketMap).map((b) => {
      const t = b._total || 1;
      return {
        time: b.time,
        low: Math.round((b.low / t) * 100),
        medium: Math.round((b.medium / t) * 100),
        high: Math.round((b.high / t) * 100),
        critical: Math.round((b.critical / t) * 100),
      };
    });
  }, [vehicleHistory]);

  // --- Top busiest stops (for "All Stops" crowd chart) ---
  const topBusiestStops = useMemo(() => {
    let counts = stopWaitCounts;
    if (hasRoute && routeStopIdSet) {
      counts = counts.filter((s) => routeStopIdSet.has(s.stopId));
    }
    const nameMap = {};
    for (const s of stops) nameMap[s.id] = s.name;
    return counts
      .filter((s) => s.count > 0)
      .sort((a, b) => b.count - a.count)
      .slice(0, 12)
      .map((s) => ({ name: nameMap[s.stopId] || s.stopId, count: s.count }));
  }, [stopWaitCounts, stops, hasRoute, routeStopIdSet]);

  // --- Freshness timestamps ---
  const predictionTime = predictions?.routes?.[0]?.time ?? null;
  const gtfsTime = gtfsRtLatest;

  return (
    <div className="analytics-page">
      {/* Filter bar + freshness indicators */}
      <div className="analytics-filter-bar">
        <label className="analytics-filter-group">
          <span className="analytics-filter-label">Route</span>
          <select value={selectedRoute} onChange={(e) => { setSelectedRoute(e.target.value); setSelectedStop('all'); }}>
            <option value="all">All Routes ({dataRoutes.length})</option>
            {dataRoutes.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
          </select>
        </label>
        <label className="analytics-filter-group">
          <span className="analytics-filter-label">Stop</span>
          <select value={selectedStop} onChange={(e) => setSelectedStop(e.target.value)}>
            <option value="all">All Stops ({filteredStops.length})</option>
            {filteredStops.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </label>
        <div className="analytics-time-pills">
          {TIME_RANGES.map((tr) => (
            <button
              key={tr.hours}
              className={`time-pill${timeRange === tr.hours ? ' time-pill-active' : ''}`}
              onClick={() => setTimeRange(tr.hours)}
            >{tr.label}</button>
          ))}
        </div>
        <div className="freshness-indicators">
          <span className="freshness-item">
            <span className="freshness-dot" style={{ background: freshnessColor(wsTimestamp, 60) }} />
            <span className="freshness-label">Live</span>
            <span className="freshness-time">{relativeTime(wsTimestamp)}</span>
          </span>
          <span className="freshness-item">
            <span className="freshness-dot" style={{ background: freshnessColor(predictionTime, 600) }} />
            <span className="freshness-label">Predictions</span>
            <span className="freshness-time">{relativeTime(predictionTime)}</span>
          </span>
          <span className="freshness-item">
            <span className="freshness-dot" style={{ background: freshnessColor(gtfsTime, 600) }} />
            <span className="freshness-label">GTFS-RT</span>
            <span className="freshness-time">{relativeTime(gtfsTime)}</span>
          </span>
        </div>
      </div>

      {/* KPI row */}
      <div className="analytics-kpi-row">
        <div className="kpi-card">
          <span className="kpi-value">{avgOccupancy}%</span>
          <span className="kpi-label">{hasRoute ? 'Route' : 'Fleet'} Avg Occupancy</span>
        </div>
        <div className="kpi-card">
          <span className="kpi-value">{totalWaiting}</span>
          <span className="kpi-label">{hasRoute ? 'Route' : 'Total'} Waiting</span>
        </div>
        <div className="kpi-card">
          <span className="kpi-value">{onTimePct}%</span>
          <span className="kpi-label">On-Time</span>
        </div>
        <div className="kpi-card">
          <span className="kpi-value">{activeVehicleCount}</span>
          <span className="kpi-label">{hasRoute ? 'Route' : 'Active'} Vehicles</span>
        </div>
      </div>

      {/* Charts grid */}
      <div className="analytics-chart-grid">
        {/* 1. Vehicle Fullness Over Time
            Responds to: route (fetched with route_id), time (fetched with hours) */}
        <div className="panel analytics-chart-card">
          <div className="panel-header"><h2>Vehicle Fullness Over Time</h2></div>
          <div className="analytics-chart-body">
            {vehicleHistory.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={vehicleHistory} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={grid} />
                  <XAxis dataKey="time" tick={tick} tickFormatter={shortTime} height={20} />
                  <YAxis domain={[0, 100]} tick={tick} tickFormatter={(v) => `${v}%`} width={36} />
                  <Tooltip contentStyle={tooltipStyle} formatter={(v) => [`${Math.round(v)}%`, 'Occupancy']} />
                  <Line type="monotone" dataKey="avg_occupancy" stroke="#9063ff" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <div className="chart-empty">No vehicle telemetry data</div>
            )}
          </div>
        </div>

        {/* 2. Stop Crowd Count / Top Busiest Stops
            Responds to: stop (switches chart type), route (filters top stops), time (fetched with hours) */}
        <div className="panel analytics-chart-card">
          <div className="panel-header">
            <h2>{hasStop ? 'Stop Crowd Count Over Time' : 'Top Busiest Stops'}</h2>
          </div>
          <div className="analytics-chart-body">
            {hasStop && stopHistory.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={stopHistory} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                  <defs>
                    <linearGradient id="crowdGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#9063ff" stopOpacity={0.3} />
                      <stop offset="100%" stopColor="#9063ff" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke={grid} />
                  <XAxis dataKey="time" tick={tick} tickFormatter={shortTime} height={20} />
                  <YAxis tick={tick} width={36} />
                  <Tooltip contentStyle={tooltipStyle} formatter={(v) => [v, 'Waiting']} />
                  <Area type="monotone" dataKey="count" stroke="#9063ff" strokeWidth={2} fill="url(#crowdGrad)" />
                </AreaChart>
              </ResponsiveContainer>
            ) : !hasStop && topBusiestStops.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={topBusiestStops} layout="vertical" margin={{ top: 8, right: 8, bottom: 0, left: 80 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={grid} />
                  <XAxis type="number" tick={tick} />
                  <YAxis dataKey="name" type="category" tick={tick} width={75} />
                  <Tooltip contentStyle={tooltipStyle} />
                  <Bar dataKey="count" radius={[0, 3, 3, 0]} name="Waiting">
                    {topBusiestStops.map((_, i) => (
                      <Cell key={i} fill={barColor(i, topBusiestStops.length)} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="chart-empty">{hasStop ? 'No crowd data for this stop' : 'No crowd data available'}</div>
            )}
          </div>
        </div>

        {/* 3. Fleet Occupancy Distribution
            Responds to: route (vehicleHistory fetched with route_id), time (fetched with hours) */}
        <div className="panel analytics-chart-card">
          <div className="panel-header"><h2>Fleet Occupancy Distribution</h2></div>
          <div className="analytics-chart-body">
            {fleetDistOverTime.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={fleetDistOverTime} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={grid} />
                  <XAxis dataKey="time" tick={tick} tickFormatter={shortTime} height={20} />
                  <YAxis tick={tick} tickFormatter={(v) => `${v}%`} width={36} />
                  <Tooltip contentStyle={tooltipStyle} />
                  <Area type="monotone" dataKey="low" stackId="1" stroke={FILL_COLORS.low} fill={FILL_COLORS.low} fillOpacity={0.6} name="Low (<40%)" />
                  <Area type="monotone" dataKey="medium" stackId="1" stroke={FILL_COLORS.medium} fill={FILL_COLORS.medium} fillOpacity={0.6} name="Medium (40-70%)" />
                  <Area type="monotone" dataKey="high" stackId="1" stroke={FILL_COLORS.high} fill={FILL_COLORS.high} fillOpacity={0.6} name="High (70-90%)" />
                  <Area type="monotone" dataKey="critical" stackId="1" stroke={FILL_COLORS.critical} fill={FILL_COLORS.critical} fillOpacity={0.6} name="Critical (90%+)" />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <div className="chart-empty">No fleet distribution data</div>
            )}
          </div>
        </div>

        {/* 4. Boarding vs Alighting
            Responds to: route (by-route aggregation when all, by-stop when specific)
            Hidden when: all routes + specific stop */}
        {showRouteCharts && (
          <div className="panel analytics-chart-card">
            <div className="panel-header">
              <h2>Boarding vs Alighting {hasRoute ? '(by Stop)' : '(by Route)'}</h2>
            </div>
            <div className="analytics-chart-body">
              {boardingAlighting.length ? (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={boardingAlighting} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke={grid} />
                    <XAxis dataKey="name" tick={tick} interval={0} angle={-30} textAnchor="end" height={50} />
                    <YAxis tick={tick} width={36} />
                    <Tooltip contentStyle={tooltipStyle} />
                    <Bar dataKey="boarded" fill="#9063ff" radius={[3, 3, 0, 0]} name="Boarded" />
                    <Bar dataKey="alighted" fill="#d7a6b3" radius={[3, 3, 0, 0]} name="Alighted" />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div className="chart-empty">No boarding data available</div>
              )}
            </div>
          </div>
        )}

        {/* 5. Route Delay Heatmap / Top Delayed Stops — full width
            Responds to: route (heatmap for specific, bar for all), time (fetched with hours)
            Hidden when: all routes + specific stop */}
        {showRouteCharts && (
          <div className="panel analytics-chart-card analytics-chart-full">
            <div className="panel-header">
              <h2>{hasRoute ? 'Route Delay Heatmap' : 'Top Delayed Stops'}</h2>
            </div>
            <div className="analytics-chart-body">
              {hasRoute && delayData.length && delayData[0]?.hours ? (() => {
                const allHours = [...new Set(delayData.flatMap((s) => (s.hours ?? []).map((h) => h.hour)))].sort((a, b) => a - b);
                const delayLookup = {};
                for (const stop of delayData) {
                  delayLookup[stop.stop_id] = {};
                  for (const h of (stop.hours ?? [])) {
                    delayLookup[stop.stop_id][h.hour] = h.avg_delay ?? 0;
                  }
                }
                return (
                  <div className="delay-heatmap-hz">
                    <div className="heatmap-hz-header">
                      <span className="heatmap-hz-corner" />
                      {delayData.map((stop, i) => (
                        <span key={i} className="heatmap-hz-stop-label" title={stop.stop_name || stop.stop_id}>
                          {stop.stop_name || stop.stop_id}
                        </span>
                      ))}
                    </div>
                    {allHours.map((hour) => (
                      <div key={hour} className="heatmap-hz-row">
                        <span className="heatmap-hz-hour">{hour}:00</span>
                        {delayData.map((stop, i) => {
                          const delay = delayLookup[stop.stop_id]?.[hour] ?? 0;
                          const intensity = Math.min(delay / 300, 1);
                          const bg = intensity > 0.6 ? '#d7a6b3' : intensity > 0.3 ? '#a78bfa' : '#9063ff';
                          return (
                            <div
                              key={i}
                              className="heatmap-hz-cell"
                              style={{ background: delay > 0 ? bg : 'transparent', opacity: delay > 0 ? 0.2 + intensity * 0.8 : 0.05 }}
                              title={`${stop.stop_name} @ ${hour}:00 — ${Math.round(delay)}s`}
                            />
                          );
                        })}
                      </div>
                    ))}
                  </div>
                );
              })() : !hasRoute && delayData.length ? (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={delayData.slice(0, 15)} layout="vertical" margin={{ top: 8, right: 8, bottom: 0, left: 80 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke={grid} />
                    <XAxis type="number" tick={tick} tickFormatter={(v) => `${Math.round(v)}s`} />
                    <YAxis dataKey="stop_name" type="category" tick={tick} width={75} />
                    <Tooltip contentStyle={tooltipStyle} formatter={(v) => [`${Math.round(v)}s`, 'Avg Delay']} />
                    <Bar dataKey="avg_delay" radius={[0, 3, 3, 0]} name="Avg Delay">
                      {delayData.slice(0, 15).map((d, i) => (
                        <Cell key={i} fill={delayColor(d.avg_delay)} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div className="chart-empty">No delay data available</div>
              )}
            </div>
          </div>
        )}

        {/* 7. Stranded Passengers
            Responds to: route (filters to that route's prediction)
            Hidden when: all routes + specific stop */}
        {showRouteCharts && (
          <div className="panel analytics-chart-card">
            <div className="panel-header"><h2>Stranded Passengers{hasRoute ? '' : ' by Route'}</h2></div>
            <div className="analytics-chart-body">
              {strandedByRoute.length ? (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={strandedByRoute} layout="vertical" margin={{ top: 8, right: 8, bottom: 0, left: 80 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke={grid} />
                    <XAxis type="number" tick={tick} />
                    <YAxis dataKey="route" type="category" tick={tick} width={75} />
                    <Tooltip contentStyle={tooltipStyle} />
                    <Bar dataKey="stranded" radius={[0, 3, 3, 0]} name="Stranded">
                      {strandedByRoute.map((_, i) => (
                        <Cell key={i} fill={barColor(i, strandedByRoute.length)} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div className="chart-empty">No stranded passengers</div>
              )}
            </div>
          </div>
        )}

        {/* 8. Resource Efficiency
            Responds to: route (filters to that route)
            Hidden when: all routes + specific stop */}
        {showRouteCharts && (
          <div className="panel analytics-chart-card">
            <div className="panel-header"><h2>Resource Efficiency{hasRoute ? '' : ' by Route'}</h2></div>
            <div className="analytics-chart-body">
              {resourceEff.length ? (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={resourceEff} layout="vertical" margin={{ top: 8, right: 8, bottom: 0, left: 80 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke={grid} />
                    <XAxis type="number" domain={[0, 100]} tick={tick} tickFormatter={(v) => `${v}%`} />
                    <YAxis dataKey="route" type="category" tick={tick} width={75} />
                    <Tooltip contentStyle={tooltipStyle} formatter={(v) => [`${v}%`, 'Utilisation']} />
                    <Bar dataKey="efficiency" radius={[0, 3, 3, 0]} name="Utilisation">
                      {resourceEff.map((r, i) => (
                        <Cell key={i} fill={effColor(r.efficiency)} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div className="chart-empty">No efficiency data</div>
              )}
            </div>
          </div>
        )}

        {/* 9. Service Alert Timeline
            System-wide alerts — not filtered by route/stop/time */}
        <div className="panel analytics-chart-card">
          <div className="panel-header"><h2>Service Alert Timeline</h2></div>
          <div className="analytics-chart-body">
            {serviceAlerts.length ? (
              <div className="service-alert-timeline">
                {serviceAlerts.map((a, i) => (
                  <div key={a.id ?? i} className="sa-timeline-item">
                    <div className={`sa-severity-dot sa-severity-${a.severity ?? 'info'}`} />
                    <div className="sa-timeline-content">
                      <span className="sa-header-text">{a.header_text || a.message || 'Service Alert'}</span>
                      <span className="sa-desc-text">{a.description_text || ''}</span>
                      {a.cause && <span className="sa-meta">Cause: {a.cause}</span>}
                      {a.effect && <span className="sa-meta">Effect: {a.effect}</span>}
                    </div>
                    <span className="sa-time">{a.received_at ? new Date(a.received_at).toLocaleTimeString() : ''}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="chart-empty">No service alerts</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
