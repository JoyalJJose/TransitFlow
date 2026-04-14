function statusColor(status) {
  if (status === 'disrupted') return 'var(--danger)';
  if (status === 'delayed') return 'var(--warning)';
  return 'var(--success)';
}

export default function RouteHealth({ routeHealth = [] }) {
  return (
    <div className="panel route-health-panel">
      <div className="panel-header">
        <h2>Route Health</h2>
      </div>

      <div className="rh-list">
        {routeHealth.map((r) => (
          <div key={r.routeId} className="rh-row">
            <span className="rh-dot" style={{ background: statusColor(r.status) }} />
            <span className="rh-name">{r.routeName}</span>
            {r.status !== 'on-time' && (
              <span className="rh-delay">+{r.delayMin}m</span>
            )}
            <span className="rh-headway">
              {r.currentHeadway}/{r.scheduledHeadway}min
            </span>
            <span className="rh-vehicles" title="Active vehicles">
              {r.activeVehicles}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
