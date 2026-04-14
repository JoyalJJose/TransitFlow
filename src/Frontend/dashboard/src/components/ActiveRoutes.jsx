import { useMemo } from 'react';
import { ROUTE_COLORS } from './MapView';

const COLOR_DEFAULT = '#9063ff';

function occColor(pct) {
  if (pct >= 90) return '#ef4444';
  if (pct >= 70) return '#e5cdc8';
  if (pct >= 40) return '#d7a6b3';
  return '#9063ff';
}

export default function ActiveRoutes({ routes = [], vehicles = [] }) {
  const routeStats = useMemo(() => {
    const byRoute = {};
    for (const v of vehicles) {
      if (!v.routeId) continue;
      if (!byRoute[v.routeId]) byRoute[v.routeId] = [];
      byRoute[v.routeId].push(v);
    }

    const nameMap = {};
    for (const r of routes) nameMap[r.id] = r.name;

    return Object.entries(byRoute)
      .map(([routeId, vList]) => {
        const avgOcc = Math.round(
          vList.reduce((s, v) => s + v.currentOccupancyPercent, 0) / vList.length,
        );
        return {
          routeId,
          name: nameMap[routeId] ?? routeId,
          vehicleCount: vList.length,
          avgOcc,
          color: ROUTE_COLORS[routeId] || COLOR_DEFAULT,
        };
      })
      .sort((a, b) => b.vehicleCount - a.vehicleCount);
  }, [routes, vehicles]);

  return (
    <div className="panel active-routes-panel">
      <div className="panel-header">
        <h2>Active Routes</h2>
        <span className="active-routes-count">{routeStats.length}</span>
      </div>
      <div className="active-routes-list">
        {routeStats.length === 0 && (
          <div className="active-routes-empty">No active routes</div>
        )}
        {routeStats.map((r) => (
          <div key={r.routeId} className="active-route-row">
            <span className="active-route-dot" style={{ background: r.color }} />
            <span className="active-route-name">{r.name}</span>
            <span className="active-route-vehicles" title="Vehicles deployed">
              {r.vehicleCount}
            </span>
            <div className="active-route-occ-track">
              <div
                className="active-route-occ-fill"
                style={{ width: `${Math.min(r.avgOcc, 100)}%`, background: occColor(r.avgOcc) }}
              />
            </div>
            <span className="active-route-occ-label">{r.avgOcc}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}
