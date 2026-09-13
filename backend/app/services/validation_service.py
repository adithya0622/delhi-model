"""Historical validation for forecast model behaviour.

The endpoint uses archived weather and OpenAQ hourly observations. It does not
pretend that a current forecast can be compared with a past observation: each
requested start date gets its own archived meteorology and observed anchor.
"""

from __future__ import annotations

import asyncio
import math
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx

from app.services.aqi_service import (
    _solve_coupled_hour,
    emission_scale,
    seasonal_factors,
)
from app.core.config import get_settings
from app.domain.species import Pollutant
from app.physics.box_model import BoxColumn
from app.physics.inversion_engine import compute_inversion_series

_OPEN_METEO_HISTORICAL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
_OPENAQ = "https://api.openaq.org/v3"
_LAT, _LON = 28.6139, 77.2090
_LOCAL_TZ = timezone(timedelta(hours=5, minutes=30))
_VARIABLES = (
    "temperature_1000hPa,temperature_925hPa,boundary_layer_height,"
    "shortwave_radiation,wind_speed_10m"
)


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("date must use YYYY-MM-DD") from exc


def _validation_metrics(
    predicted: list[float],
    observed: list[float | None],
    anchor_index: int | None = None,
) -> dict[str, float | None]:
    """Score the run and a fair persistence baseline on identical hours.

    Persistence used to be scored as `observed[t] - observed[t-1]`, which hands the
    baseline every intervening observation while the model free-runs from a single
    anchor. That is not a forecast comparison -- it is a comparison against a
    nowcast, and it made a genuinely poor forecast look competitive or a decent one
    look hopeless depending only on how noisy the series was.

    Real persistence is "tomorrow looks like the last thing I saw": the anchor
    observation held flat across the whole horizon. Both series are scored on the
    same aligned hours strictly AFTER the anchor, because at the anchor hour
    persistence is exact by construction and the model is nudged onto the same
    value, so including it flatters both and measures nothing.
    """
    if anchor_index is None:
        anchor_index = next(
            (i for i, value in enumerate(observed) if value is not None), None
        )
    anchor_value = (
        observed[anchor_index]
        if anchor_index is not None and anchor_index < len(observed)
        else None
    )

    pairs = [(p, o) for p, o in zip(predicted, observed) if o is not None]
    if not pairs:
        raise ValueError("validation window contains no aligned observations")
    errors = [p - o for p, o in pairs]
    abs_errors = [abs(error) for error in errors]

    # Scored horizon: aligned hours after the anchor, identical for both series.
    start = 0 if anchor_index is None else anchor_index + 1
    horizon = [
        (predicted[i], observed[i])
        for i in range(start, min(len(predicted), len(observed)))
        if observed[i] is not None
    ]
    if anchor_value is not None and horizon:
        model_abs = [abs(p - o) for p, o in horizon]
        persistence_abs = [abs(anchor_value - o) for _p, o in horizon]
        model_mae_horizon = sum(model_abs) / len(model_abs)
        persistence_mae = sum(persistence_abs) / len(persistence_abs)
    else:
        model_mae_horizon = None
        persistence_mae = None

    observed_mean = sum(o for _, o in pairs) / len(pairs)
    numerator = sum(error * error for error in errors)
    denominator = sum((o - observed_mean) ** 2 for _, o in pairs)
    return {
        "mae_pm25_ug_m3": round(sum(abs_errors) / len(abs_errors), 3),
        "rmse_pm25_ug_m3": round(math.sqrt(numerator / len(errors)), 3),
        "bias_pm25_ug_m3": round(sum(errors) / len(errors), 3),
        "r2_pm25": round(1.0 - numerator / denominator, 4) if denominator else None,
        # Both figures below cover the same post-anchor hours, so they are directly
        # comparable; the headline MAE above covers every aligned hour.
        "scored_horizon_hours": len(horizon),
        "model_mae_horizon_ug_m3": (
            round(model_mae_horizon, 3) if model_mae_horizon is not None else None
        ),
        "persistence_mae_pm25_ug_m3": (
            round(persistence_mae, 3) if persistence_mae is not None else None
        ),
        "persistence_definition": (
            "anchor observation held flat across the horizon, scored on the same hours"
        ),
    }


