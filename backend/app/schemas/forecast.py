"""
Pydantic schemas for all request/response models.
Strict validation — no extra fields accepted on input.
"""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, model_validator

# Re-exported for backwards compatibility: `AQICategory` and `Pollutant` now live
# in app.domain.species so the physics core does not have to import pydantic and
# the whole response layer just to name a species.
from app.domain.species import AQICategory, Pollutant

__all__ = [
    "AQICategory",
    "Pollutant",
    "DelhiBBox",
    "PollutantSubIndex",
    # The hourly model is HourlyForecast, not ForecastHour. An earlier version of
    # this list said "ForecastHour", which does not exist -- `import *` would have
    # raised AttributeError at import time. Nothing star-imports this module today,
    # so it was latent; kept correct now so it stays that way.
    "HourlyForecast",
    "ForecastResponse",
    "InversionStatus",
    "FireHotspot",
    "PlumeVector",
    "PlumeVectorsResponse",
    "StationObservation",
]


# ── Coordinate bounding box ───────────────────────────────────────────────────

class DelhiBBox(BaseModel):
    """Validated lat/lon bounding box restricted to Delhi NCR region."""
    model_config = {"extra": "forbid"}

    lat: Annotated[float, Field(ge=28.0, le=29.0, description="Latitude (Delhi NCR: 28.0–29.0°N)")]
    lon: Annotated[float, Field(ge=76.5, le=77.8, description="Longitude (Delhi NCR: 76.5–77.8°E)")]

    @model_validator(mode="after")
    def check_inside_ncr(self) -> "DelhiBBox":
        # Rough polygon check — NCR spans 28.4–28.9°N, 76.8–77.5°E at core
        # We allow the wider bbox above; this catches obvious misuse
        if self.lat < 27.5 or self.lat > 30.0:
            raise ValueError("Latitude out of plausible NCR range")
        return self


# ── Sub-index per pollutant ───────────────────────────────────────────────────

class PollutantSubIndex(BaseModel):
    pollutant: Pollutant
    concentration: float  # canonical µg/m³ for every pollutant
    concentration_unit: str = "µg/m³"
    aqi_concentration: float = 0.0
    aqi_unit: str = "µg/m³"
    sub_index: int        # 0–500 selected scale
    category: AQICategory


# ── Single forecast hour ──────────────────────────────────────────────────────

class HourlyForecast(BaseModel):
    timestamp: datetime
    aqi: int = Field(ge=0, le=500)
    aqi_standard: str = "US EPA AQI Scale (2024)"
    aqi_method: str = "EPA breakpoints applied to hourly concentrations"
    pm25_source: str = "coupled physics model"
    category: AQICategory
    dominant_pollutant: Pollutant
    sub_indices: list[PollutantSubIndex]

    # ── Meteorology → chemistry ──────────────────────────────────────────────
    pbl_height_m: float          # mixing depth AFTER the aerosol feedback
    inversion_delta_t: float     # T925hPa - T1000hPa (°C) — positive = inversion
    wind_speed_ms: float
    wind_direction_deg: float
    temperature_2m_c: float
    relative_humidity_pct: float = Field(ge=0, le=100)
    precipitation_mm: float = Field(ge=0)
    shortwave_radiation_w_m2: float = Field(ge=0)
    dew_point_2m_c: float = 0.0
    apparent_temperature_c: float = 0.0
    precipitation_probability_pct: float = Field(default=0.0, ge=0, le=100)
    rain_mm: float = Field(default=0.0, ge=0)
    showers_mm: float = Field(default=0.0, ge=0)
    visibility_m: float = Field(default=0.0, ge=0)
    cloud_cover_pct: float = Field(default=0.0, ge=0, le=100)
    surface_pressure_hpa: float = Field(default=0.0, ge=0)
    pressure_msl_hpa: float = Field(default=0.0, ge=0)
    weather_code: int = 0
    wind_gusts_ms: float = Field(default=0.0, ge=0)

    # ── Chemistry → meteorology (the return leg of the two-way coupling) ─────
    # Exposed so the feedback is auditable rather than buried in the AQI number.
    pbl_height_met_m: float = 0.0        # unperturbed PBL straight from the met model
    pbl_suppression_pct: float = 0.0     # % of mixing depth removed by aerosol
    aerosol_optical_depth: float = 0.0   # column AOD from the PM2.5 profile
    aerosol_sw_forcing_w_m2: float = 0.0 # surface shortwave removed (≤ 0)
    aerosol_dt_surface_c: float = 0.0    # surface temperature change (≤ 0)
    feedback_iterations: int = 1         # Picard iterations to convergence
    # The wind leg: hour i's surface wind after hour i-1's aerosol cooling
    # weakened momentum mixing. `wind_perturbation_frac` is the fractional
    # change (≤ 0); `wind_effective_ms` is what the box model's ventilation
    # term actually used, which can be below `wind_speed_ms`.
    wind_effective_ms: float = 0.0
    wind_perturbation_frac: float = 0.0

    plume_contribution: float    # Fraction of AQI from stubble-burn plume (0–1)


