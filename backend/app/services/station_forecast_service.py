"""Station-wise forecasting layer on top of the city-scale Chronos/ML forecast.

The Chronos-2 specialists are trained on (and therefore predict) the CAMS
0.25°-grid cell that contains Delhi — a city-scale average. Real CPCB stations
deviate from that cell average in stable, station-specific ways (Anand Vihar
runs high, Lodhi Road low). This module turns ONE city forecast into N
station forecasts:

  1. Data-driven offsets (preferred): for each catalog station we pair its
     OpenAQ hourly observations with the CAMS cell archive over the trailing
     window and compute a per-species multiplicative ratio
     ``mean(observed) / mean(cell)``. Ratios are clamped to [0.5, 2.0] and
     require >= _MIN_PAIRED_HOURS of overlap — below that the station's
     entry is not published (no invented numbers).
  2. Catalog priors (fallback): DELHI_NCR_STATIONS ships a static
     ``aqi_factor`` per station; when no measured offset exists the station
     forecast uses it and labels itself ``catalog_prior`` so the UI and API
     can always tell which basis a station is on.

Every station hour re-computes the CPCB AQI from its adjusted concentrations
with the same official breakpoint tables used everywhere else in the API —
the city response is never mutated.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.domain.aqi_scales import _cat, _sub_index
from app.services.realtime_service import DELHI_NCR_STATIONS

# Serving-side canonical keys → CPCB table keys (same map the chronos
# service uses for its p50_by_key dict).
_SPECIES_KEYS = ("pm25", "pm10", "no2", "so2", "co", "o3")

_MIN_PAIRED_HOURS = 200          # ≈ 8+ days of overlapping hourly data
_RATIO_CLAMP = (0.5, 2.0)        # ratios outside this are data errors, not geography
_OFFSETS_DIR = Path(__file__).resolve().parents[1] / "artifacts" / "station_offsets"
_OFFSETS_FILE = _OFFSETS_DIR / "offsets.json"

_OFFSETS_CACHE: dict[str, Any] | None = None


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def station_hour_aqi(concentrations: dict[str, float | None]) -> dict[str, Any]:
    """Max-of-six-sub-indices CPCB AQI from canonical µg/m³ concentrations.

    Missing species cannot win the max (sub-index 0), mirroring the city
    forecast's _hour_aqi semantics on the same breakpoint tables.
    """
    best_name, best_idx = None, 0
    for key in _SPECIES_KEYS:
        conc = concentrations.get(key)
        if conc is None:
            continue
        try:
            value = float(conc)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value) or value < 0:
            continue
        idx = _sub_index(key, value, "instant")
        if idx > best_idx:
            best_name, best_idx = key, idx
    category = _cat(best_idx, "instant")[0] if best_idx else "Unknown"
    return {
        "aqi": best_idx,
        "category": category,
        "dominant_pollutant": best_name,
    }


def compute_station_offset(
    observed: list[float | None],
    cell: list[float | None],
) -> dict[str, Any] | None:
    """Ratio-based offset from paired hourly series (pure; unit-tested).

    Returns None when too few hours overlap — the caller then falls back to
    the catalog prior instead of publishing a weakly estimated offset.
    """
    pairs = [
        (float(o), float(c))
        for o, c in zip(observed, cell)
        if o is not None and c is not None
        and math.isfinite(float(o)) and math.isfinite(float(c))
        and float(o) >= 0 and float(c) >= 5.0
    ]
    if len(pairs) < _MIN_PAIRED_HOURS:
        return None
    mean_obs = sum(o for o, _ in pairs) / len(pairs)
    mean_cell = sum(c for _, c in pairs) / len(pairs)
    if mean_cell <= 0:
        return None
    ratio = _clamp(mean_obs / mean_cell, *_RATIO_CLAMP)
    return {
        "ratio": round(ratio, 4),
        "n_hours": len(pairs),
        "mean_observed": round(mean_obs, 2),
        "mean_cell": round(mean_cell, 2),
    }


def load_offsets(path: Path | None = None) -> dict[str, Any]:
    """Load the cached measured offsets artifact (None-safe, cached)."""
    global _OFFSETS_CACHE
    file = path or _OFFSETS_FILE
    if _OFFSETS_CACHE is not None and path is None:
        return _OFFSETS_CACHE
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("offsets artifact is not an object")
        _OFFSETS_CACHE = data
        return data
    except (OSError, ValueError):
        return {"computed_at": None, "stations": {}}


def save_offsets(artifact: dict[str, Any], path: Path | None = None) -> None:
    global _OFFSETS_CACHE
    file = path or _OFFSETS_FILE
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    _OFFSETS_CACHE = None  # invalidate so the next load re-reads


def station_offsets_for(uid: str, artifact: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolved offsets for one station: measured per species where available,
    catalog ``aqi_factor`` prior for the rest. Each entry carries its true
    basis label (archive-measured vs IQAir live single-hour vs prior)."""
    artifact = artifact if artifact is not None else load_offsets()
    measured = (artifact.get("stations") or {}).get(uid) or {}
    resolved: dict[str, dict[str, Any]] = {}
    for key in _SPECIES_KEYS:
        entry = measured.get(key)
        if isinstance(entry, dict) and entry.get("ratio"):
            resolved[key] = {
                "ratio": float(entry["ratio"]),
                "n_hours": int(entry.get("n_hours") or 0),
                "basis": str(entry.get("basis") or "measured_openaq_vs_cams_cell"),
            }
    catalog = next(
        (s for s in DELHI_NCR_STATIONS if s["uid"] == uid), None
    )
    factor = float(catalog["aqi_factor"]) if catalog else 1.0
    for key in _SPECIES_KEYS:
        if key not in resolved:
            resolved[key] = {
                "ratio": factor,
                "n_hours": 0,
                "basis": "catalog_prior",
            }
    return resolved


