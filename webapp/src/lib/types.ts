/**
 * Wire types for the NCR·72 API (`/api/v1`), mirroring backend/app/schemas/forecast.py
 * and the realtime_service dict shapes. Everything here is the JSON-over-the-wire
 * shape: Python `datetime` → ISO string, Python `tuple` → fixed-length array.
 *
 * `erasableSyntaxOnly` forbids TS enums, so CPCB categories and pollutants are
 * union types plus ordered const arrays (used for sorting and iteration).
 */

// ── CPCB National AQI (2014) vocabulary ──────────────────────────────────────

export type AqiCategory =
  | "Good"
  | "Satisfactory"
  | "Moderate"
  | "Poor"
  | "Very Poor"
  | "Severe"
  | "Unhealthy for Sensitive Groups"
  | "Unhealthy"
  | "Very Unhealthy"
  | "Hazardous";

/** Ascending severity — index doubles as a rank. */
export const AQI_CATEGORIES: readonly AqiCategory[] = [
  "Good",
  "Satisfactory",
  "Moderate",
  "Poor",
  "Very Poor",
  "Severe",
] as const;

export type Pollutant = "PM2.5" | "PM10" | "O3" | "NO2" | "SO2" | "CO";

/** Canonical display order for the sub-index list. */
export const POLLUTANTS: readonly Pollutant[] = [
  "PM2.5",
  "PM10",
  "O3",
  "NO2",
  "SO2",
  "CO",
] as const;

export type InversionSeverity = "None" | "Weak" | "Moderate" | "Strong";

// ── Forecast ──────────────────────────────────────────────────────────────────

export interface PollutantSubIndex {
  pollutant: Pollutant;
  concentration: number; // µg/m³ or ppb depending on species
  sub_index: number; // 0–500 CPCB scale
  category: AqiCategory;
}

export interface HourlyForecast {
  timestamp: string; // ISO 8601
  aqi: number; // 0–500, = max(sub_index), never a mean
  aqi_standard?: string;
  aqi_method?: string;
  pm25_source?: string;
  category: AqiCategory;
  dominant_pollutant: Pollutant;
  sub_indices: PollutantSubIndex[];

  // meteorology → chemistry
  pbl_height_m: number; // mixing depth AFTER the aerosol feedback
  inversion_delta_t: number; // T925 − T1000 (°C); positive = inversion
  wind_speed_ms: number;
  wind_direction_deg: number;
  temperature_2m_c?: number;
  relative_humidity_pct?: number;
  precipitation_mm?: number;
  shortwave_radiation_w_m2?: number;
  dew_point_2m_c?: number;
  apparent_temperature_c?: number;
  precipitation_probability_pct?: number;
  rain_mm?: number;
  showers_mm?: number;
  visibility_m?: number;
  cloud_cover_pct?: number;
  surface_pressure_hpa?: number;
  pressure_msl_hpa?: number;
  weather_code?: number;
  wind_gusts_ms?: number;

  // chemistry → meteorology (the return leg, exposed for audit)
  pbl_height_met_m: number; // unperturbed PBL straight from the met model
  pbl_suppression_pct: number; // % of mixing depth removed by aerosol
  aerosol_optical_depth: number; // column AOD from the PM2.5 profile
  aerosol_sw_forcing_w_m2: number; // surface shortwave removed (≤ 0)
  aerosol_dt_surface_c: number; // surface temperature change (≤ 0)
  feedback_iterations: number; // Picard iterations to convergence
  // The wind leg: hour i's surface wind after hour i-1's aerosol cooling
  // weakened momentum mixing. ≤ wind_speed_ms; drives the box ventilation term.
  wind_effective_ms: number;
  wind_perturbation_frac: number; // fractional surface-wind change (≤ 0)

  plume_contribution: number; // fraction of AQI from stubble plume (0–1)
}

export interface LatLon {
  lat: number;
  lon: number;
}