# ── 72-hour forecast response ─────────────────────────────────────────────────

class ForecastResponse(BaseModel):
    generated_at: datetime
    location: DelhiBBox
    station_name: str
    aqi_standard: str = "US EPA AQI Scale (2024)"
    aqi_method: str = "EPA breakpoints applied to hourly concentrations"
    concentration_unit: str = "µg/m³"
    forecast_hours: list[HourlyForecast] = Field(min_length=72, max_length=72)
    model: str = "hybrid trained PM2.5 + coupled two-reservoir physics surrogate"
    ml_model: dict = Field(default_factory=dict)
    current_weather: dict = Field(default_factory=dict)
    weather_units: dict = Field(default_factory=dict)
    # Raw provider arrays (hourly) and daily aggregates, passed through so the
    # extended Open-Meteo fields — soil, cloud layers, 80/120/180 m wind and
    # temperature profile, evapotranspiration, UV, sunrise/sunset — are available
    # without a schema field per name. `weather_units`/`daily_units` label them.
    hourly_weather: dict = Field(default_factory=dict)
    daily_weather: dict = Field(default_factory=dict)
    daily_units: dict = Field(default_factory=dict)
    # "expanded" normally; "core" if the provider rejected the extended field set
    # and the request fell back to the fields the coupled column requires.
    weather_field_set: str = "expanded"
    # Which provider supplied the meteorology, and whether the boundary layer and
    # temperatures aloft were measured (Open-Meteo) or parameterised from surface
    # fields (WeatherAPI fallback). "parameterised" means the inversion strength
    # is an estimate, not a sounding.
    weather_source: str = "open-meteo"
    profile_source: str = "measured"        # measured | parameterised
    provider_failures: list[str] = Field(default_factory=list)
    spatial_resolution: str = "point forecast; no horizontal chemistry grid"
    validation_status: str = "unvalidated"
    limitations: list[str] = Field(default_factory=list)


# ── Inversion status response ─────────────────────────────────────────────────

class InversionStatus(BaseModel):
    timestamp: datetime
    delta_t_celsius: float       # T925hPa - T1000hPa
    pbl_height_m: float          # met-model mixing depth, no aerosol feedback applied
    lapse_rate_k_per_km: float   # Environmental lapse rate; negative = inverted
    inversion_present: bool
    severity: str                # "None" | "Weak" | "Moderate" | "Strong"
    # Diagnostic only: 1200 m / pbl_height_m, i.e. how compressed the layer is.
    # It is NOT the mechanism that produces concentrations any more -- the
    # prognostic box model is. Reported so the dashboard can show the compression.
    aqi_amplification_factor: float


# ── Plume vector response ─────────────────────────────────────────────────────

class FireHotspot(BaseModel):
    lat: float
    lon: float
    frp_mw: float                # Fire Radiative Power in MW
    source_state: str            # e.g. "Punjab" | "Haryana" | "Uttar Pradesh"
    detected_at: datetime
    confidence: str = ""         # VIIRS "l"/"n"/"h", or MODIS 0–100


