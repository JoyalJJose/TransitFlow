import { useMemo, useState, useCallback, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import Map, {
  Source,
  Layer,
  Popup,
  NavigationControl,
} from 'react-map-gl/mapbox';
import 'mapbox-gl/dist/mapbox-gl.css';

const MAPBOX_TOKEN = import.meta.env.VITE_MAPBOX_ACCESS_TOKEN;
const DUBLIN_CENTER = { lat: 53.3447, lng: -6.291 };
const DEFAULT_ZOOM = 14;

let _savedViewState = null;

export const ROUTE_COLORS = {
  '5552_130286': '#7c3aed',
  '5552_130287': '#6366f1',
  '5552_130289': '#3b82f6',
  '5552_130290': '#0ea5e9',
  '5552_130207': '#06b6d4',
  '5552_130209': '#14b8a6',
  '5552_130210': '#8b5cf6',
  '5552_130214': '#a855f7',
  '5552_130216': '#d946ef',
  '5552_130218': '#ec4899',
  '5552_130307': '#f472b6',
  '5552_130222': '#818cf8',
};

const ROUTE_COLOR_DEFAULT = '#9063ff';

function getRouteColor(routeId) {
  return ROUTE_COLORS[routeId] || ROUTE_COLOR_DEFAULT;
}

function busynessColor(count) {
  if (count >= 15) return '#ef4444';
  if (count >= 6) return '#f59e0b';
  return '#22c55e';
}

/* ---------- Directions API with caching ---------- */

function simpleHash(str) {
  let h = 0;
  for (let i = 0; i < str.length; i++) {
    h = ((h << 5) - h + str.charCodeAt(i)) | 0;
  }
  return (h >>> 0).toString(36);
}

async function fetchRouteGeometry(coords, token) {
  if (coords.length < 2) return { type: 'LineString', coordinates: coords };

  const raw = coords.map((c) => `${c[0].toFixed(5)},${c[1].toFixed(5)}`).join('|');
  const key = `tf_dir_${simpleHash(raw)}`;

  try {
    const cached = sessionStorage.getItem(key);
    if (cached) return JSON.parse(cached);
  } catch { /* ignore */ }

  const MAX_WAYPOINTS = 25;
  const allSegments = [];

  for (let i = 0; i < coords.length; i += MAX_WAYPOINTS - 1) {
    const chunk = coords.slice(i, i + MAX_WAYPOINTS);
    if (chunk.length < 2) break;

    const coordStr = chunk.map((c) => `${c[0]},${c[1]}`).join(';');
    const url = `https://api.mapbox.com/directions/v5/mapbox/driving/${coordStr}?geometries=geojson&overview=full&access_token=${token}`;

    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const routeCoords = data.routes?.[0]?.geometry?.coordinates;
      if (routeCoords?.length) {
        allSegments.push(...(allSegments.length ? routeCoords.slice(1) : routeCoords));
      } else {
        allSegments.push(...chunk);
      }
    } catch {
      allSegments.push(...chunk);
    }
  }

  const geometry = { type: 'LineString', coordinates: allSegments };
  try { sessionStorage.setItem(key, JSON.stringify(geometry)); } catch { /* full */ }
  return geometry;
}

/* ---------- Component helpers ---------- */

function TypeBadge({ type }) {
  const label = type === 'luas' ? 'Luas' : 'Bus';
  return <span className={`map-popup-badge map-popup-badge--${type}`}>{label}</span>;
}

