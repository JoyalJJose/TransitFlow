import { useMemo, useState, useEffect, useRef, useCallback } from 'react';

const FILL_BUCKETS = [
  { label: 'Low',      min: 0,  max: 40, color: '#9063ff' },
  { label: 'Medium',   min: 40, max: 70, color: '#d7a6b3' },
  { label: 'High',     min: 70, max: 90, color: '#e5cdc8' },
  { label: 'Critical', min: 90, max: 101, color: '#ef4444' },
];

function barColor(pct) {
  if (pct >= 90) return '#ef4444';
  if (pct >= 70) return '#e5cdc8';
  if (pct >= 40) return '#d7a6b3';
  return '#9063ff';
}

function lerp(a, b, t) {
  return a + (b - a) * t;
}

function easeInOut(t) {
  return t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t;
}

const ANIM_MS = 450;
const SLOT_COUNT = 5;

export default function FleetOverview({ vehicles = [] }) {
  const stats = useMemo(() => {
    const total = vehicles.length;
    if (!total) return { total: 0, avgOcc: 0, buckets: FILL_BUCKETS.map((b) => ({ ...b, count: 0, pct: 0 })) };

    const avgOcc = Math.round(
      vehicles.reduce((s, v) => s + v.currentOccupancyPercent, 0) / total,
    );

    const buckets = FILL_BUCKETS.map((b) => {
      const count = vehicles.filter(
        (v) => v.currentOccupancyPercent >= b.min && v.currentOccupancyPercent < b.max,
      ).length;
      return { ...b, count, pct: Math.round((count / total) * 100) };
    });

    return { total, avgOcc, buckets };
  }, [vehicles]);

  // Sorted top N target values
  const targets = useMemo(() => {
    return [...vehicles]
      .sort((a, b) => b.currentOccupancyPercent - a.currentOccupancyPercent)
      .slice(0, SLOT_COUNT)
      .map((v) => ({
        id: v.id,
        label: v.currentStopName
          ? `${v.routeName} @ ${v.currentStopName}`
          : `Route ${v.routeName}`,
        pct: v.currentOccupancyPercent,
      }));
  }, [vehicles]);

  // Slot-based animation: animate by position, not by vehicle ID
  const [slots, setSlots] = useState([]);
  const rafRef = useRef(null);
  const fromRef = useRef([]);

  const animate = useCallback((from, to) => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);

    const start = performance.now();

    function tick(now) {
      const t = Math.min((now - start) / ANIM_MS, 1);
      const e = easeInOut(t);

      const frame = to.map((target, i) => {
        const fromPct = i < from.length ? from[i].pct : 0;
        const pct = Math.round(lerp(fromPct, target.pct, e));
        return { id: target.id, label: target.label, pct };
      });

      setSlots(frame);

      if (t < 1) {
        rafRef.current = requestAnimationFrame(tick);
      } else {
        fromRef.current = to;
      }
    }

    rafRef.current = requestAnimationFrame(tick);
  }, []);

  useEffect(() => {
    const from = fromRef.current;
    animate(from, targets);

    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [targets, animate]);

  return (
    <div className="panel fleet-panel">
      <div className="panel-header">
        <h2>Fleet Overview</h2>
      </div>

      <div className="fleet-stats-row">
        <div className="fleet-stat">
          <span className="fleet-stat-value">{stats.total}</span>
          <span className="fleet-stat-label">Deployed</span>
        </div>
        <div className="fleet-stat">
          <span className="fleet-stat-value">{stats.avgOcc}%</span>
          <span className="fleet-stat-label">Avg Occupancy</span>
        </div>
      </div>

      <div className="fleet-distribution">
        <span className="fleet-dist-title">Fill-Level Distribution</span>
        <div className="fleet-dist-bar">
          {stats.buckets.map((b) =>
            b.pct > 0 ? (
              <div
                key={b.label}
                className="fleet-dist-segment"
                style={{ width: `${b.pct}%`, background: b.color }}
                title={`${b.label}: ${b.count} (${b.pct}%)`}
              />
            ) : null,
          )}
        </div>
        <div className="fleet-dist-legend">
          {stats.buckets.map((b) => (
            <span key={b.label} className="fleet-legend-item">
              <span className="fleet-legend-dot" style={{ background: b.color }} />
              {b.label} {b.count}
            </span>
          ))}
        </div>
      </div>

      {slots.length > 0 && (
        <div className="fleet-top3">
          <span className="fleet-dist-title">Most Full</span>
          {slots.map((s, i) => (
            <div key={i} className="fleet-top3-row">
              <span className="fleet-top3-id" title={s.label}>{s.label}</span>
              <div className="fleet-bar-track">
                <div
                  className="fleet-bar-fill"
                  style={{
                    width: `${s.pct}%`,
                    background: barColor(s.pct),
                  }}
                />
              </div>
              <span className="fleet-top3-pct">{s.pct}%</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
