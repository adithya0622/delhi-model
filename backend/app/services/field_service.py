"""N-station coupled forecast field (high-resolution surrogate).

Why this exists
---------------
The live forecast was a single column for all of NCR. The problem statement
asks for a high-resolution outlook. A full 3-D chemistry grid is out of scope
for a seconds-return API, so this runs the existing coupled column once per
station and interpolates the result into a map field.

Cost control: meteorology + plume are fetched ONCE at the NCR centre and
reused for every column via ``met_data_override`` / ``plume_override``.
Per-station differences come from the live anchor (seeded column mass), not
from N duplicate upstream calls. ``use_ml=False`` keeps the field physics-only
so one shared CAMS fetch does not multiply into N calls.
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timezone
from typing import Any


# ── Pure helpers (no network; unit-tested) ───────────────────────────────────


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    r = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return 2.0 * r * math.asin(min(1.0, math.sqrt(max(0.0, a))))


def idw_value(
    at_lat: float,
    at_lon: float,
    points: list[tuple[float, float, float]],
    power: float = 2.0,
) -> float:
    """Inverse-distance-weighted interpolation of ``points`` at one location."""
    if not points:
        raise ValueError("idw_value requires at least one point")
    num = 0.0
    den = 0.0
    for plat, plon, pval in points:
        # Exact hit: no weighting ambiguity.
        if abs(plat - at_lat) < 1e-9 and abs(plon - at_lon) < 1e-9:
            return float(pval)
        # Equirectangular approximation is fine here: NCR spans ~1 degree, so the
        # per-point error is far below the grid spacing this field feeds.
        dist_deg = math.hypot((plat - at_lat) * 111.0, (plon - at_lon) * 111.0 * math.cos(math.radians(at_lat)))
        dist_deg = max(dist_deg, 1e-6)
        w = 1.0 / (dist_deg**power)
        num += w * float(pval)
        den += w
    return num / den if den > 0 else float(points[0][2])


def build_idw_grid(
    station_values: list[dict[str, Any]],
    *,
    value_key: str = "aqi",
    lat_min: float = 28.0,
    lat_max: float = 29.0,
    lon_min: float = 76.5,
    lon_max: float = 77.8,
    n_lat: int = 8,
    n_lon: int = 10,
    power: float = 2.0,
) -> dict[str, Any]:
    """Interpolate per-station scalar values onto a regular lat/lon grid."""
    points = [
        (float(s["lat"]), float(s["lon"]), float(s[value_key]))
        for s in station_values
        if s.get("lat") is not None and s.get("lon") is not None and s.get(value_key) is not None
    ]
    if not points:
        raise ValueError("build_idw_grid requires at least one station value")
    n_lat = max(2, min(int(n_lat), 20))
    n_lon = max(2, min(int(n_lon), 20))
    lats = [lat_min + (lat_max - lat_min) * i / (n_lat - 1) for i in range(n_lat)]
    lons = [lon_min + (lon_max - lon_min) * j / (n_lon - 1) for j in range(n_lon)]
    values = [
        [round(idw_value(lat, lon, points, power), 1) for lon in lons]
        for lat in lats
    ]
    return {"lats": lats, "lons": lons, "values": values, "value_key": value_key}


def spread_select(stations: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    """Stride-sample ``stations`` to maximise spatial spread (no clustering)."""
    if n <= 0:
        raise ValueError("n must be positive")
    if not stations:
        return []
    if n >= len(stations):
        return list(stations)
    step = len(stations) / n
    picked: list[dict[str, Any]] = []
    seen: set[int] = set()
    for k in range(n):
        idx = min(int(k * step), len(stations) - 1)
        # Nudge forward on collision so output length is exactly n.
        while idx in seen and idx + 1 < len(stations):
            idx += 1
        seen.add(idx)
        picked.append(stations[idx])
    return picked


def summarize_station_forecast(station: dict[str, Any], forecast: dict[str, Any]) -> dict[str, Any]:
    """Compact per-station 72h series: hourly AQI + PM2.5 plus summary stats."""
    hours = forecast.get("forecast_hours") or []
    hourly_aqi: list[int] = []
    hourly_pm25: list[float] = []
    for h in hours:
        hourly_aqi.append(int(h.get("aqi", 0)))
        pm25 = 0.0
        for s in h.get("sub_indices") or []:
            name = str(s.get("pollutant", ""))
            if "2.5" in name or name == "PM2.5":
                try:
                    pm25 = float(s.get("concentration", 0.0))
                except (TypeError, ValueError):
                    pm25 = 0.0
                break
        hourly_pm25.append(round(pm25, 1))
    return {
        "uid": station.get("uid"),
        "name": station.get("name") or forecast.get("station_name"),
        "lat": station.get("lat"),
        "lon": station.get("lon"),
        "hourly_aqi": hourly_aqi,
        "hourly_pm25": hourly_pm25,
        "current_aqi": hourly_aqi[0] if hourly_aqi else 0,
        "max_aqi_72h": max(hourly_aqi) if hourly_aqi else 0,
        "mean_aqi_72h": round(sum(hourly_aqi) / len(hourly_aqi), 1) if hourly_aqi else 0.0,
    }


def pool_cpcb_windows(windows: list[dict[str, Any]]) -> dict[str, Any]:
    """Pool per-window CPCB validation metrics (pure; unit-tested).

    Each window dict must carry ``metrics`` from ``validate_window`` with
    ``model_mae_horizon_ug_m3`` / ``persistence_mae_pm25_ug_m3`` / ``mae_pm25_ug_m3``.
    """
    scored = [w for w in windows if w.get("metrics")]
    if not scored:
        raise ValueError("pool_cpcb_windows requires at least one scored window")
    model_maes = [w["metrics"]["model_mae_horizon_ug_m3"] for w in scored if w["metrics"].get("model_mae_horizon_ug_m3") is not None]
    persist_maes = [w["metrics"]["persistence_mae_pm25_ug_m3"] for w in scored if w["metrics"].get("persistence_mae_pm25_ug_m3") is not None]
    overall_maes = [w["metrics"]["mae_pm25_ug_m3"] for w in scored if w["metrics"].get("mae_pm25_ug_m3") is not None]
    pooled_model = sum(model_maes) / len(model_maes) if model_maes else None
    pooled_persist = sum(persist_maes) / len(persist_maes) if persist_maes else None
    skill = (1.0 - pooled_model / pooled_persist) if pooled_model is not None and pooled_persist else None
    return {
        "windows": len(scored),
        "pooled_model_mae_horizon_ug_m3": round(pooled_model, 3) if pooled_model is not None else None,
        "pooled_persistence_mae_ug_m3": round(pooled_persist, 3) if pooled_persist is not None else None,
        "mae_skill_score": round(skill, 3) if skill is not None else None,
        "pooled_mae_all_aligned_hours_ug_m3": round(sum(overall_maes) / len(overall_maes), 3) if overall_maes else None,
    }


# ── Async field builder (network; integration-tested via endpoint) ───────────


async def build_forecast_field(
    n_stations: int = 12,
    hour_index: int = 0,
    grid_n_lat: int = 8,
    grid_n_lon: int = 10,
) -> dict[str, Any]:
    """Run the coupled column per station; return compact series + IDW grid."""
    from app.physics.plume_advection import compute_plume_vectors
    from app.services.aqi_service import build_72h_forecast
    from app.services.realtime_service import DELHI_NCR_STATIONS, fetch_all_stations
    from app.services.weather_providers import fetch_forecast_weather

    n_stations = max(1, min(int(n_stations), 30))
    hour_index = max(0, min(int(hour_index), 71))

    inventory = list(DELHI_NCR_STATIONS)
    live = await fetch_all_stations(mode="instant")
    live_by_uid = {str(s.get("uid")): s for s in live}

    # Shared upstream: one met fetch + one plume computation for all columns.
    met_data, plume_live = await asyncio.gather(
        fetch_forecast_weather(28.6139, 77.2090),
        compute_plume_vectors(),
    )
    plume_override = dict(plume_live)
    plume_override.setdefault("pm25_profile_ug_m3", [0.0] * 72)

    targets = spread_select(inventory, n_stations)
    sem = asyncio.Semaphore(4)

    async def _one(station: dict[str, Any]) -> dict[str, Any]:
        anchor = live_by_uid.get(str(station.get("uid")))
        pollutants = (anchor or {}).get("pollutants") or {}
        live_pm25 = pollutants.get("PM2.5")
        live_pm10 = pollutants.get("PM10")
        async with sem:
            forecast = await build_72h_forecast(
                float(station["lat"]),
                float(station["lon"]),
                str(station.get("name", "Delhi-NCR")),
                live_pm25=float(live_pm25) if live_pm25 is not None else None,
                live_pm10=float(live_pm10) if live_pm10 is not None else None,
                live_pollutants={k: float(v) for k, v in pollutants.items() if v is not None} or None,
                met_data_override=met_data,
                plume_override=plume_override,
                use_ml=False,
            )
        return summarize_station_forecast(station, forecast)

    summaries = await asyncio.gather(*(_one(s) for s in targets))

    grid_points = [
        {"lat": s["lat"], "lon": s["lon"], "aqi": s["hourly_aqi"][hour_index] if len(s["hourly_aqi"]) > hour_index else s["current_aqi"]}
        for s in summaries
    ]
    grid = build_idw_grid(grid_points, value_key="aqi", n_lat=grid_n_lat, n_lon=grid_n_lon)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": "N coupled columns (shared met + plume, per-station live anchor), physics-only, IDW field",
        "hour_index": hour_index,
        "station_count": len(summaries),
        "stations": summaries,
        "grid": grid,
        "weather_source": met_data.get("weather_source", "open-meteo"),
        "profile_source": met_data.get("profile_source", "measured"),
        "limitations": [
            "columns share centre meteorology; intra-city met gradients are not resolved",
            "physics-only field (trained PM2.5 off) to avoid N duplicate chemistry fetches",
            "IDW interpolation, not advection between columns",
        ],
    }
