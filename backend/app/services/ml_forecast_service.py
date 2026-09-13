"""Runtime inference for the trained PM2.5 forecast model (v2/v3, leak-free).

v3 (preferred): seasonal sub-models (winter Nov-Feb, non-winter Mar-Oct).
  Feature contract = V3_FEATURE_NAMES = V2_FULL_FEATURE_NAMES + V3_EXTRA_FEATURE_NAMES.
  Dispatch: target month in {11,12,1,2} → model_winter; else → model_non_winter.
  Falls back to model_full when a sub-model is absent.

v2 (fallback): used when pm25_v3.joblib is absent.
  No target-hour pm2_5 leakage. Same history + co-pollutant + met features.

V1 artifacts are rejected (documented leakage).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from app.services.ml_features import (
    V2_FULL_FEATURE_NAMES,
    V3_FEATURE_NAMES,
    build_extra_features_v3,
    build_pm25_features_v2,
    history_features,
)

_V3_PATH = Path(__file__).resolve().parents[1] / "artifacts" / "pm25_v3.joblib"
_V2_PATH = Path(__file__).resolve().parents[1] / "artifacts" / "pm25_v2.joblib"
_V4_PATH = Path(__file__).resolve().parents[1] / "artifacts" / "aqi_v4.joblib"
_IST = timezone(timedelta(hours=5, minutes=30))


def _local_hour(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(_IST).replace(tzinfo=None)
    return parsed.replace(minute=0, second=0, microsecond=0)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None



@lru_cache(maxsize=1)
def _load_v3_bundle() -> dict[str, Any] | None:
    """Load pm25_v3.joblib; returns dict with model_winter/model_non_winter/model_full or None."""
    if not _V3_PATH.is_file():
        return None
    try:
        bundle = joblib.load(_V3_PATH)
        if bundle.get("feature_names") != V3_FEATURE_NAMES:
            raise ValueError("v3 feature schema mismatch")
        return bundle
    except (OSError, KeyError, TypeError, ValueError, AttributeError):
        return None


@lru_cache(maxsize=1)
def _load_v2_bundle() -> tuple[Any, dict[str, Any]] | None:
    """Load pm25_v2.joblib; returns (model, metadata) or None."""
    if not _V2_PATH.is_file():
        return None
    try:
        bundle = joblib.load(_V2_PATH)
        model = bundle["model"]
        metadata = bundle["metadata"]
        if metadata.get("feature_names") != V2_FULL_FEATURE_NAMES:
            raise ValueError("v2 feature schema mismatch")
        return model, metadata
    except (OSError, KeyError, TypeError, ValueError, AttributeError):
        return None


# Keep old name as alias for code that still calls _load_bundle()
_load_bundle = _load_v2_bundle


@lru_cache(maxsize=1)
def _load_v4_bundle() -> dict[str, Any] | None:
    """Load aqi_v4.joblib (direct CPCB/EPA AQI heads); None when absent/rejected.

    An artifact whose training-time acceptance gates failed is NOT served: the
    plan's contract is that a rejected v4 leaves the computed path primary
    rather than shipping a model that lost to its own baseline.
    """
    if not _V4_PATH.is_file():
        return None
    try:
        bundle = joblib.load(_V4_PATH)
        if bundle.get("feature_names") != V3_FEATURE_NAMES:
            raise ValueError("v4 feature schema mismatch")
        if not (bundle.get("metadata") or {}).get("accepted", False):
            raise ValueError("v4 artifact did not pass training acceptance gates")
        return bundle
    except (OSError, KeyError, TypeError, ValueError, AttributeError):
        return None


def _pick_model(target_time: datetime, v3_bundle: dict[str, Any]) -> Any:
    """Choose winter vs non-winter sub-model from v3 bundle."""
    is_winter = target_time.month in (11, 12, 1, 2)
    if is_winter and v3_bundle.get("model_winter") is not None:
        return v3_bundle["model_winter"]
    if not is_winter and v3_bundle.get("model_non_winter") is not None:
        return v3_bundle["model_non_winter"]
    return v3_bundle["model_full"]


def model_status() -> dict[str, Any]:
    v3 = _load_v3_bundle()
    if v3 is not None:
        meta = v3.get("metadata", {})
        pooled = meta.get("pooled_metrics", {})
        winter = meta.get("sub_models", {}).get("winter", {}).get("metrics", {})
        return {
            "available": True,
            "model": meta.get("model_type", "HistGradientBoosting PM2.5 (v3, seasonal)"),
            "version": meta.get("model_version"),
            "contract": "v3_seasonal",
            "target": meta.get("target", "CAMS reanalysis PM2.5 at target hour"),
            "target_unit": "µg/m³",
            "pooled_rmse": pooled.get("rmse"),
            "pooled_r2": pooled.get("r2"),
            "pooled_mae": pooled.get("mae"),
            "winter_rmse": winter.get("rmse"),
            "winter_r2": winter.get("r2"),
            "rmse_target_met": meta.get("rmse_target_met", False),
            "leakage_guarantee": "no target-hour pm2_5/us_aqi feature; seasonal dispatch",
            "mode": "v3_seasonal_sub_models",
        }
    # fall back to v2
    v2 = _load_v2_bundle()
    if v2 is not None:
        _model, metadata = v2
        held = metadata.get("held_out_test") or {}
        skill = metadata.get("skill_vs_persistence") or {}
        return {
            "available": True,
            "model": metadata.get("model_type", "HistGradientBoosting PM2.5 (v2)"),
            "version": metadata.get("model_version"),
            "contract": "v2_leak_free",
            "target": metadata.get("target", "CAMS reanalysis PM2.5 at target hour"),
            "target_unit": "µg/m³",
            "held_out_rmse_pm25_ug_m3": held.get("rmse"),
            "held_out_r2_pm25": held.get("r2"),
            "held_out_mae_pm25_ug_m3": held.get("mae"),
            "skill_vs_persistence_mae": skill.get("mae_skill_score"),
            "leakage_guarantee": "no target-hour pm2_5/us_aqi feature (enforced by test_ml_contract.py)",
            "validation": "chronological walk-forward folds + final holdout; not a guarantee",
            "mode": "v2_leak_free",
        }
    return {
        "available": False,
        "model": "physics-only",
        "mode": "none",
        "reason": "neither v3 nor v2 artifact found",
    }


def _history_from_payload(
    air_quality_payload: dict[str, Any] | None,
    forecast_origin: datetime,
) -> list[float | None]:
    """Newest-first pm2.5 history at/before the forecast origin from CAMS."""
    air = (air_quality_payload or {}).get("hourly") or {}
    times = air.get("time") or []
    values = air.get("pm2_5") or []
    by_time: dict[datetime, float] = {}
    for stamp, value in zip(times, values):
        number = _finite(value)
        if number is None or number < 0:
            continue
        try:
            by_time[_local_hour(stamp)] = number
        except ValueError:
            continue
    # newest-first: t0, t0-1h, ... t0-24h
    return [by_time.get(forecast_origin - timedelta(hours=lag)) for lag in range(25)]


def _chemistry_by_hour(air_quality_payload: dict[str, Any] | None) -> tuple[list[dict[str, float | None]], list[str]]:
    air = (air_quality_payload or {}).get("hourly") or {}
    times = list(air.get("time") or [])
    n = len(times)
    rows: list[dict[str, float | None]] = []
    for i in range(n):
        row: dict[str, float | None] = {}
        for pol in ("pm2_5", "pm10", "no2", "o3", "so2", "co", "aerosol_optical_depth", "dust"):
            vals = air.get(pol) or []
            row[pol] = _finite(vals[i]) if i < len(vals) else None
        # Normalise to the feature-builder's key names: the builder reads the
        # optical depth as `aod` (the trainer's rename), the live payload
        # spells it `aerosol_optical_depth`. Without this the live row would
        # silently carry NaN where training had a real value.
        row["aod"] = row.pop("aerosol_optical_depth", None)
        rows.append(row)
    return rows, times


def _build_inference_rows(
    *,
    forecast_times: list[str],
    weather_payload: dict[str, Any],
    air_quality_payload: dict[str, Any] | None,
    history_rows: list[dict[str, Any]] | None,
) -> tuple[list[list[float]], list[datetime], dict[str, Any] | None]:
    """Feature vectors shared by the PM2.5 (v2/v3) and direct-AQI (v4) paths.

    Returns (rows, target_stamps, fail) where ``fail`` is None on success or a
    status dict explaining why no rows could be built (missing model context is
    the caller's concern — this only covers payload/history failures).
    """
    forecast_origin = _local_hour(forecast_times[0])

    # ── Origin history: ground observations take precedence, else CAMS ──────
    recent: list[float | None] = [None] * 25
    if history_rows:
        obs: dict[datetime, float] = {}
        for row in history_rows:
            stamp = row.get("timestamp")
            value = _finite(row.get("value_ug_m3", row.get("pm25_ug_m3", row.get("value"))))
            if stamp is not None and value is not None and value >= 0:
                obs[_local_hour(str(stamp))] = value
        if obs:
            eligible = [stamp for stamp in obs if stamp <= forecast_origin]
            if eligible:
                newest = max(eligible)
                recent = [obs.get(newest - timedelta(hours=lag)) for lag in range(25)]
    if all(value is None for value in recent):
        recent = _history_from_payload(air_quality_payload, forecast_origin)
    if all(value is None for value in recent):
        return [], [], {"used": False, "reason": "no origin pm2.5 history available"}

    history_summary = history_features(recent)

    weather = weather_payload.get("hourly") or {}
    chem_rows, chem_times = _chemistry_by_hour(air_quality_payload)
    if not chem_rows and forecast_times:
        # Some callers (ml_forecast_endpoint, consensus_service) pass a
        # species-only payload with no `time` array — the chemistry grid is
        # the same hourly grid as the forecast times, so align species[i] to
        # forecast_times[i] instead of declaring the payload missing and
        # silently degrading every caller to physics-only.
        air = (air_quality_payload or {}).get("hourly") or {}
        chem_rows, chem_times = _chemistry_by_hour({
            "hourly": {"time": list(forecast_times), **air},
        })
    if not chem_rows:
        return [], [], {"used": False, "reason": "missing air-quality payload"}

    chem_by_local: dict[datetime, dict[str, float | None]] = {}
    for stamp, row in zip(chem_times, chem_rows):
        try:
            chem_by_local[_local_hour(stamp)] = row
        except ValueError:
            continue

    def _chem_at(stamp: datetime) -> dict[str, float | None]:
        direct = chem_by_local.get(stamp)
        if direct is not None:
            return direct
        for delta in (timedelta(hours=1), timedelta(hours=-1)):
            probe = chem_by_local.get(stamp + delta)
            if probe is not None:
                return probe
        return {}

    origin_chem_raw = _chem_at(forecast_origin)
    origin_chem = {k: (v if v is not None else float("nan")) for k, v in origin_chem_raw.items()}
    if not math.isfinite(float(origin_chem.get("pm2_5", float("nan")))):
        for value in recent:
            if value is not None:
                origin_chem["pm2_5"] = value
                break

    rows: list[list[float]] = []
    stamps: list[datetime] = []
    for index, stamp_str in enumerate(forecast_times):
        target = _local_hour(stamp_str)
        lead_hours = max(1, round((target - forecast_origin).total_seconds() / 3600.0))

        def at(name: str) -> Any:
            values = weather.get(name) or []
            return values[index] if index < len(values) else None

        target_chem_raw = _chem_at(target)
        target_chem = {k: (v if v is not None else float("nan")) for k, v in target_chem_raw.items()}
        target_chem.pop("pm2_5", None)  # never leak target pm2_5

        weather_row = {
            "temperature_2m": at("temperature_2m"),
            "relative_humidity_2m": at("relative_humidity_2m"),
            "precipitation": at("precipitation"),
            "boundary_layer_height": at("boundary_layer_height"),
            "shortwave_radiation": at("shortwave_radiation"),
            "wind_speed_10m": at("wind_speed_10m"),
            "wind_direction_10m": at("wind_direction_10m"),
            "temperature_1000hPa": at("temperature_1000hPa"),
            "temperature_925hPa": at("temperature_925hPa"),
        }

        v2_features = build_pm25_features_v2(
            lead_hours=lead_hours,
            target_time=target,
            history=history_summary,
            origin_chem=origin_chem,
            target_chem=target_chem,
            weather=weather_row,
        )
        extra = build_extra_features_v3(target, weather_row)
        features = [value if math.isfinite(value) else float("nan") for value in v2_features + extra]
        rows.append(features)
        stamps.append(target)

    return rows, stamps, None


def predict_pm25_series(
    *,
    forecast_times: list[str],
    weather_payload: dict[str, Any],
    air_quality_payload: dict[str, Any] | None,
    history_rows: list[dict[str, Any]] | None,
    station_lat: float,
    station_lon: float,
) -> tuple[list[float | None], dict[str, Any]]:
    """Predict PM2.5 for each forecast hour. Uses v3 seasonal sub-models when
    available, falls back to v2.

    ``history_rows`` (ground observations, newest-first friendly) are used for
    the origin history when supplied; otherwise CAMS past_days history from the
    air-quality payload is used. All other features come from the forecast
    payloads exactly as a live caller would see them at issue time.
    """
    status = model_status()
    if not status["available"] or not forecast_times:
        return [None] * len(forecast_times), {**status, "used": False, "reason": status.get("reason", "missing model")}

    v3_bundle = _load_v3_bundle()
    use_v3 = v3_bundle is not None
    if not use_v3:
        v2 = _load_v2_bundle()
        assert v2 is not None
        v2_model, _ = v2

    rows, stamps, fail = _build_inference_rows(
        forecast_times=forecast_times,
        weather_payload=weather_payload,
        air_quality_payload=air_quality_payload,
        history_rows=history_rows,
    )
    if fail is not None:
        return [None] * len(forecast_times), {**status, **fail}

    predictions: list[float | None] = []
    for features, target in zip(rows, stamps):
        if use_v3:
            model = _pick_model(target, v3_bundle)  # type: ignore[arg-type]
        else:
            model = v2_model  # type: ignore[assignment]
        try:
            prediction = float(model.predict(np.asarray([features], dtype=np.float32))[0])
        except (ValueError, TypeError):
            prediction = float("nan")
        predictions.append(round(min(max(prediction, 0.0), 1000.0), 2) if math.isfinite(prediction) else None)

    used = sum(value is not None for value in predictions)
    return predictions, {
        **status,
        "used": used > 0,
        "hours_used": used,
        "forecast_origin": stamps[0].isoformat() if stamps else None,
        "history_source": "station observations" if history_rows else "CAMS archive (past_days)",
        "model_version_used": "v3_seasonal" if use_v3 else "v2_leak_free",
    }


def aqi_model_status() -> dict[str, Any]:
    """Status of the direct-AQI model (v4), independent of the PM2.5 model."""
    v4 = _load_v4_bundle()
    if v4 is None:
        return {
            "available": False,
            "mode": "none",
            "reason": "aqi_v4 artifact absent or rejected by acceptance gates; AQI is computed from concentrations",
        }
    meta = v4.get("metadata", {})
    cpcb = meta.get("cpcb_metrics", {})
    winter = meta.get("winter_metrics", {})
    return {
        "available": True,
        "model": meta.get("model_type", "HistGradientBoosting direct AQI (v4, seasonal)"),
        "version": meta.get("model_version"),
        "contract": "v4_direct_aqi",
        "target": meta.get("target"),
        "target_unit": "AQI points (0-500)",
        "cpcb_aqi_mae": cpcb.get("aqi_mae"),
        "cpcb_band_within1_pct": cpcb.get("band_within1_pct"),
        "winter_aqi_mae": winter.get("aqi_mae") if winter else None,
        "skill_vs_computed": cpcb.get("skill_vs_computed"),
        "acceptance_gates": meta.get("acceptance_gates"),
        "mode": "v4_direct_aqi",
    }


def predict_aqi_series(
    *,
    forecast_times: list[str],
    weather_payload: dict[str, Any],
    air_quality_payload: dict[str, Any] | None,
    history_rows: list[dict[str, Any]] | None,
) -> tuple[list[int | None], list[int | None], dict[str, Any]]:
    """Directly predict CPCB and EPA AQI for each forecast hour (v4).

    Returns (cpcb_predictions, epa_predictions, status). Predictions are
    integers 0-500, or None per-hour when the model could not run. The caller
    MUST keep its computed-AQI path alongside: the endpoint serves the
    predicted values as primary and the computed block as `aqi_computed`
    precisely so a reader can always see both.
    """
    status = aqi_model_status()
    if not status["available"] or not forecast_times:
        return (
            [None] * len(forecast_times),
            [None] * len(forecast_times),
            {**status, "used": False},
        )

    v4 = _load_v4_bundle()
    assert v4 is not None

    rows, stamps, fail = _build_inference_rows(
        forecast_times=forecast_times,
        weather_payload=weather_payload,
        air_quality_payload=air_quality_payload,
        history_rows=history_rows,
    )
    if fail is not None:
        return (
            [None] * len(forecast_times),
            [None] * len(forecast_times),
            {**status, **fail},
        )

    def _pick(target: datetime, key_w: str, key_nw: str, key_f: str) -> Any:
        if target.month in (11, 12, 1, 2) and v4.get(key_w) is not None:
            return v4[key_w]
        if target.month not in (11, 12, 1, 2) and v4.get(key_nw) is not None:
            return v4[key_nw]
        return v4[key_f]

    cpcb_out: list[int | None] = []
    epa_out: list[int | None] = []
    for features, target in zip(rows, stamps):
        cpcb_model = _pick(target, "model_winter", "model_non_winter", "model_full")
        try:
            value = float(cpcb_model.predict(np.asarray([features], dtype=np.float32))[0])
            cpcb_out.append(int(round(min(max(value, 0.0), 500.0))) if math.isfinite(value) else None)
        except (ValueError, TypeError):
            cpcb_out.append(None)
        epa_model = v4.get("model_epa")
        if epa_model is not None:
            try:
                value = float(epa_model.predict(np.asarray([features], dtype=np.float32))[0])
                epa_out.append(int(round(min(max(value, 0.0), 500.0))) if math.isfinite(value) else None)
            except (ValueError, TypeError):
                epa_out.append(None)
        else:
            epa_out.append(None)

    used = sum(value is not None for value in cpcb_out)
    return cpcb_out, epa_out, {
        **status,
        "used": used > 0,
        "hours_used": used,
        "forecast_origin": stamps[0].isoformat() if stamps else None,
    }


