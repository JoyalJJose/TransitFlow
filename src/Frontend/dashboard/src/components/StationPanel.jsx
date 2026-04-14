import { useMemo } from 'react';

function statusColor(count) {
  if (count >= 20) return 'var(--danger)';
  if (count >= 10) return 'var(--warning)';
  return 'var(--success)';
}

export default function StationPanel({ stops = [], stopWaitCounts = [] }) {
  const waitMap = useMemo(() => {
    const m = {};
    stopWaitCounts.forEach((s) => { m[s.stopId] = s.count; });
    return m;
  }, [stopWaitCounts]);

  const totalWaiting = useMemo(
    () => stopWaitCounts.reduce((sum, s) => sum + s.count, 0),
    [stopWaitCounts],
  );

  const sorted = useMemo(() => {
    return [...stops].sort((a, b) => (waitMap[b.id] ?? 0) - (waitMap[a.id] ?? 0));
  }, [stops, waitMap]);

  return (
    <div className="panel station-panel">
      <div className="panel-header">
        <h2>Live Station Data</h2>
        <span className="panel-stat">{totalWaiting} total</span>
      </div>

      <ul className="station-list">
        {sorted.map((stop) => {
          const count = waitMap[stop.id] ?? 0;
          return (
            <li key={stop.id} className="station-row">
              <span
                className="station-dot"
                style={{ background: statusColor(count) }}
              />
              <span className="station-name">{stop.name}</span>
              <span className="station-count" style={{ color: statusColor(count) }}>
                {count}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
