import { Fragment, useEffect, useMemo, useState } from "react";
import {
  Circle,
  CircleMarker,
  MapContainer,
  Polyline,
  TileLayer,
  Tooltip,
  useMap,
  useMapEvents,
} from "react-leaflet";

import { heatLayer } from "@/lib/leafletHeat";
import { aqiColor } from "@/lib/aqi";
import {
  HEAT_GRADIENT,
  heatPoints,
  hexLerp,
  hotspotRadius,
  MAP_CENTER,
  MAP_ZOOM,
  type MapLayers,
  type MapStyle,
} from "@/lib/mapgeo";
import type { IndustryRecord, PlumeVectorsResponse, StationReading } from "@/lib/types";
import { classifyIndustryTier } from "@/lib/types";
import { useTranslation } from "@/i18n";
import { getTranslatedStationName, type StationLang } from "@/lib/stationTranslations";

/**
 * Online renderer — a real interactive Leaflet map on keyless raster tiles.
 * Lazy-loaded by StationMap so Leaflet's bundle is only fetched when actually
 * shown (offline mode never pays for it). Every marker is a vector CircleMarker
 * or a leaflet.heat canvas — no external marker-image assets are requested, so
 * the console CSP only needs the tile hosts under img-src.
 */

interface MapLeafletProps {
  stations: StationReading[];
  plume: PlumeVectorsResponse | null;
  industries?: IndustryRecord[];
  layers: MapLayers;
  style: MapStyle;
  selectedUid: string | null;
  onSelect: (uid: string | null) => void;
  onTileError: () => void;
}

// Custom panes keep the layer order deterministic: heat (overlayPane, 400) sits
// beneath the station glow/dots, industries, and fire hotspots regardless of mount timing.
function Panes() {
  const map = useMap();
  useEffect(() => {
    const spec: Array<[string, string]> = [
      ["ncrGlow", "440"],
      ["ncrStations", "450"],
      ["ncrIndustries", "455"],
      ["ncrFires", "460"],
    ];
    for (const [name, z] of spec) {
      const pane = map.getPane(name) ?? map.createPane(name);
      pane.style.zIndex = z;
    }
  }, [map]);
  return null;
}

function HeatLayer({ points }: { points: Array<[number, number, number]> }) {
  const map = useMap();
  useEffect(() => {
    const layer = heatLayer(points, {
      radius: 34,
      blur: 22,
      minOpacity: 0.28,
      max: 1,
      maxZoom: 11,
      gradient: HEAT_GRADIENT,
    });
    layer.addTo(map);
    return () => {
      map.removeLayer(layer);
    };
  }, [map, points]);
  return null;
}

/** Recenter only when the selected station is off-screen — never fight the user. */
function PanToSelected({ station }: { station: StationReading | null }) {
  const map = useMap();
  useEffect(() => {
    if (station && !map.getBounds().contains([station.lat, station.lon])) {
      map.panTo([station.lat, station.lon], { animate: true });
    }
  }, [map, station]);
  return null;
}

function ClearOnBackground({ onClear }: { onClear: () => void }) {
  useMapEvents({ click: () => onClear() });
  return null;
}

function AutoResize() {
  const map = useMap();
  useEffect(() => {
    const ro = new ResizeObserver(() => map.invalidateSize());
    ro.observe(map.getContainer());
    return () => ro.disconnect();
  }, [map]);
  return null;
}

/**
 * High-performance Industry Markers Layer
 * ---------------------------------------
 * Features:
 * 1. Progressive Radial Ingress Sweep: On layer/tier change, nodes bloom smoothly from Central Delhi outward.
 * 2. Animated Zoom Scatter & Bloom: As user zooms in, factories smoothly fan out and scatter from their cluster centroids to their exact pinpoint GPS coordinates.
 * 3. Zoom-Adaptive Density (LOD): Small elegant micro-dots at low zoom preventing clumsy blob overlap.
 * 4. Text-wrapping & Glassmorphism Tooltip Fix: Prevents text clipping and guarantees clean responsive word breaks.
 */
