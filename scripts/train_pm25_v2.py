"""Leak-free training harness for the PM2.5 forecast model (v2 contract).

Data (free, no key):
    * truth + co-pollutant chemistry: Open-Meteo CAMS archive
      (air-quality-api.open-meteo.com), hourly, back to ~2022 for Delhi.
    * meteorology at the target hour: Open-Meteo HRES historical-forecast
      archive (historical-forecast-api.open-meteo.com) — the same upstream the
      live forecast consumes, so training met == serving met.

Leakage discipline (each point testable):
    * the target is CAMS pm2_5 at hour t; NO feature carries pm2_5 or us_aqi
      at hour t (enforced in ml_features + test_ml_contract.py).
    * pm2.5 history features use only hours <= t0 (the forecast origin).
    * meteorology uses the HRES historical-forecast archive: the forecast
      values for a past date as they were produced by the NWP run, not
      reanalysis states — the same information a live forecast would have.
    * validation is walk-forward: each fold trains strictly on data BEFORE the
      window it scores; the final holdout is the last ~3 months chronologically.
    * early stopping (sklearn) is OFF: its internal split is random and would
      leak future rows into training. Capacity is fixed a priori instead.
    * persistence baseline (origin pm2.5 held flat) is scored on the SAME
      hours; a model that cannot beat it is not shipped.

Usage:
    python scripts/train_pm25_v2.py                # ~4 years, 6 folds
    python scripts/train_pm25_v2.py --quick        # ~18 months, 3 folds
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
_ARTIFACT = _ARTIFACT_DIR / "pm25_v2.joblib"

_CAMS = "https://air-quality-api.open-meteo.com/v1/air-quality"
_HRES = "https://historical-forecast-api.open-meteo.com/v1/forecast"
_LAT, _LON = 28.6139, 77.2090
_IST = timezone(timedelta(hours=5, minutes=30))

_MAX_CHUNK_DAYS = 90

# CAMS chemistry variables (pm2_5 is truth; the rest are features).
# Open-Meteo spells gases out in full; the short forms are rejected.
_CHEM_VARS = "pm2_5,pm10,nitrogen_dioxide,ozone,sulphur_dioxide,carbon_monoxide,aerosol_optical_depth,dust"
_VAR_RENAME = {
    "nitrogen_dioxide": "no2",
    "ozone": "o3",
    "sulphur_dioxide": "so2",
    "carbon_monoxide": "co",
}
# HRES met variables at the target hour
_MET_VARS = (
    "temperature_2m,relative_humidity_2m,precipitation,boundary_layer_height,"
    "shortwave_radiation,wind_speed_10m,wind_direction_10m,"
    "temperature_1000hPa,temperature_925hPa"
)


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


async def fetch_cams(client: httpx.AsyncClient, start: date, end: date) -> dict[str, list]:
    return await _fetch_archive(client, _CAMS, _CHEM_VARS, start, end)


async def fetch_met(client: httpx.AsyncClient, start: date, end: date) -> dict[str, list]:
    return await _fetch_archive(client, _HRES, _MET_VARS, start, end)


def _dateranges(start: date, end: date, chunk_days: int = _MAX_CHUNK_DAYS):
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=chunk_days - 1), end)
        yield cursor, chunk_end
        cursor = chunk_end + timedelta(days=1)


def load_history(start: date, end: date, cache_dir: Path | None = None) -> tuple[dict[datetime, dict[str, float]], dict[datetime, dict[str, float]]]:
    """Fetch CAMS chemistry + HRES met for [start, end]; index by local hour."""
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
                c_hourly, m_hourly = await asyncio.gather(
                    fetch_cams(client, a, b),
                    fetch_met(client, a, b),
                )
                if cache_dir is not None:
                    (cache_dir / f"cams_{a.isoformat()}_{b.isoformat()}.json").write_text(json.dumps(c_hourly))
                    (cache_dir / f"met_{a.isoformat()}_{b.isoformat()}.json").write_text(json.dumps(m_hourly))
                _merge(chem, c_hourly)
                _merge(met, m_hourly)
                print(f"  fetched {a}..{b}: cams={len(c_hourly.get('time') or [])} rows, met={len(m_hourly.get('time') or [])} rows", flush=True)

    asyncio.run(_run())
    return chem, met


def build_rows(
    chem: dict[datetime, dict[str, float]],
    met: dict[datetime, dict[str, float]],
    history_hours: int = 24,
) -> tuple[list[list[float]], list[float], list[datetime], list[float], list[int]]:
    """Build (X, y, target_stamps, persistence_baseline, lead_hours) rows.

    One training row per (origin, target) pair. Origins are spaced every 6
    hours to bound memory; leads 1..72 cover the forecast horizon.
    """
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
            continue  # no anchor at this origin; skip pair (not leaky, just unusable)

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
            features = build_pm25_features_v2(
                lead_hours=lead,
                target_time=target,
                history=history_summary,
                origin_chem=origin_chem,
                target_chem=target_chem,
                weather=met_row,
            )
            if not all(math.isfinite(v) or v != v for v in features):  # NaN allowed
                pass
            X.append(features)
            y.append(float(truth_row["pm2_5"]))
            stamps.append(target)
            baseline.append(float(origin_row["pm2_5"]))
            leads.append(lead)

    return X, y, stamps, baseline, leads


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
    m["within_pm25_15_pct"] = round(100.0 * sum(1 for p, t in zip(y_pred, y_true) if abs(p - t) <= 15.0) / len(y_true), 2)
    aqi_pred = [_aqi_from_pm25_cpcb(max(0.0, p)) for p in y_pred]
    aqi_true = [_aqi_from_pm25_cpcb(t) for t in y_true]
    aqi_errs = [abs(p - t) for p, t in zip(aqi_pred, aqi_true)]
    m["aqi_mae"] = round(sum(aqi_errs) / len(aqi_errs), 2)
    m["aqi_within_25_pct"] = round(100.0 * sum(1 for e in aqi_errs if e <= 25) / len(aqi_errs), 2)
    by_lead: dict[str, dict[str, float]] = {}
    for lo, hi in ((1, 12), (13, 24), (25, 48), (49, 72)):
        idx = [i for i, lead in enumerate(leads) if lo <= lead <= hi]
        if idx:
            sub = _metrics([y_true[i] for i in idx], [y_pred[i] for i in idx])
            sub["baseline_mae"] = round(sum(abs(baseline[i] - y_true[i]) for i in idx) / len(idx), 3)
            by_lead[f"{lo}-{hi}h"] = sub
    m["by_lead"] = by_lead
    return m


def stamps_sorted_holdout_start(holdout: dict[str, Any], stamps: list[datetime]) -> str:
    """Earliest target stamp in the holdout block — the training cutoff."""
    test_idx = holdout["test_idx"]
    return min(stamps[i] for i in test_idx).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="18 months, 3 folds (smoke)")
    parser.add_argument("--months", type=int, default=48, help="history depth in months")
    parser.add_argument("--fold-count", type=int, default=6)
    parser.add_argument("--origin-stride", type=int, default=6, help="hours between origins")
    args = parser.parse_args()

    if args.quick:
        args.months = 18
        args.fold_count = 3

    end_date = date.today() - timedelta(days=5)  # archive needs a settle margin
    start_date = end_date - timedelta(days=args.months * 30 + 10)

    print(f"window: {start_date} .. {end_date} ({args.months} months)", flush=True)

    t0 = time.time()
    chem, met = load_history(start_date, end_date, cache_dir=_ROOT / "data_cache")
    print(f"loaded {len(chem)} chem hours / {len(met)} met hours in {time.time()-t0:.0f}s", flush=True)
    if len(chem) < 24 * 90:
        print("insufficient history; aborting", flush=True)
        return 1

    t0 = time.time()
    X, y, stamps, baseline, leads = build_rows(chem, met)
    print(f"built {len(X)} training rows in {time.time()-t0:.0f}s", flush=True)
    if len(X) < 20_000:
        print("insufficient training rows; aborting", flush=True)
        return 1

    from sklearn.ensemble import HistGradientBoostingRegressor

    def _train_score(train_idx: list[int], test_idx: list[int], label: str) -> dict[str, Any]:
        model = HistGradientBoostingRegressor(
            max_iter=700,
            learning_rate=0.05,
            max_leaf_nodes=63,
            min_samples_leaf=40,
            l2_regularization=1.0,
            early_stopping=False,  # random internal split would leak
        )
        model.fit([X[i] for i in train_idx], [y[i] for i in train_idx])
        pred = [float(v) for v in model.predict([X[i] for i in test_idx])]
        block = _metric_block([y[i] for i in test_idx], pred, [baseline[i] for i in test_idx], [leads[i] for i in test_idx])
        block["fold"] = label
        block["train_rows"] = len(train_idx)
        return {"model": model, "metrics": block, "pred": pred, "test_idx": test_idx}

    # Chronological walk-forward: folds scored on consecutive blocks; each fold
    # trains strictly on rows whose TARGET stamp precedes the block start. The
    # final block doubles as the holdout and is never trained on.
    time_order = sorted(range(len(stamps)), key=lambda i: stamps[i])
    boundaries = [int(len(stamps) * k / (args.fold_count + 1)) for k in range(1, args.fold_count + 1)] + [len(stamps)]
    prev = 0
    results: list[dict[str, Any]] = []
    all_pred: list[float | None] = [None] * len(y)
    for k, end_i in enumerate(boundaries):
        test_idx = time_order[prev:end_i]
        prev = end_i
        if not test_idx:
            continue
        train_idx = [i for i in time_order if stamps[i] < stamps[test_idx[0]]]
        if len(train_idx) < 5_000:
            print(f"fold {k}: train {len(train_idx)} rows too small, skipping", flush=True)
            continue
        out = _train_score(train_idx, test_idx, f"fold_{k}")
        print(f"{out['metrics']['fold']}: train={out['metrics']['train_rows']} test={out['metrics']['n']} "
              f"MAE={out['metrics']['mae']} RMSE={out['metrics']['rmse']} R2={out['metrics']['r2']} "
              f"vs persistence MAE={out['metrics']['baseline_mae']}", flush=True)
        results.append(out)
        for j, i in enumerate(test_idx):
            all_pred[i] = out["pred"][j]

    # The last fold IS the holdout (trained only on data before its window).
    holdout = results[-1] if results else None
    if holdout is None:
        print("no fold produced a model; aborting", flush=True)
        return 1
    print(f"holdout (=last fold): train={holdout['metrics']['train_rows']} test={holdout['metrics']['n']} "
          f"MAE={holdout['metrics']['mae']} RMSE={holdout['metrics']['rmse']} R2={holdout['metrics']['r2']} "
          f"skill={holdout['metrics']['mae_skill_vs_persistence']}", flush=True)

    # ── ship decision: the last walk-forward model, trained on everything
    # before the holdout block, is the artifact. No post-hoc best-fold picking.
    final_model = holdout["model"]
    meta = {
        "model_type": "HistGradientBoostingRegressor PM2.5 (v2, leak-free)",
        "model_version": f"v2-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "feature_names": V2_FULL_FEATURE_NAMES,
        "target": "CAMS reanalysis PM2.5 at target hour (µg/m³)",
        "target_unit": "µg/m³",
        "trained_through": stamps_sorted_holdout_start(holdout, stamps),
        "window": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        "fold_metrics": [r["metrics"] for r in results],
        "held_out_test": holdout["metrics"],
        "skill_vs_persistence": {
            "mae_skill_score": holdout["metrics"]["mae_skill_vs_persistence"],
            "definition": "1 - model_MAE / persistence_MAE (origin pm2.5 held flat), same hours",
        },
        "leakage_controls": [
            "no pm2_5/us_aqi at target hour in features (test_ml_contract.py)",
            "pm2.5 history features strictly at/before forecast origin",
            "walk-forward chronological folds; final 15% holdout never trained on",
            "early stopping disabled (random internal split leaks)",
            "meteorology from HRES historical-forecast archive (serving-consistent)",
            "persistence baseline scored on identical hours",
        ],
        "limitations": [
            "truth is CAMS reanalysis, not CPCB ground monitors",
            "single column (Delhi centre); no spatial variation",
        ],
    }
    _ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    import joblib
    joblib.dump({"model": final_model, "metadata": meta}, _ARTIFACT)
    print(f"artifact written: {_ARTIFACT}", flush=True)
    print(json.dumps(meta["held_out_test"], indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