def _hourly_observations(
    payload: dict[str, Any],
    *,
    start: datetime,
    hours: int,
) -> list[float | None]:
    """Map OpenAQ hourly PM2.5 rows onto forecast hour ends."""
    by_hour: dict[datetime, list[float]] = {}
    for row in payload.get("results") or []:
        period = row.get("period") or {}
        timestamp = period.get("datetimeTo") or period.get("datetimeFrom") or {}
        # OpenAQ source records can end on half-hour UTC boundaries while their
        # local timestamp is the station's actual hourly boundary. Align in local
        # station time, not by flooring UTC (which shifts India readings by 30 min).
        dt_raw = timestamp.get("local") or timestamp.get("utc")
        value = _finite(row.get("value"))
        if not dt_raw or value is None or value < 0:
            continue
        try:
            dt = datetime.fromisoformat(dt_raw.replace("Z", "+00:00")).astimezone(_LOCAL_TZ)
        except ValueError:
            continue
        by_hour.setdefault(dt.replace(minute=0, second=0, microsecond=0), []).append(value)
    aligned: list[float | None] = []
    for i in range(hours):
        key = (start + timedelta(hours=i)).astimezone(_LOCAL_TZ).replace(
            minute=0, second=0, microsecond=0
        )
        values = by_hour.get(key, [])
        aligned.append(sum(values) / len(values) if values else None)
    return aligned


async def _fetch_archived_weather(
    client: httpx.AsyncClient,
    start_date: date,
    hours: int,
) -> dict[str, Any]:
    response = await client.get(
        _OPEN_METEO_HISTORICAL,
        params={
            "latitude": _LAT,
            "longitude": _LON,
            "start_date": start_date.isoformat(),
            "end_date": (start_date + timedelta(days=4)).isoformat(),
            "hourly": _VARIABLES,
            "timezone": "Asia/Kolkata",
            "temperature_unit": "celsius",
            "wind_speed_unit": "ms",
        },
    )
    response.raise_for_status()
    return response.json()


async def _fetch_observations(
    client: httpx.AsyncClient,
    sensor_id: int,
    start: datetime,
    end: datetime,
    api_key: str,
) -> dict[str, Any]:
    response = await client.get(
        f"{_OPENAQ}/sensors/{sensor_id}/hours",
        params={
            "datetime_from": start.isoformat(),
            "datetime_to": end.isoformat(),
            "limit": 500,
            "sort_order": "asc",
        },
        headers={"X-API-Key": api_key},
    )
    response.raise_for_status()
    return response.json()


def _model_forecast(weather: dict[str, Any], observed_pm25: list[float | None]) -> list[float]:
    hourly = weather["hourly"]
    n = min(72, len(hourly["time"]))
    inversion = compute_inversion_series(weather)[:n]
    solar = hourly.get("shortwave_radiation") or [0.0] * n
    wind = hourly.get("wind_speed_10m") or [0.0] * n
    first_obs_index = next(
        (i for i, value in enumerate(observed_pm25[:n]) if value is not None),
        None,
    )
    if first_obs_index is None:
        raise ValueError("validation window has no observed PM2.5 anchor")

    first_dt = datetime.fromisoformat(hourly["time"][0])
    season = seasonal_factors(first_dt.month)
    column = BoxColumn.at_background(inversion[0]["pbl_height_m"], season)
    carry = 0.0
    wind_carry = 0.0
    memory_decay = math.exp(-1.0 / 8.0)
    output: list[float] = []
    # Keep validation deterministic and isolate forecast skill from the live plume
    # feed: historical fire replay requires a date-indexed FIRMS archive.
    for i in range(n):
        dt = datetime.fromisoformat(hourly["time"][i])
        scales = emission_scale(dt.hour)
        observed = observed_pm25[i] if i < len(observed_pm25) else None
        if i == first_obs_index and observed is not None:
            # Anchor column mass to observed PM2.5 without altering the physics
            # thereafter; this is equivalent to the production hour-0 nudge.
            for pollutant in (Pollutant.PM25, Pollutant.PM10):
                column.mixed[pollutant] = observed * column.h_m
        state = _solve_coupled_hour(
            col=column,
            pbl_observed_m=inversion[i]["pbl_height_m"],
            solar_w_m2=max(0.0, float(solar[i] or 0.0)),
            wind_ms=max(float(wind[i] or 0.0), 0.0),
            emis_scale=scales,
            season=seasonal_factors(dt.month),
            plume_pm25=0.0,
            cooling_carry_k=carry,
            wind_carry_k=wind_carry,
        )
        carry = memory_decay * carry + (1.0 - memory_decay) * state["cooling_instant_k"]
        # Same lagged wind memory as the production integrator, so the hindcast
        # exercises the same physics the forecast serves.
        wind_carry = max(state["cooling_instant_k"], memory_decay * wind_carry)
        output.append(float(state["conc"][Pollutant.PM25]))
    return output


