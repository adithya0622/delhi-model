"""Shared per-point CAMS/HRES context helpers for the Chronos serving paths.

Extracted from ``app.api.v1.chronos_endpoint`` so the zone-level forecast
service (and any future multi-point consumer) can reuse the exact same
context-building code the city endpoint uses. No behaviour change for the
endpoint: it re-exports these names.

Context discipline (identical to the endpoint originals):
  * CAMS air-quality archive: six species + AOD/dust, IST timezone,
    14 past days for the 168 h context (or 720 h input via past_days), 4
    forecast days so the fine-tuned specialists' future covariates cover the
    full 72 h horizon.
  * HRES meteorology: the full covariate superset in one keyless call.
  * ``build_history_series`` returns hours strictly BEFORE the origin — the
    model never sees its own target window.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any

import httpx

HORIZON_HOURS = 72

_CAMS_ARCHIVE_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
_CAMS_VAR: dict[str, str] = {
    "pm2_5": "pm2_5",
    "pm10": "pm10",
    "no2": "nitrogen_dioxide",
    "so2": "sulphur_dioxide",
    "o3": "ozone",
    "co": "carbon_monoxide",
}
_MODEL_SPECIES = tuple(_CAMS_VAR)

_MET_VARS = (
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "wind_direction_10m",
    "precipitation",
    "boundary_layer_height",
    "shortwave_radiation",
    "temperature_1000hPa",
    "temperature_925hPa",
)


async def fetch_cams_context(lat: float, lon: float, past_days: int = 14) -> dict[str, list]:
    """Hourly CAMS archive (IST) for the trailing window — the model's exact
    training source (six species, µg/m³)."""
    params = {
        "latitude": lat,
        "longitude": lon,
        # AOD + dust ride along: they are covariates for the Delhi fine-tuned
        # Chronos-2 specialists and harmless extras for the other paths.
        "hourly": ",".join((*_CAMS_VAR.values(), "aerosol_optical_depth", "dust")),
        "past_days": past_days,
        # 4 days so the fine-tuned specialists' co-pollutant future covariates
        # cover the full 72-h horizon (CAMS publishes these forecast fields
        # operationally — the same contract the models were trained under).
        "forecast_days": 4,
        "timezone": "Asia/Kolkata",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(_CAMS_ARCHIVE_URL, params=params)
        response.raise_for_status()
        return response.json().get("hourly", {}) or {}


def build_history_series(
    cams_hourly: dict[str, list], origin: datetime
) -> dict[str, list[float | None]]:
    """Oldest-first per-species series for hours strictly BEFORE the origin."""
    times = cams_hourly.get("time") or []
    out: dict[str, list[float | None]] = {s: [] for s in _MODEL_SPECIES}
    for i, stamp in enumerate(times):
        try:
            stamp_dt = datetime.fromisoformat(str(stamp))
        except ValueError:
            continue
        if stamp_dt >= origin:
            continue
        for species in _MODEL_SPECIES:
            values = cams_hourly.get(_CAMS_VAR[species]) or []
            raw = values[i] if i < len(values) else None
            try:
                out[species].append(float(raw) if raw is not None and float(raw) >= 0 else None)
            except (TypeError, ValueError):
                out[species].append(None)
    return out


async def fetch_met_context(lat: float, lon: float) -> dict[str, list]:
    """Hourly meteorology (IST) covering 14 past days + forecast grid in ONE
    keyless Open-Meteo call — the covariate source for the Chronos-2 path."""
    params = {
        "latitude": lat,
        "longitude": lon,
        # The full covariate superset the Delhi fine-tuned specialists expect
        # (wind_direction/precipitation/pressure-level temperatures included;
        # extra fields are ignored by the zero-shot paths).
        "hourly": ",".join(_MET_VARS),
        "past_days": 14,
        "forecast_days": 3,
        "timezone": "Asia/Kolkata",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get("https://api.open-meteo.com/v1/forecast", params=params)
        response.raise_for_status()
        return response.json().get("hourly", {}) or {}


def _split_covariates(
    met_hourly: dict[str, list], origin: datetime
) -> dict[str, tuple[list[float | None], list[float | None]]]:
    """Split the met payload into (past-before-origin, first-72-after) per variable,
    plus calendar channels (pure functions of the timestamp, trivially future-known)."""
    times = met_hourly.get("time") or []
    cut = 0
    for i, stamp in enumerate(times):
        try:
            if datetime.fromisoformat(str(stamp)) >= origin:
                cut = i
                break
        except ValueError:
            continue
    out: dict[str, tuple[list[float | None], list[float | None]]] = {}
    for name in _MET_VARS:
        values = met_hourly.get(name) or []
        past = [float(v) if v is not None else None for v in values[:cut]]
        future = [float(v) if v is not None else None for v in values[cut : cut + HORIZON_HOURS]]
        if past and future:
            out[name] = (past, future)

    # Calendar covariates for the fine-tuned specialists (match the trainer).
    stamps = []
    for stamp in times:
        try:
            stamps.append(datetime.fromisoformat(str(stamp)))
        except ValueError:
            continue
    past_stamps, future_stamps = stamps[:cut], stamps[cut : cut + HORIZON_HOURS]

    def _cal(pair: list[datetime], j: int) -> list[float]:
        vals: list[float] = []
        for t in pair:
            if j < 2:
                hod = t.hour + t.minute / 60.0
                angle = 2 * math.pi * hod / 24.0
            else:
                angle = 2 * math.pi * t.timetuple().tm_yday / 365.25
            vals.append(math.sin(angle) if j % 2 == 0 else math.cos(angle))
        return vals

    if past_stamps and len(future_stamps) == HORIZON_HOURS:
        for j, name in enumerate(("cal_hod_sin", "cal_hod_cos", "cal_doy_sin", "cal_doy_cos")):
            out[name] = (_cal(past_stamps, j), _cal(future_stamps, j))
    return out


def _cams_covariate_split(
    cams_hourly: dict[str, list], origin: datetime
) -> dict[str, tuple[list[float | None], list[float | None]]]:
    """Co-pollutant + AOD/dust covariate pairs (past-before-origin, next-72 h)
    from the CAMS payload, channel-named exactly as the trainer named them
    (``cam_<species>`` / ``camx_<extra>``). Co-pollutant futures are allowed:
    CAMS publishes these forecast fields operationally — the leak-free
    contract only withholds the TARGET species' own future, which the
    serving service drops per specialist."""
    times = cams_hourly.get("time") or []
    cut = 0
    for i, stamp in enumerate(times):
        try:
            if datetime.fromisoformat(str(stamp)) >= origin:
                cut = i
                break
        except ValueError:
            continue

    def _pair(values: list) -> tuple[list[float | None], list[float | None]] | None:
        past = [float(v) if v is not None else None for v in values[:cut]]
        future = [float(v) if v is not None else None for v in values[cut : cut + HORIZON_HOURS]]
        if past and future:
            return (past, future)
        return None

    out: dict[str, tuple[list[float | None], list[float | None]]] = {}
    for species, var in _CAMS_VAR.items():
        pair = _pair(cams_hourly.get(var) or [])
        if pair:
            out[f"cam_{species}"] = pair
    for extra in ("aerosol_optical_depth", "dust"):
        pair = _pair(cams_hourly.get(extra) or [])
        if pair:
            out[f"camx_{extra}"] = pair
    return out
