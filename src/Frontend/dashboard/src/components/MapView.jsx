import { useMemo, useState, useCallback } from 'react';
import Map, {
  Source,
  Layer,
  Marker,
  Popup,
  NavigationControl,
} from 'react-map-gl/mapbox';
import 'mapbox-gl/dist/mapbox-gl.css';

const MAPBOX_TOKEN = import.meta.env.VITE_MAPBOX_ACCESS_TOKEN;

const DUBLIN_CENTER = { lat: 53.345, lng: -6.26 };

function vehicleColor(pct) {
  if (pct >= 90) return '#ef4444';
  if (pct >= 70) return '#e5cdc8';
  if (pct >= 40) return '#d7a6b3';
  return '#9063ff';
}

function BusIcon({ color }) {
  return (
    <svg width="26" height="18" viewBox="0 0 26 18">
      <rect x="1" y="1" width="24" height="16" rx="4" fill={color} stroke="#392061" strokeWidth="1.2" />
      <rect x="4" y="4" width="6" height="5" rx="1" fill="rgba(255,255,255,0.6)" />
      <rect x="16" y="4" width="6" height="5" rx="1" fill="rgba(255,255,255,0.6)" />
      <circle cx="7" cy="15" r="2" fill="#392061" />
      <circle cx="19" cy="15" r="2" fill="#392061" />
    </svg>
  );
}

function LuasIcon({ color }) {
  return (
    <svg width="30" height="14" viewBox="0 0 30 14">
      <rect x="1" y="1" width="28" height="12" rx="5" fill={color} stroke="#392061" strokeWidth="1.2" />
      <rect x="4" y="3.5" width="5" height="4.5" rx="1" fill="rgba(255,255,255,0.6)" />
      <rect x="12.5" y="3.5" width="5" height="4.5" rx="1" fill="rgba(255,255,255,0.6)" />
      <rect x="21" y="3.5" width="5" height="4.5" rx="1" fill="rgba(255,255,255,0.6)" />
    </svg>
  );
}

function TypeBadge({ type }) {
  const label = type === 'luas' ? 'Luas' : 'Bus';
  return <span className={`map-popup-badge map-popup-badge--${type}`}>{label}</span>;
}

function OccupancyBar({ pct }) {
  return (
    <div className="map-popup-occ-track">
      <div
        className="map-popup-occ-fill"
        style={{ width: `${Math.min(pct, 100)}%`, background: vehicleColor(pct) }}
      />
    </div>
  );
}

function FullscreenButton({ isFullscreen, onClick }) {
  return (
    <button
      type="button"
      className="map-fs-btn"
      onClick={onClick}
      title={isFullscreen ? 'Exit fullscreen' : 'Fullscreen map'}
    >
      {isFullscreen ? (
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
          <path d="M5 1v4H1M11 1v4h4M5 15v-4H1M11 15v-4h4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
      ) : (
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
          <path d="M1 5V1h4M15 5V1h-4M1 11v4h4M15 11v4h-4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
      )}
    </button>
  );
}

