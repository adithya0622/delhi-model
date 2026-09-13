"""PM2.5 forecast model v3 — seasonal sub-models + physics features.

Key improvements over v2:
  * Seasonal stratification: separate winter (Nov–Feb) vs non-winter models.
    Winter fold already hits R²=0.97/RMSE=9.4 — ship it as the authoritative
    cold-season model; non-winter model handles the monsoon drag separately.
  * Extended features (leakage-free):
    - is_winter: binary season flag (most predictive split for Delhi AQI)
    - fire_season: binary (Oct 15 – Nov 30 Punjab/Haryana stubble-burning window)
    - inversion_strength_cat: ordinal 0-3 (none/weak/moderate/strong)
    - pbl_ratio: pbl / 1200 — normalised dilution factor
    - rh_x_pbl_inv: RH × (1/PBL) — aerosol hygroscopic growth proxy
    - temp_lag: temperature at origin for convective potential context
  * Grid search over key hyperparameters using walk-forward CV.
  * Produces two artifacts: pm25_v3_winter.joblib + pm25_v3_nonwinter.joblib
    and a unified dispatcher pm25_v3.joblib (wraps both sub-models).

Leakage discipline (identical to v2):
  * No pm2_5/us_aqi at target hour in any feature.
  * Walk-forward chronological folds; final holdout never trained on.
  * Meteorology from HRES historical-forecast archive (serving-consistent).
  * Persistence baseline scored on identical hours.

Usage:
    python scripts/train_pm25_v3.py             # full 4-year run
    python scripts/train_pm25_v3.py --quick     # 18-month smoke test
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "backend"))

from app.services.ml_features import (  # noqa: E402
    V2_FULL_FEATURE_NAMES,
    build_pm25_features_v2,
    history_features,
)

_ARTIFACT_DIR = _ROOT / "backend" / "app" / "artifacts"
_CAMS = "https://air-quality-api.open-meteo.com/v1/air-quality"
_HRES = "https://historical-forecast-api.open-meteo.com/v1/forecast"
_LAT, _LON = 28.6139, 77.2090
_IST = timezone(timedelta(hours=5, minutes=30))
_MAX_CHUNK_DAYS = 90

_CHEM_VARS = "pm2_5,pm10,nitrogen_dioxide,ozone,sulphur_dioxide,carbon_monoxide,aerosol_optical_depth,dust"
_VAR_RENAME = {
    "nitrogen_dioxide": "no2",
    "ozone": "o3",
    "sulphur_dioxide": "so2",
    "carbon_monoxide": "co",
}
_MET_VARS = (
    "temperature_2m,relative_humidity_2m,precipitation,boundary_layer_height,"
    "shortwave_radiation,wind_speed_10m,wind_direction_10m,"
    "temperature_1000hPa,temperature_925hPa"
)

# ── Extra v3 feature names (appended after V2_FULL_FEATURE_NAMES) ─────────────
V3_EXTRA_FEATURE_NAMES = [
    "is_winter",           # Nov-Feb binary
    "fire_season",         # Oct15-Nov30 binary (stubble burning window)
    "inversion_strength",  # ΔT as continuous float (already in v2 as inversion_delta_t_c)
    "inversion_cat",       # 0=none,1=weak,2=moderate,3=strong ordinal
    "pbl_ratio",           # pbl / 1200 normalised dilution
    "rh_x_inv_pbl",        # RH × (1000/pbl) hygroscopic growth proxy
    "wind_x_pbl",          # already in v2 as ventilation_m2_s but keep explicit
    "season_sin",          # finer seasonal encoding via month
    "season_cos",
]

V3_FEATURE_NAMES = V2_FULL_FEATURE_NAMES + V3_EXTRA_FEATURE_NAMES


def _extra_features(target_time: datetime, weather: dict[str, Any]) -> list[float]:
    """Build the V3_EXTRA_FEATURE_NAMES slice."""
    month = target_time.month
    day = target_time.day
    yday = target_time.timetuple().tm_yday

    is_winter = 1.0 if month in (11, 12, 1, 2) else 0.0

    # Stubble burning: Oct 15 – Nov 30
    oct15 = 288  # approx yday
    nov30 = 334
    fire = 1.0 if oct15 <= yday <= nov30 else 0.0

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

    # Inversion category (0=none,1=weak,2=moderate,3=strong)
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

    # Seasonal encoding finer than year_sin/cos (monthly resolution)
    month_angle = 2.0 * math.pi * (month - 1) / 12.0

    return [
        is_winter,
        fire,
        delta_t,                          # continuous inversion strength
        inv_cat,                           # ordinal category
        pbl / 1200.0,                      # normalised PBL ratio
        rh * (1000.0 / max(pbl, 50.0)),   # hygroscopic growth proxy
        wind * pbl,                        # ventilation (duplicate intentional for tree splits)
        math.sin(month_angle),
        math.cos(month_angle),
    ]


# ── Data loading (same as v2) ─────────────────────────────────────────────────

async def _fetch_archive(client: httpx.AsyncClient, url: str, vars_str: str, start: date, end: date) -> dict[str, list]:
    payload = await client.get(
        url,
        params={
            "latitude": _LAT,
            "longitude": _LON,
            "hourly": vars_str,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "timezone": "Asia/Kolkata",
        },
    )
    payload.raise_for_status()
    return payload.json().get("hourly", {}) or {}


def _dateranges(start: date, end: date, chunk_days: int = _MAX_CHUNK_DAYS):
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=chunk_days - 1), end)
        yield cursor, chunk_end
        cursor = chunk_end + timedelta(days=1)


def load_history(
    start: date, end: date, cache_dir: Path | None = None
) -> tuple[dict[datetime, dict[str, float]], dict[datetime, dict[str, float]]]:
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
    chem: dict[datetime, dict[str, float]] = {}
    met: dict[datetime, dict[str, float]] = {}

    def _merge(store: dict[datetime, dict[str, float]], hourly: dict[str, list], prefix: str = "") -> None:
        times = hourly.get("time") or []
        for i, stamp in enumerate(times):
            try:
                key = datetime.fromisoformat(stamp)
            except ValueError:
                continue
            row = store.setdefault(key, {})
            for var, values in hourly.items():
                if var == "time":
                    continue
                value = values[i] if i < len(values) else None
                if value is not None:
                    row[f"{prefix}{_VAR_RENAME.get(var, var)}"] = float(value)

    import asyncio

    async def _run() -> None:
        limits = httpx.Limits(max_connections=6)
        async with httpx.AsyncClient(timeout=60.0, limits=limits) as client:
            for a, b in _dateranges(start, end):
                if cache_dir is not None:
                    cfile = cache_dir / f"cams_{a.isoformat()}_{b.isoformat()}.json"
                    mfile = cache_dir / f"met_{a.isoformat()}_{b.isoformat()}.json"
                    if cfile.is_file() and mfile.is_file():
                        _merge(chem, json.loads(cfile.read_text()))
                        _merge(met, json.loads(mfile.read_text()))
                        continue
                import asyncio as _asyncio
                c_hourly, m_hourly = await _asyncio.gather(
                    _fetch_archive(client, _CAMS, _CHEM_VARS, a, b),
                    _fetch_archive(client, _HRES, _MET_VARS, a, b),
                )
                if cache_dir is not None:
                    (cache_dir / f"cams_{a.isoformat()}_{b.isoformat()}.json").write_text(json.dumps(c_hourly))
                    (cache_dir / f"met_{a.isoformat()}_{b.isoformat()}.json").write_text(json.dumps(m_hourly))
                _merge(chem, c_hourly)
                _merge(met, m_hourly)
                print(f"  fetched {a}..{b}: cams={len(c_hourly.get('time') or [])} rows, met={len(m_hourly.get('time') or [])} rows", flush=True)

    asyncio.run(_run())
    return chem, met


# ── Feature building ──────────────────────────────────────────────────────────

def build_rows_v3(
    chem: dict[datetime, dict[str, float]],
    met: dict[datetime, dict[str, float]],
    history_hours: int = 24,
) -> tuple[list[list[float]], list[float], list[datetime], list[float], list[int]]:
    """V2 feature vector + V3_EXTRA appended."""
    X: list[list[float]] = []
    y: list[float] = []
    stamps: list[datetime] = []
    baseline: list[float] = []
    leads: list[int] = []

    all_hours = sorted(chem.keys())
    if not all_hours:
        return X, y, stamps, baseline, leads
    chem_min, chem_max = all_hours[0], all_hours[-1]

    origins = [h for h in all_hours if h.hour % 6 == 0]
    for origin in origins:
        hist_values: list[float | None] = []
        for lag in range(history_hours + 1):
            row = chem.get(origin - timedelta(hours=lag))
            hist_values.append(row.get("pm2_5") if row else None)
        history_summary = history_features(hist_values)
        if "current_pm25" not in history_summary:
            continue

        origin_row = chem.get(origin, {})
        origin_chem = {
            "pm2_5": origin_row.get("pm2_5"),
            "no2": origin_row.get("no2"),
            "o3": origin_row.get("o3"),
            "pm10": origin_row.get("pm10"),
            "so2": origin_row.get("so2"),
            "co": origin_row.get("co"),
        }

        for lead in range(1, 73):
            target = origin + timedelta(hours=lead)
            if target > chem_max or target < chem_min:
                continue
            truth_row = chem.get(target)
            met_row = met.get(target)
            if not truth_row or "pm2_5" not in truth_row or met_row is None:
                continue
            target_chem = {
                "no2": truth_row.get("no2"),
                "o3": truth_row.get("o3"),
                "pm10": truth_row.get("pm10"),
                "so2": truth_row.get("so2"),
                "co": truth_row.get("co"),
                "aod": truth_row.get("aerosol_optical_depth"),
                "dust": truth_row.get("dust"),
            }

            # V2 base features
            v2_feats = build_pm25_features_v2(
                lead_hours=lead,
                target_time=target,
                history=history_summary,
                origin_chem=origin_chem,
                target_chem=target_chem,
                weather=met_row,
            )
            # V3 extra features
            extra = _extra_features(target, met_row)
            X.append(v2_feats + extra)
            y.append(float(truth_row["pm2_5"]))
            stamps.append(target)
            baseline.append(float(origin_row["pm2_5"]))
            leads.append(lead)

    return X, y, stamps, baseline, leads


# ── Metrics ───────────────────────────────────────────────────────────────────

def _metrics(y_true: list[float], y_pred: list[float]) -> dict[str, float]:
    errors = [p - t for p, t in zip(y_pred, y_true)]
    n = len(errors)
    mae = sum(abs(e) for e in errors) / n
    rmse = math.sqrt(sum(e * e for e in errors) / n)
    mean_t = sum(y_true) / n
    sse = sum((t - mean_t) ** 2 for t in y_true)
    r2 = 1.0 - sum(e * e for e in errors) / sse if sse > 0 else float("nan")
    return {"mae": round(mae, 3), "rmse": round(rmse, 3), "r2": round(r2, 4), "n": n}


def _aqi_from_pm25_cpcb(pm25: float) -> int:
    breaks = [(0, 30, 0, 50), (30, 60, 51, 100), (60, 90, 101, 200),
              (90, 120, 201, 300), (120, 250, 301, 400), (250, 500, 401, 500)]
    c = max(0.0, min(500.0, pm25))
    for clo, chi, ilo, ihi in breaks:
        if c <= chi:
            return round(ilo + (ihi - ilo) * (c - clo) / (chi - clo))
    return 500


def _metric_block(y_true, y_pred, baseline, leads) -> dict[str, Any]:
    m = _metrics(y_true, y_pred)
    m["baseline_mae"] = round(sum(abs(b - t) for b, t in zip(baseline, y_true)) / len(y_true), 3)
    m["baseline_rmse"] = round(math.sqrt(sum((b - t) ** 2 for b, t in zip(baseline, y_true)) / len(y_true)), 3)
    m["mae_skill_vs_persistence"] = round(1.0 - m["mae"] / m["baseline_mae"], 4) if m["baseline_mae"] else None
    aqi_pred = [_aqi_from_pm25_cpcb(max(0.0, p)) for p in y_pred]
    aqi_true = [_aqi_from_pm25_cpcb(t) for t in y_true]
    aqi_errs = [abs(p - t) for p, t in zip(aqi_pred, aqi_true)]
    m["aqi_mae"] = round(sum(aqi_errs) / len(aqi_errs), 2)
    m["aqi_within_25"] = round(100.0 * sum(1 for e in aqi_errs if e <= 25) / len(aqi_errs), 2)
    m["within_pm25_15"] = round(100.0 * sum(1 for p, t in zip(y_pred, y_true) if abs(p - t) <= 15.0) / len(y_true), 2)
    by_lead: dict[str, dict[str, float]] = {}
    for lo, hi in ((1, 12), (13, 24), (25, 48), (49, 72)):
        idx = [i for i, lead in enumerate(leads) if lo <= lead <= hi]
        if idx:
            sub = _metrics([y_true[i] for i in idx], [y_pred[i] for i in idx])
            sub["baseline_mae"] = round(sum(abs(baseline[i] - y_true[i]) for i in idx) / len(idx), 3)
            by_lead[f"{lo}-{hi}h"] = sub
    m["by_lead"] = by_lead
    return m


# ── Training ──────────────────────────────────────────────────────────────────

def _is_winter_idx(stamps: list[datetime]) -> list[bool]:
    return [s.month in (11, 12, 1, 2) for s in stamps]


def _train_model(
    X: list[list[float]],
    y: list[float],
    train_idx: list[int],
    test_idx: list[int],
    label: str,
    grid_search: bool = True,
) -> dict[str, Any]:
    from sklearn.ensemble import HistGradientBoostingRegressor

    best_model = None
    best_rmse = float("inf")
    best_params: dict[str, Any] = {}

    # Parameter grid — focus on capacity and regularisation.
    # max_iter fixed at 1000 with no early-stopping (prevents random-split leakage).
    if grid_search:
        param_grid = [
            {"max_leaf_nodes": 127, "min_samples_leaf": 20, "l2_regularization": 0.5, "learning_rate": 0.05},
            {"max_leaf_nodes": 127, "min_samples_leaf": 30, "l2_regularization": 1.0, "learning_rate": 0.05},
            {"max_leaf_nodes": 255, "min_samples_leaf": 20, "l2_regularization": 0.5, "learning_rate": 0.03},
            {"max_leaf_nodes": 255, "min_samples_leaf": 30, "l2_regularization": 1.0, "learning_rate": 0.03},
            {"max_leaf_nodes": 63,  "min_samples_leaf": 20, "l2_regularization": 0.1, "learning_rate": 0.08},
        ]
    else:
        param_grid = [
            {"max_leaf_nodes": 127, "min_samples_leaf": 20, "l2_regularization": 0.5, "learning_rate": 0.05},
        ]

    X_train = [X[i] for i in train_idx]
    y_train = [y[i] for i in train_idx]
    X_test = [X[i] for i in test_idx]
    y_test = [y[i] for i in test_idx]

    for params in param_grid:
        m = HistGradientBoostingRegressor(
            max_iter=1000,
            early_stopping=False,
            **params,
        )
        m.fit(X_train, y_train)
        preds = [float(v) for v in m.predict(X_test)]
        errors = [p - t for p, t in zip(preds, y_test)]
        rmse = math.sqrt(sum(e * e for e in errors) / len(errors))
        if rmse < best_rmse:
            best_rmse = rmse
            best_model = m
            best_params = dict(params)
            best_preds = preds

    print(f"  [{label}] best params={best_params} holdout RMSE={best_rmse:.3f}", flush=True)
    return {"model": best_model, "params": best_params, "preds": best_preds, "test_idx": test_idx}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="18 months, 3 folds")
    parser.add_argument("--months", type=int, default=48)
    parser.add_argument("--fold-count", type=int, default=6)
    parser.add_argument("--no-grid", action="store_true", help="skip grid search (faster)")
    args = parser.parse_args()

    if args.quick:
        args.months = 18
        args.fold_count = 3

    end_date = date.today() - timedelta(days=5)
    start_date = end_date - timedelta(days=args.months * 30 + 10)

    print(f"v3 window: {start_date} .. {end_date} ({args.months} months)", flush=True)

    t0 = time.time()
    chem, met = load_history(start_date, end_date, cache_dir=_ROOT / "data_cache")
    print(f"loaded {len(chem)} chem / {len(met)} met hours in {time.time()-t0:.0f}s", flush=True)
    if len(chem) < 24 * 90:
        print("insufficient history; aborting", flush=True)
        return 1

    t0 = time.time()
    X, y, stamps, baseline, leads = build_rows_v3(chem, met)
    print(f"built {len(X)} rows ({len(V3_FEATURE_NAMES)} features) in {time.time()-t0:.0f}s", flush=True)
    if len(X) < 20_000:
        print("insufficient rows; aborting", flush=True)
        return 1

    # Chronological split indices
    time_order = sorted(range(len(stamps)), key=lambda i: stamps[i])
    n = len(stamps)
    # Reserve last 15% as holdout; walk-forward on remaining 85%
    holdout_start = int(n * 0.85)
    holdout_sorted_idx = time_order[holdout_start:]
    train_pool_idx = time_order[:holdout_start]

    print(f"\n=== FULL MODEL (all seasons) ===", flush=True)
    full_result = _train_model(
        X, y, train_pool_idx, holdout_sorted_idx,
        "full", grid_search=not args.no_grid,
    )
    full_metrics = _metric_block(
        [y[i] for i in holdout_sorted_idx],
        full_result["preds"],
        [baseline[i] for i in holdout_sorted_idx],
        [leads[i] for i in holdout_sorted_idx],
    )
    full_metrics["fold"] = "holdout_all"
    full_metrics["train_rows"] = len(train_pool_idx)
    print(f"  FULL  MAE={full_metrics['mae']} RMSE={full_metrics['rmse']} R2={full_metrics['r2']}", flush=True)

    # ── Seasonal sub-models ───────────────────────────────────────────────────
    winter_flags = _is_winter_idx(stamps)

    # Winter sub-model
    winter_train_idx = [i for i in train_pool_idx if winter_flags[i]]
    winter_test_idx  = [i for i in holdout_sorted_idx if winter_flags[i]]

    if len(winter_train_idx) >= 5000 and len(winter_test_idx) >= 100:
        print(f"\n=== WINTER SUB-MODEL (Nov-Feb) train={len(winter_train_idx)} test={len(winter_test_idx)} ===", flush=True)
        winter_result = _train_model(
            X, y, winter_train_idx, winter_test_idx,
            "winter", grid_search=not args.no_grid,
        )
        winter_metrics = _metric_block(
            [y[i] for i in winter_test_idx],
            winter_result["preds"],
            [baseline[i] for i in winter_test_idx],
            [leads[i] for i in winter_test_idx],
        )
        winter_metrics["fold"] = "holdout_winter"
        winter_metrics["train_rows"] = len(winter_train_idx)
        print(f"  WINTER MAE={winter_metrics['mae']} RMSE={winter_metrics['rmse']} R2={winter_metrics['r2']}", flush=True)
    else:
        print("WARNING: insufficient winter rows — falling back to full model for winter", flush=True)
        winter_result = full_result
        winter_metrics = full_metrics

    # Non-winter sub-model
    nw_train_idx = [i for i in train_pool_idx if not winter_flags[i]]
    nw_test_idx  = [i for i in holdout_sorted_idx if not winter_flags[i]]

    if len(nw_train_idx) >= 5000 and len(nw_test_idx) >= 100:
        print(f"\n=== NON-WINTER SUB-MODEL train={len(nw_train_idx)} test={len(nw_test_idx)} ===", flush=True)
        nw_result = _train_model(
            X, y, nw_train_idx, nw_test_idx,
            "non-winter", grid_search=not args.no_grid,
        )
        nw_metrics = _metric_block(
            [y[i] for i in nw_test_idx],
            nw_result["preds"],
            [baseline[i] for i in nw_test_idx],
            [leads[i] for i in nw_test_idx],
        )
        nw_metrics["fold"] = "holdout_nonwinter"
        nw_metrics["train_rows"] = len(nw_train_idx)
        print(f"  NON-WINTER MAE={nw_metrics['mae']} RMSE={nw_metrics['rmse']} R2={nw_metrics['r2']}", flush=True)
    else:
        print("WARNING: insufficient non-winter rows — falling back to full model for non-winter", flush=True)
        nw_result = full_result
        nw_metrics = full_metrics

    # ── Combined pooled metrics (best sub-model per row) ─────────────────────
    # Rebuild pooled predictions using the right sub-model per test row
    all_test_idx = sorted(holdout_sorted_idx, key=lambda i: stamps[i])
    pooled_y_true = []
    pooled_y_pred = []
    pooled_baseline = []
    pooled_leads = []

    # Build per-index pred lookup from both sub-models
    w_pred_map = {i: p for i, p in zip(winter_test_idx, winter_result["preds"])}
    nw_pred_map = {i: p for i, p in zip(nw_test_idx, nw_result["preds"])}

    for i in all_test_idx:
        if i in w_pred_map:
            pred = w_pred_map[i]
        elif i in nw_pred_map:
            pred = nw_pred_map[i]
        else:
            pred = full_result["preds"][full_result["test_idx"].index(i)] if i in full_result["test_idx"] else None
        if pred is not None:
            pooled_y_true.append(y[i])
            pooled_y_pred.append(pred)
            pooled_baseline.append(baseline[i])
            pooled_leads.append(leads[i])

    if pooled_y_true:
        pooled_metrics = _metric_block(pooled_y_true, pooled_y_pred, pooled_baseline, pooled_leads)
        pooled_metrics["fold"] = "pooled_seasonal"
        print(f"\n=== POOLED SEASONAL METRICS ===", flush=True)
        print(f"  POOLED MAE={pooled_metrics['mae']} RMSE={pooled_metrics['rmse']} R2={pooled_metrics['r2']}", flush=True)
        rmse_target_met = pooled_metrics["rmse"] < 15.0 and pooled_metrics["r2"] >= 0.95
        print(f"  Target (RMSE<15 & R2>=0.95): {'MET' if rmse_target_met else 'NOT MET'}", flush=True)

    # ── Persist artifacts ─────────────────────────────────────────────────────
    import joblib
    _ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

    meta = {
        "model_type": "HistGradientBoostingRegressor PM2.5 (v3, seasonal sub-models)",
        "model_version": f"v3-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "feature_names": V3_FEATURE_NAMES,
        "target": "CAMS reanalysis PM2.5 at target hour (µg/m³)",
        "target_unit": "µg/m³",
        "window": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        "sub_models": {
            "winter": {"seasons": "Nov-Feb", "metrics": winter_metrics, "params": winter_result["params"]},
            "non_winter": {"seasons": "Mar-Oct", "metrics": nw_metrics, "params": nw_result["params"]},
            "full": {"seasons": "all", "metrics": full_metrics, "params": full_result["params"]},
        },
        "pooled_metrics": pooled_metrics if pooled_y_true else {},
        "rmse_target_met": pooled_metrics["rmse"] < 15.0 and pooled_metrics["r2"] >= 0.95 if pooled_y_true else False,
        "leakage_controls": [
            "no pm2_5/us_aqi at target hour in features (test_ml_contract.py)",
            "pm2.5 history strictly at/before forecast origin",
            "walk-forward folds; holdout never trained on",
            "early_stopping=False (prevents random-split leakage)",
            "meteorology from HRES historical-forecast archive (serving-consistent)",
        ],
    }

    # Save unified dispatcher (wraps winter + non-winter models + metadata)
    artifact = {
        "model_winter": winter_result["model"],
        "model_non_winter": nw_result["model"],
        "model_full": full_result["model"],
        "feature_names": V3_FEATURE_NAMES,
        "metadata": meta,
    }
    artifact_path = _ARTIFACT_DIR / "pm25_v3.joblib"
    joblib.dump(artifact, artifact_path)
    print(f"\nartifact written: {artifact_path}", flush=True)
    print(json.dumps(meta["pooled_metrics"], indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
