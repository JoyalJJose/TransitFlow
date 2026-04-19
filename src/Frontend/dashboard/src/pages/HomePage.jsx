import { useCallback, useState } from 'react';
import StationPanel from '../components/StationPanel';
import MapView from '../components/MapView';
import CenterCharts from '../components/CenterCharts';
import FleetOverview from '../components/FleetOverview';
import PerformanceMetrics from '../components/PerformanceMetrics';
import ActiveRoutes from '../components/ActiveRoutes';
import CrowdingHotspots from '../components/CrowdingHotspots';
import SystemStats from '../components/SystemStats';

export default function HomePage({ data, theme }) {
  const [mapFullscreen, setMapFullscreen] = useState(false);

  const enterFullscreen = useCallback(() => setMapFullscreen(true), []);
  const exitFullscreen = useCallback(() => setMapFullscreen(false), []);

  return (
    <>
      <main className={`dashboard-grid${mapFullscreen ? ' dashboard-grid--hidden' : ''}`}>
        <div className="left-column">
          <SystemStats />
          <StationPanel stops={data.stops} stopWaitCounts={data.stopWaitCounts} />
          <ActiveRoutes routes={data.routes} vehicles={data.vehicles} />
          <CrowdingHotspots hotspots={data.crowdingHotspots} />
        </div>

        <div className="center-column">
          <div className="map-section">
            {!mapFullscreen && (
              <MapView
                stops={data.stops}
                stopWaitCounts={data.stopWaitCounts}
                vehicles={data.vehicles}
                routes={data.routes}
                theme={theme}
                onToggleFullscreen={enterFullscreen}
              />
            )}
          </div>
          <CenterCharts
            resourceEfficiency={data.resourceEfficiency}
            onTimeData={data.onTimeData}
            theme={theme}
          />
        </div>

        <div className="right-column">
          <FleetOverview vehicles={data.vehicles} />
          <PerformanceMetrics fleetUtilization={data.fleetUtilization} theme={theme} />
        </div>
      </main>

      {mapFullscreen && (
        <div className="map-fullscreen-overlay map-fullscreen-overlay--active">
          <MapView
            stops={data.stops}
            stopWaitCounts={data.stopWaitCounts}
            vehicles={data.vehicles}
            routes={data.routes}
            theme={theme}
            isFullscreen
            onToggleFullscreen={exitFullscreen}
          />
        </div>
      )}
    </>
  );
}