function IndustryMarkersLayer({
  industries,
  active,
}: {
  industries: IndustryRecord[];
  active: boolean;
}) {
  const map = useMap();
  const [zoom, setZoom] = useState(() => map.getZoom());
  const [progress, setProgress] = useState(0);
  const [dispersion, setDispersion] = useState(() => {
    const z = map.getZoom();
    return z <= 10 ? 0.35 : z === 11 ? 0.65 : z === 12 ? 0.85 : 1.0;
  });

  // Smoothly animate dispersion when zooming
  useMapEvents({
    zoomstart: () => {
      // Begin spring transition
    },
    zoomend: () => {
      const newZoom = map.getZoom();
      setZoom(newZoom);
      const targetDispersion = newZoom <= 10 ? 0.35 : newZoom === 11 ? 0.65 : newZoom === 12 ? 0.85 : 1.0;
      
      let start: number | null = null;
      const duration = 400; // 400ms smooth scatter animation
      const startDisp = dispersion;

      const animateScatter = (timestamp: number) => {
        if (!start) start = timestamp;
        const elapsed = timestamp - start;
        const p = Math.min(1, elapsed / duration);
        // Ease-out cubic
        const eased = 1 - Math.pow(1 - p, 3);
        setDispersion(startDisp + (targetDispersion - startDisp) * eased);
        if (p < 1) {
          requestAnimationFrame(animateScatter);
        }
      };
      requestAnimationFrame(animateScatter);
    },
  });

  // Calculate distance from central Delhi (28.6139, 77.2090) and local zone grid centroids
  const sortedWithDist = useMemo(() => {
    const centerLat = 28.6139;
    const centerLon = 77.2090;
    const list = industries.map((ind) => {
      const d = Math.hypot(ind.latitude - centerLat, ind.longitude - centerLon);
      // Compute localized cluster grid center (~1.5 km grid cell)
      const gridLat = Math.round(ind.latitude / 0.016) * 0.016;
      const gridLon = Math.round(ind.longitude / 0.016) * 0.016;
      return { ind, dist: d, gridLat, gridLon };
    });
    // Sort by radial distance from center
    list.sort((a, b) => a.dist - b.dist);
    const maxDist = list.length > 0 ? list[list.length - 1].dist : 1;
    return { list, maxDist: Math.max(0.01, maxDist) };
  }, [industries]);

  // Progressive radial sweep animation on mount or when tier/data changes
  useEffect(() => {
    if (!active || industries.length === 0) {
      setProgress(0);
      return;
    }

    let start: number | null = null;
    const duration = 500; // 500ms progressive radial sweep
    let rafId: number;

    const step = (timestamp: number) => {
      if (!start) start = timestamp;
      const elapsed = timestamp - start;
      const p = Math.min(1, elapsed / duration);
      // Ease-out cubic curve
      const eased = 1 - Math.pow(1 - p, 3);
      setProgress(eased);

      if (p < 1) {
        rafId = requestAnimationFrame(step);
      }
    };

    setProgress(0.05);
    rafId = requestAnimationFrame(step);

    return () => {
      if (rafId) cancelAnimationFrame(rafId);
    };
  }, [active, industries]);

  if (!active || industries.length === 0) return null;

  // Zoom-adaptive density scaling (LOD)
  const isZoomedOut = zoom <= 10;
  const isMidZoom = zoom > 10 && zoom <= 12;

  const baseRadiusTier1 = isZoomedOut ? 2.4 : isMidZoom ? 4.0 : 5.6;
  const baseRadiusTier2 = isZoomedOut ? 1.9 : isMidZoom ? 3.2 : 4.6;
  const baseRadiusTier3 = isZoomedOut ? 1.5 : isMidZoom ? 2.4 : 3.8;
  const anchorRadius = isZoomedOut ? 5.2 : isMidZoom ? 7.2 : 9.0;

  const baseOpacity = isZoomedOut ? 0.65 : isMidZoom ? 0.85 : 0.95;
  const strokeW = isZoomedOut ? 0.5 : 1;

  // Reveal items within current radial threshold
  const visibleThreshold = sortedWithDist.maxDist * Math.max(0.06, progress);
  const visibleItems = sortedWithDist.list.filter(
    (item) => item.dist <= visibleThreshold || item.dist <= 0.035,
  );

  return (
    <>
      {visibleItems.map(({ ind, gridLat, gridLon }, i) => {
        const tierInfo = classifyIndustryTier(ind);
        const isAnchor =
          tierInfo.tier === 1 &&
          (ind.category === "power" ||
            ind.name.toLowerCase().includes("power") ||
            ind.name.toLowerCase().includes("waste to energy") ||
            ind.name.toLowerCase().includes("wte"));

        const r = isAnchor
          ? anchorRadius
          : tierInfo.tier === 1
            ? baseRadiusTier1
            : tierInfo.tier === 2
              ? baseRadiusTier2
              : baseRadiusTier3;

        const strokeColor = isAnchor
          ? "#ffffff"
          : tierInfo.tier === 1
            ? "#7f1d1d"
            : tierInfo.tier === 2
              ? "#7c2d12"
              : "#581c87";

        // Calculated animated position (fans out / scatters to exact coordinates as zoom increases)
        const curLat = gridLat + (ind.latitude - gridLat) * dispersion;
        const curLon = gridLon + (ind.longitude - gridLon) * dispersion;

        return (
          <Fragment key={ind.id ? `ind-${ind.id}` : `ind-${i}`}>
            {/* Soft ambient glow halo for Anchor Power & WTE plants */}
            {isAnchor && (
              <CircleMarker
                center={[curLat, curLon]}
                radius={r * 1.7}
                pane="ncrGlow"
                interactive={false}
                pathOptions={{
                  stroke: false,
                  fillColor: tierInfo.color,
                  fillOpacity: 0.25,
                }}
              />
            )}

            <CircleMarker
              center={[curLat, curLon]}
              radius={r}
              pane="ncrIndustries"
              pathOptions={{
                color: strokeColor,
                weight: isAnchor ? 2 : strokeW,
                fillColor: tierInfo.color,
                fillOpacity: isAnchor ? 1 : baseOpacity,
              }}
            >
              <Tooltip direction="top" offset={[0, -6]} className="map__industryTooltip">
                <div
                  style={{
                    padding: "8px 10px",
                    fontSize: "11px",
                    lineHeight: "1.45",
                    width: "250px",
                    maxWidth: "260px",
                    boxSizing: "border-box",
                    wordBreak: "break-word",
                    overflowWrap: "anywhere",
                    whiteSpace: "normal",
                    background: "rgba(15, 23, 42, 0.96)",
                    borderRadius: "7px",
                    border: `1px solid ${tierInfo.color}80`,
                    boxShadow: "0 8px 26px rgba(0,0,0,0.6)",
                    backdropFilter: "blur(8px)",
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      marginBottom: "5px",
                    }}
                  >
                    <span
                      style={{
                        fontSize: "9.5px",
                        fontWeight: 700,
                        letterSpacing: "0.05em",
                        padding: "2px 6px",
                        borderRadius: "4px",
                        background: `${tierInfo.color}25`,
                        color: tierInfo.color,
                        border: `1px solid ${tierInfo.color}50`,
                      }}
                    >
                      {tierInfo.badge}
                    </span>
                  </div>

                  <strong
                    style={{
                      color: "#f8fafc",
                      fontSize: "11.5px",
                      lineHeight: "1.35",
                      display: "block",
                      marginBottom: "4px",
                      wordBreak: "break-word",
                      overflowWrap: "anywhere",
                      whiteSpace: "normal",
                    }}
                  >
                    {isAnchor ? "⚡ " : "🏭 "}
                    {ind.name}
                  </strong>

                  <div
                    style={{
                      color: "#cbd5e1",
                      fontSize: "11px",
                      marginBottom: "4px",
                      wordBreak: "break-word",
                      overflowWrap: "anywhere",
                    }}
                  >
                    <strong style={{ color: "#94a3b8" }}>Sector:</strong> {ind.sector || ind.category || "Industrial Source"}
                  </div>

                  <div
                    style={{
                      fontSize: "10px",
                      color: "#fca5a5",
                      marginBottom: "4px",
                      background: "rgba(0,0,0,0.35)",
                      padding: "3px 5px",
                      borderRadius: "3px",
                      wordBreak: "break-word",
                      overflowWrap: "anywhere",
                    }}
                  >
                    <strong style={{ color: "#f87171" }}>Key Pollutants:</strong> {tierInfo.pollutants}
                  </div>

                  <div
                    style={{
                      color: "#38bdf8",
                      fontSize: "10px",
                      wordBreak: "break-word",
                      overflowWrap: "anywhere",
                    }}
                  >
                    📍 {ind.city}, {ind.state} {ind.address ? `• ${ind.address.split(",")[0]}` : ""}
                  </div>
                </div>
              </Tooltip>
            </CircleMarker>
          </Fragment>
        );
      })}
    </>
  );
}

