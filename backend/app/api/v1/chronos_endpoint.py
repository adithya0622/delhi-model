"""Chronos T5 endpoint — open-source token-based foundation-model forecast.

`GET /forecast/72hr-chronos` serves the Amazon Chronos T5 forecasts (all six
pollutants, 72 h, p10/p50/p90 per species) plus official CPCB/EPA AQI per hour.

Context discipline: the model context is the trailing 168 h of CAMS archive
observations at the requested point — the same source, units, and scale the
model was trained on. The future grid (timestamps only) comes from the
operational forecast feed; the model never sees future chemistry, only its own
generated tokens.

Fallback: when the Chronos stack or artifact is unavailable (or inference
fails), the endpoint transparently serves the existing v3/v4 ML endpoint
response with `fallback_used: true` and `chronos_status` naming the reason —
never a silent degradation, never a fabricated forecast.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Query, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.services.chronos_forecast_service import (
    FT_CONTEXT_HOURS as _FT_CONTEXT_HOURS,
    HORIZON_HOURS,
    chronos_model_status,
    finetuned_serving_ready,
    predict_72hr_chronos,
    predict_72hr_chronos2_finetuned,
    predict_72hr_chronos_c2,
    serving_model,
)
from app.services.weather_providers import fetch_forecast_weather
# Module-level alias so tests (and callers) can patch the fallback handler.
from app.api.v1.ml_forecast_endpoint import forecast_72hr_ml as _ml_forecast_handler

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)

_CAMS_ARCHIVE_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
_MODEL_SPECIES = ("pm2_5", "pm10", "no2", "o3", "so2", "co")
_CAMS_VAR = {
    "pm2_5": "pm2_5",
    "pm10": "pm10",
    "no2": "nitrogen_dioxide",
    "o3": "ozone",
    "so2": "sulphur_dioxide",
    "co": "carbon_monoxide",
}


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
        "hourly": (
            "temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m,"
            "precipitation,boundary_layer_height,shortwave_radiation,"
            "temperature_1000hPa,temperature_925hPa"
        ),
        "past_days": 14,
        "forecast_days": 3,
        "timezone": "Asia/Kolkata",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get("https://api.open-meteo.com/v1/forecast", params=params)
        response.raise_for_status()
        return response.json().get("hourly", {}) or {}


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
        future = [float(v) if v is not None else None for v in values[cut:cut + HORIZON_HOURS]]
        if past and future:
            out[name] = (past, future)

    # Calendar covariates for the fine-tuned specialists (match the trainer).
    stamps = []
    for stamp in times:
        try:
            stamps.append(datetime.fromisoformat(str(stamp)))
        except ValueError:
            continue
    past_stamps, future_stamps = stamps[:cut], stamps[cut:cut + HORIZON_HOURS]

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
    from the CAMS payload, channel-named exactly as the trainer named them."""
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
        future = [float(v) if v is not None else None for v in values[cut:cut + HORIZON_HOURS]]
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


async def _fallback_to_ml(request: Request, lat: float, lon: float, station_name: str, reason: Any) -> dict[str, Any]:
    result = await _ml_forecast_handler(request, lat=lat, lon=lon, station_name=station_name)
    result["fallback_used"] = True
    result["requested_model"] = "Amazon Chronos T5 (72hr-chronos)"
    result["chronos_status"] = reason
    return result


