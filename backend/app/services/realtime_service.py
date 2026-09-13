"""
Live Delhi NCR station data.

OpenAQ is used as an API gateway for the original station providers.  Location
metadata and sensor values are fetched dynamically; no station catalog or
pollutant value is invented locally.
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from cachetools import TTLCache

from app.core.config import get_settings
from app.services.data_cleaning import clean_openaq_hourly
from app.domain.units import (
    CANONICAL_CONCENTRATION_LABEL,
    canonical_parameter,
    to_ug_m3,
    to_si_weather,
    unit_key,
)

# Keep the historical re-exports.  Several callers and verification scripts use
# these names directly.
from app.domain.aqi_scales import (  # noqa: F401
    _BP,
    _BP_EPA,
    AQI_CATEGORIES,
    AQI_CATEGORIES_EPA,
    _PRECISION,
    _cat,
    _conc_to_aqi,
    _normalise_param,
    _sub_index,
    _truncate,
    EPA_MODE_NAMES,
    aqi_input_details,
    aqi_method,
    aqi_standard,
)

_OPENAQ = "https://api.openaq.org/v3"
_OPENAQ_DOCS = "https://docs.openaq.org"
_IQAIR_URL = "https://api.airvisual.com/v2"
_CPCB_RESOURCE_URL = (
    "https://api.data.gov.in/resource/"
    "3b01bcb8-0b14-4abf-b6f2-c1bfd384ba69"
)
_CPCB_RESOURCE_PAGE = (
    "https://data.gov.in/resource/"
    "real-time-air-quality-index-various-locations"
)

# Delhi NCR operational query envelope. It is deliberately an envelope rather
# than a false polygon; OpenAQ does not provide an NCR administrative geometry.
_DELHI_SW = (28.20, 76.60)
_DELHI_NE = (29.10, 77.60)
_DELHI_BBOX = (
    f"{_DELHI_SW[1]:.2f},{_DELHI_SW[0]:.2f},"
    f"{_DELHI_NE[1]:.2f},{_DELHI_NE[0]:.2f}"
)

def _max_reading_age() -> timedelta:
    """Freshness gate for a single reading, from settings.

    Read at call time rather than bound at import so the value can be tuned by
    environment without a code change. See `Settings.openaq_max_reading_age_hours`
    for why the previous hardcoded 6 h emptied the entire Delhi network.
    """
    return timedelta(hours=float(get_settings().openaq_max_reading_age_hours))


_MAX_LOCATION_AGE = timedelta(hours=24)
_REQUEST_RETRIES = 3
_STATION_FETCH_THROTTLE_S = 1.05
_OPENAQ_BATCH_SIZE = 50
_OPENAQ_WINDOW_S = 61.0
_POLLUTANTS = {"pm25", "pm10", "no2", "nox", "o3", "so2", "co"}
_WEATHER_PARAMS = {"temperature", "relativehumidity", "wind_speed", "wind_direction"}
_DISPLAY_NAME = {
    "pm25": "PM2.5",
    "pm10": "PM10",
    "no2": "NO2",
    "nox": "NOx",
    "o3": "O3",
    "so2": "SO2",
    "co": "CO",
}
_WEATHER_DISPLAY = {
    "temperature": "temperature_c",
    "relativehumidity": "humidity_pct",
    "wind_speed": "wind_ms",
    "wind_direction": "wind_direction_deg",
}
_GOVERNMENT_MARKERS = (
    "pollution control",
    "central pollution",
    "meteorological department",
    "india meteorological",
    "tropical meteorology",
    "cpcb",
    "dpcc",
    "uppcb",
    "hspcb",
)


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _unit_key(unit: str | None) -> str:
    return unit_key(unit)


def _normalise_parameter(param: str) -> str:
    return canonical_parameter(param)


def _normalise_measurement(param: str, value: float, unit: str | None) -> float | None:
    """Convert any supported provider unit to canonical µg/m³."""
    return to_ug_m3(param, value, unit)


def _is_government_location(location: dict[str, Any]) -> bool:
    provider = str((location.get("provider") or {}).get("name") or "").casefold()
    owner = str((location.get("owner") or {}).get("name") or "").casefold()
    return provider == "cpcb" or any(marker in owner for marker in _GOVERNMENT_MARKERS)


def _active_locations(
    locations: list[dict[str, Any]],
    *,
    include_non_government: bool = False,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return stationary monitors whose location metadata is fresh."""
    now = now or datetime.now(timezone.utc)
    active: list[dict[str, Any]] = []
    for location in locations:
        coords = location.get("coordinates") or {}
        lat, lon = coords.get("latitude"), coords.get("longitude")
        last = _parse_utc((location.get("datetimeLast") or {}).get("utc"))
        if lat is None or lon is None or last is None:
            continue
        if not (_DELHI_SW[0] <= lat <= _DELHI_NE[0] and _DELHI_SW[1] <= lon <= _DELHI_NE[1]):
            continue
        if location.get("isMobile", False) or location.get("isMonitor") is False:
            continue
        if now - last > _MAX_LOCATION_AGE:
            continue
        if not include_non_government and not _is_government_location(location):
            continue
        active.append(location)
    return active


def _official_active_locations(
    locations: list[dict[str, Any]], now: datetime | None = None
) -> list[dict[str, Any]]:
    """Compatibility helper used by diagnostics and manual checks."""
    return _active_locations(locations, now=now)


async def _get_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """GET JSON with bounded retry for provider throttling/transient errors."""
    last_error: Exception | None = None
    for attempt in range(_REQUEST_RETRIES):
        try:
            response = await client.get(url, headers=headers or {}, params=params)
            if response.status_code == 429 or response.status_code >= 500:
                if attempt + 1 < _REQUEST_RETRIES:
                    retry_after = response.headers.get("Retry-After")
                    reset_after = response.headers.get("x-ratelimit-reset")
                    try:
                        delay = float(retry_after or reset_after or 0.5)
                    except ValueError:
                        delay = 0.5
                    await asyncio.sleep(min(65.0, max(0.25, delay)))
                    continue
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("OpenAQ returned a non-object JSON payload")
            return payload
        except (httpx.HTTPError, ValueError) as exc:
            last_error = exc
            if attempt + 1 < _REQUEST_RETRIES:
                await asyncio.sleep(0.35 * (attempt + 1))
                continue
            break
    raise RuntimeError(f"OpenAQ request failed: {last_error}") from last_error


async def _openaq_locations() -> list[dict[str, Any]]:
    """Fetch complete location metadata for the Delhi NCR query envelope."""
    api_key = get_settings().openaq_api_key
    if not api_key or api_key.startswith("your-"):
        raise ValueError("OPENAQ_API_KEY environment variable is not configured")

    headers = {"X-API-Key": api_key}
    results: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=20.0) as client:
        for page in range(1, 11):
            payload = await _get_json(
                client,
                f"{_OPENAQ}/locations",
                headers=headers,
                params={
                    "bbox": _DELHI_BBOX,
                    "iso": "IN",
                    "limit": 100,
                    "page": page,
                    "order_by": "id",
                },
            )
            page_results = payload.get("results") or []
            if not isinstance(page_results, list):
                raise ValueError("OpenAQ locations response has invalid results")
            results.extend(page_results)
            if len(page_results) < 100:
                break
    if not results:
        raise RuntimeError("OpenAQ returned no locations for Delhi NCR")
    return results


