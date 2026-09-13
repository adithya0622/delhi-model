"""Pure ML forecast endpoint — trained PM2.5 model + feed chemistry.

AQI here is NOT the PM2.5 sub-index alone: every hour computes all six
sub-indices (ML PM2.5, feed PM10/NO2/O3/SO2/CO) and takes the maximum, once
under CPCB 2014 breakpoints (primary, this is India) and once under US EPA
(secondary, kept for the live panel). The dominant pollutant is derived from
that maximum rather than assumed — in a Delhi winter PM2.5 nearly always wins,
but a photochemical O3 afternoon or a dust PM10 spike must be able to override
it, and the old hardcoded `dominant = "PM2.5"` made that impossible.

Concentrations are canonical µg/m³ everywhere. One unit trap is fixed at the
boundary: the Open-Meteo CAMS path delivers `chemistry["co"]` in mg/m³ while
WeatherAPI delivers µg/m³. Both are canonicalised before AQI arithmetic (which
expects µg/m³) and before `predict_pm25_series` (whose feature contract was
trained on CAMS µg/m³) — without this, the keyless fallback path fed the ML
model a CO feature 1000× off its training distribution.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Query, Request, HTTPException
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.domain.aqi_scales import _cat, _sub_index, aqi_method, aqi_standard
from app.services.ml_forecast_service import (
    aqi_model_status,
    model_status,
    predict_aqi_series,
    predict_pm25_series,
)
from app.services.weather_providers import fetch_forecast_weather
from app.services.realtime_service import fetch_iqair_realtime, fetch_weatherapi_realtime

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)

# Display name → canonical key, in the fixed order the response reports them.
_SPECIES_DISPLAY: list[tuple[str, str]] = [
    ("PM2.5", "pm25"),
    ("PM10", "pm10"),
    ("NO2", "no2"),
    ("O3", "o3"),
    ("SO2", "so2"),
    ("CO", "co"),
]

# Labelled fallbacks used when the chemistry feed has no value for a species.
# Never silently mixed into the forecast: each hour carries
# `concentration_sources` naming where every number came from.
_FALLBACK_UG_M3: dict[str, float] = {
    "pm10": 65.0 * 1.85,   # Delhi PM10/PM2.5 ratio climatology
    "no2": 24.0,
    "o3": 45.0,
    "so2": 14.0,
    "co": 450.0,           # 0.45 mg/m³, the old fallback expressed canonically
}
_FEED_LABEL = "forecast feed (WeatherAPI/CAMS)"
_FALLBACK_LABEL = "fallback climatology (feed value missing)"


def _canonicalise_chemistry(chem: dict[str, Any], weather_source: str) -> dict[str, Any]:
    """Return `chem` with every species in canonical µg/m³.

    The Open-Meteo CAMS path pre-divides carbon_monoxide by 1000 (mg/m³);
    WeatherAPI's air_quality block reports it raw (µg/m³). The ML feature
    contract was trained on CAMS µg/m³, so the keyless fallback path was
    feeding the model a CO covariate three orders of magnitude low. Fix it
    once, here, where the payload enters the application.
    """
    out: dict[str, Any] = {
        k: list(v) if isinstance(v, list) else v for k, v in chem.items()
    }
    co = out.get("co")
    if isinstance(co, list) and weather_source.startswith("open-meteo"):
        out["co"] = [None if v is None else round(float(v) * 1000.0, 2) for v in co]
    return out


def compute_hour_aqi(concentrations: dict[str, float | None], mode: str) -> dict[str, Any]:
    """AQI = max(sub-indices) for one hour under one standard.

    `concentrations` are canonical µg/m³ (CO included — `_sub_index` converts
    to each standard's published input unit at the scale boundary). Missing or
    non-finite species score sub-index 0 and therefore cannot win the max.
    """
    sub_indices: list[dict[str, Any]] = []
    for display, key in _SPECIES_DISPLAY:
        value: float | None = None
        conc = concentrations.get(key)
        if conc is not None:
            try:
                candidate = float(conc)
            except (TypeError, ValueError):
                candidate = None
            if candidate is not None and math.isfinite(candidate) and candidate >= 0:
                value = round(candidate, 2)
        idx = _sub_index(key, value, mode) if value is not None else 0
        sub_indices.append({
            "pollutant": display,
            "concentration": value,
            "concentration_unit": "µg/m³",
            "sub_index": idx,
            "category": _cat(idx, mode)[0],
        })
    best = max(sub_indices, key=lambda s: s["sub_index"])
    aqi = best["sub_index"]
    return {
        "aqi": aqi,
        "category": _cat(aqi, mode)[0],
        # "unknown" rather than a guessed species when nothing has data: an
        # all-zero hour must not be reported as PM2.5-dominated.
        "dominant_pollutant": best["pollutant"] if aqi > 0 else "unknown",
        "sub_indices": sub_indices,
    }


def _build_live_history_from_iqair(iqair_data: dict[str, Any], hours: int = 30) -> list[dict[str, Any]]:
    """Build a realistic 30-hour PM2.5 history anchored on current IQAir live reading.
    If pm25 concentration is not directly provided, inverts IQAir's AQI into PM2.5.
    """
    pm25 = iqair_data.get("pm25")
    if pm25 is None or float(pm25) <= 0:
        aqi_val = float(iqair_data.get("aqi") or 134)
        if aqi_val <= 50:
            pm25 = (aqi_val / 50.0) * 12.0
        elif aqi_val <= 100:
            pm25 = 12.1 + ((aqi_val - 51) / (100 - 51)) * (35.4 - 12.1)
        elif aqi_val <= 150:
            pm25 = 35.5 + ((aqi_val - 101) / (150 - 101)) * (55.4 - 35.5)
        elif aqi_val <= 200:
            pm25 = 55.5 + ((aqi_val - 151) / (200 - 151)) * (150.4 - 55.5)
        elif aqi_val <= 300:
            pm25 = 150.5 + ((aqi_val - 201) / (300 - 201)) * (250.4 - 150.5)
        else:
            pm25 = 250.5 + ((aqi_val - 301) / (500 - 301)) * (500.4 - 250.5)

    now = datetime.now(timezone.utc)
    history = []
    # Provide 30 hours of history to cover up to 24-hour lag + timezone shift
    for h in range(hours, -1, -1):
        t = now - timedelta(hours=h)
        hour = t.hour
        if hour < 6 or hour > 20:
            factor = 1.15  # night accumulation
        elif 10 <= hour <= 16:
            factor = 0.85  # daytime dispersion
        else:
            factor = 1.0
        history.append({
            "timestamp": t.replace(minute=0, second=0, microsecond=0).isoformat(),
            "value_ug_m3": round(float(pm25) * factor, 1),
        })
    return history


@router.get(
    "/forecast/72hr-ml",
    summary="72-hour AQI forecast from the ML PM2.5 model + feed chemistry (AQI = max of six sub-indices)",
    tags=["Forecast"],
)
@limiter.limit("30/minute")
async def forecast_72hr_ml(
    request: Request,
    lat: float = Query(28.6139, ge=28.0, le=29.0),
    lon: float = Query(77.2090, ge=76.5, le=77.8),
    station_name: str = Query("Delhi-ITO", max_length=64),
) -> dict[str, Any]:
    """
    Pure ML forecast for 72 hours.

    PM2.5 comes from the trained HistGradientBoosting model (no physics
    coupling). PM10/NO2/O3/SO2/CO come from the chemistry feed
    (WeatherAPI when keyed, Open-Meteo CAMS otherwise). Every hour reports
    the official max-of-sub-indices AQI under CPCB 2014 (primary) and US EPA
    (secondary), with the dominant pollutant derived — never assumed.
    """
    try:
        met_data = await fetch_forecast_weather(lat, lon)
        iqair_data = await fetch_iqair_realtime()
        live_history = _build_live_history_from_iqair(iqair_data, 30)
        ml_info = model_status()

        weather_source = str(met_data.get("weather_source", "unknown"))
        chem = _canonicalise_chemistry(met_data.get("chemistry") or {}, weather_source)

        forecast_times = met_data.get("hourly", {}).get("time", [])[:72]
        if not forecast_times:
            raise RuntimeError("No forecast times available from weather provider")

        # Chemistry rides on the same hourly grid as the forecast times; pass
        # the grid explicitly so predict_pm25_series can align rows by time.
        air_quality_payload = {"hourly": {"time": list(forecast_times), **chem}} if chem else None

        ml_predictions, ml_status = predict_pm25_series(
            forecast_times=forecast_times,
            weather_payload=met_data,
            air_quality_payload=air_quality_payload,
            history_rows=live_history,
            station_lat=lat,
            station_lon=lon,
        )
        # Direct-AQI heads (v4): predict the AQI number itself. When the
        # artifact is absent or was rejected by its training acceptance gates
        # this returns all-None and the hour rows fall back to the computed
        # block — the fallback is labelled per hour via `aqi_source`.
        aqi_predictions, epa_predictions, aqi_status = predict_aqi_series(
            forecast_times=forecast_times,
            weather_payload=met_data,
            air_quality_payload=air_quality_payload,
            history_rows=live_history,
        )

        hourly = met_data.get("hourly", {})
        forecast_hours: list[dict[str, Any]] = []

        for i, stamp in enumerate(forecast_times):
            # ── PM2.5 from the trained model ────────────────────────────────
            ml_pm25 = ml_predictions[i] if i < len(ml_predictions) else None
            if ml_pm25 is not None:
                p_pm25 = round(float(ml_pm25), 1)
                pm25_source = "ML model"
            else:
                p_pm25 = 65.0
                pm25_source = "fallback climatology (ML unavailable)"

            # ── Co-pollutants from the feed, labelled fallbacks when missing ─
            sources: dict[str, str] = {"PM2.5": pm25_source}

            def pick(key: str, display: str) -> float:
                values = chem.get(key) or []
                raw = values[i] if i < len(values) else None
                if raw is not None and float(raw) >= 0:
                    sources[display] = _FEED_LABEL
                    return round(float(raw), 2)
                sources[display] = _FALLBACK_LABEL
                return _FALLBACK_UG_M3[key]

            concentrations: dict[str, float | None] = {"pm25": p_pm25}
            # _SPECIES_DISPLAY tuples are (display, key) — the same order
            # compute_hour_aqi unpacks them in. Unpacking as (key, display)
            # here silently inverted both lookups (chem["PM10"],
            # _FALLBACK_UG_M3["PM10"]) and 502'd every request.
            for display, key in _SPECIES_DISPLAY[1:]:
                concentrations[key] = pick(key, display)

            # ── Computed AQI = max(sub-indices), both standards ────────────
            cpcb_block = compute_hour_aqi(concentrations, "instant")
            epa_block = compute_hour_aqi(concentrations, "epa")

            # ── Served AQI: direct v4 prediction when available ────────────
            aqi_pred = aqi_predictions[i] if i < len(aqi_predictions) else None
            epa_pred = epa_predictions[i] if i < len(epa_predictions) else None
            served_cpcb = aqi_pred if aqi_pred is not None else cpcb_block["aqi"]
            served_epa = epa_pred if epa_pred is not None else epa_block["aqi"]

            def at(name: str) -> Any:
                values = hourly.get(name) or []
                return values[i] if i < len(values) else None

            t1000 = at("temperature_1000hPa")
            t925 = at("temperature_925hPa")
            inversion_dt = round(float(t925) - float(t1000), 2) if (t1000 is not None and t925 is not None) else 0.0

            forecast_hours.append({
                "timestamp": stamp,
                # Primary AQI: the model's prediction when v4 is serving, else
                # the computed value. `aqi_source` names which one this is —
                # a predicted number and a breakpoint table entry are different
                # kinds of claims and are never blended silently.
                "aqi": served_cpcb,
                "aqi_source": "direct ML v4" if aqi_pred is not None else "computed from concentrations",
                "aqi_method": (
                    "direct ML v4 prediction (HistGradientBoosting trained against CPCB 2014 breakpoints)"
                    if aqi_pred is not None
                    else aqi_method("instant")
                ),
                "category": _cat(served_cpcb, "instant")[0],
                # Species attribution always comes from the computed sub-index
                # block: a direct AQI regressor yields no dominant species.
                "dominant_pollutant": cpcb_block["dominant_pollutant"],
                "sub_indices": cpcb_block["sub_indices"],
                # Audit trail: the same hour's breakpoint-computed AQI over the
                # six reported concentrations, on the published table.
                "aqi_computed": cpcb_block["aqi"],
                "aqi_computed_standard": aqi_standard("instant"),
                "aqi_computed_method": aqi_method("instant"),
                "concentration_sources": sources,
                "epa": {
                    "aqi": served_epa,
                    "aqi_source": "direct ML v4" if epa_pred is not None else "computed from concentrations",
                    "aqi_computed": epa_block["aqi"],
                    "aqi_standard": aqi_standard("epa"),
                    "aqi_method": aqi_method("epa"),
                    "category": _cat(served_epa, "epa")[0],
                    "dominant_pollutant": epa_block["dominant_pollutant"],
                    "sub_indices": epa_block["sub_indices"],
                },
                "pm25_source": pm25_source,
                # Meteorology (from WeatherAPI)
                "pbl_height_m": at("boundary_layer_height") or 0,
                "pbl_height_met_m": at("boundary_layer_height") or 0,
                "pbl_suppression_pct": 0,
                "inversion_delta_t": inversion_dt,
                "aerosol_optical_depth": 0,
                "aerosol_sw_forcing_w_m2": 0,
                "aerosol_dt_surface_c": 0,
                "feedback_iterations": 0,
                "wind_speed_ms": at("wind_speed_10m") or 0,
                "wind_direction_deg": at("wind_direction_10m") or 0,
                "temperature_2m_c": at("temperature_2m") or 0,
                "relative_humidity_pct": at("relative_humidity_2m") or 0,
                "precipitation_mm": at("precipitation") or 0,
                "shortwave_radiation_w_m2": at("shortwave_radiation") or 0,
                "dew_point_2m_c": at("dew_point_2m") or 0,
                "apparent_temperature_c": at("apparent_temperature") or 0,
                "precipitation_probability_pct": at("precipitation_probability") or 0,
                "rain_mm": at("rain") or 0,
                "showers_mm": at("showers") or 0,
                "visibility_m": at("visibility") or 0,
                "cloud_cover_pct": at("cloud_cover") or 0,
                "surface_pressure_hpa": at("surface_pressure") or 0,
                "pressure_msl_hpa": at("pressure_msl") or 0,
                "weather_code": int(at("weather_code") or 0),
                "wind_gusts_ms": at("wind_gusts_10m") or 0,
                "plume_contribution": 0.0,
            })

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "location": {"lat": lat, "lon": lon},
            "station_name": station_name,
            "aqi_standard": aqi_standard("instant"),
            "aqi_method": aqi_method("instant"),
            "concentration_unit": "µg/m³",
            "forecast_hours": forecast_hours,
            "model": (
                "Direct-AQI v4 (HistGradientBoosting, CPCB+EPA heads) when serving; "
                "otherwise AQI computed as max of six sub-indices over ML PM2.5 + feed chemistry"
            ),
            "ml_model": ml_status,
            "aqi_model": aqi_status,
            "weather_source": weather_source,
            "provider_failures": met_data.get("provider_failures", []),
            "live_anchor": {
                "pm25_ug_m3": live_history[-1]["value_ug_m3"] if live_history else None,
                "source": "IQAir + WeatherAPI",
            },
            "limitations": [
                "Pure ML PM2.5 — no physics coupling loop (use /forecast/72hr for the coupled run)",
                "PM10/NO2/O3/SO2/CO are feed concentrations, not ML predictions; missing feed values fall back to labelled climatology (see concentration_sources)",
                "When aqi_source is 'direct ML v4', AQI is a model prediction; aqi_computed on the same hour is the breakpoint-table value over the reported concentrations — compare them, they are different claims",
                "dominant_pollutant always comes from the computed sub-indices; the direct AQI model does not attribute species",
                "EPA block applies breakpoints to instantaneous hourly concentrations; the coupled endpoint applies NowCast / 8-hour averaging",
                "No aerosol-radiation feedback beyond what the ML model learned from training features",
                "Live history synthesized from the current IQAir reading (no true 24 h archive)",
            ],
        }

    except Exception as e:
        raise HTTPException(status_code=502, detail=f"ML forecast unavailable: {str(e)}")


@router.get(
    "/forecast/ml-status",
    summary="ML model status and held-out metrics",
    tags=["Forecast"],
)
@limiter.limit("60/minute")
async def ml_status_endpoint(request: Request) -> dict[str, Any]:
    """Return ML model status, version, and held-out test metrics."""
    return model_status()


@router.get(
    "/forecast/aqi-status",
    summary="Direct-AQI model (v4) status and acceptance gates",
    tags=["Forecast"],
)
@limiter.limit("60/minute")
async def aqi_status_endpoint(request: Request) -> dict[str, Any]:
    """Status of the direct-AQI model: version, holdout metrics, acceptance
    gates. `available: false` means /forecast/72hr-ml is serving computed AQI."""
    return aqi_model_status()
