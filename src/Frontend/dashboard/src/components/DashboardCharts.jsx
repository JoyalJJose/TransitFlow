import { useMemo } from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts';

function occColor(pct) {
  if (pct >= 90) return '#ef4444';
  if (pct >= 70) return '#f97316';
  if (pct >= 40) return '#eab308';
  return '#22c55e';
}

function waitColor(count) {
  if (count >= 15) return '#ef4444';
  if (count >= 6) return '#eab308';
  return '#22c55e';
}

export default function DashboardCharts({
  stops = [],
  stopWaitCounts = [],
  vehicles = [],
  routes = [],
}) {
  const waitData = useMemo(() => {
    const stopMap = {};
    stops.forEach((s) => { stopMap[s.id] = s.name; });
    return stopWaitCounts
      .map((s) => ({
        name: stopMap[s.stopId] ?? s.stopId,
        count: s.count,
      }))
      .sort((a, b) => b.count - a.count);
  }, [stops, stopWaitCounts]);

  const vehicleData = useMemo(() => {
    const routeMap = {};
    routes.forEach((r) => { routeMap[r.id] = r.name; });
    return vehicles.map((v) => ({
      name: `${v.id} (${routeMap[v.routeId] ?? v.routeId})`,
      occupancy: v.currentOccupancyPercent,
    }));
  }, [vehicles, routes]);

  return (
    <div className="dashboard-charts">
      <div className="chart-card">
        <h3>People Waiting by Stop</h3>
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={waitData} margin={{ top: 5, right: 20, bottom: 60, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#333" />
            <XAxis
              dataKey="name"
              angle={-35}
              textAnchor="end"
              interval={0}
              tick={{ fill: '#aaa', fontSize: 12 }}
              height={70}
            />
            <YAxis tick={{ fill: '#aaa', fontSize: 12 }} />
            <Tooltip
              contentStyle={{ background: '#1e1e2e', border: 'none', borderRadius: 8 }}
              labelStyle={{ color: '#ccc' }}
            />
            <Bar dataKey="count" radius={[4, 4, 0, 0]}>
              {waitData.map((entry, idx) => (
                <Cell key={idx} fill={waitColor(entry.count)} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="chart-card">
        <h3>Vehicle Occupancy</h3>
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={vehicleData} margin={{ top: 5, right: 20, bottom: 60, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#333" />
            <XAxis
              dataKey="name"
              angle={-35}
              textAnchor="end"
              interval={0}
              tick={{ fill: '#aaa', fontSize: 12 }}
              height={70}
            />
            <YAxis
              domain={[0, 100]}
              tick={{ fill: '#aaa', fontSize: 12 }}
              tickFormatter={(v) => `${v}%`}
            />
            <Tooltip
              contentStyle={{ background: '#1e1e2e', border: 'none', borderRadius: 8 }}
              labelStyle={{ color: '#ccc' }}
              formatter={(value) => [`${value}%`, 'Occupancy']}
            />
            <Bar dataKey="occupancy" radius={[4, 4, 0, 0]}>
              {vehicleData.map((entry, idx) => (
                <Cell key={idx} fill={occColor(entry.occupancy)} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