function MapLegend() {
  const [collapsed, setCollapsed] = useState(false);

  if (collapsed) {
    return (
      <button
        type="button"
        className="map-legend-toggle"
        onClick={() => setCollapsed(false)}
        title="Show legend"
      >
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
          <circle cx="4" cy="4" r="2" fill="#22c55e" />
          <circle cx="12" cy="4" r="2" fill="#eab308" />
          <circle cx="4" cy="12" r="2" fill="#f97316" />
          <circle cx="12" cy="12" r="2" fill="#ef4444" />
        </svg>
      </button>
    );
  }

  return (
    <div className="map-legend" role="group" aria-label="Map legend">
      <button
        type="button"
        className="map-legend-close"
        onClick={() => setCollapsed(true)}
        title="Hide legend"
        aria-label="Hide legend"
      >
        ×
      </button>

      <div className="map-legend-section">
        <span className="map-legend-section-title">Stops (waiting)</span>
        <div className="map-legend-row map-legend-row--inline">
          <span className="map-legend-chip">
            <span className="map-legend-swatch map-legend-swatch--dot" style={{ background: '#22c55e' }} />
            &lt;6
          </span>
          <span className="map-legend-chip">
            <span className="map-legend-swatch map-legend-swatch--dot" style={{ background: '#f59e0b' }} />
            6–14
          </span>
          <span className="map-legend-chip">
            <span className="map-legend-swatch map-legend-swatch--dot" style={{ background: '#ef4444' }} />
            15+
          </span>
          <span className="map-legend-chip">
            <span className="map-legend-swatch map-legend-swatch--dot map-legend-swatch--inactive" />
            Off
          </span>
        </div>
      </div>

      <div className="map-legend-section">
        <span className="map-legend-section-title">Vehicles (occupancy)</span>
        <div className="map-legend-row">
          <span className="map-legend-swatch map-legend-swatch--dot" style={{ background: '#22c55e' }} />
          <span>&lt; 40%</span>
        </div>
        <div className="map-legend-row">
          <span className="map-legend-swatch map-legend-swatch--dot" style={{ background: '#eab308' }} />
          <span>40 – 70%</span>
        </div>
        <div className="map-legend-row">
          <span className="map-legend-swatch map-legend-swatch--dot" style={{ background: '#f97316' }} />
          <span>70 – 90%</span>
        </div>
        <div className="map-legend-row">
          <span className="map-legend-swatch map-legend-swatch--dot" style={{ background: '#ef4444' }} />
          <span>90%+</span>
        </div>
      </div>
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

/* ---------- Main MapView Component ---------- */

export default function MapView({
  stops = [],
  stopWaitCounts = [],
  vehicles = [],
  routes = [],
  theme = 'light',
  isFullscreen = false,
  onToggleFullscreen,
}) {
  const dark = theme === 'dark';
  const navigate = useNavigate();

  const [cursor, setCursor] = useState('');
  const [stopPopup, setStopPopup] = useState(null);
  const [vehiclePopup, setVehiclePopup] = useState(null);

  const waitMap = useMemo(() => {
    const m = {};
    stopWaitCounts.forEach((s) => { m[s.stopId] = s.count; });
    return m;
  }, [stopWaitCounts]);

  const stopLookup = useMemo(() => {
    const m = {};
    stops.forEach((s) => { m[s.id] = s; });
    return m;
  }, [stops]);

  /* ---- Active routes (those with vehicles) ---- */
  const activeRouteIds = useMemo(() => {
    const ids = new Set();
    for (const v of vehicles) ids.add(v.routeId);
    return ids;
  }, [vehicles]);

  const activeRoutes = useMemo(
    () => routes.filter((r) => activeRouteIds.has(r.id)),
    [routes, activeRouteIds],
  );

  const activeStopIds = useMemo(() => {
    const s = new Set();
    for (const r of activeRoutes) {
      for (const sid of (r.stopIds ?? [])) s.add(sid);
    }
    return s;
  }, [activeRoutes]);

  /* ---- Map of stopId -> list of routes serving it ---- */
  const stopToRoutes = useMemo(() => {
    const m = {};
    for (const r of activeRoutes) {
      for (const sid of (r.stopIds ?? [])) {
        if (!m[sid]) m[sid] = [];
        m[sid].push(r);
      }
    }
    return m;
  }, [activeRoutes]);

  const handleMove = useCallback((evt) => {
    _savedViewState = evt.viewState;
  }, []);

  /* ---- Route geometry fetching ---- */
  const [routeGeometries, setRouteGeometries] = useState({});

  const activeRouteKey = useMemo(
    () => [...activeRouteIds].sort().join(','),
    [activeRouteIds],
  );

  useEffect(() => {
    if (!activeRouteKey || !stops.length || !MAPBOX_TOKEN) return;

    const currentIds = activeRouteKey.split(',');
    const currentRoutes = routes.filter((r) => currentIds.includes(r.id));
    const lookup = {};
    stops.forEach((s) => { lookup[s.id] = s; });

    let cancelled = false;
    async function loadGeometries() {
      const results = {};
      await Promise.all(
        currentRoutes.map(async (route) => {
          const coords = (route.stopIds ?? [])
            .map((sid) => {
              const st = lookup[sid];
              return st ? [st.lng, st.lat] : null;
            })
            .filter(Boolean);
          if (coords.length < 2) return;
          const geometry = await fetchRouteGeometry(coords, MAPBOX_TOKEN);
          if (!cancelled) results[route.id] = geometry;
        }),
      );
      if (!cancelled) setRouteGeometries(results);
    }

    loadGeometries();
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeRouteKey]);

  /* ---- Route lines GeoJSON ---- */
  const routeLinesGeoJSON = useMemo(() => ({
    type: 'FeatureCollection',
    features: activeRoutes
      .filter((r) => routeGeometries[r.id])
      .map((r) => ({
        type: 'Feature',
        geometry: routeGeometries[r.id],
        properties: { routeId: r.id },
      })),
  }), [activeRoutes, routeGeometries]);

  /* ---- Route line paint ---- */
  const routeLinePaint = useMemo(() => {
    const colorExpr = ['match', ['get', 'routeId']];
    for (const r of activeRoutes) {
      colorExpr.push(r.id, getRouteColor(r.id));
    }
    colorExpr.push(ROUTE_COLOR_DEFAULT);
    return {
      'line-color': colorExpr,
      'line-width': 3,
      'line-opacity': 0.6,
    };
  }, [activeRoutes]);

  /* ---- Active stops GeoJSON ---- */
  const activeStopsGeoJSON = useMemo(() => ({
    type: 'FeatureCollection',
    features: stops
      .filter((s) => activeStopIds.has(s.id))
      .map((s) => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [s.lng, s.lat] },
        properties: { id: s.id, count: waitMap[s.id] ?? 0 },
      })),
  }), [stops, activeStopIds, waitMap]);

  /* ---- Inactive stops GeoJSON ---- */
  const inactiveStopsGeoJSON = useMemo(() => ({
    type: 'FeatureCollection',
    features: stops
      .filter((s) => !activeStopIds.has(s.id))
      .map((s) => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [s.lng, s.lat] },
        properties: { id: s.id },
      })),
  }), [stops, activeStopIds]);

  /* ---- Active stop circle paint (traffic-light, zoom-aware) ---- */
  const activeStopPaint = useMemo(() => ({
    'circle-radius': [
      'interpolate', ['linear'], ['zoom'],
      10, [
        'interpolate', ['linear'], ['get', 'count'],
        0, 1.5,
        10, 2,
        20, 2.5,
        40, 3,
      ],
      14, [
        'interpolate', ['linear'], ['get', 'count'],
        0, 4,
        10, 5.5,
        20, 7,
        40, 8.5,
      ],
      17, [
        'interpolate', ['linear'], ['get', 'count'],
        0, 7,
        10, 9,
        20, 11,
        40, 13,
      ],
    ],
    'circle-color': [
      'step', ['get', 'count'],
      '#22c55e',
      6, '#f59e0b',
      15, '#ef4444',
    ],
    'circle-stroke-width': 1.5,
    'circle-stroke-color': '#ffffff',
    'circle-opacity': 0.9,
  }), []);

  /* ---- Inactive stop circle paint (greyed out, zoom-aware) ---- */
  const inactiveStopPaint = useMemo(() => ({
    'circle-radius': [
      'interpolate', ['linear'], ['zoom'],
      10, 0.8,
      14, 2,
      17, 3.5,
    ],
    'circle-color': dark ? '#666' : '#aaa',
    'circle-opacity': 0.3,
    'circle-stroke-width': 0,
  }), [dark]);

  /* ---- Vehicles GeoJSON ---- */
  const vehiclesGeoJSON = useMemo(() => ({
    type: 'FeatureCollection',
    features: vehicles
      .filter((v) => v.lat != null && v.lng != null)
      .map((v) => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [v.lng, v.lat] },
        properties: {
          id: v.id,
          routeId: v.routeId,
          routeName: v.routeName,
          type: v.type,
          occupancy: v.currentOccupancyPercent,
          passengers: v.passengerCount,
          capacity: v.capacity,
          state: v.state,
          currentStopName: v.currentStopName || '',
          label: v.routeName?.replace('Route ', '').replace('LUAS ', '') || '',
        },
      })),
  }), [vehicles]);

  /* ---- Vehicle layer paint ---- */
  const vehicleGlowPaint = useMemo(() => ({
    'circle-radius': 18,
    'circle-color': [
      'step', ['get', 'occupancy'],
      '#22c55e',
      40, '#eab308',
      70, '#f97316',
      90, '#ef4444',
    ],
    'circle-opacity': 0.25,
    'circle-stroke-width': 0,
  }), []);

  const vehicleCirclePaint = useMemo(() => ({
    'circle-radius': 9,
    'circle-color': [
      'step', ['get', 'occupancy'],
      '#22c55e',
      40, '#eab308',
      70, '#f97316',
      90, '#ef4444',
    ],
    'circle-stroke-width': 2.5,
    'circle-stroke-color': '#ffffff',
    'circle-opacity': 1,
  }), []);

  const vehicleLabelLayout = useMemo(() => ({
    'text-field': ['get', 'label'],
    'text-size': 10,
    'text-font': ['DIN Pro Bold', 'Arial Unicode MS Bold'],
    'text-offset': [0, 2],
    'text-anchor': 'top',
    'text-allow-overlap': true,
    'text-ignore-placement': true,
  }), []);

  const vehicleLabelPaint = useMemo(() => ({
    'text-color': dark ? '#e0d8f0' : '#392061',
    'text-halo-color': dark ? '#1a1b2e' : '#ffffff',
    'text-halo-width': 1.5,
  }), [dark]);

  /* ---- Click handler (stops + vehicles) ---- */
  const handleMapClick = useCallback(
    (e) => {
      const features = e.features;
      if (!features || !features.length) {
        setStopPopup(null);
        setVehiclePopup(null);
        return;
      }

      const feature = features[0];
      const layerId = feature.layer?.id;

      if (layerId === 'vehicle-circles') {
        const p = feature.properties;
        setStopPopup(null);
        setVehiclePopup({
          lng: feature.geometry.coordinates[0],
          lat: feature.geometry.coordinates[1],
          routeName: p.routeName,
          type: p.type,
          occupancy: p.occupancy,
          passengers: p.passengers,
          capacity: p.capacity,
          state: p.state,
          currentStopName: p.currentStopName,
        });
        return;
      }

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

  if (!MAPBOX_TOKEN) {
    return (
      <div className="map-placeholder">
        <p>
          Set <code>VITE_MAPBOX_ACCESS_TOKEN</code> in <code>.env</code> to enable the map.
        </p>
      </div>
    );
  }

  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <Map
        initialViewState={_savedViewState ?? {
          latitude: DUBLIN_CENTER.lat,
          longitude: DUBLIN_CENTER.lng,
          zoom: DEFAULT_ZOOM,
        }}
        onMove={handleMove}
        style={{ width: '100%', height: '100%' }}
        mapStyle={dark ? 'mapbox://styles/mapbox/dark-v11' : 'mapbox://styles/mapbox/light-v11'}
        mapboxAccessToken={MAPBOX_TOKEN}
        attributionControl={false}
        logoPosition="top-left"
        interactiveLayerIds={['active-stop-circles', 'vehicle-circles']}
        onClick={handleMapClick}
        onMouseEnter={() => setCursor('pointer')}
        onMouseLeave={() => setCursor('')}
        cursor={cursor}
      >
        <NavigationControl position="bottom-right" showCompass={false} />

        {/* ---- Route polylines (bottom layer) ---- */}
        <Source id="route-lines" type="geojson" data={routeLinesGeoJSON}>
          <Layer
            id="route-line-layer"
            type="line"
            paint={routeLinePaint}
            layout={{ 'line-cap': 'round', 'line-join': 'round' }}
          />
        </Source>

        {/* ---- Inactive stop dots (greyed out, non-interactive) ---- */}
        <Source id="inactive-stops" type="geojson" data={inactiveStopsGeoJSON}>
          <Layer id="inactive-stop-circles" type="circle" paint={inactiveStopPaint} />
        </Source>

        {/* ---- Active stops (traffic-light circles) ---- */}
        <Source id="active-stops" type="geojson" data={activeStopsGeoJSON}>
          <Layer id="active-stop-circles" type="circle" paint={activeStopPaint} />
        </Source>

        {/* ---- Vehicle glow + dots + labels ---- */}
        <Source id="vehicles" type="geojson" data={vehiclesGeoJSON}>
          <Layer id="vehicle-glow" type="circle" paint={vehicleGlowPaint} />
          <Layer id="vehicle-circles" type="circle" paint={vehicleCirclePaint} />
          <Layer id="vehicle-labels" type="symbol" layout={vehicleLabelLayout} paint={vehicleLabelPaint} />
        </Source>

        {/* ---- Vehicle popup ---- */}
        {vehiclePopup && (
          <Popup
            longitude={vehiclePopup.lng}
            latitude={vehiclePopup.lat}
            anchor="bottom"
            closeOnClick={false}
            onClose={() => setVehiclePopup(null)}
            className="map-popup"
            offset={[0, -8]}
          >
            <div className="map-popup-inner">
              <div className="map-popup-title">{vehiclePopup.routeName}</div>
              <TypeBadge type={vehiclePopup.type} />
              <div className="map-popup-occ-track">
                <div
                  className="map-popup-occ-fill"
                  style={{
                    width: `${Math.min(vehiclePopup.occupancy, 100)}%`,
                    background: vehiclePopup.occupancy >= 90 ? '#ef4444'
                      : vehiclePopup.occupancy >= 70 ? '#f97316'
                      : vehiclePopup.occupancy >= 40 ? '#eab308' : '#22c55e',
                  }}
                />
              </div>
              <div className="map-popup-stat-row">
                <div className="map-popup-stat">
                  <span className="map-popup-stat-value">{vehiclePopup.occupancy}%</span>
                  <span className="map-popup-stat-label">occupancy</span>
                </div>
                <div className="map-popup-stat">
                  <span className="map-popup-stat-value">{vehiclePopup.passengers}/{vehiclePopup.capacity}</span>
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

        {/* ---- Stop popup ---- */}
        {stopPopup && (
          <Popup
            longitude={stopPopup.lng}
            latitude={stopPopup.lat}
            anchor="bottom"
            closeOnClick={false}
            onClose={() => setStopPopup(null)}
            className="map-popup"
            offset={[0, -10]}
          >
            {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions */}
            <div className="map-popup-inner" onClick={(e) => e.stopPropagation()}>
              <div className="map-popup-title">{stopPopup.stop.name}</div>
              <TypeBadge type={stopPopup.stop.type} />

              <div className="map-popup-stat">
                <span
                  className="stop-popup-count-badge"
                  style={{ background: busynessColor(stopPopup.count) }}
                >
                  {stopPopup.count}
                </span>
                <span className="map-popup-stat-label">waiting</span>
              </div>

              {stopToRoutes[stopPopup.stop.id]?.length > 0 && (
                <div className="stop-popup-routes">
                  {stopToRoutes[stopPopup.stop.id].map((r) => (
                    <button
                      key={r.id}
                      className="stop-popup-route-pill stop-popup-route-pill--clickable"
                      onClick={(e) => {
                        e.stopPropagation();
                        navigate(`/analytics?route=${r.id}&stop=${stopPopup.stop.id}`);
                      }}
                    >
                      <span className="stop-popup-route-dot" style={{ background: getRouteColor(r.id) }} />
                      {r.name}
                    </button>
                  ))}
                </div>
              )}

              <button
                className="stop-popup-analytics-btn"
                onClick={(e) => {
                  e.stopPropagation();
                  navigate(`/analytics?stop=${stopPopup.stop.id}`);
                }}
              >
                View in Analytics
              </button>
            </div>
          </Popup>
        )}
      </Map>
      {onToggleFullscreen && (
        <FullscreenButton isFullscreen={isFullscreen} onClick={onToggleFullscreen} />
      )}
      <MapLegend />
    </div>
  );
}
