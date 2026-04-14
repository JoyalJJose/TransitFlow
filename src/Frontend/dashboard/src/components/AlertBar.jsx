import { useState, useMemo, useEffect } from 'react';
import { apiGet } from '../services/apiService';

const AlertIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
    <line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
  </svg>
);

const severityClass = {
  info: 'alert-info',
  warning: 'alert-warning',
  critical: 'alert-critical',
  decision: 'alert-decision',
};

export default function AlertBar({ alerts = [] }) {
  const [dismissed, setDismissed] = useState(new Set());
  const [decisions, setDecisions] = useState([]);

  useEffect(() => {
    apiGet('/api/scheduler/decisions?limit=5').then((d) => {
      if (d) setDecisions(d);
    }).catch(() => {});
    const interval = setInterval(() => {
      apiGet('/api/scheduler/decisions?limit=5').then((d) => {
        if (d) setDecisions(d);
      }).catch(() => {});
    }, 30000);
    return () => clearInterval(interval);
  }, []);

  const combined = useMemo(() => {
    const decisionAlerts = decisions.map((d) => ({
      id: `decision-${d.id}`,
      severity: 'decision',
      message: `${d.decision_type}: Route ${d.route_id} dir ${d.direction_id} — peak ${Math.round((d.predicted_occupancy_pct ?? 0) * 100)}% occ${d.total_stranded > 0 ? `, ${d.total_stranded} stranded` : ''}`,
    }));
    return [...alerts, ...decisionAlerts].filter((a) => !dismissed.has(a.id));
  }, [alerts, decisions, dismissed]);

  const current = combined[0];
  if (!current) return null;

  return (
    <div className={`alert-bar ${severityClass[current.severity] ?? ''}`}>
      <div className="alert-content">
        <AlertIcon />
        <span className="alert-msg">{current.message}</span>
        {combined.length > 1 && (
          <span className="alert-badge">+{combined.length - 1} more</span>
        )}
      </div>
      <div className="alert-actions">
        <button className="alert-btn" onClick={() => {}}>Acknowledge</button>
        <button className="alert-btn" onClick={() => {}}>Details</button>
        <button
          className="alert-btn alert-btn-dismiss"
          onClick={() => setDismissed((s) => new Set(s).add(current.id))}
        >
          Dismiss
        </button>
      </div>
    </div>
  );
}