async def validate_window(
    start_date: str,
    *,
    sensor_id: int = 12235610,
    hours: int = 72,
) -> dict[str, Any]:
    """Validate one archived 72-hour run against one OpenAQ PM2.5 sensor."""
    if hours < 24 or hours > 72:
        raise ValueError("hours must be between 24 and 72")
    target = _date(start_date)
    start_local = datetime.combine(target, datetime.min.time(), tzinfo=_LOCAL_TZ)
    end_local = start_local + timedelta(hours=hours)
    api_key = get_settings().openaq_api_key
    if not api_key or api_key.startswith("your-"):
        raise ValueError("OPENAQ_API_KEY is required for validation")

    async with httpx.AsyncClient(timeout=60.0) as client:
        weather, observations = await asyncio.gather(
            _fetch_archived_weather(client, target, hours),
            _fetch_observations(client, sensor_id, start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc), api_key),
        )
    # API returns midnight-local rows. Select requested local start explicitly,
    # then keep exactly `hours` of aligned weather and observations.
    target_start = start_local
    start_index = next(
        (
            i
            for i, value in enumerate(weather["hourly"]["time"])
            if datetime.fromisoformat(value).replace(tzinfo=_LOCAL_TZ) == target_start
        ),
        None,
    )
    if start_index is None:
        raise ValueError("archived weather response did not contain requested start")
    weather = {
        **weather,
        "hourly": {
            key: values[start_index : start_index + hours]
            for key, values in weather["hourly"].items()
        },
    }
    if len(weather["hourly"]["time"]) < hours:
        raise ValueError("archived weather response contained fewer than requested hours")
    observed = _hourly_observations(observations, start=target_start, hours=hours)
    predicted = _model_forecast(weather, observed)
    # Same anchor the model nudges onto, so the baseline starts from the same
    # information the forecast had.
    anchor_index = next((i for i, value in enumerate(observed) if value is not None), None)
    metrics = _validation_metrics(predicted, observed, anchor_index=anchor_index)
    observations = sum(value is not None for value in observed)
    model_horizon = metrics["model_mae_horizon_ug_m3"]
    persistence = metrics["persistence_mae_pm25_ug_m3"]
    return {
        "start_date": target.isoformat(),
        "sensor_id": sensor_id,
        "hours_requested": hours,
        "hours_aligned": observations,
        "weather_source": _OPEN_METEO_HISTORICAL,
        "weather_window": f"{target.isoformat()} through {(target + timedelta(days=4)).isoformat()}",
        "observation_source": f"{_OPENAQ}/sensors/{sensor_id}/hours",
        "metrics": metrics,
        "skill_note": (
            "Insufficient post-anchor observations to compare against persistence."
            if model_horizon is None or persistence is None
            else f"Model MAE {model_horizon} beats persistence {persistence} on the same hours."
            if model_horizon < persistence
            else f"Model MAE {model_horizon} does not beat persistence {persistence} on the same hours."
        ),
        "limitations": [
            "archived stubble-fire emissions are excluded",
            "one PM2.5 sensor is used",
            "historical meteorology is reanalysis/archived forecast data, not a coupled chemistry run",
            "persistence is the anchor observation held flat, scored on the same post-anchor hours",
        ],
        "observations": observations,
    }


async def validate_cpcb_windows(
    dates: list[str],
    *,
    sensor_id: int = 12235610,
    hours: int = 72,
) -> dict[str, Any]:
    """Validate several archived windows against CPCB/OpenAQ ground truth.

    Sequential (not parallel): OpenAQ free keys allow ~60 req/min and each
    window costs 1 met + 1 obs fetch. Callers must cap dates to <= 5.
    """
    from app.services.field_service import pool_cpcb_windows

    cleaned: list[str] = []
    for raw in dates:
        day = _date(str(raw).strip()).isoformat()
        if day not in cleaned:
            cleaned.append(day)
    if not cleaned:
        raise ValueError("dates must contain at least one YYYY-MM-DD entry")
    if len(cleaned) > 5:
        raise ValueError("at most 5 validation windows per request (upstream budget)")
    windows: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for day in cleaned:
        try:
            windows.append(await validate_window(day, sensor_id=sensor_id, hours=hours))
        except Exception as exc:  # one bad window must not fail the batch
            failures.append({"date": day, "error": str(exc)})
    if not windows:
        raise RuntimeError(f"all {len(cleaned)} CPCB windows failed: {failures}")
    return {
        "truth": "CPCB/OpenAQ surface observations (ground truth primary; CAMS secondary)",
        "sensor_id": sensor_id,
        "hours": hours,
        "pooled": pool_cpcb_windows(windows),
        "windows": windows,
        "failures": failures,
    }
