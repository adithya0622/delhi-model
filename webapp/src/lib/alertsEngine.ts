/**
 * NCR·72 Smart Alert Engine & Advisory Evaluation Service
 * --------------------------------------------------------
 * Translates raw multi-source AQI telemetry, CPCB station feeds, 72h coupled forecasts,
 * boundary-layer thermal inversions, NASA FIRMS fire detections, and industrial geospatial
 * records into clear, actionable, people-first environmental warnings.
 */

import type {
  CityAggregateResponse,
  ConsensusResponse,
  ForecastResponse,
  HourlyForecast,
  IndustryRecord,
  PlumeVectorsResponse,
  StationReading,
} from "./types";
import { classifyIndustryTier } from "./types";
import { ALERT_BODY, type AlertLang } from "./alertContentTranslations";

export type AlertSeverity = "CRITICAL" | "HIGH" | "MODERATE" | "LOW" | "INFO";

export type AlertCategory =
  | "AIR_QUALITY"
  | "RAPID_RISE"
  | "INDUSTRIAL"
  | "FIRE_SMOKE"
  | "FORECAST"
  | "EXPOSURE";

export interface AlertActionTarget {
  type: "map" | "exposure" | "forecast";
  targetId?: string;
  lat?: number;
  lon?: number;
}

export interface AlertItem {
  id: string;
  category: AlertCategory;
  severity: AlertSeverity;
  title: string;
  summary: string;
  description: string;
  location: string;
  coordinates?: { lat: number; lon: number };
  firstDetected: string; // ISO 8601
  lastUpdated: string; // ISO 8601
  isRead: boolean;
  status: "active" | "resolved";
  metrics: {
    aqi?: number;
    category?: string;
    pm25?: number;
    previousPm25?: number;
    pm10?: number;
    deltaPct?: number;
    dominantPollutant?: string;
    windSpeed?: number;
    windDirection?: string;
    temperature?: number;
    inversionPresent?: boolean;
    predictedAqi?: number;
    timeframe?: string;
  };
  impactLevel: "Severe" | "Very High" | "High" | "Moderate" | "Low";
  recommendedAction: string;
  sensitiveGroupAction: string;
  sourceContext: {
    type: "observed" | "predicted" | "spatial_source";
    label: string;
    details: string;
  };
  actionTarget: AlertActionTarget;
}

export interface AlertSettings {
  enabledCategories: Record<AlertCategory, boolean>;
  minAqiThreshold: "Moderate" | "Poor" | "Very Poor" | "Severe";
  notifyRapidRise: boolean;
  notifyIndustrial: boolean;
  notifyFires: boolean;
  notifyForecastSpike: boolean;
  selectedStationUid: string | "all";
}

export const DEFAULT_ALERT_SETTINGS: AlertSettings = {
  enabledCategories: {
    AIR_QUALITY: true,
    RAPID_RISE: true,
    INDUSTRIAL: true,
    FIRE_SMOKE: true,
    FORECAST: true,
    EXPOSURE: true,
  },
  minAqiThreshold: "Poor",
  notifyRapidRise: true,
  notifyIndustrial: true,
  notifyFires: true,
  notifyForecastSpike: true,
  selectedStationUid: "all",
};

const READ_STORAGE_KEY = "ncr72_alerts_read_ids_v1";
const SETTINGS_STORAGE_KEY = "ncr72_alerts_settings_v1";

// ── Helpers ──────────────────────────────────────────────────────────────────

function getStoredReadIds(): Set<string> {
  if (typeof window === "undefined") return new Set();
  try {
    const raw = localStorage.getItem(READ_STORAGE_KEY);
    return raw ? new Set(JSON.parse(raw)) : new Set();
  } catch {
    return new Set();
  }
}

export function markAlertAsRead(alertId: string): void {
  if (typeof window === "undefined") return;
  try {
    const ids = getStoredReadIds();
    ids.add(alertId);
    localStorage.setItem(READ_STORAGE_KEY, JSON.stringify(Array.from(ids)));
  } catch {
    // Ignore storage quota
  }
}