export interface ForecastResponse {
  generated_at: string; // ISO 8601
  location: LatLon;
  station_name: string;
  forecast_hours: HourlyForecast[]; // 72 entries
}

// ── Inversion ───────────────────────────────────────────────────────────────

export interface InversionStatus {
  timestamp: string;
  delta_t_celsius: number; // T925 − T1000
  pbl_height_m: number; // met-model mixing depth, no aerosol feedback
  lapse_rate_k_per_km: number; // negative = inverted
  inversion_present: boolean;
  severity: InversionSeverity;
  aqi_amplification_factor: number; // diagnostic compression, 1200/pbl
}

// ── Plume / fire ──────────────────────────────────────────────────────────────

export interface FireHotspot {
  lat: number;
  lon: number;
  frp_mw: number; // Fire Radiative Power, MW
  source_state: string; // "Punjab" | "Haryana" | "Uttar Pradesh" | …
  detected_at: string;
  confidence: string; // VIIRS "l"/"n"/"h" or MODIS 0–100
}

/** [lat, lon] waypoint. */
export type TrajPoint = [number, number];
/** [u, v] wind components, m/s. */
export type WindUV = [number, number];

export interface PlumeVector {
  origin: FireHotspot;
  trajectory: TrajPoint[]; // hourly (lat, lon) waypoints
  arrival_delhi_t_hours: number | null; // null if it misses Delhi
  pm25_contribution_ug_m3: number; // transport-layer, not surface
  pm25_column_ug_m2: number;
  closest_approach_km: number;
  travel_distance_km: number;
}

export interface PlumeVectorsResponse {
  timestamp: string;
  wind_850hpa_u: number; // hour-0 u, m/s
  wind_850hpa_v: number; // hour-0 v, m/s
  hotspots: FireHotspot[];
  plumes: PlumeVector[];
  wind_series: WindUV[]; // hourly 850 hPa wind driving advection
  hotspot_count_total: number; // detections before truncation to `plumes`
  pm25_profile_ug_m3: number[]; // 72 hourly transport-layer aggregates
}

// ── Forecast field (N coupled columns + IDW grid, physics-only) ───────────────

export interface ForecastFieldStation {
  uid: string;
  name: string;
  lat: number;
  lon: number;
  hourly_aqi: number[];
  hourly_pm25: number[];
  current_aqi: number;
  max_aqi_72h: number;
  mean_aqi_72h: number;
}

export interface ForecastFieldGrid {
  lats: number[];
  lons: number[];
  values: number[][];
  value_key: string;
}

export interface ForecastFieldResponse {
  generated_at: string;
  method: string;
  hour_index: number;
  station_count: number;
  stations: ForecastFieldStation[];
  grid: ForecastFieldGrid;
  weather_source: string;
  profile_source: string;
  limitations: string[];
}

// ── Realtime (bare dicts from realtime_service, no envelope) ──────────────────

export interface CityOverview {
  aqi: number;
  category: AqiCategory;
  color: string; // raw CPCB colour from backend — we re-derive, don't trust
  updated: string | null;
  pm25: number | null;
  pm10: number | null;
  o3: number | null;
  no2: number | null;
  temp: number | null;
  wind: number | null;
}

export interface StationReading {
  uid: string;
  name: string;
  lat: number;
  lon: number;
  aqi: number;
  category: AqiCategory;
  color: string; // raw CPCB colour — re-derived on the client
  dominant_pollutant: Pollutant | string;
  updated: string | null;
  pollutants: Partial<Record<string, number>>;
  weather?: {
    temperature?: number;
    humidity?: number;
    wind_speed?: number;
    wind_direction?: number;
    pressure?: number;
    condition?: string;
  };
  source: string;
}

export interface HealthResponse {
  status: string;
  timestamp: string;
}

// ── Sample bundle (public/sample-forecast.json) ───────────────────────────────

export type ScenarioId = "november" | "august";