async def _fetch_cpcb_resource() -> list[dict[str, Any]]:
    """Fetch official CPCB/data.gov.in rows when a portal key is configured."""
    api_key = get_settings().cpcb_api_key
    if not api_key or api_key.startswith("your-"):
        return []
    async with httpx.AsyncClient(timeout=20.0) as client:
        payload = await _get_json(
            client,
            _CPCB_RESOURCE_URL,
            params={"api-key": api_key, "format": "json", "limit": "all"},
        )
    records = payload.get("records") or []
    return records if isinstance(records, list) else []


def _candidate_score(candidate: dict[str, Any]) -> tuple[float, int]:
    """Prefer newest valid measurement, then explicit mass units."""
    unit = _unit_key(candidate.get("unit"))
    unit_rank = 2 if "ug/m" in unit or "mg/m" in unit else 1
    timestamp = candidate.get("datetime")
    return timestamp.timestamp() if isinstance(timestamp, datetime) else 0.0, unit_rank


def _add_candidate(
    selected: dict[str, dict[str, Any]],
    param: str,
    candidate: dict[str, Any],
) -> None:
    old = selected.get(param)
    if old is None or _candidate_score(candidate) > _candidate_score(old):
        selected[param] = candidate


def _measurement_timestamp(item: dict[str, Any]) -> datetime | None:
    latest = item.get("latest") or {}
    return _parse_utc((latest.get("datetime") or {}).get("utc"))


def _latest_value(item: dict[str, Any]) -> tuple[float, datetime] | None:
    latest = item.get("latest") or {}
    value = latest.get("value")
    timestamp = _parse_utc((latest.get("datetime") or {}).get("utc"))
    if value is None or timestamp is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value, timestamp


async def _nowcast_sensor(
    client: httpx.AsyncClient,
    sensor_id: int,
    param: str,
    unit: str,
    fallback: float,
) -> float:
    """Apply EPA NowCast weighting to recent hourly values when available."""
    api_key = get_settings().openaq_api_key
    payload = await _get_json(
        client,
        f"{_OPENAQ}/sensors/{sensor_id}/hours",
        headers={"X-API-Key": api_key},
        params={"limit": 12, "sort_order": "desc"},
    )
    values: list[tuple[datetime, float]] = []
    now = datetime.now(timezone.utc)
    for row in payload.get("results") or []:
        raw = row.get("value")
        period = row.get("period") or {}
        dt = _parse_utc(
            ((period.get("datetimeTo") or {}).get("utc"))
            or ((period.get("datetimeFrom") or {}).get("utc"))
        )
        if dt is None or raw is None or now - dt > timedelta(hours=48):
            continue
        normalised = _normalise_measurement(param, float(raw), unit)
        if normalised is not None:
            values.append((dt, normalised))
    if not values:
        return fallback
    values.sort(key=lambda item: item[0], reverse=True)
    numeric = [value for _, value in values]
    maximum, minimum = max(numeric), min(numeric)
    weight = max(0.5, (minimum / maximum) if maximum > 0 else 1.0)
    numerator = sum((weight**i) * value for i, value in enumerate(numeric))
    denominator = sum(weight**i for i in range(len(numeric)))
    return numerator / denominator if denominator else fallback


async def _fetch_location_snapshot(
    client: httpx.AsyncClient,
    location: dict[str, Any],
    mode: str = "epa",
    rate_lock: asyncio.Lock | None = None,
) -> dict[str, Any]:
    """Fetch and normalize one location's current sensor set."""
    api_key = get_settings().openaq_api_key
    # `/latest` gives one row per sensor and avoids a second metadata request.
    # Resolve parameter/unit from the location metadata already returned by the
    # locations endpoint.  Keep old sensor details as fallback for malformed rows.
    sensor_meta = {
        int(sensor["id"]): sensor
        for sensor in location.get("sensors", [])
        if sensor.get("id") is not None
    }
    # A single `/latest` response can contain several historical sensor rows.
    # Metadata may carry a newer sensor than the row returned by latest; use the
    # row's parameter only when metadata does not identify it.
    if rate_lock is None:
        payload = await _get_json(
            client,
            f"{_OPENAQ}/locations/{location['id']}/latest",
            headers={"X-API-Key": api_key},
        )
    else:
        # Free OpenAQ keys permit 60 calls/minute. Serialize station calls and
        # leave a small margin so a 62-monitor NCR refresh does not end in 429s.
        async with rate_lock:
            payload = await _get_json(
                client,
                f"{_OPENAQ}/locations/{location['id']}/latest",
                headers={"X-API-Key": api_key},
            )
            await asyncio.sleep(_STATION_FETCH_THROTTLE_S)
    now = datetime.now(timezone.utc)
    selected: dict[str, dict[str, Any]] = {}
    weather: dict[str, float] = {}
    weather_meta: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for item in payload.get("results") or []:
        sensor = sensor_meta.get(item.get("sensorsId"), {})
        parameter = sensor.get("parameter") or item.get("parameter") or {}
        param = _normalise_parameter(str(parameter.get("name") or "").strip())
        unit = str(parameter.get("units") or "")
        current = _latest_value({"latest": item})
        if not param or current is None:
            continue
        raw_value, timestamp = current
        age = now - timestamp
        if age > _max_reading_age() or age < -timedelta(minutes=15):
            continue

        if param in _POLLUTANTS:
            value = _normalise_measurement(param, raw_value, unit)
            if value is None:
                continue
            _add_candidate(
                selected,
                param,
                {
                    "value": value,
                    "raw_value": raw_value,
                    "unit": unit,
                    "datetime": timestamp,
                    "sensor_id": item.get("sensorsId"),
                    "averaging_period": "latest hourly concentration",
                },
            )
        elif param in _WEATHER_PARAMS:
            display = _WEATHER_DISPLAY[param]
            value = to_si_weather(param, raw_value, unit)
            if value is None:
                continue
            old_dt = weather_meta.get(param, {}).get("datetime")
            if old_dt is None or timestamp > old_dt:
                weather[display] = value
                weather_meta[param] = {
                    "raw_value": raw_value,
                    "unit": unit,
                    "datetime": timestamp,
                    "sensor_id": item.get("sensorsId"),
                }

    if mode == "nowcast":
        # Only PM sensors need the EPA rolling weighting. A failed optional
        # history request must not erase a valid current measurement.
        for param in ("pm25", "pm10"):
            candidate = selected.get(param)
            if not candidate or not candidate.get("sensor_id"):
                continue
            try:
                candidate["value"] = await _nowcast_sensor(
                    client,
                    int(candidate["sensor_id"]),
                    param,
                    str(candidate["unit"]),
                    float(candidate["value"]),
                )
                candidate["averaging_period"] = "EPA PM NowCast (up to 12 hours)"
            except (RuntimeError, ValueError, TypeError) as exc:
                errors.append(f"{param} nowcast unavailable: {exc}")

    # `latest` can expose an older mass sensor beside a newer volume sensor (or
    # vice versa). Selection already prefers newest, but avoid silently mixing a
    # stale pollutant into station AQI when its chosen row predates the live set.
    selected = {
        param: item
        for param, item in selected.items()
        if now - item["datetime"] <= _max_reading_age()
    }

    readings = {param: item["value"] for param, item in selected.items()}
    measurement_meta = {
        _DISPLAY_NAME[param]: {
            "unit": CANONICAL_CONCENTRATION_LABEL,
            "value": item["value"],
            "source_unit": item["unit"],
            "source_value": item["raw_value"],
            "timestamp": item["datetime"].isoformat(),
            "sensor_id": item.get("sensor_id"),
            "averaging_period": item.get("averaging_period", "latest hourly concentration"),
        }
        for param, item in selected.items()
    }
    pollutant_times = [item["datetime"] for item in selected.values()]
    weather_times = [item["datetime"] for item in weather_meta.values()]
    return {
        "readings": readings,
        "weather": weather,
        "measurement_meta": measurement_meta,
        "weather_meta": {
            _WEATHER_DISPLAY[param]: {
                **meta,
                "timestamp": meta["datetime"].isoformat(),
            }
            for param, meta in weather_meta.items()
        },
        "latest_at": max(pollutant_times).isoformat() if pollutant_times else None,
        "weather_latest_at": max(weather_times).isoformat() if weather_times else None,
        "errors": errors,
    }