export default function MapView({
  stops = [],
  stopWaitCounts = [],
  vehicles = [],
  theme = 'light',
  isFullscreen = false,
  onToggleFullscreen,
}) {
  const dark = theme === 'dark';
  const [cursor, setCursor] = useState('');
  const [stopPopup, setStopPopup] = useState(null);
  const [vehiclePopup, setVehiclePopup] = useState(null);

  const waitMap = useMemo(() => {
    const m = {};
    stopWaitCounts.forEach((s) => {
      m[s.stopId] = s.count;
    });
    return m;
  }, [stopWaitCounts]);

  const stopLookup = useMemo(() => {
    const m = {};
    stops.forEach((s) => {
      m[s.id] = s;
    });
    return m;
  }, [stops]);

  const center = useMemo(() => {
    if (!stops.length) return DUBLIN_CENTER;
    const avgLat = stops.reduce((s, st) => s + st.lat, 0) / stops.length;
    const avgLng = stops.reduce((s, st) => s + st.lng, 0) / stops.length;
    return { lat: avgLat, lng: avgLng };
  }, [stops]);

  const stopsGeoJSON = useMemo(
    () => ({
      type: 'FeatureCollection',
      features: stops.map((stop) => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [stop.lng, stop.lat] },
        properties: { id: stop.id, count: waitMap[stop.id] ?? 0 },
      })),
    }),
    [stops, waitMap],
  );

  const circleColor = useMemo(
    () => [
      'interpolate',
      ['linear'],
      ['get', 'count'],
      0,
      '#9063ff',
      10,
      '#d7a6b3',
      20,
      '#ef4444',
    ],
    [],
  );

  const stopsPaint = useMemo(
    () => ({
      'circle-radius': [
        'interpolate',
        ['linear'],
        ['get', 'count'],
        0, 4,
        10, 7,
        30, 12,
      ],
      'circle-color': circleColor,
      'circle-stroke-width': 1.2,
      'circle-stroke-color': dark ? '#e5cdc8' : '#392061',
      'circle-opacity': 0.85,
    }),
    [dark, circleColor],
  );

  const handleStopClick = useCallback(
    (e) => {
      const feature = e.features?.[0];
      if (!feature) return;
      const id = feature.properties.id;
      const stop = stopLookup[id];
      if (!stop) return;
      setVehiclePopup(null);
      setStopPopup({
        lng: feature.geometry.coordinates[0],
        lat: feature.geometry.coordinates[1],
        stop,
        count: waitMap[id] ?? 0,
      });
    },
    [stopLookup, waitMap],
  );

  const handleVehicleClick = useCallback((v) => {
    setStopPopup(null);
    setVehiclePopup(v);
  }, []);

  if (!MAPBOX_TOKEN) {
    return (
      <div className="map-placeholder">
        <p>
          Set <code>VITE_MAPBOX_ACCESS_TOKEN</code> in <code>.env</code> to
          enable the map.
        </p>
      </div>
    );
  }

  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <Map
        initialViewState={{
          latitude: center.lat,
          longitude: center.lng,
          zoom: 12,
        }}
        style={{ width: '100%', height: '100%' }}
        mapStyle={
          dark
            ? 'mapbox://styles/mapbox/dark-v11'
            : 'mapbox://styles/mapbox/light-v11'
        }
        mapboxAccessToken={MAPBOX_TOKEN}
        attributionControl={false}
        logoPosition="top-left"
        interactiveLayerIds={['stop-circles']}
        onClick={handleStopClick}
        onMouseEnter={() => setCursor('pointer')}
        onMouseLeave={() => setCursor('')}
        cursor={cursor}
      >
        <NavigationControl position="bottom-right" showCompass={false} />

      {/* ---- Stop circles (GeoJSON layer) ---- */}
      <Source id="stops" type="geojson" data={stopsGeoJSON}>
        <Layer id="stop-circles" type="circle" paint={stopsPaint} />
      </Source>

      {/* ---- Vehicle markers ---- */}
      {vehicles
        .filter((v) => v.lat != null && v.lng != null)
        .map((v) => (
          <Marker
            key={v.id}
            latitude={v.lat}
            longitude={v.lng}
            anchor="center"
            onClick={(e) => {
              e.originalEvent.stopPropagation();
              handleVehicleClick(v);
            }}
          >
            <div className="vehicle-marker" title={`${v.routeName} — ${v.currentOccupancyPercent}%`}>
              {v.type === 'luas' ? (
                <LuasIcon color={vehicleColor(v.currentOccupancyPercent)} />
              ) : (
                <BusIcon color={vehicleColor(v.currentOccupancyPercent)} />
              )}
              <span className="vehicle-marker-label">{v.routeName}</span>
            </div>
          </Marker>
        ))}

      {/* ---- Stop popup ---- */}
      {stopPopup && (
        <Popup
          longitude={stopPopup.lng}
          latitude={stopPopup.lat}
          anchor="bottom"
          closeOnClick={false}
          onClose={() => setStopPopup(null)}
          className="map-popup"
        >
          <div className="map-popup-inner">
            <div className="map-popup-title">{stopPopup.stop.name}</div>
            <TypeBadge type={stopPopup.stop.type} />
            <div className="map-popup-stat">
              <span className="map-popup-stat-value">{stopPopup.count}</span>
              <span className="map-popup-stat-label">waiting</span>
            </div>
          </div>
        </Popup>
      )}

      {/* ---- Vehicle popup ---- */}
      {vehiclePopup && (
        <Popup
          longitude={vehiclePopup.lng}
          latitude={vehiclePopup.lat}
          anchor="bottom"
          closeOnClick={false}
          onClose={() => setVehiclePopup(null)}
          className="map-popup"
        >
          <div className="map-popup-inner">
            <div className="map-popup-title">{vehiclePopup.routeName}</div>
            <TypeBadge type={vehiclePopup.type} />
            <OccupancyBar pct={vehiclePopup.currentOccupancyPercent} />
            <div className="map-popup-stat-row">
              <div className="map-popup-stat">
                <span className="map-popup-stat-value">
                  {vehiclePopup.currentOccupancyPercent}%
                </span>
                <span className="map-popup-stat-label">occupancy</span>
              </div>
              <div className="map-popup-stat">
                <span className="map-popup-stat-value">
                  {vehiclePopup.passengerCount}/{vehiclePopup.capacity}
                </span>
                <span className="map-popup-stat-label">passengers</span>
              </div>
            </div>
            {vehiclePopup.currentStopName && (
              <div className="map-popup-detail">
                {vehiclePopup.state === 'ARRIVING' ? 'Arriving at' : 'At'}{' '}
                {vehiclePopup.currentStopName}
              </div>
            )}
          </div>
        </Popup>
      )}
    </Map>
      {onToggleFullscreen && (
        <FullscreenButton isFullscreen={isFullscreen} onClick={onToggleFullscreen} />
      )}
    </div>
  );
}