class PlumeVector(BaseModel):
    origin: FireHotspot
    trajectory: list[tuple[float, float]]  # (lat, lon) waypoints, hourly
    arrival_delhi_t_hours: float | None     # None if plume misses Delhi
    # Concentration this plume adds to the transport layer (µg/m³). How much of
    # it reaches the surface depends on Delhi's mixing depth that hour, which the
    # box model resolves — so this is the layer value, not a surface value.
    pm25_contribution_ug_m3: float
    pm25_column_ug_m2: float = 0.0          # column loading delivered over Delhi
    closest_approach_km: float = 0.0        # min distance of the trajectory to Delhi
    travel_distance_km: float = 0.0         # along-trajectory path to that point


class PlumeVectorsResponse(BaseModel):
    timestamp: datetime
    wind_850hpa_u: float         # u-component m/s at 850 hPa (hour 0)
    wind_850hpa_v: float         # v-component m/s at 850 hPa (hour 0)
    hotspots: list[FireHotspot]
    plumes: list[PlumeVector]
    # Hourly 850 hPa wind used to advect the trajectories. Declared so it is
    # actually serialised — previously the service computed it and Pydantic
    # silently dropped it from the response.
    wind_series: list[tuple[float, float]] = []
    # Detections found, before truncation to the largest contributors in
    # `plumes`. Emissions are summed over all of them, so this is the honest
    # fire count for the dashboard.
    hotspot_count_total: int = 0
    # Per-hour aggregate smoke concentration in the transport layer (µg/m³),
    # 72 entries. This is what the forecast consumes.
    pm25_profile_ug_m3: list[float] = []
    # Feed provenance. An empty `hotspots` list is ambiguous on its own -- it can
    # mean no fires, no API key, or a provider outage -- so the status is declared
    # rather than left for the UI to guess.
    fire_source: str = "VIIRS_SNPP_NRT"
    fire_source_status: str = "ok"        # ok | not_configured | unavailable
    transport_wind_status: str = "open-meteo-850hpa"  # or climatological-fallback


# ── Ingestion (mutation) schema ───────────────────────────────────────────────

class StationObservation(BaseModel):
    """POST body for ingesting a live station reading."""
    model_config = {"extra": "forbid"}

    station_id: str = Field(min_length=2, max_length=64)
    location: DelhiBBox
    timestamp: datetime
    pm25: float = Field(ge=0, le=1000)
    pm10: float = Field(ge=0, le=1000)
    no2: float = Field(ge=0, le=500)
    o3: float = Field(ge=0, le=500)
    so2: float = Field(ge=0, le=500)
    co: float = Field(ge=0, le=100000, description="CO in canonical µg/m³")


# ── Exposure Tracker & Activity Planner Schemas ───────────────────────────────

class ExposureRequest(BaseModel):
    activity_type: str = Field(default="heavy", description="Activity type: resting, moderate, heavy")
    duration_hours: float = Field(default=1.0, ge=0.1, le=24.0, description="Duration in hours")
    target_time: str = Field(default="+0h", description="Target start time e.g. +0h, +24h")
    current_pm25: float = Field(default=50.0, ge=0.0, le=1000.0, description="Current or base PM2.5 in µg/m³")
    forecast_72h: list[dict] = Field(default_factory=list, description="Optional 72-hour forecast points array")


class SmartSchedule(BaseModel):
    recommended_hour: str
    recommended_timestamp: str
    optimal_avg_pm25: float
    target_avg_pm25: float | None = None
    projected_exposure_reduction_percent: int
    advice_string: str


class ExposureResponse(BaseModel):
    inhaled_mass_mcg: float
    cigarettes_equivalent: float
    health_warning: str
    smart_schedule: SmartSchedule
    activity_metadata: dict | None = None


# ── Dynamic Source Apportionment Schemas ──────────────────────────────────────

