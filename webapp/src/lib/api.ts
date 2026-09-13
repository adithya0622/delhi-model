/**
 * Data access for the NCR·72 console.
 *
 * Two independent concerns live here:
 *   1. Live API calls to `/api/v1/*` (absolute paths — proxied in dev, same-origin
 *      under the `/console` mount in prod), each with its own abort timeout.
 *   2. The sample bundle loaded from the public dir, used as a labelled fallback
 *      when the live forecast is unreachable, or forced via `?sample=`.
 *
 * The forecast is the slow call — it solves a coupled single-column model to a
 * fixed point per hour — so it gets a long timeout. Nothing here fabricates data:
 * a failed live call either falls back to the clearly-labelled sample (forecast)
 * or surfaces as an error the panel renders as "feed unavailable" (plume, stations).
 */

import type {
  CityOverview,
  ConsensusResponse,
  CityAggregateResponse,
  ExposureRequest,
  ExposureResponse,
  ForecastFieldResponse,
  ForecastResponse,
  HealthResponse,
  InversionStatus,
  PlumeVectorsResponse,
  SourceApportionmentResponse,
  SourceTimeSeriesResponse,
  StationReading,
  MlForecast72hrResponse,
  ChronosForecastResponse,
  IqairRealtimeResponse,
  WeatherapiRealtimeResponse,
  Historical7dResponse,
  BacktestReport,
  AqiCategory,
} from "./types";

export type {
  MlForecast72hrResponse,
  ChronosForecastResponse,
  IqairRealtimeResponse,
  WeatherapiRealtimeResponse,
  Historical7dResponse,
  BacktestReport,
};

const API = "/api/v1";

function toAqiCategory(value: string): AqiCategory {
  const valid: AqiCategory[] = [
    "Good",
    "Moderate",
    "Unhealthy for Sensitive Groups",
    "Unhealthy",
    "Very Unhealthy",
    "Hazardous",
  ];
  return valid.includes(value as AqiCategory) ? (value as AqiCategory) : "Moderate";
}

function toPollutant(value: string) {
  const valid = ["PM2.5", "PM10", "O3", "NO2", "SO2", "CO"] as const;
  return valid.includes(value as typeof valid[number]) ? value : "PM2.5";
}

function normalizeMlForecast(data: any): MlForecast72hrResponse {
  if (!data?.forecast_hours) return data;
  return {
    ...data,
    forecast_hours: data.forecast_hours.map((h: any) => ({
      ...h,
      category: toAqiCategory(h.category),
      dominant_pollutant: toPollutant(h.dominant_pollutant),
      sub_indices:
        h.sub_indices?.map((s: any) => ({
          ...s,
          pollutant: toPollutant(s.pollutant),
          category: toAqiCategory(s.category),
        })) ?? [],
    })),
  };
}

/** Per-endpoint timeouts (ms). */
export const TIMEOUTS = {
  forecast: 60_000,
  field: 120_000,
  inversion: 30_000,
  plume: 30_000,
  realtime: 95_000,
  health: 8_000,
  chronos: 240_000,
} as const;

