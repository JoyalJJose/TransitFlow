import {
  BarChart,
  Bar,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts';

function effColor(pct) {
  if (pct >= 70) return '#0e7490';
  if (pct >= 50) return '#1596ad';
  if (pct >= 30) return '#3ab0c4';
  return '#6bc4d4';
}

function shortRoute(name) {
  if (name.startsWith('LUAS ')) return name.replace('LUAS ', '').replace(' Line', '');
  if (name.startsWith('Route ')) return name.slice(6);
  return name;
}

function shortTime(t) {
  return parseInt(t.split(':')[0], 10).toString();
}

export default function CenterCharts({
  resourceEfficiency = [],
  onTimeData = [],
  theme = 'light',
}) {
  const dark = theme === 'dark';
  const grid = dark ? 'rgba(144,99,255,0.12)' : 'rgba(57,32,97,0.08)';
  const tick = { fill: dark ? 'rgba(229,205,200,0.65)' : 'rgba(57,32,97,0.45)', fontSize: 9 };
  const tooltipStyle = {
    background: dark ? '#2a2b44' : '#fff',
    border: `1px solid ${dark ? 'rgba(144,99,255,0.2)' : 'rgba(57,32,97,0.12)'}`,
    borderRadius: 6,
    fontSize: 12,
  };

  return (
    <div className="center-charts">
      <div className="chart-card-sm">
        <h3>Resource Efficiency</h3>
        <div className="chart-card-body">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={resourceEfficiency} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={grid} />
              <XAxis dataKey="route" hide />
              <YAxis domain={[0, 100]} tick={tick} tickFormatter={(v) => `${v}%`} width={32} />
              <Tooltip
                contentStyle={tooltipStyle}
                labelStyle={{ color: dark ? '#f0e4df' : '#392061' }}
                formatter={(v) => [`${v}%`, 'Efficiency']}
              />
              <Bar dataKey="efficiency" radius={[3, 3, 0, 0]}>
                {resourceEfficiency.map((entry, i) => (
                  <Cell key={i} fill={effColor(entry.efficiency)} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="chart-card-sm">
        <h3>On-Time Performance</h3>
        <div className="chart-card-body">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={onTimeData} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id="onTimeGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#9063ff" stopOpacity={0.3} />
                  <stop offset="100%" stopColor="#9063ff" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke={grid} />
              <XAxis
                dataKey="time"
                tick={tick}
                tickFormatter={shortTime}
                interval={0}
                height={18}
              />
              <YAxis domain={[60, 100]} tick={tick} tickFormatter={(v) => `${v}%`} width={32} />
              <Tooltip
                contentStyle={tooltipStyle}
                labelStyle={{ color: dark ? '#f0e4df' : '#392061' }}
                formatter={(v) => [`${v}%`, 'On-Time']}
              />
              <Area
                type="monotone"
                dataKey="onTimePercent"
                stroke="#9063ff"
                strokeWidth={2}
                fill="url(#onTimeGrad)"
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