export interface SampleScenario {
  id: ScenarioId;
  label: string;
  blurb: string;
  forecast: ForecastResponse;
  inversion: InversionStatus[]; // 72 entries
  plume: PlumeVectorsResponse;
}

export interface SampleBundle {
  kind: string; // "sample"
  generated_by: string;
  note: string;
  scenarios: SampleScenario[];
}


// ── Five-source consensus dashboard feed ──────────────────────────────────────
export interface ConsensusMetrics {
  pm25: number;
  pm10: number;
  aqi: number;
  temp: number;
  wind: number;
  no2?: number;
  o3?: number;
  so2?: number;
  co?: number;
}

export interface ConsensusForecastPoint {
  horizon_hours: number;
  timestamp: string;
  pm25: number;
  aqi: number;
  category: AqiCategory;
  wind_speed: number;
  temperature: number;
  rule: string;
  explanation: string;
}

export interface ConsensusResponse {
  generated_at: string;
  location: LatLon;
  metrics: ConsensusMetrics;
  successful_sources: string[];
  source_count: number;
  forecast: ConsensusForecastPoint[];
  explainability: string;
  severe_alert: boolean;
}

export interface ConsensusPanel {
  status: "loading" | "ok" | "error";
  data: ConsensusResponse | null;
  error: string | null;
}

export interface MlForecastRequest {
  current_pm25: number;
  forecast_wind_speed: number;
  forecast_temp: number;
  hour_of_day: number;
  month: number;
}

export interface MlForecastPoint {
  horizon_hours: 12 | 24 | 48 | 72;
  pm25: number;
  aqi: number;
}

export interface MlForecastResponse {
  generated_at: string;
  model: string;
  model_metrics: { mae?: number; rmse?: number };
  predictions: MlForecastPoint[];
  explainability: string;
  alert_status: "CRITICAL" | "NORMAL";
}

export type ActivityType = "resting" | "moderate" | "heavy";

export interface BacktestMetrics {
  n: number;
  mbe_ug_m3?: number;
  mae_ug_m3?: number;
  rmse_ug_m3?: number;
  pearson_r?: number | null;
  nash_sutcliffe_e?: number | null;
  mean_obs_ug_m3?: number;
  mean_pred_ug_m3?: number;
  bootstrap_mae_ci95?: { lo: number; hi: number };
}

export interface BacktestReport {
  available: boolean;
  status?: string;
  reason?: string;
  generated_at?: string;
  protocol?: {
    truth: string;
    meteorology: string;
    windows: number;
    window_hours: number;
    stride_days: number;
    min_lead_days: number;
    exclusions: string[];
  };
  pooled?: BacktestMetrics;
  skill_vs_persistence?: {
    persistence: BacktestMetrics;
    model: BacktestMetrics;
    mae_skill_score: number | null;
    interpretation: string;
  };
  by_lead?: Record<string, BacktestMetrics>;
  windows?: Array<BacktestMetrics & { start_ist: string; anchor_pm25_ug_m3: number }>;
  honesty_note?: string;
  cache?: { age_s: number; fresh: boolean; refresh_interval_h: number };
}

export interface ExposureRequest {
  activity_type: ActivityType;
  duration_hours: number;
  target_time?: string;
  current_pm25: number;
  forecast_72h?: Array<Record<string, any>>;
}

export interface ChronosHour {
  hour_index: number;
  timestamp: string;
  aqi_cpcb: number;
  aqi_category: string;
  dominant_pollutant: string;
  aqi_epa: number;
  aqi_epa_category: string;
  epa_dominant_pollutant: string;
  pollutants: Record<string, { p10?: number; p50: number; p90?: number }>;
}

export interface ChronosForecastResponse {
  model_name: string;
  architecture: string;
  vocabulary_size: number;
  context_hours: number;
  forecast_horizon_hours: number;
  location: { lat: number; lon: number };
  station_name: string;
  generated_at: string;
  hourly: ChronosHour[];
  verification: Record<string, any>;
  chronos_status: Record<string, any>;
  fallback_used: boolean;
  limitations?: string[];
}