@router.get(
    "/forecast/72hr-chronos",
    summary="72-hour token-based foundation-model forecast (Amazon Chronos T5): six pollutants + AQI with p10/p50/p90 bands",
    tags=["Forecast"],
)
@limiter.limit("30/minute")
async def forecast_72hr_chronos(
    request: Request,
    lat: float = Query(28.6139, ge=28.0, le=29.0),
    lon: float = Query(77.2090, ge=76.5, le=77.8),
    station_name: str = Query("Delhi-ITO", max_length=64),
    num_samples: int = Query(20, ge=5, le=50, description="Chronos sample paths per species (quantiles from these)"),
) -> dict[str, Any]:
    status = chronos_model_status()
    # The ft variant can serve even without the T5 artifact present.
    ft_capable = serving_model() == "chronos2_ft" and finetuned_serving_ready()
    if not status.get("available") and not ft_capable:
        return await _fallback_to_ml(request, lat, lon, station_name, status)

    try:
        met_data = await fetch_forecast_weather(lat, lon)
        forecast_times = list((met_data.get("hourly") or {}).get("time") or [])[:HORIZON_HOURS]
        if len(forecast_times) < HORIZON_HOURS:
            raise RuntimeError("operational forecast grid is shorter than 72 h")

        origin = min(datetime.fromisoformat(str(t)) for t in forecast_times)
        cams_hourly = await fetch_cams_context(lat, lon)
        history_series = build_history_series(cams_hourly, origin)

        if serving_model() == "chronos2_ft":
            # Delhi fine-tuned specialists: full covariate superset — CAMS
            # co-pollutant/AOD/dust forecast fields + HRES meteorology +
            # calendar channels, each as (past, next-72h) pairs.
            met_hourly = await fetch_met_context(lat, lon)
            covariates = _split_covariates(met_hourly, origin)
            covariates.update(_cams_covariate_split(cams_hourly, origin))
            hours, chronos_status = predict_72hr_chronos2_finetuned(
                history_series, covariates, {"hourly": {"time": forecast_times}}
            )
        elif serving_model() == "chronos2":
            # Zero-shot Chronos-2: native multivariate; meteorology rides
            # along as past + future-known covariates from one keyless call.
            met_hourly = await fetch_met_context(lat, lon)
            covariates = _split_covariates(met_hourly, origin)
            hours, chronos_status = predict_72hr_chronos_c2(
                history_series, {"hourly": {"time": forecast_times}}, covariates
            )
        else:
            hours, chronos_status = predict_72hr_chronos(
                history_series,
                {"hourly": {"time": forecast_times}},
                num_samples=num_samples,
            )
        if hours is None:
            raise RuntimeError(chronos_status.get("reason", "chronos inference unavailable"))
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        return await _fallback_to_ml(
            request, lat, lon, station_name, {**status, "reason": f"{type(exc).__name__}: {exc}"}
        )

    # ── Verification block: holdout metrics of the SERVED variant only ──────
    # (never mix the T5 artifact's numbers into a Chronos-2 response or vice versa)
    variant = serving_model()
    is_c2 = variant == "chronos2"
    is_ft = variant == "chronos2_ft"
    ft_block = chronos_status.get("delhi_finetune") or {}
    verification: dict[str, Any] = {}
    if is_ft:
        aqi = (ft_block.get("aqi") or {})
        overall, winter = aqi.get("overall") or {}, aqi.get("winter") or {}
        pm = ft_block.get("pm2_5") or {}
        verification = {
            "delhi_finetune_gates": {
                "verdict": ft_block.get("gates_verdict"),
                "gates": ft_block.get("gates") or {},
                "pm2_5_rmse": pm.get("rmse"),
                "pm2_5_r2": pm.get("r2"),
                "pm2_5_zero_shot": ft_block.get("pm2_5_zero_shot"),
                "targets": "RMSE < 15, R2 > 0.87 (leak-free chronological holdout)",
                "ablation_no_future_covariates": (ft_block.get("ablation") or {}).get("pm2_5_no_future_covariates"),
                "leakage_note": ft_block.get("leakage_note"),
                "holdout_start": ft_block.get("holdout_start"),
                "eval_origins": ft_block.get("eval_origins"),
            },
            "species_holdout": ft_block.get("species") or {},
        }
        if overall:
            verification.update({
                "cpcb_aqi_mae": overall.get("aqi_cpcb_mae"),
                "cpcb_aqi_rmse": overall.get("aqi_cpcb_rmse"),
                "cpcb_aqi_r2": overall.get("aqi_cpcb_r2"),
                "winter_cpcb_aqi_mae": winter.get("aqi_cpcb_mae"),
                "winter_cpcb_aqi_r2": winter.get("aqi_cpcb_r2"),
            })
    else:
        holdout = chronos_status.get("holdout") or {}
        aqi_block = holdout.get("aqi") or {}
        overall = aqi_block.get("overall") or {}
        winter = aqi_block.get("winter") or {}
        persistence = holdout.get("persistence") or {}
        if overall.get("n"):
            verification = {
                "cpcb_aqi_mae": overall.get("aqi_cpcb_mae"),
                "cpcb_aqi_rmse": overall.get("aqi_cpcb_rmse"),
                "cpcb_aqi_r2": overall.get("aqi_cpcb_r2"),
                "winter_r2": winter.get("aqi_cpcb_r2"),
                "winter_cpcb_aqi_mae": winter.get("aqi_cpcb_mae"),
                "persistence_cpcb_aqi_mae": persistence.get("aqi_cpcb_mae"),
                "holdout_start": chronos_status.get("holdout_start"),
                "holdout_hours_scored": overall.get("n"),
            }
            c2 = chronos_status.get("chronos2_benchmark")
            if c2 and c2.get("cpcb_aqi_mae") is not None:
                verification["model_comparison"] = {
                    "served_chronos_t5_finetuned": {"cpcb_aqi_mae": verification["cpcb_aqi_mae"]},
                    "chronos2_zero_shot_with_covariates": {"cpcb_aqi_mae": c2["cpcb_aqi_mae"]},
                    "flat_persistence": {"cpcb_aqi_mae": verification.get("persistence_cpcb_aqi_mae")},
                    "leaderboard": (chronos_status.get("model_comparison") or {}).get("aqi_mae_leaderboard") or {},
                    "winner_by_aqi_mae": (chronos_status.get("model_comparison") or {}).get("winner_by_aqi_mae"),
                }

    names = {
        "chronos2_ft": "Amazon Chronos-2 (Open Source Foundation Model — Delhi fine-tuned, covariate-aware)",
        "chronos2": "Amazon Chronos-2 (Open Source Foundation Model — universal multivariate)",
        "t5": "Amazon Chronos T5 (Open Source Foundation Model)",
    }
    architectures = {
        "chronos2_ft": (
            "Patch-based time-series encoder with quantile regression heads; one LoRA fine-tuned "
            "specialist per pollutant on Delhi's 4-year CAMS/HRES archive, conditioned on operationally "
            "available future covariates (co-pollutant CAMS fields + meteorology + calendar)"
        ),
        "chronos2": (
            "Patch-based time-series encoder with quantile regression heads; "
            "all six pollutants forecast jointly with meteorology covariates"
        ),
        "t5": (
            "Transformer-based tokenized time-series generator "
            "(mean-scale uniform-bin tokeniser → T5 encoder-decoder → autoregressive token generation)"
        ),
    }
    return {
        "model_name": names[variant],
        "architecture": architectures[variant],
        "vocabulary_size": None if is_c2 or is_ft else chronos_status.get("vocabulary_size"),
        "context_hours": _FT_CONTEXT_HOURS if is_ft else chronos_status.get("serving_context_hours"),
        "forecast_horizon_hours": HORIZON_HOURS,
        "location": {"lat": lat, "lon": lon},
        "station_name": station_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "hourly": hours,
        "verification": verification,
        "chronos_status": chronos_status,
        "fallback_used": False,
        "limitations": [
            (
                "Context = trailing 720 h of CAMS archive observations; the forecast conditions on "
                "operationally published CAMS/HRES forecast fields (co-pollutants + meteorology) for the "
                "target window — the target pollutant's own future is never an input (leak-free)"
                if is_ft
                else "Context = trailing 168 h of CAMS archive observations at this point; the model sees no future chemistry — only its own generated tokens"
            ),
            "AQI is computed from the p50 concentrations with the official CPCB 2014 / US EPA breakpoint tables (max of six sub-indices)",
            "p10/p90 bands reflect the model's sampled token trajectories, not calibrated uncertainty for extreme episodes",
            "Beyond the model's native prediction window the forecast rolls out autoregressively on its own medians",
            "Verification metrics are CAMS-archive holdout scores (model-vs-reanalysis), not ground-station scores",
        ],
    }


@router.get(
    "/forecast/chronos-status",
    summary="Chronos T5 model status, token spec, and holdout metrics",
    tags=["Forecast"],
)
@limiter.limit("60/minute")
async def chronos_status_endpoint(request: Request) -> dict[str, Any]:
    """Availability of the Chronos artifact: token spec, holdout metrics, and
    the fallback reason when unavailable."""
    return chronos_model_status()
