import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';

function shortTime(t) {
  return parseInt(t.split(':')[0], 10).toString();
}

export default function PerformanceMetrics({ fleetUtilization = [], theme = 'light' }) {
  const dark = theme === 'dark';

  return (
    <div className="panel perf-panel">
      <div className="panel-header">
        <h2>Fleet Utilization</h2>
      </div>

      <div className="chart-panel-body">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={fleetUtilization} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id="fleetUtilGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#d7a6b3" stopOpacity={0.35} />
                <stop offset="100%" stopColor="#d7a6b3" stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke={dark ? 'rgba(144,99,255,0.12)' : 'rgba(57,32,97,0.08)'} />
            <XAxis
              dataKey="time"
              tick={{ fill: dark ? 'rgba(229,205,200,0.65)' : 'rgba(57,32,97,0.45)', fontSize: 9 }}
              tickFormatter={shortTime}
              interval={0}
              height={18}
            />
            <YAxis
              domain={[0, 100]}
              tick={{ fill: dark ? 'rgba(229,205,200,0.65)' : 'rgba(57,32,97,0.45)', fontSize: 9 }}
              tickFormatter={(v) => `${v}%`}
              width={32}
            />
            <Tooltip
              contentStyle={{
                background: dark ? '#2a2b44' : '#fff',
                border: `1px solid ${dark ? 'rgba(144,99,255,0.2)' : 'rgba(57,32,97,0.12)'}`,
                borderRadius: 6,
                fontSize: 12,
              }}
              labelStyle={{ color: dark ? '#f0e4df' : '#392061' }}
              formatter={(v) => [`${v}%`, 'Avg Occupancy']}
            />
            <Area
              type="monotone"
              dataKey="avgOccupancy"
              stroke="#d7a6b3"
              strokeWidth={2}
              fill="url(#fleetUtilGrad)"
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