export default function MapLeaflet({
  stations,
  plume,
  industries = [],
  layers,
  style,
  selectedUid,
  onSelect,
  onTileError,
}: MapLeafletProps) {
  const { language } = useTranslation();
  const points = useMemo(() => heatPoints(stations), [stations]);
  const selected = useMemo(
    () => stations.find((s) => s.uid === selectedUid) ?? null,
    [stations, selectedUid],
  );

  return (
    <MapContainer
      className="map__leaflet"
      center={MAP_CENTER}
      zoom={MAP_ZOOM}
      minZoom={6}
      maxZoom={style.maxZoom}
      scrollWheelZoom
      worldCopyJump={false}
    >
      <TileLayer
        key={style.id}
        url={style.url}
        attribution={style.attribution}
        maxZoom={style.maxZoom}
        eventHandlers={{ tileerror: onTileError }}
      />

      <Panes />
      <AutoResize />
      <ClearOnBackground onClear={() => onSelect(null)} />
      <PanToSelected station={selected} />

      {layers.heatmap && points.length ? <HeatLayer points={points} /> : null}

      {/* Delhi anchor + 100/200/300 km reference rings */}
      {[100000, 200000, 300000].map((r) => (
        <Circle
          key={r}
          center={MAP_CENTER}
          radius={r}
          pathOptions={{ color: "#8CA3B6", weight: 1, opacity: 0.22, fill: false, dashArray: "4 5" }}
        />
      ))}
      <CircleMarker
        center={MAP_CENTER}
        radius={5}
        pathOptions={{ color: "#E9F0F6", weight: 2, fillColor: "#0A1119", fillOpacity: 1 }}
      >
        <Tooltip permanent direction="right" className="map__delhiTip" offset={[6, 0]}>
          DELHI
        </Tooltip>
      </CircleMarker>

      {/* Stubble-plume trajectories + FRP-scaled fire hotspots */}
      {layers.fires && plume
        ? plume.plumes.map((pl, i) =>
            pl.trajectory.length >= 2 ? (
              <Polyline
                key={`traj-${i}`}
                positions={pl.trajectory}
                pathOptions={{ color: "#F2892F", weight: 1.4, opacity: 0.5 }}
              />
            ) : null,
          )
        : null}
      {layers.fires && plume
        ? plume.hotspots.map((hs, i) => (
            <CircleMarker
              key={`fire-${i}`}
              center={[hs.lat, hs.lon]}
              radius={hotspotRadius(hs.frp_mw)}
              pane="ncrFires"
              pathOptions={{
                stroke: false,
                fillColor: hexLerp("#F2892F", "#E8503C", Math.min(1, hs.frp_mw / 90)),
                fillOpacity: 0.85,
              }}
            >
              <Tooltip>
                {hs.source_state} · FRP {hs.frp_mw.toFixed(0)} MW
              </Tooltip>
            </CircleMarker>
          ))
        : null}

      {/* Delhi-Only Industrial Facilities with Progressive Sweep & Zoom-Adaptive LOD */}
      <IndustryMarkersLayer
        industries={industries}
        active={Boolean(layers.industries && industries.length > 0)}
      />

      {/* Stations: a soft AQI "plume" glow behind a clickable dot */}
      {layers.stations
        ? stations.map((s) => {
            const c = aqiColor(s.aqi);
            const isSel = s.uid === selectedUid;
            const glowR = 10 + (Math.min(500, s.aqi) / 500) * 16;
            return (
              <Fragment key={s.uid}>
                <CircleMarker
                  center={[s.lat, s.lon]}
                  radius={glowR}
                  pane="ncrGlow"
                  interactive={false}
                  pathOptions={{ stroke: false, fillColor: c, fillOpacity: 0.28 }}
                />
                <CircleMarker
                  center={[s.lat, s.lon]}
                  radius={isSel ? 7 : 4.5}
                  pane="ncrStations"
                  bubblingMouseEvents={false}
                  pathOptions={{
                    color: "#E9F0F6",
                    weight: isSel ? 2 : 1,
                    fillColor: c,
                    fillOpacity: 1,
                  }}
                  eventHandlers={{ click: () => onSelect(s.uid) }}
                >
                  <Tooltip direction="top" offset={[0, -8]} className="map__stationTip">
                    <div style={{ padding: "4px 6px", minWidth: "170px", fontFamily: "var(--font-sans, system-ui)", fontSize: "11px", lineHeight: "1.4" }}>
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "8px", marginBottom: "4px" }}>
                        <strong style={{ color: "#f8fafc", fontSize: "12px" }}>
                          {getTranslatedStationName(s.name, (language as StationLang) || "en")}
                        </strong>
                        <span style={{ padding: "1px 6px", borderRadius: "4px", background: `${c}25`, color: c, border: `1px solid ${c}60`, fontWeight: 700, fontSize: "10px" }}>
                          {Math.round(s.aqi)}
                        </span>
                      </div>
                      <div style={{ color: c, fontWeight: 600, fontSize: "10.5px", marginBottom: "4px" }}>
                        {s.category}
                      </div>
                      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "3px 6px", fontSize: "10px", color: "#cbd5e1", borderTop: "1px solid rgba(255,255,255,0.1)", paddingTop: "4px" }}>
                        {s.pollutants?.["PM2.5"] != null && <div>PM2.5: <span style={{ color: "#f8fafc" }}>{s.pollutants["PM2.5"]}</span></div>}
                        {s.pollutants?.["PM10"] != null && <div>PM10: <span style={{ color: "#f8fafc" }}>{s.pollutants["PM10"]}</span></div>}
                        {s.weather?.temperature != null && <div>Temp: <span style={{ color: "#f8fafc" }}>{s.weather.temperature}°C</span></div>}
                        {s.weather?.wind_speed != null && <div>Wind: <span style={{ color: "#f8fafc" }}>{s.weather.wind_speed} km/h</span></div>}
                      </div>
                      <div style={{ fontSize: "9px", color: "#94a3b8", marginTop: "4px" }}>
                        IQAir Live AQI · WeatherAPI
                      </div>
                    </div>
                  </Tooltip>
                </CircleMarker>
              </Fragment>
            );
          })
        : null}
    </MapContainer>
  );
}