export interface MlForecast72hrResponse {
  generated_at: string;
  location: { lat: number; lon: number };
  station_name: string;
  aqi_standard: string;
  aqi_method: string;
  concentration_unit: string;
  forecast_hours: Array<HourlyForecast>;
  model: string;
  ml_model: any;
  weather_source: string;
  provider_failures: any[];
  live_anchor?: { pm25_ug_m3: number | null; source: string };
  limitations?: string[];
}

export interface IqairRealtimeResponse {
  aqi: number;
  aqi_standard: string;
  aqi_method: string;
  category: string;
  color: string;
  updated: string;
  pm25: number | null;
  pm10: number | null;
  o3: number | null;
  no2: number | null;
  so2: number | null;
  co: number | null;
  pollutant_unit: string;
  temp: number | null;
  wind: number | null;
  humidity: number | null;
  pressure: number | null;
  station_count: number;
  source: string;
  location: string;
  coordinates: [number, number] | null;
}

export interface WeatherapiRealtimeResponse {
  temp: number;
  feels_like: number;
  humidity: number;
  wind_kph: number;
  wind_dir: string;
  wind_deg: number;
  pressure_mb: number;
  condition: string;
  condition_code: number;
  precip_mm: number;
  vis_km: number;
  uv: number;
  air_quality: {
    pm2_5: number | null;
    pm10: number | null;
    no2: number | null;
    o3: number | null;
    so2: number | null;
    co: number | null;
    us_epa_index?: number | null;
  };
  last_updated: string;
  source: string;
}

export interface Historical7dHour {
  timestamp: string;
  pm25: number | null;
  pm10: number | null;
  no2: number | null;
  o3: number | null;
  so2: number | null;
  co: number | null;
  aqi: number | null;
}

export interface Historical7dResponse {
  source: string;
  count: number;
  hours: Historical7dHour[];
}

export interface SmartSchedule {
  recommended_hour: string;
  recommended_timestamp: string;
  optimal_avg_pm25: number;
  target_avg_pm25?: number;
  projected_exposure_reduction_percent: number;
  advice_string: string;
}

export interface ExposureResponse {
  inhaled_mass_mcg: number;
  cigarettes_equivalent: number;
  health_warning: string;
  smart_schedule: SmartSchedule;
  activity_metadata?: {
    activity_type: string;
    breathing_rate_m3_h: number;
    duration_hours: number;
    ambient_pm25_ug_m3: number;
  };
}

export interface VehicleBreakdown {
  heavy_trucks_pct: number;
  two_three_wheelers_pct: number;
  cars_pct: number;
  heavy_trucks_mcg: number;
  two_three_wheelers_mcg: number;
  cars_mcg: number;
}

export interface SourceApportionmentResponse {
  total_pm25: number;
  transport_pct: number;
  dust_pct: number;
  biomass_pct: number;
  industry_pct: number;
  transport_mcg: number;
  dust_mcg: number;
  biomass_mcg: number;
  industry_mcg: number;
  vehicle_breakdown: VehicleBreakdown;
  proxy_status: string;
}

export interface ApportionmentHour {
  timestamp: string;
  total_pm25: number;
  dust_mcg: number;
  biomass_mcg: number;
  industry_mcg: number;
  trucks_mcg: number;
  two_wheelers_mcg: number;
  cars_mcg: number;
}

export interface SourceTimeSeriesResponse {
  forecast: ApportionmentHour[];
}

export interface PollutantDetail {
  index: number;
  conc: number;
  unit: string;
}

export interface CityAggregateResponse {
  location_label: string;
  station_count: number;
  overall_aqi: number;
  aqi_category: string;
  dominant_pollutant: string;
  color: string;
  sub_indices: Record<string, PollutantDetail>;
  timestamp: string;
}

