import { useMemo, useState, useEffect, useCallback } from 'react';
import { apiGet } from '../services/apiService';

function statusColor(count) {
  if (count >= 20) return 'var(--danger)';
  if (count >= 10) return 'var(--warning)';
  return 'var(--success)';
}

function relativeTime(ts) {
  if (!ts) return '';
  const diff = (Date.now() - new Date(ts).getTime()) / 1000;
  if (diff < 60) return `${Math.round(diff)}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  return `${Math.round(diff / 3600)}h ago`;
}

function StopDrawer({ stop, count, onClose }) {
  const [history, setHistory] = useState([]);

  useEffect(() => {
    setHistory([]);
    apiGet(`/api/stops/${stop.id}/history?hours=2`).then((d) => setHistory(d ?? [])).catch(() => setHistory([]));
  }, [stop.id]);

  return (
    <div className="stop-drawer-overlay" onClick={onClose}>
      <div className="stop-drawer" onClick={(e) => e.stopPropagation()}>
        <div className="stop-drawer-header">
          <div>
            <h3 className="stop-drawer-name">{stop.name}</h3>
            <span className="stop-drawer-id">{stop.deviceId || stop.id}</span>
          </div>
          <button className="stop-drawer-close" onClick={onClose}>&times;</button>
        </div>
        <div className="stop-drawer-status">
          <span className={`device-dot${stop.isOnline ? ' device-dot-online' : ''}`} />
          <span>{stop.isOnline ? 'Online' : 'Offline'}</span>
          {stop.lastSeen && <span className="stop-drawer-seen">{relativeTime(stop.lastSeen)}</span>}
        </div>
        <div className="stop-drawer-count">
          <span className="stop-drawer-count-val" style={{ color: statusColor(count) }}>{count}</span>
          <span className="stop-drawer-count-label">waiting</span>
        </div>
        <div className="stop-drawer-sparkline">
          <span className="stop-drawer-spark-label">Last 2h</span>
          {history.length > 0 ? (
            <div className="sparkline">
              {(() => {
                const max = Math.max(...history.map((h) => h.count), 1);
                return history.slice(-30).map((h, i) => (
                  <div
                    key={i}
                    className="sparkline-bar"
                    style={{ height: `${(h.count / max) * 100}%`, background: statusColor(h.count) }}
                    title={`${h.count} at ${h.time}`}
                  />
                ));
              })()}
            </div>
          ) : (
            <span className="stop-drawer-no-data">No history data</span>
          )}
        </div>
      </div>
    </div>
  );
}

export default function StationPanel({ stops = [], stopWaitCounts = [] }) {
  const [selectedStop, setSelectedStop] = useState(null);

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
            <li key={stop.id} className="station-row station-row-clickable" onClick={() => setSelectedStop(stop)}>
              <span className={`station-online-dot${stop.isOnline ? ' station-online' : ' station-offline'}`} />
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

      {selectedStop && (
        <StopDrawer
          stop={selectedStop}
          count={waitMap[selectedStop.id] ?? 0}
          onClose={() => setSelectedStop(null)}
        />
      )}
    </div>
  );
}
