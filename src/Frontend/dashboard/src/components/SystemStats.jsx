import { useEffect, useRef, useState } from 'react';
import { apiGet } from '../services/apiService';

const POLL_INTERVAL_MS = 30_000;

function formatUptime(totalSeconds) {
  if (totalSeconds == null || Number.isNaN(totalSeconds) || totalSeconds < 0) {
    return '--';
  }
  const s = Math.floor(totalSeconds);
  const days = Math.floor(s / 86400);
  const hours = Math.floor((s % 86400) / 3600);
  const minutes = Math.floor((s % 3600) / 60);
  const seconds = s % 60;

  if (days > 0) return `${days}d ${hours}h ${minutes}m`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  const mm = String(minutes).padStart(2, '0');
  const ss = String(seconds).padStart(2, '0');
  return `00:${mm}:${ss}`;
}

function dotClass(status) {
  if (status === true || status === 'ok' || status === 'enabled') {
    return 'system-stats-dot system-stats-dot-ok';
  }
  if (status === 'unknown' || status === 'disabled' || status == null) {
    return 'system-stats-dot';
  }
  return 'system-stats-dot system-stats-dot-down';
}

export default function SystemStats() {
  const [health, setHealth] = useState(null);
  const fetchedAtRef = useRef(null);
  const [, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const h = await apiGet('/api/health');
        if (cancelled) return;
        fetchedAtRef.current = Date.now();
        setHealth(h);
      } catch {
        // leave previous snapshot in place; a later poll may recover
      }
    };

    load();
    const pollId = setInterval(load, POLL_INTERVAL_MS);
    const tickId = setInterval(() => setTick((t) => t + 1), 1000);

    return () => {
      cancelled = true;
      clearInterval(pollId);
      clearInterval(tickId);
    };
  }, []);

  const baseUptime = health?.uptime_s;
  const elapsedSinceFetch =
    fetchedAtRef.current != null ? (Date.now() - fetchedAtRef.current) / 1000 : 0;
  const liveUptime =
    baseUptime != null ? baseUptime + elapsedSinceFetch : null;

  return (
    <div className="panel system-stats-panel">
      <div className="panel-header">
        <h2>System Stats</h2>
        <span className="system-stats-ws" title="Connected WebSocket clients">
          WS {health?.connected_clients ?? 0}
        </span>
      </div>
      <div className="system-stats-body">
        <div>
          <div className="system-stats-uptime-val">{formatUptime(liveUptime)}</div>
          <div className="system-stats-uptime-label">Uptime</div>
        </div>
        <div className="system-stats-chips">
          <span className="system-stats-chip" title="Database">
            <span className={dotClass(health?.db)} />
            DB
          </span>
          <span className="system-stats-chip" title="MQTT broker">
            <span className={dotClass(health?.mqtt)} />
            MQTT
          </span>
          <span className="system-stats-chip" title="GTFS-RT feed">
            <span className={dotClass(health?.gtfs_rt)} />
            GTFS-RT
          </span>
        </div>
      </div>
    </div>
  );
}