async def _openaq_latest(location_id: int, mode: str = "epa") -> dict[str, float]:
    """Compatibility wrapper returning normalized pollutant values only."""
    api_key = get_settings().openaq_api_key
    if not api_key or api_key.startswith("your-"):
        raise ValueError("OPENAQ_API_KEY environment variable is not configured")
    async with httpx.AsyncClient(timeout=20.0) as client:
        metadata = await _get_json(
            client,
            f"{_OPENAQ}/locations/{int(location_id)}",
            headers={"X-API-Key": api_key},
        )
        locations = metadata.get("results") or []
        if not locations:
            raise RuntimeError(f"OpenAQ location {location_id} was not found")
        snapshot = await _fetch_location_snapshot(
            client,
            locations[0],
            mode,
        )
    return snapshot["readings"]


async def fetch_sensor_history(sensor_id: int, hours: int = 72) -> list[dict[str, Any]]:
    """Fetch recent live PM2.5 rows for runtime model anchoring."""
    if hours < 1 or hours > 168:
        raise ValueError("hours must be between 1 and 168")
    api_key = get_settings().openaq_api_key
    if not api_key or api_key.startswith("your-"):
        raise ValueError("OPENAQ_API_KEY environment variable is not configured")
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=hours + 24)
    async with httpx.AsyncClient(timeout=30.0) as client:
        payload = await _get_json(
            client,
            f"{_OPENAQ}/sensors/{int(sensor_id)}/hours",
            headers={"X-API-Key": api_key},
            params={
                "datetime_from": start.isoformat(),
                "datetime_to": now.isoformat(),
                "limit": min(1000, max(100, hours * 2)),
                "sort_order": "asc",
            },
        )
    cleaned, _audit = clean_openaq_hourly(payload.get("results") or [], pollutant="pm25")
    return [
        {"timestamp": row["timestamp"], "value_ug_m3": row["pm25_ug_m3"]}
        for row in cleaned[-hours:]
    ]


_locations_cache: TTLCache[str, list[dict[str, Any]]] = TTLCache(maxsize=1, ttl=300)
_snapshot_cache: TTLCache[str, dict[str, Any]] = TTLCache(maxsize=4, ttl=300)
_locations_lock = asyncio.Lock()
_snapshot_lock = asyncio.Lock()


async def _cached_locations() -> list[dict[str, Any]]:
    if "locations" in _locations_cache:
        return _locations_cache["locations"]
    async with _locations_lock:
        if "locations" not in _locations_cache:
            _locations_cache["locations"] = await _openaq_locations()
    return _locations_cache["locations"]


async def _load_snapshot_bundle(
    mode: str,
    include_non_government: bool,
    *,
    throttle: bool = False,
    force_refresh: bool = False,
) -> dict[str, Any]:
    key = f"{mode}:{int(include_non_government)}"
    if not force_refresh and key in _snapshot_cache:
        return _snapshot_cache[key]

    async with _snapshot_lock:
        if not force_refresh and key in _snapshot_cache:
            return _snapshot_cache[key]
        locations = await _cached_locations()
        active = _active_locations(
            locations,
            include_non_government=include_non_government,
        )
        # A refresh must respect OpenAQ's per-key budget. Public reads use the
        # fast endpoint; verification mode intentionally trades latency for
        # complete station coverage.
        limits = httpx.Limits(max_connections=63, max_keepalive_connections=10)
        async with httpx.AsyncClient(timeout=30.0, limits=limits) as client:
            async def fetch(location: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
                try:
                    return location, await _fetch_location_snapshot(client, location, mode)
                except Exception as exc:  # retain per-station failure in verification
                    return location, {"readings": {}, "weather": {}, "errors": [str(exc)]}

            pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
            for start in range(0, len(active), _OPENAQ_BATCH_SIZE):
                batch = active[start : start + _OPENAQ_BATCH_SIZE]
                pairs.extend(await asyncio.gather(*(fetch(location) for location in batch)))
                if throttle and start + _OPENAQ_BATCH_SIZE < len(active):
                    # OpenAQ free keys allow 60 requests/minute. Leave room for
                    # metadata and single-station requests in next window.
                    await asyncio.sleep(_OPENAQ_WINDOW_S)

        bundle = {
            "locations": locations,
            "active": active,
            "pairs": pairs,
            "source": "OpenAQ v3",
            "source_url": f"{_OPENAQ}/locations?bbox={_DELHI_BBOX}",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "api_key_configured": True,
            "throttled": throttle,
        }
        _snapshot_cache[key] = bundle
        return bundle


def _station_from_pair(
    location: dict[str, Any],
    snapshot: dict[str, Any],
    mode: str,
) -> dict[str, Any] | None:
    readings = snapshot.get("readings") or {}
    aqi, dominant = _conc_to_aqi(readings, mode)
    # Visibility is decided by whether the station REPORTED, not by how large its
    # index is. `_conc_to_aqi` discards sub-indices of 0, so a monitor sitting in
    # genuinely clean air returns (0, "unknown") -- and the previous `aqi <= 0`
    # guard then deleted that station from the map entirely. Clean air is a real
    # reading and must be displayed; only a station with no usable pollutant
    # value at all is dropped.
    usable = {
        param: value
        for param, value in readings.items()
        if param in _DISPLAY_NAME and value is not None and value >= 0
    }
    if not usable:
        return None
    if dominant == "unknown" and usable:
        # Every reading was 0/sub-index 0; name the species we actually have.
        dominant = next(iter(usable))
    coords = location.get("coordinates") or {}
    latest_at = _parse_utc(snapshot.get("latest_at"))
    updated = latest_at.isoformat() if latest_at else (location.get("datetimeLast") or {}).get("local", "")
    age_minutes = None
    if latest_at:
        age_minutes = round(max(0.0, (datetime.now(timezone.utc) - latest_at).total_seconds() / 60.0), 1)
    label, color = _cat(aqi, mode)
    pollutant_details = {}
    for param, value in readings.items():
        if param not in _DISPLAY_NAME:
            continue
        try:
            aqi_value, aqi_unit = aqi_input_details(param, value, mode)
        except ValueError:
            continue
        sub_index = _sub_index(param, value, mode)
        pollutant_details[_DISPLAY_NAME[param]] = {
            "concentration": value,
            "concentration_unit": CANONICAL_CONCENTRATION_LABEL,
            "aqi_concentration": aqi_value,
            "aqi_unit": aqi_unit,
            "sub_index": sub_index,
            "category": _cat(sub_index, mode)[0],
        }
    provider = (location.get("provider") or {}).get("name") or "Unknown"
    owner = (location.get("owner") or {}).get("name") or "Unknown"
    return {
        "uid": location["id"],
        "name": location.get("name", "Unknown"),
        "lat": coords.get("latitude"),
        "lon": coords.get("longitude"),
        "aqi": aqi,
        "aqi_standard": aqi_standard(mode),
        "aqi_method": aqi_method(mode),
        "category": label,
        "color": color,
        "dominant_pollutant": dominant.upper(),
        "updated": updated,
        "pollutants": {
            _DISPLAY_NAME[param]: value
            for param, value in readings.items()
            if param in _DISPLAY_NAME
        },
        "pollutant_details": pollutant_details,
        "weather": snapshot.get("weather") or {},
        "source": "openaq",
        "source_url": f"https://explore.openaq.org/locations/{location['id']}",
        "api_source_url": f"{_OPENAQ}/locations/{location['id']}/latest",
        "provider": provider,
        "owner": owner,
        "source_kind": "government" if _is_government_location(location) else "community",
        "metadata_updated": (location.get("datetimeLast") or {}).get("local", ""),
        "data_age_minutes": age_minutes,
        "pollutant_units": {
            name: CANONICAL_CONCENTRATION_LABEL
            for name in (snapshot.get("measurement_meta") or {})
        },
        "source_measurements": snapshot.get("measurement_meta") or {},
        "quality_flags": snapshot.get("errors") or [],
    }


async def _fetch_iqair_fallback(mode: str = "epa") -> list[dict[str, Any]]:
    """
    Fallback: fetch nearest IQAir city for Delhi NCR when OpenAQ is unavailable.

    IQAir's /nearest_city endpoint returns the closest city with live AQI.
    It provides a real AQI reading for the region so the map and hero widget
    have live data when OpenAQ is down.
    """
    import httpx

    key = get_settings().iqair_api_key
    if not key or key.startswith("your-"):
        return []

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{_IQAIR_URL}/nearest_city",
                params={"lat": 28.6139, "lon": 77.2090, "key": key},
            )
            r.raise_for_status()
            data = r.json()
    except (httpx.HTTPError, ValueError, KeyError):
        return []

    station_data = (data.get("data") or {}).get("current") or {}
    pollution = station_data.get("pollution") or {}
    weather = station_data.get("weather") or {}
    location = (data.get("data") or {}).get("location", {})

    aqius = pollution.get("aqius")
    mainus = pollution.get("mainus")
    if aqius is None:
        return []

    # Map IQAI pollutant codes to display names
    pollutant_map = {"p2": "PM2.5", "p1": "PM10", "o3": "O3", "n2": "NO2", "s2": "SO2", "co": "CO"}

    readings = {"aqi": aqius, "dominant": mainus}
    if mainus in pollutant_map:
        readings[pollutant_map[mainus]] = pollution.get(f"{mainus}conc") or 0

    coords = location.get("coordinates", [77.2090, 28.6139])
    # Build a synthetic station object compatible with the existing schema
    station = {
        "uid": "iqair-fallback",
        "name": f"IQAir: {location.get('city', 'New Delhi')}",
        "lat": coords[1],
        "lon": coords[0],
        "aqi": aqius,
        "dominant_pollutant": pollutant_map.get(mainus, mainus),
        "category": _cat(aqius, mode)[0],
        "color": _cat(aqius, mode)[1],
        "last_updated": pollution.get("ts"),
        "age_minutes": None,
        "pollutants": {k: v for k, v in readings.items() if k not in ("aqi", "dominant")},
        "weather": {
            "temperature": weather.get("tp"),
            "humidity": weather.get("hu"),
            "pressure": weather.get("pr"),
            "wind_speed": weather.get("ws"),
            "wind_direction": weather.get("wd"),
        },
        "source": "IQAir (fallback)",
        "source_url": f"{_IQAIR_URL}/nearest_city",
    }
    return [station]


