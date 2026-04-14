function trendArrow(trend) {
  if (trend === 'rising') return { symbol: '\u2191', color: 'var(--danger)' };
  if (trend === 'falling') return { symbol: '\u2193', color: 'var(--success)' };
  return { symbol: '\u2014', color: 'var(--text-muted)' };
}

export default function CrowdingHotspots({ hotspots = [] }) {
  return (
    <div className="panel hotspots-panel">
      <div className="panel-header">
        <h2>Crowding Hotspots</h2>
      </div>

      <div className="hs-list">
        {hotspots.map((h) => {
          const t = trendArrow(h.trend);
          return (
            <div key={h.stopId} className="hs-row">
              <span className="hs-name">{h.stopName}</span>
              <span className="hs-count">{h.count}</span>
              <span className="hs-trend" style={{ color: t.color }}>
                {t.symbol}
              </span>
              <span className="hs-delta" style={{ color: t.color }}>
                {h.delta > 0 ? `+${h.delta}` : h.delta}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