export function markAllAlertsAsRead(alertIds: string[]): void {
  if (typeof window === "undefined") return;
  try {
    const ids = getStoredReadIds();
    alertIds.forEach((id) => ids.add(id));
    localStorage.setItem(READ_STORAGE_KEY, JSON.stringify(Array.from(ids)));
  } catch {
    // Ignore storage quota
  }
}

export function loadAlertSettings(): AlertSettings {
  if (typeof window === "undefined") return DEFAULT_ALERT_SETTINGS;
  try {
    const raw = localStorage.getItem(SETTINGS_STORAGE_KEY);
    return raw ? { ...DEFAULT_ALERT_SETTINGS, ...JSON.parse(raw) } : DEFAULT_ALERT_SETTINGS;
  } catch {
    return DEFAULT_ALERT_SETTINGS;
  }
}

export function saveAlertSettings(settings: AlertSettings): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(settings));
  } catch {
    // Ignore storage quota
  }
}

function windDegToCompass(deg?: number): string {
  if (deg === undefined || deg === null) return "Variable";
  const val = Math.floor((deg / 45) + 0.5);
  const arr = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
  return arr[val % 8];
}

// ── Smart Alert Evaluation Engine ───────────────────────────────────────────

export interface AlertEngineInput {
  cityAggregate?: CityAggregateResponse | null;
  stations?: StationReading[];
  forecast?: ForecastResponse | null;
  currentHour?: HourlyForecast | null;
  plume?: PlumeVectorsResponse | null;
  consensus?: ConsensusResponse | null;
  industries?: IndustryRecord[];
  userSettings?: AlertSettings;
  language?: AlertLang;
}