export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(detail || `HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

interface FetchOpts {
  timeoutMs: number;
  signal?: AbortSignal;
  method?: "GET" | "POST";
  body?: string;
}

async function fetchJson<T>(path: string, opts: FetchOpts): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(new DOMException("timeout", "TimeoutError")), opts.timeoutMs);

  // Bridge an external abort (component unmount / scenario switch) into ours.
  const onExternalAbort = () => ctrl.abort(opts.signal?.reason);
  if (opts.signal) {
    if (opts.signal.aborted) ctrl.abort(opts.signal.reason);
    else opts.signal.addEventListener("abort", onExternalAbort, { once: true });
  }

  try {
    const res = await fetch(path, {
      signal: ctrl.signal,
      method: opts.method ?? "GET",
      headers: { Accept: "application/json", ...(opts.body ? { "Content-Type": "application/json" } : {}) },
      body: opts.body,
    });
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const body = await res.json();
        if (body && typeof body.detail === "string") detail = body.detail;
      } catch {
        /* non-JSON error body — keep the status line */
      }
      throw new ApiError(res.status, detail);
    }
    return (await res.json()) as T;
  } finally {
    clearTimeout(timer);
    if (opts.signal) opts.signal.removeEventListener("abort", onExternalAbort);
  }
}

// ── Live endpoints ────────────────────────────────────────────────────────────

export interface ForecastParams {
  lat?: number;
  lon?: number;
  station_name?: string;
  base_aqi?: number;
}

export function getConsensus(signal?: AbortSignal): Promise<ConsensusResponse> {
  return fetchJson<ConsensusResponse>(`${API}/forecast/consensus`, {
    timeoutMs: TIMEOUTS.forecast,
    signal,
  });
}

export function getForecast(params: ForecastParams = {}, signal?: AbortSignal): Promise<ForecastResponse> {
  const q = new URLSearchParams();
  if (params.lat != null) q.set("lat", String(params.lat));
  if (params.lon != null) q.set("lon", String(params.lon));
  if (params.station_name) q.set("station_name", params.station_name);
  if (params.base_aqi != null) q.set("base_aqi", String(params.base_aqi));
  const qs = q.toString();
  return fetchJson<ForecastResponse>(`${API}/forecast/72hr${qs ? `?${qs}` : ""}`, {
    timeoutMs: TIMEOUTS.forecast,
    signal,
  });
}

export function getChronosForecast(signal?: AbortSignal): Promise<ChronosForecastResponse> {
  return fetchJson<ChronosForecastResponse>(`${API}/forecast/72hr-chronos`, {
    timeoutMs: TIMEOUTS.chronos,
    signal,
  });
}

export function getInversion(signal?: AbortSignal): Promise<InversionStatus[]> {
  return fetchJson<InversionStatus[]>(`${API}/inversion/status`, { timeoutMs: TIMEOUTS.inversion, signal });
}

export function getPlume(signal?: AbortSignal): Promise<PlumeVectorsResponse> {
  return fetchJson<PlumeVectorsResponse>(`${API}/plume/vectors`, { timeoutMs: TIMEOUTS.plume, signal });
}

export function getOverview(signal?: AbortSignal): Promise<CityOverview> {
  return fetchJson<CityOverview>(`${API}/realtime/overview`, { timeoutMs: TIMEOUTS.realtime, signal });
}

export function getStations(signal?: AbortSignal): Promise<StationReading[]> {
  return fetchJson<StationReading[]>(`${API}/realtime/stations`, { timeoutMs: TIMEOUTS.realtime, signal });
}

export function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return fetchJson<HealthResponse>(`${API}/health`, { timeoutMs: TIMEOUTS.health, signal });
}

export function calculateExposure(req: ExposureRequest, signal?: AbortSignal): Promise<ExposureResponse> {
  return fetchJson<ExposureResponse>(`${API}/exposure/calculate`, {
    method: "POST",
    body: JSON.stringify(req),
    timeoutMs: TIMEOUTS.realtime,
    signal,
  });
}

export function getSourceApportionment(
  pm25?: number,
  no2?: number,
  hour?: number,
  signal?: AbortSignal
): Promise<SourceApportionmentResponse> {
  const params = new URLSearchParams();
  if (pm25 != null) params.set("pm25", pm25.toString());
  if (no2 != null) params.set("no2", no2.toString());
  if (hour != null) params.set("hour", hour.toString());
  const qs = params.toString() ? `?${params.toString()}` : "";
  return fetchJson<SourceApportionmentResponse>(`${API}/forecast/source-apportionment${qs}`, {
    timeoutMs: TIMEOUTS.realtime,
    signal,
  });
}

export function getSourceTimeSeries(signal?: AbortSignal): Promise<SourceTimeSeriesResponse> {
  return fetchJson<SourceTimeSeriesResponse>(`${API}/forecast/source-timeseries`, {
    timeoutMs: TIMEOUTS.realtime,
    signal,
  });
}

export function getCityAggregate(signal?: AbortSignal): Promise<CityAggregateResponse> {
  return fetchJson<CityAggregateResponse>(`${API}/current-aggregate`, {
    timeoutMs: TIMEOUTS.realtime,
    signal,
  });
}

export function getIqairRealtime(signal?: AbortSignal): Promise<IqairRealtimeResponse> {
  return fetchJson<IqairRealtimeResponse>(`${API}/realtime/iqair`, {
    timeoutMs: TIMEOUTS.realtime,
    signal,
  });
}

export function getWeatherapiRealtime(signal?: AbortSignal): Promise<WeatherapiRealtimeResponse> {
  return fetchJson<WeatherapiRealtimeResponse>(`${API}/realtime/weatherapi`, {
    timeoutMs: TIMEOUTS.realtime,
    signal,
  });
}

export function getMlStatus(signal?: AbortSignal): Promise<Record<string, any>> {
  return fetchJson<Record<string, any>>(`${API}/forecast/ml-status`, {
    timeoutMs: TIMEOUTS.realtime,
    signal,
  });
}

export function getMlForecast72hr(
  params: { lat?: number; lon?: number; station_name?: string } = {},
  signal?: AbortSignal
): Promise<MlForecast72hrResponse> {
  const q = new URLSearchParams();
  if (params.lat != null) q.set("lat", String(params.lat));
  if (params.lon != null) q.set("lon", String(params.lon));
  if (params.station_name) q.set("station_name", params.station_name);
  const qs = q.toString();
  return fetchJson<any>(`${API}/forecast/72hr-ml${qs ? `?${qs}` : ""}`, {
    timeoutMs: TIMEOUTS.forecast,
    signal,
  }).then(normalizeMlForecast);
}

export function getValidationBacktest(signal?: AbortSignal): Promise<BacktestReport> {
  return fetchJson<BacktestReport>(`${API}/validation/backtest`, {
    timeoutMs: TIMEOUTS.forecast,
    signal,
  });
}

export function getForecastField(
  nStations = 12,
  hourIndex = 0,
  signal?: AbortSignal
): Promise<ForecastFieldResponse> {
  const q = new URLSearchParams({
    n_stations: String(nStations),
    hour_index: String(hourIndex),
  });
  return fetchJson<ForecastFieldResponse>(`${API}/forecast/field?${q.toString()}`, {
    timeoutMs: TIMEOUTS.field,
    signal,
  });
}

export function getHistoricalAirQuality(signal?: AbortSignal): Promise<Historical7dResponse> {
  return fetchJson<Historical7dResponse>(`${API}/history/7d`, {
    timeoutMs: TIMEOUTS.realtime,
    signal,
  });
}