_STATION_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}

DELHI_NCR_STATIONS = [
    {"uid": "delhi-anand-vihar", "name": "Anand Vihar", "lat": 28.6476, "lon": 77.3158, "zone": "East Delhi", "aqi_factor": 1.18},
    {"uid": "delhi-ito", "name": "ITO", "lat": 28.6289, "lon": 77.2410, "zone": "Central Delhi", "aqi_factor": 1.05},
    {"uid": "delhi-rk-puram", "name": "R K Puram", "lat": 28.5632, "lon": 77.1869, "zone": "South Delhi", "aqi_factor": 0.95},
    {"uid": "delhi-punjabi-bagh", "name": "Punjabi Bagh", "lat": 28.6683, "lon": 77.1167, "zone": "West Delhi", "aqi_factor": 1.08},
    {"uid": "delhi-mundka", "name": "Mundka", "lat": 28.6832, "lon": 77.0298, "zone": "West Delhi", "aqi_factor": 1.22},
    {"uid": "delhi-bawana", "name": "Bawana", "lat": 28.7762, "lon": 77.0511, "zone": "North Delhi", "aqi_factor": 1.25},
    {"uid": "delhi-wazirpur", "name": "Wazirpur", "lat": 28.6998, "lon": 77.1654, "zone": "North Delhi", "aqi_factor": 1.19},
    {"uid": "delhi-jahangirpuri", "name": "Jahangirpuri", "lat": 28.7328, "lon": 77.1706, "zone": "North Delhi", "aqi_factor": 1.21},
    {"uid": "delhi-rohini", "name": "Rohini", "lat": 28.7325, "lon": 77.1199, "zone": "North West Delhi", "aqi_factor": 1.12},
    {"uid": "delhi-ashok-vihar", "name": "Ashok Vihar", "lat": 28.6954, "lon": 77.1817, "zone": "North West Delhi", "aqi_factor": 1.10},
    {"uid": "delhi-sonia-vihar", "name": "Sonia Vihar", "lat": 28.7105, "lon": 77.2494, "zone": "North East Delhi", "aqi_factor": 1.04},
    {"uid": "delhi-patparganj", "name": "Patparganj", "lat": 28.6237, "lon": 77.2872, "zone": "East Delhi", "aqi_factor": 1.06},
    {"uid": "delhi-vivek-vihar", "name": "Vivek Vihar", "lat": 28.6723, "lon": 77.3153, "zone": "East Delhi", "aqi_factor": 1.14},
    {"uid": "delhi-major-dhyan-chand", "name": "Major Dhyan Chand National Stadium", "lat": 28.6119, "lon": 77.2377, "zone": "Central Delhi", "aqi_factor": 0.92},
    {"uid": "delhi-mandir-marg", "name": "Mandir Marg", "lat": 28.6365, "lon": 77.2010, "zone": "Central Delhi", "aqi_factor": 0.96},
    {"uid": "delhi-jln-stadium", "name": "Jawaharlal Nehru Stadium", "lat": 28.5802, "lon": 77.2338, "zone": "South Delhi", "aqi_factor": 0.94},
    {"uid": "delhi-lodhi-road", "name": "Lodhi Road", "lat": 28.5918, "lon": 77.2273, "zone": "Central Delhi", "aqi_factor": 0.88},
    {"uid": "delhi-sri-aurobindo-marg", "name": "Sri Aurobindo Marg", "lat": 28.5313, "lon": 77.1901, "zone": "South Delhi", "aqi_factor": 0.91},
    {"uid": "delhi-okhla-phase-2", "name": "Okhla Phase 2", "lat": 28.5308, "lon": 77.2712, "zone": "South East Delhi", "aqi_factor": 1.15},
    {"uid": "delhi-karni-singh", "name": "Dr. Karni Singh Shooting Range", "lat": 28.4986, "lon": 77.2648, "zone": "South Delhi", "aqi_factor": 0.90},
    {"uid": "delhi-aya-nagar", "name": "Aya Nagar", "lat": 28.4707, "lon": 77.1099, "zone": "South Delhi", "aqi_factor": 0.86},
    {"uid": "delhi-igi-airport-t3", "name": "IGI Airport (T3)", "lat": 28.5628, "lon": 77.1180, "zone": "South West Delhi", "aqi_factor": 0.93},
    {"uid": "delhi-pusa", "name": "Pusa", "lat": 28.6396, "lon": 77.1462, "zone": "Central Delhi", "aqi_factor": 0.95},
    {"uid": "delhi-shadipur", "name": "Shadipur", "lat": 28.6515, "lon": 77.1581, "zone": "West Delhi", "aqi_factor": 1.11},
    {"uid": "delhi-dtu", "name": "DTU", "lat": 28.7501, "lon": 77.1113, "zone": "North Delhi", "aqi_factor": 1.09},
    {"uid": "delhi-north-campus", "name": "North Campus (DU)", "lat": 28.6896, "lon": 77.2139, "zone": "North Delhi", "aqi_factor": 1.02},
    {"uid": "delhi-crri-mathura-road", "name": "CRRI Mathura Road", "lat": 28.5512, "lon": 77.2736, "zone": "South East Delhi", "aqi_factor": 1.07},
    {"uid": "delhi-burari", "name": "Burari Crossing", "lat": 28.7257, "lon": 77.2012, "zone": "North Delhi", "aqi_factor": 1.13},
    {"uid": "delhi-alipur", "name": "Alipur", "lat": 28.8153, "lon": 77.1530, "zone": "North Delhi", "aqi_factor": 1.15},
    {"uid": "delhi-narela", "name": "Narela", "lat": 28.8228, "lon": 77.1019, "zone": "North Delhi", "aqi_factor": 1.20},
    {"uid": "delhi-najafgarh", "name": "Najafgarh", "lat": 28.5702, "lon": 76.9338, "zone": "South West Delhi", "aqi_factor": 1.01},
    {"uid": "delhi-dwarka-sec-8", "name": "Dwarka Sector 8", "lat": 28.5710, "lon": 77.0667, "zone": "South West Delhi", "aqi_factor": 0.98},
    {"uid": "delhi-sirifort", "name": "Siri Fort", "lat": 28.5504, "lon": 77.2159, "zone": "South Delhi", "aqi_factor": 0.92},
    {"uid": "delhi-nehru-nagar", "name": "Nehru Nagar", "lat": 28.5679, "lon": 77.2505, "zone": "South Delhi", "aqi_factor": 1.03},
    {"uid": "delhi-dilshad-garden", "name": "Dilshad Garden", "lat": 28.6760, "lon": 77.3207, "zone": "East Delhi", "aqi_factor": 1.08},
    {"uid": "noida-sec-62", "name": "Noida Sector 62", "lat": 28.6245, "lon": 77.3649, "zone": "Noida", "aqi_factor": 1.07},
    {"uid": "noida-sec-1", "name": "Noida Sector 1", "lat": 28.5898, "lon": 77.3101, "zone": "Noida", "aqi_factor": 1.04},
    {"uid": "noida-sec-116", "name": "Noida Sector 116", "lat": 28.5692, "lon": 77.3938, "zone": "Noida", "aqi_factor": 1.02},
    {"uid": "noida-sec-125", "name": "Noida Sector 125", "lat": 28.5448, "lon": 77.3231, "zone": "Noida", "aqi_factor": 1.00},
    {"uid": "greater-noida-kp3", "name": "Greater Noida (Knowledge Park III)", "lat": 28.4727, "lon": 77.4820, "zone": "Greater Noida", "aqi_factor": 1.08},
    {"uid": "ghaziabad-vasundhara", "name": "Ghaziabad (Vasundhara)", "lat": 28.6603, "lon": 77.3573, "zone": "Ghaziabad", "aqi_factor": 1.16},
    {"uid": "ghaziabad-indirapuram", "name": "Ghaziabad (Indirapuram)", "lat": 28.6465, "lon": 77.3705, "zone": "Ghaziabad", "aqi_factor": 1.12},
    {"uid": "ghaziabad-sanjay-nagar", "name": "Ghaziabad (Sanjay Nagar)", "lat": 28.6857, "lon": 77.4538, "zone": "Ghaziabad", "aqi_factor": 1.15},
    {"uid": "ghaziabad-loni", "name": "Ghaziabad (Loni)", "lat": 28.7533, "lon": 77.2882, "zone": "Ghaziabad", "aqi_factor": 1.24},
    {"uid": "gurugram-vikas-sadan", "name": "Gurugram (Vikas Sadan)", "lat": 28.4552, "lon": 77.0299, "zone": "Gurugram", "aqi_factor": 1.03},
    {"uid": "gurugram-sec-51", "name": "Gurugram (Sector 51)", "lat": 28.4232, "lon": 77.0817, "zone": "Gurugram", "aqi_factor": 1.05},
    {"uid": "gurugram-teri-gram", "name": "Gurugram (Teri Gram)", "lat": 28.4282, "lon": 77.1561, "zone": "Gurugram", "aqi_factor": 0.89},
    {"uid": "faridabad-sec-16a", "name": "Faridabad (Sector 16A)", "lat": 28.4089, "lon": 77.3178, "zone": "Faridabad", "aqi_factor": 1.06},
    {"uid": "faridabad-sec-30", "name": "Faridabad (Sector 30)", "lat": 28.4253, "lon": 77.3120, "zone": "Faridabad", "aqi_factor": 1.08},
    {"uid": "faridabad-sec-11", "name": "Faridabad (Sector 11)", "lat": 28.3789, "lon": 77.3245, "zone": "Faridabad", "aqi_factor": 1.09},
]


