import { useMemo } from 'react';

export default function SummaryCards({
  stops = [],
  stopWaitCounts = [],
  vehicles = [],
  lastUpdated,
}) {
  const stats = useMemo(() => {
    const totalWaiting = stopWaitCounts.reduce((sum, s) => sum + s.count, 0);
    const activeVehicles = vehicles.length;
    const avgOccupancy =
      activeVehicles > 0
        ? Math.round(
            vehicles.reduce((s, v) => s + v.currentOccupancyPercent, 0) /
              activeVehicles,
          )
        : 0;

    const HIGH_WAIT_THRESHOLD = 10;
    const highWaitStops = stopWaitCounts.filter(
      (s) => s.count > HIGH_WAIT_THRESHOLD,
    ).length;

    let busiestStop = { name: '—', count: 0 };
    if (stopWaitCounts.length) {
      const busiest = stopWaitCounts.reduce((a, b) =>
        a.count >= b.count ? a : b,
      );
      const stopInfo = stops.find((s) => s.id === busiest.stopId);
      busiestStop = { name: stopInfo?.name ?? busiest.stopId, count: busiest.count };
    }

    return { totalWaiting, activeVehicles, avgOccupancy, highWaitStops, busiestStop };
  }, [stops, stopWaitCounts, vehicles]);

  const updatedStr = lastUpdated
    ? new Date(lastUpdated).toLocaleTimeString()
    : '—';

  return (
    <div className="summary-cards">
      <Card label="Total Waiting" value={stats.totalWaiting} accent="#3b82f6" />
      <Card label="Active Vehicles" value={stats.activeVehicles} accent="#8b5cf6" />
      <Card label="Avg Occupancy" value={`${stats.avgOccupancy}%`} accent="#f59e0b" />
      <Card
        label="Busiest Stop"
        value={`${stats.busiestStop.name} (${stats.busiestStop.count})`}
        accent="#ef4444"
      />
      <Card label="High-Wait Stops" value={stats.highWaitStops} accent="#ec4899" />
      <Card label="Last Updated" value={updatedStr} accent="#06b6d4" />
    </div>
  );
}

function Card({ label, value, accent }) {
  return (
    <div className="summary-card" style={{ borderTopColor: accent }}>
      <span className="card-label">{label}</span>
      <span className="card-value">{value}</span>
    </div>
  );
}
