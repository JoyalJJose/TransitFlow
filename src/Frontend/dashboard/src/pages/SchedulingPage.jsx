import { useState, useEffect, useMemo, useCallback, Fragment } from 'react';
import { apiGet } from '../services/apiService';

function occColor(pct) {
  if (pct >= 90) return '#ef4444';
  if (pct >= 70) return '#e5cdc8';
  if (pct >= 40) return '#d7a6b3';
  return '#9063ff';
}

function relativeTime(ts) {
  if (!ts) return '';
  const diff = (Date.now() - new Date(ts).getTime()) / 1000;
  if (diff < 60) return `${Math.round(diff)}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  return `${Math.round(diff / 3600)}h ago`;
}

function ConfidenceBar({ value }) {
  const pct = Math.round((value ?? 0) * 100);
  return (
    <div className="conf-bar-track">
      <div className="conf-bar-fill" style={{ width: `${pct}%`, background: occColor(100 - pct) }} />
      <span className="conf-bar-label">{pct}%</span>
    </div>
  );
}

export default function SchedulingPage({ data, theme }) {
  const routes = data?.routes ?? [];

  const [selectedRoute, setSelectedRoute] = useState('');
  const [selectedDirection, setSelectedDirection] = useState(0);
  const [predictions, setPredictions] = useState(null);
  const [decisions, setDecisions] = useState([]);
  const [selectedDecision, setSelectedDecision] = useState(null);
  const [collapsedVehicles, setCollapsedVehicles] = useState(new Set());
  const [decisionFilter, setDecisionFilter] = useState('all');

  useEffect(() => {
    if (!selectedRoute && routes.length) {
      setSelectedRoute(routes[0].id);
    }
  }, [routes, selectedRoute]);

  const fetchPredictions = useCallback(async () => {
    if (!selectedRoute) return;
    try {
      const p = await apiGet(`/api/predictions/${selectedRoute}?direction_id=${selectedDirection}`);
      setPredictions(p);
    } catch (e) {
      console.error('Prediction fetch error:', e);
    }
  }, [selectedRoute, selectedDirection]);

  const fetchDecisions = useCallback(async () => {
    try {
      const d = await apiGet('/api/scheduler/decisions?limit=50');
      setDecisions(d ?? []);
    } catch (e) {
      console.error('Decisions fetch error:', e);
    }
  }, []);

  useEffect(() => { fetchPredictions(); }, [fetchPredictions]);
  useEffect(() => { fetchDecisions(); }, [fetchDecisions]);

  useEffect(() => {
    if (decisions.length && !selectedDecision) {
      setSelectedDecision(decisions[0]);
    }
  }, [decisions, selectedDecision]);

  const vehiclePredictions = predictions?.vehicle_predictions ?? [];
  const routeStops = predictions?.stops ?? [];
  const strandedStops = predictions?.stranded_at_stops ?? {};

  const filteredDecisions = useMemo(() => {
    if (decisionFilter === 'all') return decisions;
    return decisions.filter((d) => d.route_id === decisionFilter);
  }, [decisions, decisionFilter]);

  const stopNameMap = useMemo(() => {
    const m = {};
    for (const s of (data?.stops ?? [])) m[s.id] = s.name;
    return m;
  }, [data]);

  return (
    <div className="scheduling-page">
      <div className="scheduling-filter-bar">
        <label className="analytics-filter-group">
          <span className="analytics-filter-label">Route</span>
          <select value={selectedRoute} onChange={(e) => setSelectedRoute(e.target.value)}>
            {routes.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
          </select>
        </label>
        <div className="analytics-time-pills">
          <button className={`time-pill${selectedDirection === 0 ? ' time-pill-active' : ''}`} onClick={() => setSelectedDirection(0)}>Inbound</button>
          <button className={`time-pill${selectedDirection === 1 ? ' time-pill-active' : ''}`} onClick={() => setSelectedDirection(1)}>Outbound</button>
        </div>
        <button className="sched-refresh-btn" onClick={() => { fetchPredictions(); fetchDecisions(); }}>Refresh</button>
      </div>

      <div className="scheduling-body">
        <div className="scheduling-left">
          {/* Route Prediction Visualizer */}
          <div className="panel sched-viz-panel">
            <div className="panel-header"><h2>Route Prediction</h2></div>
            <div className="sched-viz-body">
              {routeStops.length ? (
                <div className="route-viz-list">
                  {routeStops.map((stop) => {
                    const waiting = stop.people_waiting ?? 0;
                    const stranded = strandedStops[stop.stop_id] ?? 0;
                    const maxLoad = vehiclePredictions.reduce((max, vp) => {
                      const sp = vp.stops?.find((s) => s.stop_id === stop.stop_id);
                      return sp ? Math.max(max, sp.predicted_passengers ?? 0) : max;
                    }, 0);
                    const capacity = vehiclePredictions[0]?.vehicle_capacity ?? 80;
                    const loadPct = capacity > 0 ? Math.min((maxLoad / capacity) * 100, 100) : 0;
                    const dotColor = occColor(loadPct);
                    const barColor = loadPct >= 90 ? '#ef4444' : loadPct >= 70 ? '#e5cdc8' : '#9063ff';
                    return (
                      <div key={stop.stop_id} className="route-viz-row">
                        <div className="route-viz-track">
                          <div className="route-viz-line" />
                          <div className="route-viz-dot" style={{ background: dotColor, borderColor: dotColor }} />
                          <div className="route-viz-line" />
                        </div>
                        <div className="route-viz-info">
                          <span className="route-viz-name">{stopNameMap[stop.stop_id] || stop.stop_id}</span>
                          <div className="route-viz-badges">
                            {waiting > 0 && <span className="route-viz-badge route-viz-badge--waiting">{waiting} waiting</span>}
                            {stranded > 0 && <span className="route-viz-badge route-viz-badge--stranded">{stranded} stranded</span>}
                          </div>
                          <div className="route-viz-bar-wrap">
                            <div className="route-viz-bar-track">
                              <div className="route-viz-bar-fill" style={{ width: `${loadPct}%`, background: barColor }} />
                            </div>
                            <span className="route-viz-bar-label">{Math.round(loadPct)}%</span>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="chart-empty">No prediction data for this route</div>
              )}
            </div>
          </div>

          {/* Predictions Table */}
          <div className="panel sched-table-panel">
            <div className="panel-header"><h2>Vehicle Predictions</h2></div>
            <div className="sched-table-body">
              {vehiclePredictions.length ? (
                <table className="sched-table">
                  <thead>
                    <tr>
                      <th>Vehicle</th>
                      <th>Peak Load</th>
                      <th>Confidence</th>
                      <th>Stops</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {vehiclePredictions.map((vp) => {
                      const isExpanded = !collapsedVehicles.has(vp.vehicle_id);
                      return (
                        <Fragment key={vp.vehicle_id}>
                          <tr
                            className={`sched-row${isExpanded ? ' sched-row-expanded' : ''}`}
                            onClick={() => setCollapsedVehicles((prev) => {
                              const next = new Set(prev);
                              if (next.has(vp.vehicle_id)) next.delete(vp.vehicle_id);
                              else next.add(vp.vehicle_id);
                              return next;
                            })}
                          >
                            <td className="sched-cell-id">{vp.vehicle_id}</td>
                            <td><span className="sched-peak" style={{ color: occColor(vp.peak_occupancy_pct * 100) }}>{Math.round(vp.peak_occupancy_pct * 100)}%</span></td>
                            <td><ConfidenceBar value={vp.confidence} /></td>
                            <td>{vp.stops?.length ?? 0}</td>
                            <td className="sched-expand-icon">{isExpanded ? '\u25B2' : '\u25BC'}</td>
                          </tr>
                          {isExpanded && (
                            <tr className="sched-detail-row">
                              <td colSpan={5}>
                                <div className="sched-stop-detail">
                                  {(vp.stops ?? []).map((sp) => (
                                    <div key={sp.stop_id} className="sched-stop-item">
                                      <span className={`sched-data-dot${sp.has_data ? '' : ' sched-data-dot-none'}`} />
                                      <span className="sched-stop-name">{stopNameMap[sp.stop_id] || sp.stop_id}</span>
                                      <span className="sched-stop-pax">{sp.predicted_passengers}</span>
                                      <span className="sched-stop-board">+{sp.boarded}</span>
                                      <span className="sched-stop-alight">-{sp.alighted}</span>
                                    </div>
                                  ))}
                                </div>
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      );
                    })}
                  </tbody>
                </table>
              ) : (
                <div className="chart-empty">No vehicle predictions available</div>
              )}
            </div>
          </div>
        </div>

        <div className="scheduling-right">
          {/* Decisions Feed */}
          <div className="panel sched-decisions-panel">
            <div className="panel-header">
              <h2>Scheduler Decisions</h2>
              <select className="sched-decision-filter" value={decisionFilter} onChange={(e) => setDecisionFilter(e.target.value)}>
                <option value="all">All Routes</option>
                {routes.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
              </select>
            </div>
            <div className="sched-decisions-list">
              {filteredDecisions.length ? filteredDecisions.map((d) => {
                const routeName = routes.find((r) => r.id === d.route_id)?.name ?? d.route_id;
                return (
                  <div
                    key={d.id}
                    className={`sched-decision-card${selectedDecision?.id === d.id ? ' sched-decision-selected' : ''}`}
                    onClick={() => setSelectedDecision(d)}
                  >
                    <div className="sched-decision-border" />
                    <div className="sched-decision-content">
                      <div className="sched-decision-top">
                        <span className="sched-decision-badge">{d.decision_type}</span>
                        <span className="sched-decision-time">{relativeTime(d.decided_at)}</span>
                      </div>
                      <span className="sched-decision-route">{routeName} dir {d.direction_id}</span>
                      <span className="sched-decision-summary">
                        Peak {Math.round((d.predicted_occupancy_pct ?? 0) * 100)}% occ
                        {d.total_stranded > 0 && ` \u2022 ${d.total_stranded} stranded`}
                      </span>
                    </div>
                  </div>
                );
              }) : (
                <div className="chart-empty">No scheduler decisions</div>
              )}
            </div>
          </div>

          {/* Decision Detail */}
          <div className="panel sched-detail-panel">
            <div className="panel-header"><h2>Decision Detail</h2></div>
            <div className="sched-detail-body">
              {selectedDecision ? (
                <div className="decision-detail">
                  <div className="dd-row"><span className="dd-label">Type</span><span className="dd-value">{selectedDecision.decision_type}</span></div>
                  <div className="dd-row"><span className="dd-label">Route</span><span className="dd-value">{routes.find((r) => r.id === selectedDecision.route_id)?.name ?? selectedDecision.route_id}</span></div>
                  <div className="dd-row"><span className="dd-label">Direction</span><span className="dd-value">{selectedDecision.direction_id}</span></div>
                  <div className="dd-row"><span className="dd-label">Trigger Vehicle</span><span className="dd-value">{selectedDecision.trigger_vehicle_id ?? '-'}</span></div>
                  <div className="dd-row"><span className="dd-label">Trigger Stop</span><span className="dd-value">{stopNameMap[selectedDecision.trigger_stop_id] ?? selectedDecision.trigger_stop_id ?? '-'}</span></div>
                  <div className="dd-row"><span className="dd-label">Predicted Occ</span><span className="dd-value" style={{ color: occColor((selectedDecision.predicted_occupancy_pct ?? 0) * 100) }}>{Math.round((selectedDecision.predicted_occupancy_pct ?? 0) * 100)}%</span></div>
                  <div className="dd-row"><span className="dd-label">Total Stranded</span><span className="dd-value">{selectedDecision.total_stranded ?? 0}</span></div>
                  <div className="dd-row"><span className="dd-label">Threshold</span><span className="dd-value">{selectedDecision.threshold ?? '-'}</span></div>
                  <div className="dd-row"><span className="dd-label">Status</span><span className={`dd-status dd-status-${selectedDecision.status ?? 'pending'}`}>{selectedDecision.status ?? 'pending'}</span></div>
                  {selectedDecision.message && <div className="dd-message">{selectedDecision.message}</div>}
                </div>
              ) : (
                <div className="chart-empty">Select a decision to view details</div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
