"""Shared PM2.5 feature contract for offline training and live inference.

Two contracts live here:

* ``FEATURE_NAMES`` (v1) — the legacy contract used by the original artifact.
  Kept only so the loader can still reject mismatched artifacts cleanly.
* ``V2_FEATURE_NAMES`` — the current contract. Its defining property is a
  LEAKAGE GUARANTEE: no feature may carry the target quantity (CAMS pm2_5 or
  us_aqi) at the TARGET hour. Everything else — pm2.5 history at or before the
  forecast origin, CAMS co-pollutant forecast fields at the target hour,
  archived HRES meteorology at the target hour, lead and calendar encodings —
  is information that exists at issue time in live serving. The guard is
  enforced by test_ml_contract.py, not by convention.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

FEATURE_NAMES = [
    "station_lat",
    "station_lon",
    "lead_hours",
    "current_pm25",
    "lag1_pm25",
    "lag3_pm25",
    "lag6_pm25",
    "lag12_pm25",
    "lag24_pm25",
    "mean6_pm25",
    "mean24_pm25",
    "std24_pm25",
    "trend3_pm25",
    "cams_pm25",
    "cams_origin_pm25",
    "cams_change_pm25",
    "nudged_cams_12h",
    "nudged_cams_24h",
    "nudged_cams_48h",
    "temperature_2m_c",
    "relative_humidity_pct",
    "precipitation_mm",
    "pbl_height_m",
    "shortwave_radiation_w_m2",
    "wind_speed_ms",
    "wind_direction_sin",
    "wind_direction_cos",
    "inversion_delta_t_c",
    "ventilation_m2_s",
    "target_hour_sin",
    "target_hour_cos",
    "target_year_sin",
    "target_year_cos",
]


def _value(mapping: dict[str, Any], key: str) -> float:
    try:
        value = float(mapping.get(key))
    except (TypeError, ValueError):
        return float("nan")
    return value if math.isfinite(value) else float("nan")


def build_pm25_features(
    *,
    station_lat: float,
    station_lon: float,
    lead_hours: int,
    target_time: datetime,
    history: dict[str, float],
    cams_pm25: float,
    cams_origin_pm25: float,
    weather: dict[str, Any],
) -> list[float]:
    """Build one feature row in `FEATURE_NAMES` order."""
    current = _value(history, "current_pm25")
    cams_target = float(cams_pm25)
    cams_origin = float(cams_origin_pm25)
    wind_speed = _value(weather, "wind_speed_10m")
    wind_direction = math.radians(_value(weather, "wind_direction_10m"))
    pbl = _value(weather, "boundary_layer_height")
    t1000 = _value(weather, "temperature_1000hPa")
    t925 = _value(weather, "temperature_925hPa")
    hour_angle = 2.0 * math.pi * target_time.hour / 24.0
    year_angle = 2.0 * math.pi * (target_time.timetuple().tm_yday - 1) / 365.25

    features = {
        "station_lat": float(station_lat),
        "station_lon": float(station_lon),
        "lead_hours": float(lead_hours),
        "current_pm25": current,
        "lag1_pm25": _value(history, "lag1_pm25"),
        "lag3_pm25": _value(history, "lag3_pm25"),
        "lag6_pm25": _value(history, "lag6_pm25"),
        "lag12_pm25": _value(history, "lag12_pm25"),
        "lag24_pm25": _value(history, "lag24_pm25"),
        "mean6_pm25": _value(history, "mean6_pm25"),
        "mean24_pm25": _value(history, "mean24_pm25"),
        "std24_pm25": _value(history, "std24_pm25"),
        "trend3_pm25": _value(history, "trend3_pm25"),
        "cams_pm25": cams_target,
        "cams_origin_pm25": cams_origin,
        "cams_change_pm25": cams_target - cams_origin,
        "nudged_cams_12h": cams_target + (current - cams_origin) * math.exp(-lead_hours / 12.0),
        "nudged_cams_24h": cams_target + (current - cams_origin) * math.exp(-lead_hours / 24.0),
        "nudged_cams_48h": cams_target + (current - cams_origin) * math.exp(-lead_hours / 48.0),
        "temperature_2m_c": _value(weather, "temperature_2m"),
        "relative_humidity_pct": _value(weather, "relative_humidity_2m"),
        "precipitation_mm": _value(weather, "precipitation"),
        "pbl_height_m": pbl,
        "shortwave_radiation_w_m2": _value(weather, "shortwave_radiation"),
        "wind_speed_ms": wind_speed,
        "wind_direction_sin": math.sin(wind_direction),
        "wind_direction_cos": math.cos(wind_direction),
        "inversion_delta_t_c": t925 - t1000,
        "ventilation_m2_s": wind_speed * pbl,
        "target_hour_sin": math.sin(hour_angle),
        "target_hour_cos": math.cos(hour_angle),
        "target_year_sin": math.sin(year_angle),
        "target_year_cos": math.cos(year_angle),
    }
    return [features[name] for name in FEATURE_NAMES]


# ── V2 contract (current) ────────────────────────────────────────────────────

# CAMS hourly variables the training/live pipelines consume. pm2_5 appears here
# as TRUTH and as ORIGIN history only — never as a target-hour feature.
CHEMISTRY_HOURLY_VARS = ("pm2_5", "pm10", "no2", "o3", "so2", "co")

V2_FEATURE_NAMES = [
    # forecast configuration
    "lead_hours",
    # pm2.5 history at/before the origin (same series family as live anchoring)
    "current_pm25",
    "lag1_pm25",
    "lag3_pm25",
    "lag6_pm25",
    "lag12_pm25",
    "lag24_pm25",
    "mean6_pm25",
    "mean24_pm25",
    "std24_pm25",
    "trend3_pm25",
    # CAMS origin chemistry (t0, known at issue time)
    "origin_pm25",
    "origin_no2",
    "origin_o3",
    "origin_pm10",
    "origin_so2",
    "origin_co",
    # CAMS target-hour co-pollutant forecast fields (available at issue time;
    # pm2_5 and us_aqi at target are deliberately ABSENT — see module docstring)
    "target_no2",
    "target_o3",
    "target_pm10",
    "target_so2",
    "target_co",
    # co-pollutant evolution origin -> target
    "no2_change",
    "o3_change",
    "pm10_change",
    # CAMS target-hour aerosol fields (forecast fields, available at issue
    # time; NOT the target quantity). AOD carries column aerosol information
    # and dust separates the crustal share — both help most in winter episodes.
    "target_aod",
    "target_dust",
    # nudged persistence: origin pm2.5 relaxed toward the co-pollutant-implied level
    "nudged_12h",
    "nudged_24h",
    "nudged_48h",
    # archived HRES meteorology at the target hour (independent upstream)
    "temperature_2m_c",
    "relative_humidity_pct",
    "precipitation_mm",
    "pbl_height_m",
    "shortwave_radiation_w_m2",
    "wind_speed_ms",
    "wind_direction_sin",
    "wind_direction_cos",
    "inversion_delta_t_c",
    "ventilation_m2_s",
    # calendar encodings of the target hour
    "target_hour_sin",
    "target_hour_cos",
    "target_year_sin",
    "target_year_cos",
]

# Chemical-regime composition features carried over from the v1 contract,
# rebuilt from origin + target co-pollutants only (no target pm2_5 anywhere).
V2_CHEMICAL_FEATURE_NAMES = [
    "no2_o3_ratio",
    "oxidation_capacity",
    "pm_formation_potential",
    "co_no2_ratio",
    "is_rush_hour",
    "is_nocturnal",
    "is_morning_transition",
    "is_evening_transition",
]

V2_FULL_FEATURE_NAMES = V2_FEATURE_NAMES + V2_CHEMICAL_FEATURE_NAMES


def build_pm25_features_v2(
    *,
    lead_hours: int,
    target_time: datetime,
    history: dict[str, float],
    origin_chem: dict[str, float],
    target_chem: dict[str, float],
    weather: dict[str, Any],
) -> list[float]:
    """Build one feature row in ``V2_FULL_FEATURE_NAMES`` order.

    ``history``     — output of ``history_features`` (may be partial/empty;
                      missing values become NaN, which HistGradientBoosting
                      consumes natively).
    ``origin_chem`` — CAMS chemistry AT the forecast origin (keys: pm2_5,
                      no2, o3, pm10, so2, co).
    ``target_chem`` — CAMS co-pollutant forecast fields AT the target hour
                      (keys: no2, o3, pm10, so2, co). pm2_5 must NOT be set
                      here; the builder ignores it by construction.
    ``weather``     — archived HRES forecast fields at the target hour (same
                      key names the live Open-Meteo payload uses).
    """
    origin_pm25 = _value(origin_chem, "pm2_5")
    target_no2 = _value(target_chem, "no2")
    target_o3 = _value(target_chem, "o3")
    target_pm10 = _value(target_chem, "pm10")
    target_so2 = _value(target_chem, "so2")
    target_co = _value(target_chem, "co")

    wind_speed = _value(weather, "wind_speed_10m")
    wind_direction = math.radians(_value(weather, "wind_direction_10m"))
    pbl = _value(weather, "boundary_layer_height")
    t1000 = _value(weather, "temperature_1000hPa")
    t925 = _value(weather, "temperature_925hPa")
    hour_angle = 2.0 * math.pi * target_time.hour / 24.0
    year_angle = 2.0 * math.pi * (target_time.timetuple().tm_yday - 1) / 365.25

    lead = float(max(1, int(lead_hours)))
    current = _value(history, "current_pm25")
    bias = (current - origin_pm25) if math.isfinite(current) and math.isfinite(origin_pm25) else 0.0
    bias *= math.isfinite(current) and math.isfinite(origin_pm25)  # 0 when either is NaN

    # Chemical-regime composition, target co-pollutants only. Fallbacks for a
    # missing co-pollutant derive from OTHER co-pollutants, never from pm2_5.
    no2_eff = target_no2 if math.isfinite(target_no2) else 20.0
    o3_eff = target_o3 if math.isfinite(target_o3) else 40.0
    co_eff = target_co if math.isfinite(target_co) else 500.0
    solar = _value(weather, "shortwave_radiation")
    if not math.isfinite(solar):
        solar = 200.0
    rh = _value(weather, "relative_humidity_2m")
    if not math.isfinite(rh):
        rh = 50.0
    if not math.isfinite(pbl) or pbl <= 0:
        pbl = 500.0

    hour = target_time.hour
    features = {
        "lead_hours": lead,
        "current_pm25": current,
        "lag1_pm25": _value(history, "lag1_pm25"),
        "lag3_pm25": _value(history, "lag3_pm25"),
        "lag6_pm25": _value(history, "lag6_pm25"),
        "lag12_pm25": _value(history, "lag12_pm25"),
        "lag24_pm25": _value(history, "lag24_pm25"),
        "mean6_pm25": _value(history, "mean6_pm25"),
        "mean24_pm25": _value(history, "mean24_pm25"),
        "std24_pm25": _value(history, "std24_pm25"),
        "trend3_pm25": _value(history, "trend3_pm25"),
        "origin_pm25": origin_pm25,
        "origin_no2": _value(origin_chem, "no2"),
        "origin_o3": _value(origin_chem, "o3"),
        "origin_pm10": _value(origin_chem, "pm10"),
        "origin_so2": _value(origin_chem, "so2"),
        "origin_co": _value(origin_chem, "co"),
        "target_no2": target_no2,
        "target_o3": target_o3,
        "target_pm10": target_pm10,
        "target_so2": target_so2,
        "target_co": target_co,
        "no2_change": target_no2 - _value(origin_chem, "no2"),
        "o3_change": target_o3 - _value(origin_chem, "o3"),
        "pm10_change": target_pm10 - _value(origin_chem, "pm10"),
        "target_aod": _value(target_chem, "aod"),
        "target_dust": _value(target_chem, "dust"),
        "nudged_12h": origin_pm25 + bias * math.exp(-lead / 12.0),
        "nudged_24h": origin_pm25 + bias * math.exp(-lead / 24.0),
        "nudged_48h": origin_pm25 + bias * math.exp(-lead / 48.0),
        "temperature_2m_c": _value(weather, "temperature_2m"),
        "relative_humidity_pct": rh,
        "precipitation_mm": _value(weather, "precipitation"),
        "pbl_height_m": pbl,
        "shortwave_radiation_w_m2": solar,
        "wind_speed_ms": wind_speed,
        "wind_direction_sin": math.sin(wind_direction),
        "wind_direction_cos": math.cos(wind_direction),
        "inversion_delta_t_c": t925 - t1000,
        "ventilation_m2_s": wind_speed * pbl,
        "target_hour_sin": math.sin(hour_angle),
        "target_hour_cos": math.cos(hour_angle),
        "target_year_sin": math.sin(year_angle),
        "target_year_cos": math.cos(year_angle),
        # chemical-regime composition
        "no2_o3_ratio": no2_eff / max(o3_eff, 1.0),
        "oxidation_capacity": o3_eff * solar / 1000.0,
        "pm_formation_potential": (no2_eff + co_eff / 100.0) * rh / 100.0 * (1000.0 / max(pbl, 1.0)),
        "co_no2_ratio": co_eff / max(no2_eff, 1.0),
        "is_rush_hour": 1.0 if hour in (7, 8, 9, 18, 19, 20) else 0.0,
        "is_nocturnal": 1.0 if hour < 6 or hour > 22 else 0.0,
        "is_morning_transition": 1.0 if hour in (5, 6, 7, 8) else 0.0,
        "is_evening_transition": 1.0 if hour in (17, 18, 19, 20) else 0.0,
    }
    return [features[name] for name in V2_FULL_FEATURE_NAMES]


def history_features(values: list[float | None]) -> dict[str, float]:
    """Summarize newest-first hourly PM2.5 values for live inference."""
    clean = [
        float(value)
        if value is not None and math.isfinite(float(value)) and float(value) >= 0
        else float("nan")
        for value in values
    ]
    if not clean or not math.isfinite(clean[0]):
        return {}

    def at(hours: int) -> float:
        return clean[hours] if hours < len(clean) else float("nan")

    recent6 = [value for value in clean[:6] if math.isfinite(value)]
    recent24 = [value for value in clean[:24] if math.isfinite(value)]
    mean6 = sum(recent6) / len(recent6)
    mean24 = sum(recent24) / len(recent24)
    variance24 = sum((value - mean24) ** 2 for value in recent24) / len(recent24)
    return {
        "current_pm25": clean[0],
        "lag1_pm25": at(1),
        "lag3_pm25": at(3),
        "lag6_pm25": at(6),
        "lag12_pm25": at(12),
        "lag24_pm25": at(24),
        "mean6_pm25": mean6,
        "mean24_pm25": mean24,
        "std24_pm25": math.sqrt(variance24),
        "trend3_pm25": clean[0] - at(3) if math.isfinite(at(3)) else float("nan"),
    }


# ── Direct-AQI target builder (v4) ─────────────────────────────────────


def compute_aqi_targets(concentrations: dict[str, float | None]) -> tuple[int, int]:
    """CPCB and EPA AQI for one hour from canonical µg/m³ concentrations.

    The single place the v4 training targets come from — the same breakpoint
    tables (`app.domain.aqi_scales`) the serving endpoint uses for the computed
    block, so "predicted" and "computed" AQI are always on identical scales.
    Missing species score sub-index 0 and cannot win the max, matching the
    serving contract. Returns (cpcb_aqi, epa_aqi), each capped 0–500 by the
    scales themselves.
    """
    from app.domain.aqi_scales import _cat, _sub_index

    keys = ("pm25", "pm10", "no2", "o3", "so2", "co")

    def aqi_for(mode: str) -> int:
        best = 0
        for key in keys:
            value = concentrations.get(key)
            if value is None:
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(number) or number < 0:
                continue
            idx = _sub_index(key, round(number, 2), mode)
            if idx > best:
                best = idx
        return int(best)

    cpcb = aqi_for("instant")
    epa = aqi_for("epa")
    # Sanity against the scales' own category mapping (raises on internal
    # inconsistency rather than training on a broken target).
    _cat(cpcb, "instant")
    _cat(epa, "epa")
    return cpcb, epa


# ── V3 contract (seasonal sub-models) ────────────────────────────────────

V3_EXTRA_FEATURE_NAMES = [
    "is_winter",        # Nov-Feb binary
    "fire_season",      # Oct15-Nov30 binary stubble-burning window
    "inversion_strength",  # ΔT continuous
    "inversion_cat",    # 0-3 ordinal (none/weak/moderate/strong)
    "pbl_ratio",        # pbl / 1200 normalised
    "rh_x_inv_pbl",     # RH × (1000/pbl) hygroscopic proxy
    "wind_x_pbl",       # ventilation duplicate for tree splits
    "season_sin",       # monthly season encoding
    "season_cos",
]

V3_FEATURE_NAMES = V2_FULL_FEATURE_NAMES + V3_EXTRA_FEATURE_NAMES


def build_extra_features_v3(target_time: datetime, weather: dict[str, Any]) -> list[float]:
    """Build the V3_EXTRA_FEATURE_NAMES slice (9 features).

    Called by both the training harness and live inference so the vector is
    identical in both paths. All values are derived from target_time and the
    HRES weather payload — no external key needed.
    """
    month = target_time.month
    yday = target_time.timetuple().tm_yday

    is_winter = 1.0 if month in (11, 12, 1, 2) else 0.0

    # Stubble burning: Oct 15 (yday≈288) – Nov 30 (yday≈334)
    fire = 1.0 if 288 <= yday <= 334 else 0.0

    try:
        pbl = float(weather.get("boundary_layer_height") or 500.0)
        if not math.isfinite(pbl) or pbl <= 0:
            pbl = 500.0
    except (TypeError, ValueError):
        pbl = 500.0

    try:
        t925 = float(weather.get("temperature_925hPa") or 0.0)
        t1000 = float(weather.get("temperature_1000hPa") or 0.0)
        delta_t = t925 - t1000
        if not math.isfinite(delta_t):
            delta_t = 0.0
    except (TypeError, ValueError):
        delta_t = 0.0

    try:
        rh = float(weather.get("relative_humidity_2m") or 50.0)
        if not math.isfinite(rh):
            rh = 50.0
    except (TypeError, ValueError):
        rh = 50.0

    try:
        wind = float(weather.get("wind_speed_10m") or 2.0)
        if not math.isfinite(wind):
            wind = 2.0
    except (TypeError, ValueError):
        wind = 2.0

    # Inversion category: 0=none, 0.5=sub-threshold, 1=weak, 2=moderate, 3=strong
    if delta_t <= 0:
        inv_cat = 0.0
    elif delta_t < 1.5:
        inv_cat = 0.5
    elif delta_t < 3.5:
        inv_cat = 1.0
    elif delta_t < 6.0:
        inv_cat = 2.0
    else:
        inv_cat = 3.0

    month_angle = 2.0 * math.pi * (month - 1) / 12.0

    return [
        is_winter,
        fire,
        delta_t,
        inv_cat,
        pbl / 1200.0,
        rh * (1000.0 / max(pbl, 50.0)),
        wind * pbl,
        math.sin(month_angle),
        math.cos(month_angle),
    ]