def calibrate_station(
    station: dict[str, Any],
    city_hours: list[dict[str, Any]],
    offsets: dict[str, Any],
) -> dict[str, Any]:
    """One station's 72-h forecast from the city series + its offsets (pure).

    ``city_hours`` is the city forecast's hourly list (chronos or ML shape);
    species are read from whichever key style the hour carries — chronos uses
    ``pollutants.<model_key>.p50`` with model keys (pm2_5 …), the ML fallback
    uses flat display keys (PM2.5 …). Concentrations are adjusted
    multiplicatively and the station's CPCB AQI is recomputed from its own
    values. The input series is never mutated.
    """
    _DISPLAY_TO_KEY = {
        "PM2.5": "pm25", "PM10": "pm10", "NO2": "no2",
        "SO2": "so2", "CO": "co", "O3": "o3",
    }
    _MODEL_TO_KEY = {"pm2_5": "pm25", "pm10": "pm10", "no2": "no2", "so2": "so2", "co": "co", "o3": "o3"}

    hours_out: list[dict[str, Any]] = []
    for city_hour in city_hours:
        city_conc: dict[str, float] = {}
        pollutants = city_hour.get("pollutants") or {}
        for mkey, skey in _MODEL_TO_KEY.items():
            block = pollutants.get(mkey)
            if isinstance(block, dict) and block.get("p50") is not None:
                city_conc[skey] = float(block["p50"])
        if not city_conc:
            for display, skey in _DISPLAY_TO_KEY.items():
                raw = city_hour.get(display)
                if raw is not None:
                    city_conc[skey] = float(raw)
        if not city_conc and isinstance(city_hour.get("concentrations"), dict):
            for display, skey in _DISPLAY_TO_KEY.items():
                raw = (city_hour.get("concentrations") or {}).get(display)
                if raw is not None:
                    city_conc[skey] = float(raw)
        if not city_conc:
            # ML-fallback shape: per-hour sub_indices list items carry the
            # concentration the city AQI was computed from.
            for item in city_hour.get("sub_indices") or []:
                if not isinstance(item, dict):
                    continue
                skey = _DISPLAY_TO_KEY.get(str(item.get("pollutant") or ""))
                raw = item.get("concentration")
                if skey and raw is not None:
                    city_conc[skey] = float(raw)

        station_conc: dict[str, float] = {}
        adjustments: dict[str, dict[str, Any]] = {}
        for skey in _SPECIES_KEYS:
            base = city_conc.get(skey)
            if base is None:
                continue
            off = offsets.get(skey) or {}
            ratio = float(off.get("ratio", 1.0))
            adjusted = max(0.0, base * ratio)
            station_conc[skey] = round(adjusted, 2)
            adjustments[skey] = {
                "city": round(base, 2),
                "station": round(adjusted, 2),
                "ratio": round(ratio, 4),
                "basis": off.get("basis", "catalog_prior"),
            }

        aqi = station_hour_aqi(station_conc)
        hours_out.append({
            "hour_index": city_hour.get("hour_index"),
            "timestamp": city_hour.get("timestamp"),
            "aqi_cpcb": aqi["aqi"],
            "aqi_category": aqi["category"],
            "dominant_pollutant": aqi["dominant_pollutant"],
            "concentrations": station_conc,
            "adjustments": adjustments,
        })

    offsets_summary = {
        skey: {
            "ratio": offsets[skey]["ratio"],
            "basis": offsets[skey]["basis"],
            "n_hours": offsets[skey].get("n_hours", 0),
        }
        for skey in _SPECIES_KEYS if skey in offsets
    }
    bases = {v["basis"] for v in offsets_summary.values()}
    if "measured_openaq_vs_cams_cell" in bases:
        offset_basis = "measured"
    elif "iqair_live_single_hour" in bases:
        offset_basis = "iqair_live"
    else:
        offset_basis = "catalog_prior"
    return {
        "uid": station["uid"],
        "name": station["name"],
        "zone": station.get("zone"),
        "lat": station.get("lat"),
        "lon": station.get("lon"),
        "offset_basis": offset_basis,
        "offsets": offsets_summary,
        "hourly": hours_out,
        "current": hours_out[0] if hours_out else None,
    }


