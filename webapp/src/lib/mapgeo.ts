/**
 * Shared map geometry, basemap styles, and pure helpers used by both map
 * renderers (Leaflet online, Canvas offline) and the side info box.
 *
 * The domain bounds and the Delhi anchor are carried over verbatim from the
 * prototype's plume map so the offline schematic frames the same area the
 * physics model reasons about.
 */

import type { StationReading } from "./types";

// ── Domain (Punjab/Haryana stubble belt → Delhi) ─────────────────────────────
export const DOMAIN = { lon0: 73.6, lon1: 78.4, lat0: 27.9, lat1: 31.7 } as const;
export const DELHI = { lat: 28.61, lon: 77.21 } as const;

/** Leaflet view defaults. */
export const MAP_CENTER: [number, number] = [DELHI.lat, DELHI.lon];
export const MAP_ZOOM = 8;
export const MAP_BOUNDS: [[number, number], [number, number]] = [
  [DOMAIN.lat0, DOMAIN.lon0],
  [DOMAIN.lat1, DOMAIN.lon1],
];

// ── Basemap styles (all keyless raster tile hosts) ───────────────────────────
// The CSP for /console (backend/app/core/security.py) whitelists exactly these
// hosts under img-src. Adding a style here means adding its host there too.
export type MapStyleId = "dark" | "satellite" | "streets" | "terrain";

export interface MapStyle {
  id: MapStyleId;
  label: string;
  url: string;
  attribution: string;
  maxZoom: number;
  /** true = dark basemap; false = light imagery/terrain (affects overlay tint). */
  dark: boolean;
}

export const MAP_STYLES: Record<MapStyleId, MapStyle> = {
  dark: {
    id: "dark",
    label: "Dark",
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
    attribution: "Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ",
    maxZoom: 16,
    dark: true,
  },
  satellite: {
    id: "satellite",
    label: "Satellite",
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attribution: "Tiles &copy; Esri — Source: Esri, Maxar, Earthstar Geographics",
    maxZoom: 19,
    dark: true,
  },
  streets: {
    id: "streets",
    label: "Streets",
    url: "https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png",
    attribution: "&copy; OpenStreetMap contributors &copy; CARTO",
    maxZoom: 19,
    dark: false,
  },
  terrain: {
    id: "terrain",
    label: "Terrain",
    url: "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
    attribution: "&copy; OpenStreetMap contributors, SRTM — style: OpenTopoMap (CC-BY-SA)",
    maxZoom: 17,
    dark: false,
  },
};

export const MAP_STYLE_ORDER: readonly MapStyleId[] = ["dark", "satellite", "streets", "terrain"];

/** Which overlay layers are drawn, shared by both renderers and the controls. */
export interface MapLayers {
  stations: boolean;
  heatmap: boolean;
  fires: boolean;
  industries: boolean;
}

/**
 * AQI heat gradient, keyed by normalized intensity (= aqi / 500). Stops land on
 * the CPCB band boundaries (50/100/200/300/400/500) so the surface colour tracks
 * category, not an arbitrary ramp. Mirrors AQI_HEX in lib/aqi.ts.
 */
export const HEAT_GRADIENT: Record<number, string> = {
  0.1: "#4FB477", // Good
  0.2: "#9FC93C", // Satisfactory
  0.4: "#EFC02D", // Moderate
  0.6: "#F2892F", // Poor
  0.8: "#E8503C", // Very Poor
  1.0: "#C0356A", // Severe
};

// ── Pure helpers ─────────────────────────────────────────────────────────────

/** Punjab/Haryana separation used by the plume model (drawn on the schematic). */
export function dividerLat(lon: number): number {
  return 29.9 - 0.353 * (lon - 75.2);
}

/** Linear hex→hex interpolation, returned as an `rgb(...)` string. */
export function hexLerp(a: string, b: string, t: number): string {
  const pa = [parseInt(a.slice(1, 3), 16), parseInt(a.slice(3, 5), 16), parseInt(a.slice(5, 7), 16)];
  const pb = [parseInt(b.slice(1, 3), 16), parseInt(b.slice(3, 5), 16), parseInt(b.slice(5, 7), 16)];
  const c = pa.map((v, i) => Math.round(v + (pb[i] - v) * Math.max(0, Math.min(1, t))));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

/** Fire-hotspot marker radius (px): ∝ √FRP, clamped. Shared by both renderers. */
export function hotspotRadius(frpMw: number): number {
  return Math.max(2.5, Math.min(16, Math.sqrt(Math.max(0, frpMw)) * 1.15));
}

/** A linear lon→x / lat→y projection onto a w×h canvas for the offline schematic. */
export function makeProjector(w: number, h: number) {
  const { lon0, lon1, lat0, lat1 } = DOMAIN;
  return {
    x: (lon: number) => ((lon - lon0) / (lon1 - lon0)) * w,
    y: (lat: number) => (1 - (lat - lat0) / (lat1 - lat0)) * h,
  };
}

/**
 * Restore the CPCB display form of a pollutant key. The realtime feed sends the
 * dominant pollutant and the concentration keys uppercased with the dot dropped
 * (e.g. "PM25"); everything else is passed through unchanged.
 */
export function normalizeDominant(p: string): string {
  const key = p.toUpperCase().replace(/\s+/g, "");
  const map: Record<string, string> = {
    PM25: "PM2.5",
    "PM2.5": "PM2.5",
    PM10: "PM10",
    O3: "O3",
    NO2: "NO2",
    SO2: "SO2",
    CO: "CO",
  };
  return map[key] ?? p;
}

/**
 * Station readings → leaflet.heat points `[lat, lon, intensity]`. Intensity is
 * aqi/500 (floored at a small value so even Good stations register), so the
 * heat surface is a direct, honest function of the AQI each station reports.
 */
export function heatPoints(stations: StationReading[]): Array<[number, number, number]> {
  return stations.map((s) => [s.lat, s.lon, Math.max(0.06, Math.min(1, s.aqi / 500))]);
}

export interface WindStat {
  u: number;
  v: number;
  speed: number;
  /** Meteorological direction the wind blows FROM, degrees. */
  from: number;
}

/** Speed + "from" bearing for an (u, v) wind vector. */
export function windStat(u: number, v: number): WindStat {
  return { u, v, speed: Math.hypot(u, v), from: (Math.atan2(u, v) * 180) / Math.PI + 180 };
}
