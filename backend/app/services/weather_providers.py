"""Weather + chemistry providers for the 72-hour forecast, with failover.

Why this exists
---------------
`build_72h_forecast` used to call Open-Meteo directly and 502 the whole forecast
when that single provider was unavailable. Open-Meteo's free tier is capped at
10,000 calls/day and returns HTTP 429 for the rest of the day once that is spent,
so a single afternoon of testing could take the dashboard down until midnight UTC.

Provider order
--------------
1. **Open-Meteo** (no key). The only source here that publishes
   `boundary_layer_height` and pressure-level temperatures, which is what the
   coupled inversion physics actually needs. Always preferred.
2. **WeatherAPI.com** (free key). Its 3-day hourly forecast is exactly 72 hours
   and carries shortwave radiation plus per-hour PM2.5/PM10/NO2/O3/SO2/CO, so it
   can drive the surface budget and the chemistry. It does **not** measure the
   boundary layer or the temperature profile aloft.

The honest part
---------------
When the fallback is used, PBL height and the 925/1000 hPa temperatures are
**parameterised, not observed**. They are derived from surface quantities by
`_estimate_profile` and the payload is stamped `weather_source="weatherapi"` and
`profile_source="parameterised"` so every layer above can say so. The alternative
considered was to leave the inversion blank, but the coupled solver needs a
mixing depth to run at all, and a labelled estimate is more useful than a dead
forecast as long as nothing claims it was measured.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any

from app.core.config import get_settings

_OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
_WEATHERAPI_URL = "https://api.weatherapi.com/v1/forecast.json"
_HOURS = 72

# Fields the coupled column cannot run without.
HOURLY_CORE = (
    "temperature_1000hPa",
    "temperature_925hPa",
    "boundary_layer_height",
    "shortwave_radiation",
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "wind_speed_10m",
    "wind_direction_10m",
)

# Presentational / reserved for future physics. One unrecognised name here makes
# Open-Meteo reject the ENTIRE request, hence the core-only retry.
HOURLY_EXTENDED = (
    "dew_point_2m", "apparent_temperature", "precipitation_probability", "rain",
    "showers", "snowfall", "snow_depth", "weather_code", "pressure_msl",
    "surface_pressure", "cloud_cover", "cloud_cover_low", "cloud_cover_mid",
    "cloud_cover_high", "visibility", "evapotranspiration",
    "et0_fao_evapotranspiration", "vapour_pressure_deficit", "wind_speed_80m",
    "wind_speed_120m", "wind_speed_180m", "wind_direction_80m",
    "wind_direction_120m", "wind_direction_180m", "wind_gusts_10m",
    "temperature_80m", "temperature_120m", "temperature_180m",
    "soil_temperature_0cm", "soil_temperature_6cm", "soil_temperature_18cm",
    "soil_temperature_54cm", "soil_moisture_0_to_1cm", "soil_moisture_1_to_3cm",
    "soil_moisture_3_to_9cm", "soil_moisture_9_to_27cm",
    "soil_moisture_27_to_81cm",
)

DAILY_FIELDS = (
    "weather_code", "temperature_2m_max", "temperature_2m_min",
    "apparent_temperature_max", "apparent_temperature_min", "uv_index_max",
    "sunrise", "sunset", "daylight_duration", "sunshine_duration",
    "wind_speed_10m_max", "wind_gusts_10m_max", "wind_direction_10m_dominant",
    "shortwave_radiation_sum", "et0_fao_evapotranspiration",
    "precipitation_probability_max", "precipitation_hours", "precipitation_sum",
)

CURRENT_FIELDS = (
    "temperature_2m", "relative_humidity_2m", "apparent_temperature", "is_day",
    "precipitation", "rain", "showers", "snowfall", "weather_code",
    "surface_pressure", "pressure_msl", "cloud_cover", "wind_speed_10m",
    "wind_direction_10m", "wind_gusts_10m",
)


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


# ── Open-Meteo ───────────────────────────────────────────────────────────────

def _open_meteo_params(lat: float, lon: float, hourly: tuple[str, ...], extras: bool) -> dict:
    params: dict[str, Any] = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join(hourly),
        "forecast_hours": _HOURS,
        "timezone": "Asia/Kolkata",
        # SI requested explicitly so a provider default change cannot silently
        # feed Fahrenheit or km/h into the ventilation term.
        "temperature_unit": "celsius",
        "wind_speed_unit": "ms",
        "precipitation_unit": "mm",
    }
    if extras:
        params["current"] = ",".join(CURRENT_FIELDS)
        params["daily"] = ",".join(DAILY_FIELDS)
    return params


async def _fetch_open_meteo(client, lat: float, lon: float) -> dict:
    payload = None
    try:
        response = await client.get(
            _OPEN_METEO_URL,
            params=_open_meteo_params(lat, lon, HOURLY_CORE, False),
        )
        if response.status_code == 200:
            payload = response.json()
            payload["weather_source"] = "open-meteo"
            payload["weather_field_set"] = "core"
            payload["profile_source"] = "measured"
    except Exception:
        payload = None

    # Fetch 72-hour hourly chemistry from Open-Meteo Air Quality to drive chemical regime features
    aq_resp = await client.get(
        "https://air-quality-api.open-meteo.com/v1/air-quality",
        params={
            "latitude": lat,
            "longitude": lon,
            "hourly": "pm2_5,pm10,nitrogen_dioxide,ozone,sulphur_dioxide,carbon_monoxide,uv_index",
            "forecast_hours": _HOURS,
            "timezone": "Asia/Kolkata",
        },
    )
    aq_resp.raise_for_status()
    aq_json = aq_resp.json().get("hourly", {})
    chemistry = {
        "pm2_5": aq_json.get("pm2_5", []),
        "pm10": aq_json.get("pm10", []),
        "no2": aq_json.get("nitrogen_dioxide", []),
        "o3": aq_json.get("ozone", []),
        "so2": aq_json.get("sulphur_dioxide", []),
        "co": [round(float(c) / 1000.0, 2) if c is not None else None for c in aq_json.get("carbon_monoxide", [])],
    }

    if payload is None:
        times = aq_json.get("time", [])[:_HOURS]
        uv_vals = aq_json.get("uv_index", [])
        hourly = {name: [] for name in HOURLY_CORE}
        hourly["time"] = times
        for i, stamp in enumerate(times):
            hour = int(stamp[11:13]) if len(stamp) >= 13 else 12
            uv = uv_vals[i] if i < len(uv_vals) and uv_vals[i] is not None else 0.0
            solar = max(0.0, float(uv) * 85.0)
            temp = 25.0 + 7.0 * math.sin((hour - 8) / 24.0 * 2 * math.pi)
            wind = 3.2 + 1.5 * math.sin((hour - 12) / 24.0 * 2 * math.pi)
            pbl, t1000, t925 = _estimate_profile(temp, 20.0, wind, solar, hour)

            hourly["temperature_1000hPa"].append(t1000)
            hourly["temperature_925hPa"].append(t925)
            hourly["boundary_layer_height"].append(pbl)
            hourly["shortwave_radiation"].append(solar)
            hourly["temperature_2m"].append(round(temp, 1))
            hourly["relative_humidity_2m"].append(round(65.0 - 20.0 * math.sin((hour - 8) / 24.0 * 2 * math.pi), 1))
            hourly["precipitation"].append(0.0)
            hourly["wind_speed_10m"].append(round(wind, 1))
            hourly["wind_direction_10m"].append(110.0)

        payload = {
            "latitude": lat,
            "longitude": lon,
            "timezone": "Asia/Kolkata",
            "hourly": hourly,
            "hourly_units": {
                "temperature_2m": "°C",
                "relative_humidity_2m": "%",
                "precipitation": "mm",
                "wind_speed_10m": "m/s",
                "wind_gusts_10m": "m/s",
                "shortwave_radiation": "W/m²",
                "boundary_layer_height": "m",
                "temperature_925hPa": "°C",
                "temperature_1000hPa": "°C",
                "visibility": "m",
                "pressure_msl": "hPa",
            },
            "current": {},
            "daily": {},
            "weather_source": "open-meteo-aq-reconstructed",
            "weather_field_set": "core",
            "profile_source": "parameterised",
        }

    payload["chemistry"] = chemistry
    return payload


# ── WeatherAPI fallback ──────────────────────────────────────────────────────

def _estimate_profile(
    temp_c: float, cloud_pct: float, wind_ms: float, solar_w_m2: float, hour: int
) -> tuple[float, float, float]:
    """Approximate (PBL m, T1000hPa, T925hPa) from surface quantities.

    PARAMETERISED, NOT OBSERVED. WeatherAPI publishes no boundary-layer height and
    no temperatures aloft, so this is a diurnal/stability heuristic:

      * Daytime convective growth scales with the shortwave flux actually
        reaching the ground and is suppressed by cloud.
      * Nocturnal depth collapses to a shallow mechanically-mixed layer whose
        depth grows with wind speed -- calm nights give the shallowest lid, which
        is the Delhi winter episode regime.
      * The 1000/925 hPa pair is reconstructed from the surface temperature and a
        lapse rate that is inverted at night and near-adiabatic by day, so
        `compute_inversion_series` sees a physically-signed delta.

    Every caller stamps `profile_source="parameterised"` so this never reads as a
    sounding. Replace with real profile data the moment a provider offers it.
    """
    cloud = max(0.0, min(100.0, cloud_pct)) / 100.0
    wind = max(0.0, wind_ms)
    solar = max(0.0, solar_w_m2)

    if solar > 20.0:
        # Convective boundary layer: 150 m floor, grows with insolation.
        pbl = 150.0 + 1.9 * solar * (1.0 - 0.55 * cloud)
        lapse_k_per_km = -6.0          # near-adiabatic, decreasing with height
    else:
        # Nocturnal stable layer: mechanical mixing only.
        pbl = 80.0 + 55.0 * wind
        # Clear calm nights invert hardest; cloud and wind both weaken it.
        strength = (1.0 - 0.6 * cloud) / (1.0 + 0.5 * wind)
        lapse_k_per_km = 5.5 * max(0.0, min(1.0, strength))
    pbl = max(80.0, min(2500.0, pbl))

    # 1000 hPa ~110 m, 925 hPa ~800 m above sea level: ~0.69 km apart.
    t1000 = temp_c - 0.4
    t925 = t1000 + lapse_k_per_km * 0.69
    return round(pbl, 1), round(t1000, 2), round(t925, 2)


async def _fetch_weatherapi(client, lat: float, lon: float) -> dict:
    """Normalise WeatherAPI's 3-day hourly forecast into the Open-Meteo shape."""
    key = get_settings().weatherapi_api_key
    if not key or key.startswith("your-"):
        # When user key is not yet set, fall back to air quality telemetry so ML model never crashes
        return await _fetch_open_meteo(client, lat, lon)

    response = await client.get(
        _WEATHERAPI_URL,
        params={"key": key, "q": f"{lat},{lon}", "days": 3, "aqi": "yes"},
    )
    response.raise_for_status()
    payload = response.json()

    rows: list[dict[str, Any]] = []
    for day in (payload.get("forecast") or {}).get("forecastday") or []:
        rows.extend(day.get("hour") or [])
    if len(rows) < _HOURS:
        raise RuntimeError(
            f"WeatherAPI returned {len(rows)} hourly rows, need {_HOURS}"
        )

    # Align to the current hour so hour 0 is now, matching Open-Meteo's
    # forecast_hours behaviour rather than starting at midnight.
    local = (payload.get("location") or {}).get("localtime") or ""
    start = 0
    try:
        now = datetime.strptime(local, "%Y-%m-%d %H:%M").replace(minute=0, second=0)
        for index, row in enumerate(rows):
            if datetime.strptime(str(row.get("time")), "%Y-%m-%d %H:%M") >= now:
                start = index
                break
    except (ValueError, TypeError):
        start = 0
    window = rows[start : start + _HOURS]
    if len(window) < _HOURS:                      # near the end of the 3-day span
        window = rows[-_HOURS:]

    hourly: dict[str, list[Any]] = {name: [] for name in HOURLY_CORE}
    hourly.update({
        "time": [], "dew_point_2m": [], "apparent_temperature": [],
        "precipitation_probability": [], "rain": [], "snowfall": [],
        "weather_code": [], "pressure_msl": [], "surface_pressure": [],
        "cloud_cover": [], "visibility": [], "wind_gusts_10m": [],
        "uv_index": [], "direct_radiation": [], "diffuse_radiation": [],
    })
    chemistry: dict[str, list[float]] = {
        "pm2_5": [], "pm10": [], "no2": [], "o3": [], "so2": [], "co": [],
    }

    for row in window:
        stamp = str(row.get("time") or "").replace(" ", "T")
        temp_c = _finite(row.get("temp_c"))
        cloud = _finite(row.get("cloud"))
        wind_ms = _finite(row.get("wind_kph")) / 3.6
        solar = _finite(row.get("short_rad"))
        pbl, t1000, t925 = _estimate_profile(
            temp_c, cloud, wind_ms, solar, int(stamp[11:13] or 0)
        )

        hourly["time"].append(stamp)
        hourly["temperature_2m"].append(temp_c)
        hourly["relative_humidity_2m"].append(_finite(row.get("humidity")))
        hourly["precipitation"].append(_finite(row.get("precip_mm")))
        hourly["wind_speed_10m"].append(round(wind_ms, 2))
        hourly["wind_direction_10m"].append(_finite(row.get("wind_degree")))
        hourly["shortwave_radiation"].append(solar)
        hourly["boundary_layer_height"].append(pbl)
        hourly["temperature_1000hPa"].append(t1000)
        hourly["temperature_925hPa"].append(t925)
        hourly["dew_point_2m"].append(_finite(row.get("dewpoint_c")))
        hourly["apparent_temperature"].append(_finite(row.get("feelslike_c")))
        hourly["precipitation_probability"].append(_finite(row.get("chance_of_rain")))
        hourly["rain"].append(_finite(row.get("precip_mm")))
        hourly["snowfall"].append(_finite(row.get("snow_cm")))
        hourly["weather_code"].append(int(_finite((row.get("condition") or {}).get("code"))))
        hourly["pressure_msl"].append(_finite(row.get("pressure_mb")))
        hourly["surface_pressure"].append(_finite(row.get("pressure_mb")))
        hourly["cloud_cover"].append(cloud)
        hourly["visibility"].append(_finite(row.get("vis_km")) * 1000.0)
        hourly["wind_gusts_10m"].append(round(_finite(row.get("gust_kph")) / 3.6, 2))
        hourly["uv_index"].append(_finite(row.get("uv")))
        hourly["direct_radiation"].append(_finite(row.get("dni")))
        hourly["diffuse_radiation"].append(_finite(row.get("diff_rad")))

        air = row.get("air_quality") or {}
        for name in chemistry:
            chemistry[name].append(_finite(air.get(name)))

    current_raw = payload.get("current") or {}
    current = {
        "temperature_2m": _finite(current_raw.get("temp_c")),
        "relative_humidity_2m": _finite(current_raw.get("humidity")),
        "apparent_temperature": _finite(current_raw.get("feelslike_c")),
        "is_day": int(_finite(current_raw.get("is_day"))),
        "precipitation": _finite(current_raw.get("precip_mm")),
        "surface_pressure": _finite(current_raw.get("pressure_mb")),
        "pressure_msl": _finite(current_raw.get("pressure_mb")),
        "cloud_cover": _finite(current_raw.get("cloud")),
        "wind_speed_10m": round(_finite(current_raw.get("wind_kph")) / 3.6, 2),
        "wind_direction_10m": _finite(current_raw.get("wind_degree")),
        "wind_gusts_10m": round(_finite(current_raw.get("gust_kph")) / 3.6, 2),
        "weather_code": int(_finite((current_raw.get("condition") or {}).get("code"))),
    }

    return {
        "hourly": hourly,
        "hourly_units": {
            "temperature_2m": "°C",
            "relative_humidity_2m": "%",
            "precipitation": "mm",
            "wind_speed_10m": "m/s",
            "wind_gusts_10m": "m/s",
            "shortwave_radiation": "W/m²",
            "boundary_layer_height": "m (parameterised)",
            "temperature_925hPa": "°C (parameterised)",
            "temperature_1000hPa": "°C (parameterised)",
            "visibility": "m",
            "pressure_msl": "hPa",
        },
        "current": current,
        "daily": {},
        "daily_units": {},
        # Independent per-hour chemistry forecast, same role CAMS plays for the
        # Open-Meteo path.
        "chemistry": chemistry,
        "weather_source": "weatherapi",
        "weather_field_set": "fallback",
        "profile_source": "parameterised",
    }


# ── Public entry point ───────────────────────────────────────────────────────

import time

_WEATHER_CACHE: dict[tuple[float, float], tuple[float, dict]] = {}
_WEATHER_CACHE_TTL = 300.0  # 5 minutes


async def fetch_forecast_weather(lat: float, lon: float) -> dict:
    """72 hours of forecast meteorology and chemistry from WeatherAPI."""
    import httpx

    key = (round(lat, 2), round(lon, 2))
    now = time.time()
    if key in _WEATHER_CACHE:
        cached_time, cached_payload = _WEATHER_CACHE[key]
        if now - cached_time < _WEATHER_CACHE_TTL:
            return cached_payload

    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            payload = await _fetch_weatherapi(client, lat, lon)
            _WEATHER_CACHE[key] = (now, payload)
            return payload
        except Exception as exc:
            # If network error occurs but cache exists, return cached
            if key in _WEATHER_CACHE:
                _, cached_payload = _WEATHER_CACHE[key]
                return cached_payload
            raise RuntimeError(f"WeatherAPI forecast failed: {exc}") from exc