class VehicleBreakdown(BaseModel):
    heavy_trucks_pct: float = Field(description="Heavy commercial vehicles % of transport")
    two_three_wheelers_pct: float = Field(description="Two & three-wheelers % of transport")
    cars_pct: float = Field(description="Cars & light vehicles % of transport")
    heavy_trucks_mcg: float = Field(description="Heavy trucks PM2.5 contribution in µg/m³")
    two_three_wheelers_mcg: float = Field(description="2/3-Wheelers PM2.5 contribution in µg/m³")
    cars_mcg: float = Field(description="Cars PM2.5 contribution in µg/m³")


class SourceApportionmentResponse(BaseModel):
    total_pm25: float = Field(description="Total PM2.5 concentration in µg/m³")
    transport_pct: float = Field(description="Vehicular transport share % — the only chemistry-driven sector")
    dust_pct: float = Field(description="Road & soil dust share % — fixed climatological share")
    biomass_pct: float = Field(description="Biomass share % — fixed climatological share, NOT FIRMS-derived")
    industry_pct: float = Field(description="Industrial & power plant share % — fixed climatological share")
    transport_mcg: float = Field(description="Transport PM2.5 mass in µg/m³")
    dust_mcg: float = Field(description="Dust PM2.5 mass in µg/m³")
    biomass_mcg: float = Field(description="Biomass PM2.5 mass in µg/m³")
    industry_mcg: float = Field(description="Industry PM2.5 mass in µg/m³")
    vehicle_breakdown: VehicleBreakdown = Field(description="Fleet sub-breakdown for transport sector")
    proxy_status: str = Field(description="NO2 chemical proxy diagnosis and fleet time rule")
    method_basis: str = Field(default="", description="What is measured vs assumed in this split")


class ApportionmentHour(BaseModel):
    timestamp: str = Field(description="Formatted day & time e.g. Tue 14:00")
    total_pm25: float = Field(description="Total hourly forecasted PM2.5 in µg/m³")
    dust_mcg: float = Field(description="Road and soil dust contribution in µg/m³")
    biomass_mcg: float = Field(description="Biomass contribution in µg/m³ (fixed share, not FIRMS-derived)")
    industry_mcg: float = Field(description="Industrial & point-source contribution in µg/m³")
    trucks_mcg: float = Field(description="Heavy diesel commercial trucks contribution in µg/m³")
    two_wheelers_mcg: float = Field(description="Two & three-wheelers contribution in µg/m³")
    cars_mcg: float = Field(description="Cars & light vehicles contribution in µg/m³")


class SourceTimeSeriesResponse(BaseModel):
    forecast: list[ApportionmentHour] = Field(description="72-hour hourly sector-mix trajectory")
    method_basis: str = Field(default="", description="What is measured vs assumed in this split")


# ── City-Wide Aggregate Schemas ───────────────────────────────────────────────

class PollutantDetail(BaseModel):
    index: int = Field(description="AQI sub-index for this pollutant")
    conc: float = Field(description="Aggregate concentration value")
    unit: str = Field(default="µg/m³", description="Canonical measurement unit")
    aqi_conc: float = Field(default=0.0, description="Value used at AQI breakpoint boundary")
    aqi_unit: str = Field(default="µg/m³", description="Published AQI breakpoint unit")


class CityAggregateResponse(BaseModel):
    location_label: str = Field(description="Unified city network label")
    station_count: int = Field(description="Number of current reporting monitors")
    overall_aqi: int = Field(description="Overall maximum headline AQI")
    aqi_standard: str = Field(default="US EPA AQI Scale (2024)")
    aqi_method: str = Field(default="EPA breakpoints applied to hourly concentrations")
    aqi_category: str = Field(description="Selected AQI category label")
    dominant_pollutant: str = Field(description="Dominant pollutant driving the maximum AQI, e.g. 'O3'")
    color: str = Field(description="AQI tier hex color")
    sub_indices: dict[str, PollutantDetail] = Field(description="Pollutant sub-indices and concentrations")
    iqair_aqi: int | None = Field(default=None, description="Independent IQAir city-model AQI, for cross-reference only — never the headline")
    timestamp: str = Field(description="ISO timestamp of aggregate computation")