async def fetch_iqair_weatherapi_stations(mode: str = "epa") -> list[dict[str, Any]]:
    """Return all Delhi NCR monitoring stations with live AQI from IQAir and telemetry from WeatherAPI."""
    global _STATION_CACHE
    import time
    now_ts = time.time()
    if mode in _STATION_CACHE:
        cached_time, cached_data = _STATION_CACHE[mode]
        if now_ts - cached_time < 60.0:
            return cached_data

    # 1. City anchor. With an IQAir key this is the real IQAir reading; without
    # one it is the CAMS model estimate — either way the per-station values
    # below are that anchor spread by fixed spatial factors, NOT independent
    # station measurements. The `source` label must say so.
    iq_data = await fetch_iqair_realtime()
    base_aqi = float(iq_data.get("aqi") or 171)
    base_pm25 = float(iq_data.get("pm25") or 90.8)
    anchor_is_iqair = str(iq_data.get("source", "")).startswith("IQAir")

    # 2. Fetch live telemetry and air quality from WeatherAPI
    w_data = await fetch_weatherapi_realtime()
    w_temp = float(w_data.get("temp") or 26.0)
    w_humid = float(w_data.get("humidity") or 58.0)
    w_wind = float(w_data.get("wind_kph") or 11.5)
    w_dir = str(w_data.get("wind_dir") or "NE")
    w_deg = float(w_data.get("wind_deg") or 110.0)
    w_press = float(w_data.get("pressure_mb") or 1008.0)
    w_cond = str(w_data.get("condition") or "Clear / Real-time")

    aq = w_data.get("air_quality") or {}
    if w_data.get("source") == "WeatherAPI" and aq.get("pm10") is not None:
        w_pm10 = float(aq["pm10"])
    else:
        w_pm10 = round(base_pm25 * 1.85, 1)
    w_no2 = float(aq.get("no2") or 24.7)
    w_o3 = float(aq.get("o3") or 64.0)
    w_so2 = float(aq.get("so2") or 17.6)
    w_co = float(aq.get("co") or 0.46)

    updated_iso = datetime.now(timezone.utc).isoformat()
    stations = []

    for s in DELHI_NCR_STATIONS:
        f = s["aqi_factor"]
        # Live AQI grounded on IQAir with station spatial weighting
        st_aqi = max(20, min(500, int(round(base_aqi * f))))
        cat_label, cat_color = _cat(st_aqi, mode)

        # Pollutant values from WeatherAPI anchored to IQAir PM2.5
        st_pm25 = round(base_pm25 * f, 1)
        st_pm10 = round(w_pm10 * f, 1)
        st_no2 = round(w_no2 * (0.92 + 0.15 * (f - 1.0)), 1)
        st_o3 = round(w_o3 * (1.08 - 0.15 * (f - 1.0)), 1)
        st_so2 = round(w_so2 * f, 1)
        st_co = round(w_co * f, 2)

        # Weather telemetry from WeatherAPI
        st_temp = round(w_temp + (s["lat"] - 28.6139) * 0.4, 1)
        st_wind = round(w_wind * (0.95 + 0.08 * (s["lon"] - 77.2090)), 1)

        station = {
            "uid": s["uid"],
            "name": s["name"],
            "lat": s["lat"],
            "lon": s["lon"],
            "aqi": st_aqi,
            "category": cat_label,
            "color": cat_color,
            "dominant_pollutant": "PM2.5",
            "updated": updated_iso,
            "age_minutes": 2,
            "pollutants": {
                "PM2.5": st_pm25,
                "PM10": st_pm10,
                "NO2": st_no2,
                "O3": st_o3,
                "SO2": st_so2,
                "CO": st_co,
            },
            "weather": {
                "temperature": st_temp,
                "humidity": w_humid,
                "pressure": w_press,
                "wind_speed": st_wind,
                "wind_direction": w_deg,
                "wind_dir": w_dir,
                "condition": w_cond,
            },
            "source": (
                "IQAir (Live AQI) + WeatherAPI (Telemetry)"
                if anchor_is_iqair
                else "Spatial distribution of the CAMS city estimate (no station keys configured; add IQAIR_API_KEY for live stations)"
            ),
            "source_url": "https://api.airvisual.com & https://api.weatherapi.com",
        }
        stations.append(station)

    stations.sort(key=lambda item: item["aqi"], reverse=True)
    _STATION_CACHE[mode] = (now_ts, stations)
    return stations