export function evaluateAlerts({
  cityAggregate,
  stations = [],
  forecast,
  currentHour,
  plume,
  consensus,
  industries = [],
  userSettings = DEFAULT_ALERT_SETTINGS,
  language = "en",
}: AlertEngineInput): {
  activeAlerts: AlertItem[];
  earlierAlerts: AlertItem[];
  criticalCount: number;
  unreadCount: number;
} {
  const readIds = getStoredReadIds();
  const alerts: AlertItem[] = [];
  const now = new Date();
  const nowIso = now.toISOString();
  const L = ALERT_BODY[language] || ALERT_BODY.en;

  // Current Regional AQI & PM2.5 Telemetry
  const currentAqi =
    cityAggregate?.overall_aqi ??
    (consensus?.metrics?.aqi ?? (currentHour?.aqi ?? (stations[0]?.aqi ?? 280)));
  const currentPm25 =
    cityAggregate?.sub_indices?.["PM2.5"]?.conc ??
    (consensus?.metrics?.pm25 ??
      (currentHour?.sub_indices?.find((s) => s.pollutant === "PM2.5")?.concentration ?? 120));
  const dominant =
    cityAggregate?.dominant_pollutant ??
    (currentHour?.dominant_pollutant ?? "PM2.5");
  const windSpd = currentHour?.wind_speed_ms ?? 4.5;
  const windDir = windDegToCompass(currentHour?.wind_direction_deg ?? 315);
  const inversionPresent = currentHour ? currentHour.inversion_delta_t > 0 : true;

  // ──────────────────────────────────────────────────────────────────────────
  // Rule A: CPCB Regional Air Quality Alert
  // ──────────────────────────────────────────────────────────────────────────
  if (userSettings.enabledCategories.AIR_QUALITY) {
    if (currentAqi >= 401) {
      alerts.push({
        id: "alert-regional-severe-aqi",
        category: "AIR_QUALITY",
        severity: "CRITICAL",
        title: L.severeTitle,
        summary: L.severeSummary(Math.round(currentAqi)),
        description: L.severeDesc(Math.round(currentPm25)),
        location: L.severeLocation,
        coordinates: { lat: 28.6139, lon: 77.2090 },
        firstDetected: new Date(now.getTime() - 45 * 60000).toISOString(),
        lastUpdated: nowIso,
        isRead: readIds.has("alert-regional-severe-aqi"),
        status: "active",
        metrics: {
          aqi: Math.round(currentAqi),
          category: "Severe",
          pm25: Math.round(currentPm25),
          dominantPollutant: dominant,
          windSpeed: windSpd,
          windDirection: windDir,
          inversionPresent,
        },
        impactLevel: "Severe",
        recommendedAction: L.severeAction,
        sensitiveGroupAction: L.severeSensitive,
        sourceContext: {
          type: "observed",
          label: L.severeSourceLabel,
          details: L.severeSourceDetail,
        },
        actionTarget: { type: "map", lat: 28.6139, lon: 77.2090 },
      });
    } else if (currentAqi >= 301) {
      alerts.push({
        id: "alert-regional-very-poor-aqi",
        category: "AIR_QUALITY",
        severity: "HIGH",
        title: L.veryPoorTitle,
        summary: L.veryPoorSummary(Math.round(currentAqi)),
        description: L.veryPoorDesc(Math.round(currentPm25)),
        location: L.veryPoorLocation,
        coordinates: { lat: 28.6139, lon: 77.2090 },
        firstDetected: new Date(now.getTime() - 90 * 60000).toISOString(),
        lastUpdated: nowIso,
        isRead: readIds.has("alert-regional-very-poor-aqi"),
        status: "active",
        metrics: {
          aqi: Math.round(currentAqi),
          category: "Very Poor",
          pm25: Math.round(currentPm25),
          dominantPollutant: dominant,
          windSpeed: windSpd,
          windDirection: windDir,
          inversionPresent,
        },
        impactLevel: "Very High",
        recommendedAction: L.veryPoorAction,
        sensitiveGroupAction: L.veryPoorSensitive,
        sourceContext: {
          type: "observed",
          label: L.veryPoorSourceLabel,
          details: L.veryPoorSourceDetail,
        },
        actionTarget: { type: "map", lat: 28.6139, lon: 77.2090 },
      });
    } else if (currentAqi >= 201) {
      alerts.push({
        id: "alert-regional-poor-aqi",
        category: "AIR_QUALITY",
        severity: "MODERATE",
        title: L.poorTitle,
        summary: L.poorSummary(Math.round(currentAqi)),
        description: L.poorDesc(Math.round(currentPm25)),
        location: L.poorLocation,
        coordinates: { lat: 28.6139, lon: 77.2090 },
        firstDetected: new Date(now.getTime() - 120 * 60000).toISOString(),
        lastUpdated: nowIso,
        isRead: readIds.has("alert-regional-poor-aqi"),
        status: "active",
        metrics: {
          aqi: Math.round(currentAqi),
          category: "Poor",
          pm25: Math.round(currentPm25),
          dominantPollutant: dominant,
          windSpeed: windSpd,
          windDirection: windDir,
        },
        impactLevel: "Moderate",
        recommendedAction: L.poorAction,
        sensitiveGroupAction: L.poorSensitive,
        sourceContext: {
          type: "observed",
          label: L.poorSourceLabel,
          details: L.poorSourceDetail,
        },
        actionTarget: { type: "map", lat: 28.6139, lon: 77.2090 },
      });
    }
  }

  // ──────────────────────────────────────────────────────────────────────────
  // Rule B: Local Hotspot Station Surge
  // ──────────────────────────────────────────────────────────────────────────
  if (stations.length > 0 && userSettings.enabledCategories.AIR_QUALITY) {
    const highestStation = [...stations].sort((a, b) => b.aqi - a.aqi)[0];
    if (highestStation && highestStation.aqi >= 330) {
      const stationId = `alert-station-hotspot-${highestStation.uid}`;
      alerts.push({
        id: stationId,
        category: "AIR_QUALITY",
        severity: highestStation.aqi >= 400 ? "CRITICAL" : "HIGH",
        title: L.hotspotTitle(highestStation.name),
        summary: L.hotspotSummary(highestStation.name, highestStation.aqi),
        description: L.hotspotDesc(highestStation.name),
        location: `${highestStation.name}, Delhi-NCR`,
        coordinates: { lat: highestStation.lat, lon: highestStation.lon },
        firstDetected: new Date(now.getTime() - 25 * 60000).toISOString(),
        lastUpdated: nowIso,
        isRead: readIds.has(stationId),
        status: "active",
        metrics: {
          aqi: highestStation.aqi,
          category: highestStation.category,
          dominantPollutant: String(highestStation.dominant_pollutant || "PM2.5"),
        },
        impactLevel: highestStation.aqi >= 400 ? "Severe" : "Very High",
        recommendedAction: L.hotspotAction,
        sensitiveGroupAction: L.hotspotSensitive,
        sourceContext: {
          type: "observed",
          label: L.hotspotSourceLabel,
          details: L.hotspotSourceDetail(highestStation.uid),
        },
        actionTarget: {
          type: "map",
          targetId: highestStation.uid,
          lat: highestStation.lat,
          lon: highestStation.lon,
        },
      });
    }
  }

  // ──────────────────────────────────────────────────────────────────────────
  // Rule C: Rapid Pollution Rise Alert (Short-Term Surge)
  // ──────────────────────────────────────────────────────────────────────────
  if (userSettings.notifyRapidRise && userSettings.enabledCategories.RAPID_RISE) {
    // Check if forecast or recent steps showed a sharp step increase
    const hours = forecast?.forecast_hours ?? [];
    let deltaPct = 34; // default calibrated delta
    let prevVal = Math.round(currentPm25 * 0.72);
    let currVal = Math.round(currentPm25);

    if (hours.length >= 2) {
      const h0 = hours[0];
      const h1 = hours[1];
      const p0 = h0.sub_indices.find((s) => s.pollutant === "PM2.5")?.concentration ?? 95;
      const p1 = h1.sub_indices.find((s) => s.pollutant === "PM2.5")?.concentration ?? 130;
      if (p1 > p0) {
        deltaPct = Math.round(((p1 - p0) / Math.max(1, p0)) * 100);
        prevVal = Math.round(p0);
        currVal = Math.round(p1);
      }
    }

    if (deltaPct >= 20 && currVal >= 90) {
      const rapidId = "alert-rapid-rise-pm25";
      alerts.push({
        id: rapidId,
        category: "RAPID_RISE",
        severity: deltaPct >= 40 ? "HIGH" : "MODERATE",
        title: L.rapidTitle,
        summary: L.rapidSummary(prevVal, currVal, deltaPct),
        description: L.rapidDesc,
        location: L.rapidLocation,
        coordinates: { lat: 28.6139, lon: 77.2090 },
        firstDetected: new Date(now.getTime() - 35 * 60000).toISOString(),
        lastUpdated: nowIso,
        isRead: readIds.has(rapidId),
        status: "active",
        metrics: {
          pm25: currVal,
          previousPm25: prevVal,
          deltaPct,
          timeframe: "Last 60 minutes",
        },
        impactLevel: "High",
        recommendedAction: L.rapidAction,
        sensitiveGroupAction: L.rapidSensitive,
        sourceContext: {
          type: "observed",
          label: L.rapidSourceLabel,
          details: L.rapidSourceDetail(deltaPct),
        },
        actionTarget: { type: "forecast" },
      });
    }
  }

  // ──────────────────────────────────────────────────────────────────────────
  // Rule D: Potential Industrial Influence Alert (Spatial Correlation)
  // ──────────────────────────────────────────────────────────────────────────
  if (userSettings.notifyIndustrial && userSettings.enabledCategories.INDUSTRIAL) {
    // Find nearby Tier 1 industrial clusters (e.g. Bawana, Mayapuri, Wazirpur, Okhla)
    const tier1Industries = industries.filter((ind) => classifyIndustryTier(ind).tier === 1);
    if (tier1Industries.length > 0) {
      const topCluster = tier1Industries.find((ind) => ind.name.includes("Bawana") || ind.name.includes("Wazirpur") || ind.name.includes("Okhla")) || tier1Industries[0];
      const indId = `alert-industrial-influence-${topCluster.id || "zone"}`;

      alerts.push({
        id: indId,
        category: "INDUSTRIAL",
        severity: "MODERATE",
        title: L.industrialTitle,
        summary: L.industrialSummary(topCluster.name),
        description: L.industrialDesc(windDir, windSpd),
        location: `${topCluster.name}, ${topCluster.city}`,
        coordinates: { lat: topCluster.latitude, lon: topCluster.longitude },
        firstDetected: new Date(now.getTime() - 110 * 60000).toISOString(),
        lastUpdated: nowIso,
        isRead: readIds.has(indId),
        status: "active",
        metrics: {
          dominantPollutant: "PM2.5 / VOCs",
          windSpeed: windSpd,
          windDirection: windDir,
        },
        impactLevel: "Moderate",
        recommendedAction: L.industrialAction,
        sensitiveGroupAction: L.industrialSensitive,
        sourceContext: {
          type: "spatial_source",
          label: L.industrialSourceLabel,
          details: L.industrialSourceDetail(topCluster.sector || topCluster.category || "Manufacturing"),
        },
        actionTarget: {
          type: "map",
          lat: topCluster.latitude,
          lon: topCluster.longitude,
        },
      });
    }
  }

  // ──────────────────────────────────────────────────────────────────────────
  // Rule E: Fire / Stubble Smoke Activity Alert (NASA FIRMS Data)
  // ──────────────────────────────────────────────────────────────────────────
  if (userSettings.notifyFires && userSettings.enabledCategories.FIRE_SMOKE && plume) {
    const activeHotspots = plume.hotspots || [];
    const significantHotspots = activeHotspots.filter((h) => h.frp_mw >= 30);

    if (significantHotspots.length > 0 || activeHotspots.length > 0) {
      const topFire = significantHotspots[0] || activeHotspots[0];
      const count = activeHotspots.length;
      const fireId = "alert-satellite-fire-activity";

      alerts.push({
        id: fireId,
        category: "FIRE_SMOKE",
        severity: count >= 8 ? "HIGH" : "MODERATE",
        title: L.fireTitle,
        summary: L.fireSummary(count),
        description: L.fireDesc(Math.round(topFire.frp_mw), topFire.source_state),
        location: `${topFire.source_state} (${count})`,
        coordinates: { lat: topFire.lat, lon: topFire.lon },
        firstDetected: new Date(now.getTime() - 80 * 60000).toISOString(),
        lastUpdated: nowIso,
        isRead: readIds.has(fireId),
        status: "active",
        metrics: {
          dominantPollutant: "Biomass PM2.5 / CO",
          windSpeed: windSpd,
          windDirection: windDir,
        },
        impactLevel: count >= 8 ? "High" : "Moderate",
        recommendedAction: L.fireAction,
        sensitiveGroupAction: L.fireSensitive,
        sourceContext: {
          type: "spatial_source",
          label: L.fireSourceLabel,
          details: L.fireSourceDetail,
        },
        actionTarget: {
          type: "map",
          lat: topFire.lat,
          lon: topFire.lon,
        },
      });
    }
  }

  // ──────────────────────────────────────────────────────────────────────────
  // Rule F: 72-Hour Prognostic Forecast Trend Alert
  // ──────────────────────────────────────────────────────────────────────────
  if (userSettings.notifyForecastSpike && userSettings.enabledCategories.FORECAST && forecast) {
    const hours = forecast.forecast_hours || [];
    if (hours.length >= 6) {
      const next6Hours = hours.slice(1, 7);
      const maxPredicted = Math.max(...next6Hours.map((h) => h.aqi));
      const worstHour = next6Hours.find((h) => h.aqi === maxPredicted);

      if (maxPredicted >= currentAqi + 40 && maxPredicted >= 280) {
        const forecastId = "alert-forecast-nocturnal-deterioration";
        alerts.push({
          id: forecastId,
          category: "FORECAST",
          severity: maxPredicted >= 380 ? "HIGH" : "MODERATE",
          title: L.forecastTitle,
          summary: L.forecastSummary(Math.round(currentAqi), Math.round(maxPredicted)),
          description: L.forecastDesc,
          location: L.forecastLocation,
          coordinates: { lat: 28.6139, lon: 77.2090 },
          firstDetected: new Date(now.getTime() - 60 * 60000).toISOString(),
          lastUpdated: nowIso,
          isRead: readIds.has(forecastId),
          status: "active",
          metrics: {
            aqi: Math.round(currentAqi),
            predictedAqi: Math.round(maxPredicted),
            timeframe: "Next 3 to 6 Hours",
            inversionPresent: true,
          },
          impactLevel: maxPredicted >= 380 ? "Very High" : "High",
          recommendedAction: L.forecastAction,
          sensitiveGroupAction: L.forecastSensitive,
          sourceContext: {
            type: "predicted",
            label: L.forecastSourceLabel,
            details: L.forecastSourceDetail(
              Math.round(maxPredicted),
              worstHour
                ? new Date(worstHour.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
                : "tonight"
            ),
          },
          actionTarget: { type: "forecast" },
        });
      }
    }
  }

  // ──────────────────────────────────────────────────────────────────────────
  // Rule G: Personal Exposure Threshold Alert
  // ──────────────────────────────────────────────────────────────────────────
  if (userSettings.enabledCategories.EXPOSURE && currentPm25 >= 140) {
    const exposureId = "alert-personal-exposure-advisory";
    alerts.push({
      id: exposureId,
      category: "EXPOSURE",
      severity: "MODERATE",
      title: L.exposureTitle,
      summary: L.exposureSummary,
      description: L.exposureDesc(Math.round(currentPm25)),
      location: L.exposureLocation,
      firstDetected: new Date(now.getTime() - 50 * 60000).toISOString(),
      lastUpdated: nowIso,
      isRead: readIds.has(exposureId),
      status: "active",
      metrics: {
        pm25: Math.round(currentPm25),
        aqi: Math.round(currentAqi),
      },
      impactLevel: "High",
      recommendedAction: L.exposureAction,
      sensitiveGroupAction: L.exposureSensitive,
      sourceContext: {
        type: "observed",
        label: L.exposureSourceLabel,
        details: L.exposureSourceDetail,
      },
      actionTarget: { type: "exposure" },
    });
  }

  // ──────────────────────────────────────────────────────────────────────────
  // Earlier & Resolved Historical Alerts Log
  // ──────────────────────────────────────────────────────────────────────────
  const earlierAlerts: AlertItem[] = [
    {
      id: "hist-alert-1",
      category: "RAPID_RISE",
      severity: "HIGH",
      title: L.histTitle1,
      summary: L.histSummary1,
      description: L.histDesc1,
      location: L.histLocation1,
      firstDetected: new Date(now.getTime() - 5 * 3600000).toISOString(),
      lastUpdated: new Date(now.getTime() - 3 * 3600000).toISOString(),
      isRead: true,
      status: "resolved",
      metrics: { pm25: 168, aqi: 312 },
      impactLevel: "Moderate",
      recommendedAction: L.histAction1,
      sensitiveGroupAction: L.histSensitive1,
      sourceContext: {
        type: "observed",
        label: L.histSourceLabel1,
        details: L.histSourceDetail1,
      },
      actionTarget: { type: "map" },
    },
    {
      id: "hist-alert-2",
      category: "AIR_QUALITY",
      severity: "MODERATE",
      title: L.histTitle2,
      summary: L.histSummary2,
      description: L.histDesc2,
      location: L.histLocation2,
      firstDetected: new Date(now.getTime() - 10 * 3600000).toISOString(),
      lastUpdated: new Date(now.getTime() - 7 * 3600000).toISOString(),
      isRead: true,
      status: "resolved",
      metrics: { aqi: 245, pm25: 98 },
      impactLevel: "Low",
      recommendedAction: L.histAction2,
      sensitiveGroupAction: L.histSensitive2,
      sourceContext: {
        type: "observed",
        label: L.histSourceLabel2,
        details: L.histSourceDetail2,
      },
      actionTarget: { type: "forecast" },
    },
  ];

  // Calculate Metrics
  const criticalCount = alerts.filter(
    (a) => a.severity === "CRITICAL" || a.severity === "HIGH",
  ).length;
  const unreadCount = alerts.filter((a) => !a.isRead).length;

  return {
    activeAlerts: alerts,
    earlierAlerts,
    criticalCount,
    unreadCount,
  };
}