def build_station_forecasts(
    city_hours: list[dict[str, Any]],
    artifact: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Full station layer over one city forecast (pure; endpoint-facing)."""
    artifact = artifact if artifact is not None else load_offsets()
    stations = [
        calibrate_station(station, city_hours, station_offsets_for(station["uid"], artifact))
        for station in DELHI_NCR_STATIONS
    ]
    measured = sum(1 for s in stations if s["offset_basis"] == "measured")
    iqair_live = sum(1 for s in stations if s["offset_basis"] == "iqair_live")
    ranked = sorted(
        stations,
        key=lambda s: (s["current"] or {}).get("aqi_cpcb") or 0,
        reverse=True,
    )
    return {
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "artifact_generated_at": artifact.get("computed_at"),
        "station_count": len(stations),
        "stations_measured": measured,
        "stations_iqair_live": iqair_live,
        "stations_catalog_prior": len(stations) - measured - iqair_live,
        "most_polluted": [s["uid"] for s in ranked[:3]],
        "cleanest": [s["uid"] for s in ranked[-3:]],
        "stations": stations,
    }


# ── Offset refresh (admin-triggered; network-bound) ─────────────────────────

_CAMS_CELL_LAT, _CAMS_CELL_LON = 28.6139, 77.2090  # the training cell
_PAST_DAYS = 60                     # Open-Meteo air-quality archive max ≈ 92
_REFRESH_SPECIES = ("pm25", "pm10", "no2", "o3")  # so2/co: <0.1% AQI dominance
_OPENAQ = "https://api.openaq.org/v3"
_CAMS_ARCHIVE_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
_MIN_CELL_UG = 5.0
_IST_TZ = timezone(timedelta(hours=5, minutes=30))  # aware IST
_IST = timedelta(hours=5, minutes=30)  # naive-hour conversion offset (IST = UTC+5:30)
_IQAIR_URL = "https://api.airvisual.com/v2/nearest_city"


def _hour_key(raw: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.replace(minute=0, second=0, microsecond=0)


def _ist_hour(raw: str | datetime) -> datetime | None:
    """Timestamp → aware IST datetime floored to the hour.

    The floor must happen AFTER the timezone conversion: flooring 04:00 UTC
    to the UTC hour and then adding 5:30 yields 09:30 IST, which never
    matches a whole-hour IST key. Converting first (04:00 UTC = 09:30 IST)
    and then flooring gives 09:00 IST — the correct cell hour.
    """
    try:
        if isinstance(raw, datetime):
            dt = raw
        else:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_IST_TZ)  # naive treated as IST wall-clock
    return dt.astimezone(_IST_TZ).replace(minute=0, second=0, microsecond=0)


async def _fetch_cams_cell_history(client: Any) -> dict[datetime, dict[str, float]]:
    """Trailing-window CAMS archive for the training cell, keyed by hour."""
    import httpx

    params = {
        "latitude": _CAMS_CELL_LAT,
        "longitude": _CAMS_CELL_LON,
        "hourly": "pm2_5,pm10,nitrogen_dioxide,ozone",
        "past_days": _PAST_DAYS,
        "forecast_days": 1,
        "timezone": "Asia/Kolkata",
    }
    response = await client.get(_CAMS_ARCHIVE_URL, params=params)
    response.raise_for_status()
    hourly = (response.json() or {}).get("hourly", {}) or {}
    times = hourly.get("time") or []
    out: dict[datetime, dict[str, float]] = {}
    var_map = {"pm2_5": "pm25", "pm10": "pm10", "nitrogen_dioxide": "no2", "ozone": "o3"}
    for i, stamp in enumerate(times):
        key = _hour_key(stamp)
        if key is None:
            continue
        row: dict[str, float] = {}
        for var, skey in var_map.items():
            values = hourly.get(var) or []
            raw = values[i] if i < len(values) else None
            if raw is not None and float(raw) >= 0:
                row[skey] = float(raw)
        if row:
            out[key] = row
    return out


_PACER: dict[str, float] = {"next": 0.0}
_PACER_LOCK: Any = None  # created lazily inside a running loop


def _pacer_lock() -> Any:
    import asyncio

    global _PACER_LOCK
    if _PACER_LOCK is None:
        _PACER_LOCK = asyncio.Lock()
    return _PACER_LOCK


async def _pace() -> None:
    """Global ≈1 req/s pacing across all concurrent refresh tasks — OpenAQ's
    60 req/min budget is shared with the live backend's realtime polling."""
    import asyncio
    import time

    async with _pacer_lock():
        now = time.monotonic()
        if now < _PACER["next"]:
            await asyncio.sleep(_PACER["next"] - now)
        _PACER["next"] = time.monotonic() + 1.05


async def _get_with_429_retry(
    client: Any,
    url: str,
    *,
    headers: dict[str, str],
    params: dict[str, Any],
    max_attempts: int = 6,
) -> Any:
    """GET with global pacing and backoff on OpenAQ 429s."""
    import asyncio

    import httpx

    for attempt in range(max_attempts):
        await _pace()
        response = await client.get(url, headers=headers, params=params)
        if response.status_code != 429:
            response.raise_for_status()
            return response
        wait = 5.0 * (attempt + 1)
        await asyncio.sleep(wait)
    raise httpx.HTTPStatusError(
        "OpenAQ rate limit persisted after retries",
        request=response.request,
        response=response,
    )


async def _station_sensor_map(
    client: Any,
    api_key: str,
    *,
    fresh_hours: float = 168.0,
) -> dict[str, dict[str, int]]:
    """Map catalog station uid → {species: openaq_sensor_id} by proximity.

    Only FRESH monitors qualify: OpenAQ carries long-dead locations (some
    CPCB feeds end years ago), and pairing a 2018 sensor against the CAMS
    cell produces meaningless offsets. Each candidate location's /latest
    row must be newer than ``fresh_hours`` to count.
    """
    headers = {"X-API-Key": api_key}
    locations: list[dict[str, Any]] = []
    for page in range(1, 11):
        response = await _get_with_429_retry(
            client,
            f"{_OPENAQ}/locations",
            headers=headers,
            params={"bbox": "76.85,28.35,77.55,28.9", "iso": "IN", "limit": 100, "page": page},
        )
        results = (response.json() or {}).get("results") or []
        locations.extend(results)
        if len(results) < 100:
            break

    # Probe only locations plausibly near a catalog station (≤2 km).
    near: list[tuple[float, dict[str, Any]]] = []
    for loc in locations:
        coords = loc.get("coordinates") or {}
        lat, lon = coords.get("latitude"), coords.get("longitude")
        if lat is None or lon is None:
            continue
        d2 = min(
            (station["lat"] - lat) ** 2 + (station["lon"] - lon) ** 2
            for station in DELHI_NCR_STATIONS
        )
        if d2 <= 4.0:
            near.append((d2, loc))

    # Freshness check via /latest (age of the newest sensor row).
    cutoff = datetime.now(timezone.utc) - timedelta(hours=fresh_hours)
    fresh: list[tuple[float, dict[str, Any]]] = []
    for d2, loc in near:
        loc_id = loc.get("id")
        if loc_id is None:
            continue
        try:
            latest = await _get_with_429_retry(
                client,
                f"{_OPENAQ}/locations/{loc_id}/latest",
                headers=headers,
                params={},
            )
        except Exception:
            continue
        newest: datetime | None = None
        for row in (latest.json() or {}).get("results") or []:
            stamp = _hour_key(((row.get("datetime") or {}).get("utc")) or "")
            if stamp is not None:
                stamp = stamp.replace(tzinfo=timezone.utc)
                newest = stamp if newest is None or stamp > newest else newest
        if newest is not None and newest >= cutoff:
            fresh.append((d2, loc))

    best: dict[str, tuple[float, dict[str, Any]]] = {}
    for d2, loc in fresh:
        coords = loc.get("coordinates") or {}
        lat, lon = coords.get("latitude"), coords.get("longitude")
        for station in DELHI_NCR_STATIONS:
            s_d2 = (station["lat"] - lat) ** 2 + (station["lon"] - lon) ** 2
            if s_d2 > 4.0:
                continue
            if station["uid"] not in best or s_d2 < best[station["uid"]][0]:
                best[station["uid"]] = (s_d2, loc)

    sensors_by_name: dict[str, dict[str, int]] = {}
    for uid, (_d2, loc) in best.items():
        found: dict[str, int] = {}
        for sensor in loc.get("sensors") or []:
            param = ((sensor.get("parameter") or {}).get("name") or "").strip().lower()
            if param in _REFRESH_SPECIES and sensor.get("id") is not None:
                found[param] = int(sensor["id"])
        if found:
            sensors_by_name[uid] = found
    return sensors_by_name


async def _fetch_sensor_hours(
    client: Any,
    api_key: str,
    sensor_id: int,
    sem: asyncio.Semaphore,
) -> dict[datetime, float]:
    import asyncio

    headers = {"X-API-Key": api_key}
    window_start = datetime.now(timezone.utc) - timedelta(days=_PAST_DAYS)
    out: dict[datetime, float] = {}
    async with sem:
        # Cheap recency probe first: sensors whose newest hourly row predates
        # the offset window can't pair with the cell archive at all (OpenAQ
        # keeps long-dead CPCB feeds; /latest can even misreport freshness).
        try:
            probe = await _get_with_429_retry(
                client,
                f"{_OPENAQ}/sensors/{sensor_id}/hours",
                headers=headers,
                params={"limit": 1, "sort_order": "desc"},
            )
            probe_rows = (probe.json() or {}).get("results") or []
            if probe_rows:
                p = probe_rows[0].get("period") or {}
                newest = _ist_hour(((p.get("datetimeTo")) or {}).get("utc") or "")
                if newest is not None:
                    if newest < window_start.astimezone(_IST_TZ):
                        return {}
            elif not probe_rows:
                return {}
        except Exception:
            pass  # fall through and try the paged fetch anyway
        for page in range(1, 4):
            try:
                response = await _get_with_429_retry(
                    client,
                    f"{_OPENAQ}/sensors/{sensor_id}/hours",
                    headers=headers,
                params={
                    "datetime_from": window_start.isoformat(),
                    "limit": 1000,
                    "page": page,
                    "sort_order": "asc",
                },
                )
            except Exception:
                break
            results = (response.json() or {}).get("results") or []
            for row in results:
                period = row.get("period") or {}
                ts = period.get("datetimeTo") or period.get("datetimeFrom") or {}
                key = _hour_key(ts.get("local") or ts.get("utc") or "")
                value = row.get("value")
                if key is None or value is None or float(value) < 0:
                    continue
                out[key] = float(value)
            if len(results) < 1000:
                break
    return out


def _pm25_from_epa_aqi(aqius: float) -> float | None:
    """Invert the US EPA PM2.5 AQI band → concentration (µg/m³).

    Only meaningful when PM2.5 is the AQI's dominant pollutant (caller
    checks IQAir's ``mainus == 'p2'``) — otherwise aqius reflects another
    pollutant and the inversion would overstate PM2.5. Uses the same
    _BP_EPA table the app computes EPA AQI with, so round-trips exactly.
    """
    from app.domain.aqi_scales import _BP_EPA

    for conc_lo, conc_hi, aqi_lo, aqi_hi in _BP_EPA["pm25"]:
        if aqi_lo <= aqius <= aqi_hi:
            if aqi_hi == aqi_lo:
                return float(conc_lo)
            return float(conc_lo + (aqius - aqi_lo) / (aqi_hi - aqi_lo) * (conc_hi - conc_lo))
    return None


async def _iqair_station_pm25(
    client: Any,
    lat: float,
    lon: float,
    api_key: str,
    cell: dict[datetime, dict[str, float]],
) -> dict[str, Any] | None:
    """Live PM2.5 (µg/m³) for one station point via IQAir's nearest monitor.

    IQAir exposes aqius + dominant pollutant, not the concentration; when
    PM2.5 is dominant we invert the exact EPA breakpoint table the app uses.
    The CAMS-cell denominator is taken at the observation's own hour (ts
    converted to IST, floored) so the ratio is time-aligned, not latest-hour.
    Returns None whenever any link in that chain is missing — the station
    then simply stays on its catalog prior.
    """
    try:
        response = await client.get(
            _IQAIR_URL,
            params={"lat": lat, "lon": lon, "key": api_key},
        )
        if response.status_code != 200:
            return None
        data = ((response.json() or {}).get("data") or {})
        pollution = ((data.get("current") or {}).get("pollution")) or {}
        aqius = pollution.get("aqius")
        mainus = pollution.get("mainus")
        ts = pollution.get("ts")
        if aqius is None or mainus != "p2":
            return None  # PM2.5 not the dominant US pollutant — cannot invert
        pm25 = _pm25_from_epa_aqi(float(aqius))
        if pm25 is None:
            return None
        # Denominator: cell PM2.5 at the observation hour (ts → IST, floored).
        cell_pm25: float | None = None
        obs_key = _ist_hour(str(ts or ""))
        if obs_key is not None:
            cell_pm25 = cell.get(obs_key.replace(tzinfo=None), {}).get("pm25")
        if cell_pm25 is None or cell_pm25 < _MIN_CELL_UG:
            return None
        return {
            "pm25": pm25,
            "cell_pm25": float(cell_pm25),
            "aqius": aqius,
            "station_ts": ts,
        }
    except Exception:
        return None


async def refresh_station_offsets(api_key: str, max_stations: int = 48) -> dict[str, Any]:
    """Recompute measured offsets for the catalog and persist the artifact.

    Network-bound; called by the admin POST endpoint. Stations without a
    qualifying overlap simply stay on their catalog prior.
    """
    import asyncio

    import httpx

    sem = asyncio.Semaphore(4)
    async with httpx.AsyncClient(timeout=45.0) as client:
        cell = await _fetch_cams_cell_history(client)
        sensor_map = await _station_sensor_map(client, api_key)

        # CAMS cell's most recent PM2.5 hour — the denominator for the
        # IQAir single-hour fallback ratio.
        cell_now: float | None = None
        if cell:
            latest_cell_key = max(cell.keys())
            cell_now = cell[latest_cell_key].get("pm25")

        async def one(uid: str, sensors: dict[str, int]) -> dict[str, Any]:
            measured: dict[str, Any] = {}
            for species in _REFRESH_SPECIES:
                sensor_id = sensors.get(species)
                if sensor_id is None:
                    continue
                try:
                    obs = await _fetch_sensor_hours(client, api_key, sensor_id, sem)
                except Exception:
                    continue
                _hour_keys = sorted(obs.keys())
                pairs_by_key: dict[datetime, tuple[float, float | None]] = {}
                for orig in _hour_keys:
                    # Cell archive is keyed by naive IST wall-clock; OpenAQ
                    # rows are aware UTC (naive rows treated as IST). Map
                    # every observation onto its IST cell hour.
                    if orig.tzinfo is not None:
                        cell_key = orig.replace(tzinfo=None) + _IST
                    else:
                        cell_key = orig
                    value = obs[orig]
                    pairs_by_key[orig] = (value, cell.get(cell_key, {}).get(species))
                offset = compute_station_offset(
                    [v[0] for v in pairs_by_key.values()],
                    [v[1] for v in pairs_by_key.values()],
                )
                if offset is not None:
                    measured[species] = offset
            return measured

        uids = list(sensor_map.items())[:max_stations]
        results = await asyncio.gather(*(one(uid, sensors) for uid, sensors in uids))
        measured_by_uid = {uid: m for (uid, _s), m in zip(uids, results) if m}

        # ── IQAir live fallback for stations OpenAQ couldn't measure ──────
        # Real measured archive ratios are never overwritten; stations with
        # no usable OpenAQ history get a live single-hour PM2.5 anchor.
        from app.core.config import get_settings as _gs

        iqair_key = _gs().iqair_api_key
        iqair_usable = bool(iqair_key) and not str(iqair_key).startswith("your-")
        if iqair_usable:
            for station in DELHI_NCR_STATIONS:
                uid = station["uid"]
                if uid in measured_by_uid and "pm25" in measured_by_uid[uid]:
                    continue  # real measured ratio exists — never overwrite
                live = await _iqair_station_pm25(
                    client, station["lat"], station["lon"], str(iqair_key), cell
                )
                if not live:
                    continue
                ratio = _clamp(float(live["pm25"]) / float(live["cell_pm25"]), *_RATIO_CLAMP)
                measured_by_uid[uid] = {
                    "pm25": {
                        "ratio": round(ratio, 4),
                        "n_hours": 1,
                        "mean_observed": round(float(live["pm25"]), 2),
                        "mean_cell": round(float(live["cell_pm25"]), 2),
                        "basis": "iqair_live_single_hour",
                        "iqair_station_ts": live.get("station_ts"),
                        "iqair_aqius": live.get("aqius"),
                    }
                }
    stations = measured_by_uid
    artifact = {
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "cell": {"lat": _CAMS_CELL_LAT, "lon": _CAMS_CELL_LON, "pm25_now": cell_now},
        "window_days": _PAST_DAYS,
        "min_paired_hours": _MIN_PAIRED_HOURS,
        "stations": stations,
    }
    if stations:
        save_offsets(artifact)
    return {
        **artifact,
        "stations_with_offsets": len(stations),
        "saved": bool(stations),
        "note": (
            "stations below "
            f"{_MIN_PAIRED_HOURS} paired hours keep their catalog prior"
        ),
    }