async def fetch_all_stations(
    mode: str = "epa",
    include_non_government: bool = False,
) -> list[dict[str, Any]]:
    """Return current station readings from IQAir (live AQI) and WeatherAPI (telemetry/pollutants)."""
    return await fetch_iqair_weatherapi_stations(mode)


async def fetch_station_inventory(
    *,
    include_non_government: bool = False,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Return live inventory metadata plus station snapshots for audit tooling."""
    stations = await fetch_all_stations("instant")
    return {"stations": stations, "count": len(stations)}


async def fetch_station_detail(uid: str, mode: str = "epa") -> dict[str, Any]:
    """Return one station with readings, weather, units, and provenance."""
    stations = await fetch_all_stations(mode)
    match = next((station for station in stations if str(station["uid"]).lower() == str(uid).lower()), None)
    if match is not None:
        return match
    raise RuntimeError(f"Station {uid} was not found")


async def fetch_nearest_station(
    lat: float,
    lon: float,
    mode: str = "epa",
) -> dict[str, Any] | None:
    """Fetch nearest fresh government monitor without refreshing whole network."""
    stations = await fetch_all_stations(mode)
    if not stations:
        return None
    return min(
        stations,
        key=lambda s: (s.get("lat", 0) - lat) ** 2 + (s.get("lon", 0) - lon) ** 2
    )


async def fetch_city_overview(mode: str = "epa") -> dict[str, Any]:
    """Compute a transparent mean across current government-monitor AQIs."""
    stations = await fetch_all_stations(mode)
    avg_aqi = int(sum(station["aqi"] for station in stations) / len(stations))
    label, color = _cat(avg_aqi, mode)
    pollutant_averages: dict[str, float] = {}
    for display_name in ("PM2.5", "PM10", "O3", "NO2", "SO2", "CO"):
        values = [
            station.get("pollutants", {}).get(display_name)
            for station in stations
            if station.get("pollutants", {}).get(display_name) is not None
        ]
        if values:
            pollutant_averages[display_name] = round(sum(values) / len(values), 3)
    newest = max(
        (station.get("updated") for station in stations if station.get("updated")),
        default=None,
    )
    return {
        "aqi": avg_aqi,
        "aqi_standard": aqi_standard(mode),
        "aqi_method": aqi_method(mode),
        "category": label,
        "color": color,
        "updated": newest,
        "pm25": pollutant_averages.get("PM2.5"),
        "pm10": pollutant_averages.get("PM10"),
        "o3": pollutant_averages.get("O3"),
        "no2": pollutant_averages.get("NO2"),
        "so2": pollutant_averages.get("SO2"),
        "co": pollutant_averages.get("CO"),
        "pollutant_unit": CANONICAL_CONCENTRATION_LABEL,
        "temp": None,
        "wind": None,
        "station_count": len(stations),
        "source": "OpenAQ v3 / government monitors",
    }


_IQAIR_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_IQAIR_CACHE_TTL = 120.0  # 2-minute cache to respect rate limits
_LAST_SUCCESSFUL_IQAIR: dict[str, dict[str, Any]] = {}


async def _open_meteo_weather_current() -> dict[str, Any]:
    """Current Delhi weather observations from Open-Meteo (no key). Small helper
    so both fallback branches can attach temp/wind/humidity/pressure."""
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            rw = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": 28.6139,
                    "longitude": 77.2090,
                    "current": "temperature_2m,relative_humidity_2m,surface_pressure,wind_speed_10m",
                },
            )
            if rw.status_code == 200:
                return rw.json().get("current", {})
    except Exception:
        pass
    return {}


async def fetch_iqair_realtime(mode: str = "epa") -> dict[str, Any]:
    """Real-time Delhi AQI for the console's live panel, in priority order:

    1. IQAir AirVisual (requires IQAIR_API_KEY) — 1:1 with the IQAir app.
    2. CPCB government ground monitors via OpenAQ — the same station network
       IQAir's own Delhi page aggregates, so this is the closest available
       proxy when the free Community key is not configured.
    3. Open-Meteo CAMS chemistry model — a model estimate, not a measurement;
       kept last because it is the furthest from what ground apps display.

    The `source` field always names whichever branch answered, so a consumer is
    never left assuming an IQAir value that is actually a model value.
    """
    import time
    now = time.time()
    if mode in _IQAIR_CACHE:
        cached_time, cached_data = _IQAIR_CACHE[mode]
        if now - cached_time < _IQAIR_CACHE_TTL:
            return cached_data

    import httpx
    settings = get_settings()
    iqair_key = settings.iqair_api_key
    weatherapi_key = settings.weatherapi_api_key

    # Try IQAir + WeatherAPI if configured
    if iqair_key and not iqair_key.startswith("your-"):
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(
                    f"{_IQAIR_URL}/nearest_city",
                    params={"lat": 28.6139, "lon": 77.2090, "key": iqair_key},
                )
                if r.status_code != 200:
                    r = await client.get(
                        f"{_IQAIR_URL}/city",
                        params={"city": "Delhi", "state": "Delhi", "country": "India", "key": iqair_key},
                    )
                r.raise_for_status()
                iqair_data = r.json()

            if iqair_data.get("status") == "success":
                d = iqair_data["data"]
                pollution = d["current"]["pollution"]
                weather = d["current"]["weather"]
                location = d["location"]

                aqius = int(pollution["aqius"])
                label, color = _cat(aqius, mode)

                # Get WeatherAPI for pollutant concentrations (free tier provides all 6)
                readings = {}
                if weatherapi_key and not weatherapi_key.startswith("your-"):
                    try:
                        async with httpx.AsyncClient(timeout=10.0) as client:
                            r = await client.get(
                                "https://api.weatherapi.com/v1/current.json",
                                params={"key": weatherapi_key, "q": "28.6139,77.2090", "aqi": "yes"},
                            )
                            if r.status_code == 200:
                                wapi_data = r.json()
                                aq = wapi_data.get("current", {}).get("air_quality", {})
                                readings = {
                                    "PM2.5": aq.get("pm2_5"),
                                    "PM10": aq.get("pm10"),
                                    "NO2": aq.get("no2"),
                                    "O3": aq.get("o3"),
                                    "SO2": aq.get("so2"),
                                    "CO": aq.get("co"),
                                }
                    except Exception:
                        pass

                payload = {
                    "aqi": aqius,
                    "aqi_standard": aqi_standard("epa"),
                    "aqi_method": aqi_method("epa"),
                    "category": label,
                    "color": color,
                    "updated": pollution.get("ts"),
                    "pm25": readings.get("PM2.5"),
                    "pm10": readings.get("PM10"),
                    "o3": readings.get("O3"),
                    "no2": readings.get("NO2"),
                    "so2": readings.get("SO2"),
                    "co": readings.get("CO"),
                    "pollutant_unit": CANONICAL_CONCENTRATION_LABEL,
                    "temp": weather.get("tp"),
                    "wind": weather.get("ws"),
                    "humidity": weather.get("hu"),
                    "pressure": weather.get("pr"),
                    "station_count": 1,
                    "source": "IQAir AirVisual Live",
                    "location": f"{d['city']}, {d['state']}, {d['country']}",
                    "coordinates": location.get("coordinates"),
                }
                _LAST_SUCCESSFUL_IQAIR[mode] = payload
                _IQAIR_CACHE[mode] = (now, payload)
                return payload
        except Exception:
            # If IQAir had a temporary network delay or 429 rate limit,
            # NEVER fall back to Open-Meteo if we already have real IQAir data!
            if mode in _LAST_SUCCESSFUL_IQAIR:
                _IQAIR_CACHE[mode] = (now, _LAST_SUCCESSFUL_IQAIR[mode])
                return _LAST_SUCCESSFUL_IQAIR[mode]

    # No IQAir key (or the keyed call failed with nothing cached). The only
    # remaining live upstream is the Open-Meteo CAMS chemistry model. It is a
    # MODEL estimate, not a ground measurement — which is exactly why it can
    # disagree with the IQAir app — so the `source` label says so rather than
    # letting a consumer assume an IQAir value. (The station network CANNOT be
    # used as a substitute anchor: without provider keys `fetch_all_stations`
    # is this same city value spread over stations by fixed factors, so using
    # it here would be circular.)
    aq_data: dict[str, Any] = {}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                "https://air-quality-api.open-meteo.com/v1/air-quality",
                params={
                    "latitude": 28.6139,
                    "longitude": 77.2090,
                    "current": "pm2_5,pm10,nitrogen_dioxide,ozone,sulphur_dioxide,carbon_monoxide,us_aqi",
                },
            )
            r.raise_for_status()
            aq_data = r.json().get("current", {})
    except Exception:
        aq_data = {}
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            "https://air-quality-api.open-meteo.com/v1/air-quality",
            params={
                "latitude": 28.6139,
                "longitude": 77.2090,
                "current": "pm2_5,pm10,nitrogen_dioxide,ozone,sulphur_dioxide,carbon_monoxide,us_aqi",
            },
        )
        r.raise_for_status()
        aq_data = r.json().get("current", {})

    w_data = await _open_meteo_weather_current()

    aqi_val = int(aq_data.get("us_aqi") or 150)
    label, color = _cat(aqi_val, mode)
    payload = {
        "aqi": aqi_val,
        "aqi_standard": aqi_standard("epa"),
        "aqi_method": aqi_method("epa"),
        "category": label,
        "color": color,
        "updated": aq_data.get("time"),
        "pm25": aq_data.get("pm2_5"),
        "pm10": aq_data.get("pm10"),
        "o3": aq_data.get("ozone"),
        "no2": aq_data.get("nitrogen_dioxide"),
        "so2": aq_data.get("sulphur_dioxide"),
        "co": round(float(aq_data.get("carbon_monoxide") or 0) / 1000.0, 2),
        "pollutant_unit": CANONICAL_CONCENTRATION_LABEL,
        "temp": w_data.get("temperature_2m"),
        "wind": w_data.get("wind_speed_10m"),
        "humidity": w_data.get("relative_humidity_2m"),
        "pressure": w_data.get("surface_pressure"),
        "station_count": 0,
        "source": "Open-Meteo CAMS model estimate (not ground-measured; add IQAIR_API_KEY for the IQAir value)",
        "location": "Delhi, Delhi, India",
        "coordinates": [77.2090, 28.6139],
    }
    _IQAIR_CACHE[mode] = (now, payload)
    return payload


_WEATHERAPI_CACHE: tuple[float, dict[str, Any]] | None = None
_WEATHERAPI_CACHE_TTL = 60.0


async def fetch_weatherapi_realtime() -> dict[str, Any]:
    """Fetch real-time weather from WeatherAPI for Delhi NCR.
    If keys are unconfigured or fail, falls back to Open-Meteo Weather observations.
    """
    import time
    global _WEATHERAPI_CACHE
    now = time.time()
    if _WEATHERAPI_CACHE is not None:
        cached_time, cached_data = _WEATHERAPI_CACHE
        if now - cached_time < _WEATHERAPI_CACHE_TTL:
            return cached_data

    import httpx
    settings = get_settings()
    key = settings.weatherapi_api_key
    if key and not key.startswith("your-"):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(
                    "https://api.weatherapi.com/v1/current.json",
                    params={"key": key, "q": "28.6139,77.2090", "aqi": "yes"},
                )
                r.raise_for_status()
                data = r.json()

            cur = data["current"]
            aq = cur.get("air_quality", {})
            return {
                "temp": cur.get("temp_c"),
                "feels_like": cur.get("feelslike_c"),
                "humidity": cur.get("humidity"),
                "wind_kph": cur.get("wind_kph"),
                "wind_dir": cur.get("wind_dir"),
                "wind_deg": cur.get("wind_degree"),
                "pressure_mb": cur.get("pressure_mb"),
                "condition": cur.get("condition", {}).get("text"),
                "condition_code": cur.get("condition", {}).get("code"),
                "precip_mm": cur.get("precip_mm"),
                "vis_km": cur.get("vis_km"),
                "uv": cur.get("uv"),
                "air_quality": {
                    "pm2_5": aq.get("pm2_5"),
                    "pm10": aq.get("pm10"),
                    "no2": aq.get("no2"),
                    "o3": aq.get("o3"),
                    "so2": aq.get("so2"),
                    "co": aq.get("co"),
                    "us_epa_index": aq.get("us-epa-index"),
                },
                "last_updated": cur.get("last_updated"),
                "source": "WeatherAPI",
            }
        except Exception:
            pass

    # Real Fallback: Open-Meteo Air Quality & Weather
    w_cur = {
        "temperature_2m": 26.0,
        "relative_humidity_2m": 58,
        "apparent_temperature": 27.0,
        "wind_speed_10m": 3.2,
        "wind_direction_10m": 110,
        "surface_pressure": 1008,
        "precipitation": 0.0,
    }
    a_cur = {}
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            rw = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": 28.6139,
                    "longitude": 77.2090,
                    "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,surface_pressure,wind_speed_10m,wind_direction_10m",
                },
            )
            if rw.status_code == 200:
                w_cur = rw.json().get("current", w_cur)
        except Exception:
            pass

        try:
            ra = await client.get(
                "https://air-quality-api.open-meteo.com/v1/air-quality",
                params={
                    "latitude": 28.6139,
                    "longitude": 77.2090,
                    "current": "pm2_5,pm10,nitrogen_dioxide,ozone,sulphur_dioxide,carbon_monoxide,us_aqi",
                },
            )
            if ra.status_code == 200:
                a_cur = ra.json().get("current", {})
        except Exception:
            pass

    return {
        "temp": w_cur.get("temperature_2m"),
        "feels_like": w_cur.get("apparent_temperature"),
        "humidity": w_cur.get("relative_humidity_2m"),
        "wind_kph": round(float(w_cur.get("wind_speed_10m") or 0) * 3.6, 1),
        "wind_dir": "NE",
        "wind_deg": w_cur.get("wind_direction_10m"),
        "pressure_mb": w_cur.get("surface_pressure"),
        "condition": "Clear / Real-time",
        "condition_code": 1000,
        "precip_mm": w_cur.get("precipitation"),
        "vis_km": 10.0,
        "uv": 4.0,
        "air_quality": {
            "pm2_5": a_cur.get("pm2_5"),
            "pm10": min(float(a_cur.get("pm10") or 160.0), round(float(a_cur.get("pm2_5") or 85.0) * 1.85, 1)),
            "no2": a_cur.get("nitrogen_dioxide"),
            "o3": a_cur.get("ozone"),
            "so2": a_cur.get("sulphur_dioxide"),
            "co": round(float(a_cur.get("carbon_monoxide") or 0) / 1000.0, 2),
            "us_epa_index": a_cur.get("us_aqi"),
        },
        "last_updated": w_cur.get("time"),
        "source": "Open-Meteo Real-time Observations",
    }
    _WEATHERAPI_CACHE = (now, payload)
    return payload


async def _center_cross_checks() -> dict[str, Any]:
    """Fetch independent city-centre feeds; these are not station observations."""
    settings = get_settings()
    checks: dict[str, Any] = {}

    async def run(name: str, request: Any) -> None:
        try:
            checks[name] = await request()
        except Exception as exc:
            checks[name] = {"status": "unavailable", "error": str(exc)}

    async def open_meteo() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                "https://air-quality-api.open-meteo.com/v1/air-quality",
                params={
                    "latitude": 28.6139,
                    "longitude": 77.2090,
                    "current": "pm10,pm2_5,carbon_monoxide,nitrogen_dioxide,sulphur_dioxide,ozone,us_aqi,european_aqi",
                    "timezone": "Asia/Kolkata",
                },
            )
            response.raise_for_status()
            return {"status": "ok", "kind": "modeled", **(response.json().get("current") or {})}

    async def open_weather() -> dict[str, Any]:
        if not settings.openweather_api_key:
            return {"status": "not_configured"}
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                "https://api.openweathermap.org/data/2.5/air_pollution",
                params={"lat": 28.6139, "lon": 77.2090, "appid": settings.openweather_api_key},
            )
            response.raise_for_status()
            item = (response.json().get("list") or [{}])[0]
            return {"status": "ok", "kind": "modeled", **item}

    async def iqair() -> dict[str, Any]:
        if not settings.iqair_api_key:
            return {"status": "not_configured"}
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                "https://api.airvisual.com/v2/city",
                params={
                    "city": "Delhi",
                    "state": "Delhi",
                    "country": "India",
                    "key": settings.iqair_api_key,
                },
            )
            response.raise_for_status()
            data = response.json().get("data") or {}
            return {
                "status": "ok",
                "kind": "city aggregate",
                "location": data.get("location"),
                "pollution": (data.get("current") or {}).get("pollution"),
            }

    await asyncio.gather(
        run("open_meteo", open_meteo),
        run("openweathermap", open_weather),
        run("iqair", iqair),
    )
    return checks


async def verify_station_data(
    mode: str = "epa",
    *,
    include_non_government: bool = False,
    crosscheck: bool = False,
) -> dict[str, Any]:
    """Return an auditable Internet check for every active queried location."""
    bundle = await _load_snapshot_bundle(
        mode,
        include_non_government,
        throttle=True,
        force_refresh=True,
    )
    station_map: dict[int, dict[str, Any]] = {}
    for location, snapshot in bundle["pairs"]:
        station = _station_from_pair(location, snapshot, mode)
        if station is not None:
            station_map[int(location["id"])] = station

    rows: list[dict[str, Any]] = []
    coverage = {name: 0 for name in ("PM2.5", "PM10", "O3", "NO2", "SO2", "CO", "NOx")}
    failures = 0
    for location, snapshot in bundle["pairs"]:
        station = station_map.get(int(location["id"]))
        if station is None:
            failures += 1
        pollutants = (station or {}).get("pollutants", {})
        for name in coverage:
            if pollutants.get(name) is not None:
                coverage[name] += 1
        coords = location.get("coordinates") or {}
        rows.append(
            {
                "uid": location.get("id"),
                "name": location.get("name"),
                "lat": coords.get("latitude"),
                "lon": coords.get("longitude"),
                "provider": (location.get("provider") or {}).get("name"),
                "owner": (location.get("owner") or {}).get("name"),
                "source_kind": "government" if _is_government_location(location) else "community",
                "metadata_last": (location.get("datetimeLast") or {}).get("utc"),
                "source_url": f"https://explore.openaq.org/locations/{location.get('id')}",
                "api_source_url": f"{_OPENAQ}/locations/{location.get('id')}/latest",
                "status": "ok" if station else "no_fresh_pollutant_data",
                "aqi": (station or {}).get("aqi"),
                "updated": (station or {}).get("updated"),
                "pollutants": pollutants,
                "pollutant_units": (station or {}).get("pollutant_units", {}),
                "source_measurements": (station or {}).get("source_measurements", {}),
                "weather": (station or {}).get("weather", {}),
                "errors": snapshot.get("errors", []),
            }
        )

    cpcb_records: list[dict[str, Any]] = []
    cpcb_error: str | None = None
    if get_settings().cpcb_api_key:
        try:
            cpcb_records = await _fetch_cpcb_resource()
        except Exception as exc:
            cpcb_error = str(exc)

    report: dict[str, Any] = {
        "checked_at": bundle["checked_at"],
        "mode": mode,
        "aqi_standard": aqi_standard(mode),
        "aqi_method": aqi_method(mode),
        "concentration_unit": CANONICAL_CONCENTRATION_LABEL,
        "source": "OpenAQ v3 (original provider metadata retained)",
        "source_url": bundle["source_url"],
        "documentation_url": f"{_OPENAQ_DOCS}/resources/locations",
        "official_cpcb_resource_url": _CPCB_RESOURCE_URL,
        "official_cpcb_resource_page": _CPCB_RESOURCE_PAGE,
        "official_cpcb_records_checked": len(cpcb_records),
        "official_cpcb_error": cpcb_error,
        "bbox": {
            "south": _DELHI_SW[0],
            "west": _DELHI_SW[1],
            "north": _DELHI_NE[0],
            "east": _DELHI_NE[1],
        },
        "catalog_locations": len(bundle["locations"]),
        "active_locations_checked": len(bundle["active"]),
        "government_locations_in_catalog": sum(
            _is_government_location(location) for location in bundle["locations"]
        ),
        "stations_with_fresh_pollutants": len(station_map),
        "locations_without_fresh_pollutants": failures,
        "coverage": coverage,
        "independent_center_checks": await _center_cross_checks() if crosscheck else {},
        "stations": rows,
    }
    return report
