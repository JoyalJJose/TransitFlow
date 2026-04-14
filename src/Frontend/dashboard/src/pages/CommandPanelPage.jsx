import { useState, useEffect, useCallback, useMemo, Fragment } from 'react';
import { apiGet, apiPost, apiPut } from '../services/apiService';

function relativeTime(ts) {
  if (!ts) return '';
  const diff = (Date.now() - new Date(ts).getTime()) / 1000;
  if (diff < 60) return `${Math.round(diff)}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return `${Math.round(diff / 86400)}d ago`;
}

function HealthChip({ label, status, neutral = false }) {
  const color = neutral
    ? 'var(--accent)'
    : status === 'ok' ? 'var(--online)' : status === 'degraded' ? 'var(--warning)' : 'var(--danger)';
  return (
    <div className="health-chip">
      <span className="health-dot" style={{ background: color }} />
      <span className="health-label">{label}</span>
      <span className="health-status" style={{ color }}>{status}</span>
    </div>
  );
}

function AccordionSection({ title, defaultOpen = true, children }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="panel cmd-section">
      <button className="panel-header cmd-accordion-header" onClick={() => setOpen(!open)}>
        <h2>{title}</h2>
        <span className="cmd-chevron">{open ? '\u25BC' : '\u25B6'}</span>
      </button>
      {open && <div className="cmd-section-body">{children}</div>}
    </div>
  );
}

const DEVICES_PER_PAGE = 25;

function DeviceExpandedRow({ device, onSendCommand }) {
  const [logs, setLogs] = useState([]);
  const [logsLoaded, setLogsLoaded] = useState(false);
  const [captureInterval, setCaptureInterval] = useState(10);
  const [imageSendInterval, setImageSendInterval] = useState(30);
  const [confThreshold, setConfThreshold] = useState(0.25);
  const [zone, setZone] = useState(device.zone ?? 'default');

  const fetchLogs = useCallback(async () => {
    try {
      const data = await apiGet(`/api/devices/${device.device_id}/logs?limit=20`);
      setLogs(data ?? []);
      setLogsLoaded(true);
    } catch (e) { console.error('Log fetch error:', e); }
  }, [device.device_id]);

  useEffect(() => { fetchLogs(); }, [fetchLogs]);

  const togglePipeline = useCallback(() => {
    onSendCommand(device.device_id, { action: device.pipeline_active ? 'stop_pipeline' : 'start_pipeline' });
  }, [device, onSendCommand]);

  const applyConfig = useCallback(() => {
    onSendCommand(device.device_id, {
      action: 'update_config',
      settings: { capture_interval: captureInterval, image_send_interval: imageSendInterval, conf_threshold: confThreshold, zone },
    });
  }, [device.device_id, captureInterval, imageSendInterval, confThreshold, zone, onSendCommand]);

  return (
    <tr className="dev-expanded-row">
      <td colSpan={6}>
        <div className="dev-expanded-body">
          <div className="dev-expanded-col">
            <h4 className="dev-expanded-title">Actions</h4>
            <button className={`device-toggle${device.pipeline_active ? ' device-toggle-on' : ''}`} onClick={togglePipeline}>
              Pipeline: {device.pipeline_active ? 'ON' : 'OFF'}
            </button>
          </div>
          <div className="dev-expanded-col">
            <h4 className="dev-expanded-title">Configuration</h4>
            <label className="device-slider-group"><span>Capture Interval</span><input type="range" min={1} max={60} value={captureInterval} onChange={(e) => setCaptureInterval(Number(e.target.value))} /><span className="device-slider-val">{captureInterval}s</span></label>
            <label className="device-slider-group"><span>Image Send</span><input type="range" min={5} max={120} value={imageSendInterval} onChange={(e) => setImageSendInterval(Number(e.target.value))} /><span className="device-slider-val">{imageSendInterval}s</span></label>
            <label className="device-slider-group"><span>Conf. Threshold</span><input type="range" min={5} max={95} value={Math.round(confThreshold * 100)} onChange={(e) => setConfThreshold(Number(e.target.value) / 100)} /><span className="device-slider-val">{confThreshold.toFixed(2)}</span></label>
            <label className="device-input-group"><span>Zone</span><input type="text" value={zone} onChange={(e) => setZone(e.target.value)} /></label>
            <button className="cmd-btn cmd-btn-primary" onClick={applyConfig}>Apply Config</button>
          </div>
          <div className="dev-expanded-col dev-expanded-logs">
            <h4 className="dev-expanded-title">Recent Logs</h4>
            {logsLoaded ? (logs.length ? logs.slice(0, 8).map((l, i) => (
              <div key={i} className={`device-log-entry device-log-${(l.level ?? '').toLowerCase()}`}>
                <span className="device-log-time">{l.time ? new Date(l.time).toLocaleTimeString() : ''}</span>
                <span className="device-log-level">{l.level}</span>
                <span className="device-log-msg">{l.message}</span>
              </div>
            )) : <span className="dev-no-logs">No logs</span>) : <span className="dev-no-logs">Loading...</span>}
          </div>
        </div>
      </td>
    </tr>
  );
}

function DeviceTable({ devices, routes, onSendCommand }) {
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [typeFilter, setTypeFilter] = useState('all');
  const [page, setPage] = useState(0);
  const [expandedId, setExpandedId] = useState(null);

  const types = useMemo(() => {
    const s = new Set();
    for (const d of devices) if (d.transport_type) s.add(d.transport_type);
    return [...s].sort();
  }, [devices]);

  const filtered = useMemo(() => {
    let list = devices;
    if (statusFilter === 'online') list = list.filter((d) => d.is_online);
    else if (statusFilter === 'offline') list = list.filter((d) => !d.is_online);
    if (typeFilter !== 'all') list = list.filter((d) => d.transport_type === typeFilter);
    if (search) {
      const q = search.toLowerCase();
      list = list.filter((d) =>
        (d.stop_name ?? '').toLowerCase().includes(q) ||
        (d.device_id ?? '').toLowerCase().includes(q),
      );
    }
    return list;
  }, [devices, statusFilter, typeFilter, search]);

  useEffect(() => { setPage(0); }, [search, statusFilter, typeFilter]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / DEVICES_PER_PAGE));
  const pageDevices = filtered.slice(page * DEVICES_PER_PAGE, (page + 1) * DEVICES_PER_PAGE);

  const onlineCount = devices.filter((d) => d.is_online).length;

  return (
    <div className="dev-table-wrap">
      <div className="dev-toolbar">
        <input
          className="dev-search"
          type="text"
          placeholder="Search by name or ID..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select className="dev-filter" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="all">All ({devices.length})</option>
          <option value="online">Online ({onlineCount})</option>
          <option value="offline">Offline ({devices.length - onlineCount})</option>
        </select>
        <select className="dev-filter" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
          <option value="all">All types</option>
          {types.map((t) => <option key={t} value={t}>{t.charAt(0).toUpperCase() + t.slice(1)}</option>)}
        </select>
        <span className="dev-result-count">{filtered.length} device{filtered.length !== 1 ? 's' : ''}</span>
      </div>
      <div className="dev-table-scroll">
        <table className="dev-table">
          <thead>
            <tr>
              <th>Status</th>
              <th>Stop Name</th>
              <th>Device ID</th>
              <th>Type</th>
              <th>Pipeline</th>
              <th>Last Seen</th>
            </tr>
          </thead>
          <tbody>
            {pageDevices.map((d) => (
              <Fragment key={d.device_id}>
                <tr
                  className={`dev-row${expandedId === d.device_id ? ' dev-row-selected' : ''}${d.is_online ? '' : ' dev-row-offline'}`}
                  onClick={() => setExpandedId(expandedId === d.device_id ? null : d.device_id)}
                >
                  <td><span className={`device-dot${d.is_online ? ' device-dot-online' : ''}`} /></td>
                  <td className="dev-cell-name">{d.stop_name}</td>
                  <td className="dev-cell-id">{d.device_id}</td>
                  <td>{d.transport_type && <span className={`device-type-badge device-type-${d.transport_type}`}>{d.transport_type}</span>}</td>
                  <td><span className={`dev-pill${d.pipeline_active ? ' dev-pill-on' : ''}`}>{d.pipeline_active ? 'ON' : 'OFF'}</span></td>
                  <td className="dev-cell-time">{d.last_seen ? relativeTime(d.last_seen) : '-'}</td>
                </tr>
                {expandedId === d.device_id && (
                  <DeviceExpandedRow device={d} onSendCommand={onSendCommand} />
                )}
              </Fragment>
            ))}
            {!pageDevices.length && (
              <tr><td colSpan={6} className="chart-empty">No devices match filters</td></tr>
            )}
          </tbody>
        </table>
      </div>
      {totalPages > 1 && (
        <div className="dev-pagination">
          <button className="dev-page-btn" disabled={page === 0} onClick={() => setPage(page - 1)}>&lsaquo; Prev</button>
          <span className="dev-page-info">Page {page + 1} of {totalPages}</span>
          <button className="dev-page-btn" disabled={page >= totalPages - 1} onClick={() => setPage(page + 1)}>Next &rsaquo;</button>
        </div>
      )}
    </div>
  );
}

export default function CommandPanelPage({ data, theme }) {
  const routes = data?.routes ?? [];

  const [health, setHealth] = useState(null);
  const [devices, setDevices] = useState([]);
  const [models, setModels] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [adminLog, setAdminLog] = useState([]);
  const [showResolved, setShowResolved] = useState(false);

  const [predConfig, setPredConfig] = useState({ alighting_fraction: 0.05, default_capacity: 80 });
  const [evalConfig, setEvalConfig] = useState({ occupancy_threshold: 0.9, min_stranded: 5, min_confidence: 0.3 });
  const [evalRoute, setEvalRoute] = useState('default');

  const fetchAll = useCallback(async () => {
    try {
      const [h, d, m, a, al, pc, ec] = await Promise.all([
        apiGet('/api/health'),
        apiGet('/api/devices'),
        apiGet('/api/models'),
        apiGet('/api/alerts'),
        apiGet('/api/admin/log?limit=50'),
        apiGet('/api/config/prediction'),
        apiGet('/api/config/evaluator'),
      ]);
      if (h) setHealth(h);
      if (d) setDevices(d);
      if (m) setModels(m);
      if (a) setAlerts(a);
      if (al) setAdminLog(al);
      if (pc) setPredConfig(pc);
      if (ec) setEvalConfig(ec);
    } catch (e) {
      console.error('Command panel fetch error:', e);
    }
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const sendCommand = useCallback(async (deviceId, command) => {
    try {
      await apiPost('/api/admin/command', { device_id: deviceId, ...command });
      setTimeout(fetchAll, 1000);
    } catch (e) {
      console.error('Command send error:', e);
    }
  }, [fetchAll]);

  const resolveAlert = useCallback(async (id) => {
    try {
      await apiPost(`/api/alerts/${id}/resolve`, {});
      fetchAll();
    } catch (e) {
      console.error('Resolve alert error:', e);
    }
  }, [fetchAll]);

  const savePredConfig = useCallback(async () => {
    try {
      await apiPut('/api/config/prediction', predConfig);
    } catch (e) {
      console.error('Save pred config error:', e);
    }
  }, [predConfig]);

  const saveEvalConfig = useCallback(async () => {
    try {
      await apiPut('/api/config/evaluator', { route_id: evalRoute === 'default' ? null : evalRoute, ...evalConfig });
    } catch (e) {
      console.error('Save eval config error:', e);
    }
  }, [evalConfig, evalRoute]);

  const visibleAlerts = useMemo(() => {
    if (showResolved) return alerts;
    return alerts.filter((a) => !a.resolved_at);
  }, [alerts, showResolved]);

  return (
    <div className="command-panel-page">
      {/* System Health Banner */}
      <div className="health-banner">
        <HealthChip label="Database" status={health?.db ? 'ok' : 'down'} />
        <HealthChip label="MQTT" status={health?.mqtt ?? 'unknown'} />
        <HealthChip label="GTFS-RT" status={health?.gtfs_rt ?? 'unknown'} />
        <HealthChip label="WS Clients" status={`${health?.connected_clients ?? 0}`} neutral />
        <HealthChip label="PG LISTEN" status={health?.pg_listen ?? 'unknown'} />
      </div>

      {/* Edge Device Management */}
      <AccordionSection title={`Edge Device Management (${devices.length})`} defaultOpen={false}>
        <DeviceTable devices={devices} routes={routes} onSendCommand={sendCommand} />
      </AccordionSection>

      {/* Prediction & Evaluation Config */}
      <AccordionSection title="Prediction & Evaluation Config">
        <div className="cmd-config-grid">
          <div className="cmd-config-col">
            <h3 className="cmd-config-title">Prediction Engine</h3>
            <label className="cmd-field">
              <span>Alighting Fraction</span>
              <input type="number" step={0.01} min={0} max={1} value={predConfig.alighting_fraction} onChange={(e) => setPredConfig({ ...predConfig, alighting_fraction: Number(e.target.value) })} />
            </label>
            <label className="cmd-field">
              <span>Default Capacity</span>
              <input type="number" min={1} value={predConfig.default_capacity} onChange={(e) => setPredConfig({ ...predConfig, default_capacity: Number(e.target.value) })} />
            </label>
            <button className="cmd-btn cmd-btn-primary" onClick={savePredConfig}>Save</button>
          </div>
          <div className="cmd-config-col">
            <h3 className="cmd-config-title">Evaluator Thresholds</h3>
            <label className="cmd-field">
              <span>Route</span>
              <select value={evalRoute} onChange={(e) => setEvalRoute(e.target.value)}>
                <option value="default">All (default)</option>
                {routes.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
              </select>
            </label>
            <label className="cmd-field">
              <span>Occupancy Threshold</span>
              <input type="number" step={0.05} min={0} max={1} value={evalConfig.occupancy_threshold} onChange={(e) => setEvalConfig({ ...evalConfig, occupancy_threshold: Number(e.target.value) })} />
            </label>
            <label className="cmd-field">
              <span>Min Stranded</span>
              <input type="number" min={0} value={evalConfig.min_stranded} onChange={(e) => setEvalConfig({ ...evalConfig, min_stranded: Number(e.target.value) })} />
            </label>
            <label className="cmd-field">
              <span>Min Confidence</span>
              <input type="number" step={0.05} min={0} max={1} value={evalConfig.min_confidence} onChange={(e) => setEvalConfig({ ...evalConfig, min_confidence: Number(e.target.value) })} />
            </label>
            <button className="cmd-btn cmd-btn-primary" onClick={saveEvalConfig}>Save</button>
          </div>
        </div>
      </AccordionSection>

      {/* GTFS-RT Feed */}
      <AccordionSection title="GTFS-RT Feed">
        <div className="cmd-feed-status">
          <span className="cmd-feed-item">Last fetch: {health?.gtfs_rt_last_fetch ? relativeTime(health.gtfs_rt_last_fetch) : 'N/A'}</span>
          <span className="cmd-feed-item">Entities: {health?.gtfs_rt_entities ?? 'N/A'}</span>
          <span className="cmd-feed-item">Errors: {health?.gtfs_rt_errors ?? 0}</span>
        </div>
        <div className="cmd-feed-config">
          <span className="cmd-kv">Poll interval: {health?.gtfs_rt_poll_interval ?? 60}s</span>
          <span className="cmd-kv">Retain: {health?.gtfs_rt_retain ?? 20} fetches</span>
          <span className="cmd-kv">Timeout: {health?.gtfs_rt_timeout ?? 30}s</span>
        </div>
      </AccordionSection>

      {/* Model Versions */}
      <AccordionSection title="Model Versions">
        {models.length ? (
          <table className="cmd-table">
            <thead><tr><th>Filename</th><th>SHA256</th><th>Size</th><th>Uploaded</th><th>Active</th></tr></thead>
            <tbody>
              {models.map((m) => (
                <tr key={m.id} className={m.is_active ? 'cmd-row-active' : ''}>
                  <td>{m.filename}</td>
                  <td className="cmd-mono">{(m.sha256 ?? '').slice(0, 12)}...</td>
                  <td>{m.file_size ? `${(m.file_size / 1024 / 1024).toFixed(1)} MB` : '-'}</td>
                  <td>{m.uploaded_at ? relativeTime(m.uploaded_at) : '-'}</td>
                  <td>{m.is_active ? <span className="cmd-active-badge">active</span> : '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <div className="chart-empty">No model versions found</div>}
      </AccordionSection>

      {/* System Alerts */}
      <AccordionSection title="System Alerts">
        <div className="cmd-alerts-list">
          {visibleAlerts.length ? visibleAlerts.map((a) => (
            <div key={a.id} className={`cmd-alert-row cmd-alert-${a.severity}${a.resolved_at ? ' cmd-alert-resolved' : ''}`}>
              <div className="cmd-alert-border" />
              <div className="cmd-alert-content">
                <div className="cmd-alert-top">
                  <span className="cmd-alert-severity">{a.severity}</span>
                  <span className="cmd-alert-time">{relativeTime(a.created_at)}</span>
                </div>
                <span className="cmd-alert-msg">{a.message}</span>
                {(a.device_id || a.route_id) && (
                  <span className="cmd-alert-entity">{a.device_id ?? ''} {a.route_id ?? ''}</span>
                )}
              </div>
              {!a.resolved_at && (
                <button className="cmd-btn" onClick={() => resolveAlert(a.id)}>Resolve</button>
              )}
            </div>
          )) : <div className="chart-empty">No alerts</div>}
        </div>
        <button className="cmd-link-btn" onClick={() => setShowResolved(!showResolved)}>
          {showResolved ? 'Show active only' : 'Show resolved alerts'}
        </button>
      </AccordionSection>

      {/* Admin Activity Log */}
      <AccordionSection title="Admin Activity Log" defaultOpen={false}>
        {adminLog.length ? (
          <table className="cmd-table cmd-table-compact">
            <thead><tr><th>Time</th><th>Device</th><th>Action</th><th>Command</th><th>By</th></tr></thead>
            <tbody>
              {adminLog.map((l) => (
                <tr key={l.id}>
                  <td>{l.occurred_at ? new Date(l.occurred_at).toLocaleString() : ''}</td>
                  <td>{l.target_device_id ?? '-'}</td>
                  <td>{l.action}</td>
                  <td className="cmd-mono cmd-truncate" title={JSON.stringify(l.command)}>{JSON.stringify(l.command).slice(0, 40)}</td>
                  <td>{l.initiated_by ?? 'system'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <div className="chart-empty">No admin activity</div>}
      </AccordionSection>

      {/* Dashboard Tuning */}
      <AccordionSection title="Dashboard Tuning">
        <div className="cmd-feed-config">
          <span className="cmd-kv">Coalesce Window: {health?.coalesce_ms ?? 500}ms</span>
        </div>
      </AccordionSection>
    </div>
  );
}