export interface IndustryRecord {
  id?: string | number;
  name: string;
  city: "Delhi" | string;
  state: "Delhi" | string;
  latitude: number;
  longitude: number;
  category?: string | null;
  sector?: string | null;
  status?: string | null;
  capacity?: string | number | null;
  address?: string | null;
  tier?: 1 | 2 | 3;
}

export interface IndustryResponse {
  city: string;
  state: string;
  count: number;
  source: string;
  records: IndustryRecord[];
}

export type IndustryTierFilter = "all" | "tier1" | "tier2" | "tier3";

export interface IndustryTierInfo {
  tier: 1 | 2 | 3;
  label: string;
  badge: string;
  categoryName: string;
  color: string;
  pollutants: string;
  desc: string;
}

export function classifyIndustryTier(ind: IndustryRecord): IndustryTierInfo {
  const cat = (ind.category || "").toLowerCase();
  const name = (ind.name || "").toLowerCase();
  const sector = (ind.sector || "").toLowerCase();

  // Tier 1: Heavy Direct Polluters (CPCB Red Category)
  if (
    cat === "power" ||
    cat === "metal" ||
    cat === "chemical" ||
    cat === "plastic" ||
    cat === "electroplating" ||
    name.includes("power") ||
    name.includes("waste to energy") ||
    name.includes("wte") ||
    name.includes("smelt") ||
    name.includes("foundry") ||
    name.includes("pyrolysis") ||
    name.includes("rolling") ||
    name.includes("electroplat") ||
    name.includes("acid") ||
    sector.includes("steel") ||
    sector.includes("smelt") ||
    sector.includes("polymer") ||
    sector.includes("chemical") ||
    sector.includes("electroplat")
  ) {
    const isPower = cat === "power" || name.includes("power") || name.includes("waste to energy") || name.includes("wte");
    return {
      tier: 1,
      label: "Tier 1: High Emission",
      badge: "🔴 TIER 1 · HIGH EMISSION (RED)",
      categoryName: isPower ? "Power & Waste-to-Energy" : "Heavy Combustion / Chemical",
      color: isPower ? "#f59e0b" : "#ef4444",
      pollutants: "PM2.5, SO2, NOx, Toxic VOCs, Heavy Metals",
      desc: "Continuous high-temperature combustion, boiler stacks, plastic pyrolysis & toxic fumes.",
    };
  }

  // Tier 2: Moderate & Fugitive Polluters (CPCB Orange Category)
  if (
    cat === "building_materials" ||
    cat === "textile" ||
    cat === "food" ||
    cat === "wood" ||
    cat === "waste_recycling" ||
    name.includes("concrete") ||
    name.includes("rmc") ||
    name.includes("stone") ||
    name.includes("dyeing") ||
    name.includes("boiler") ||
    name.includes("sawmill") ||
    name.includes("e-waste") ||
    name.includes("crush") ||
    sector.includes("concrete") ||
    sector.includes("dyeing") ||
    sector.includes("flour") ||
    sector.includes("timber")
  ) {
    return {
      tier: 2,
      label: "Tier 2: Moderate / Fugitive",
      badge: "🟠 TIER 2 · MODERATE (ORANGE)",
      categoryName: "Fugitive Dust / Process Boiler",
      color: "#f97316",
      pollutants: "PM10, Mineral Dust, Boiler Smoke, Solvents",
      desc: "Ready-mix batching, stone cutting, boiler steam drying & solvent vaporization.",
    };
  }

  // Tier 3: Low Direct / Ancillary (CPCB Green & White Category)
  return {
    tier: 3,
    label: "Tier 3: Ancillary & Logistics",
    badge: "🟢 TIER 3 · ANCILLARY (GREEN)",
    categoryName: "Assembly & Secondary Hub",
    color: "#a855f7",
    pollutants: "DG Set NOx, Heavy Fleet Diesel PM",
    desc: "Minimal direct stack emission; pollutes via backup diesel generators and truck fleets.",
  };
}

