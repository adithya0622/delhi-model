"""AQI forecast model v4 — DIRECT AQI prediction (no breakpoint computation at inference).

Difference from v3: v3 predicts PM2.5 (µg/m³) and the endpoint computes AQI
from concentrations. v4 predicts the AQI number itself:

  * Target: CPCB 2014 AQI (primary head) and US EPA AQI (secondary head)
    computed ONCE at training time from CAMS target-hour concentrations via
    app.services.ml_features.compute_aqi_targets — the same breakpoint tables
    the serving endpoint uses for its computed block, so the "predicted" and
    "computed" numbers are always on identical scales.
  * Features: exactly the v3 61-feature contract (V3_FEATURE_NAMES) — pm2.5
    history at/before origin, origin chemistry, target-hour co-pollutant
    forecast fields, archived HRES meteorology, inversion/PBL extras, season
    encodings. NO target-hour pm2_5, NO target-hour us_aqi (the leakage rule
    is stricter here precisely because the target is derived from chemistry).
  * Seasonal sub-models (winter Nov-Feb / non-winter Mar-Oct), same dispatch
    as v3.
  * Baselines on identical holdout hours:
      - persistence: origin CPCB AQI held flat to the target hour
      - computed pipeline: AQI recomputed from the target-hour co-pollutant
        fields with pm2.5 ORIGIN value standing in for pm2.5 — an upper bound
        on what a zero-ML pipeline knowing only issue-time data could do.

Leakage discipline (v3 rules, tightened):
  * No pm2_5/us_aqi at target hour in any feature (target_chem excludes pm2_5
    by construction in build_pm25_features_v2; aqi targets are derived from
    concentrations that include pm2_5, which is exactly why the pm2_5 feature
    must stay absent).
  * Walk-forward chronological folds; final 15% holdout never trained on.
  * early_stopping=False.
  * Serving-consistent meteorology (HRES historical-forecast archive).

Usage:
    python scripts/train_aqi_v4.py             # full 4-year run
    python scripts/train_aqi_v4.py --quick     # 18-month smoke test
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

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "backend"))

from app.services.ml_features import (  # noqa: E402
    V3_FEATURE_NAMES,
    compute_aqi_targets,
)
from app.domain.aqi_scales import _cat  # noqa: E402

# Reuse the v3 machinery verbatim: data loading, feature building, trainer.
sys.path.insert(0, str(_ROOT / "scripts"))
from train_pm25_v3 import (  # noqa: E402
    _extra_features,
    _train_model,
    load_history,
)

_ARTIFACT_DIR = _ROOT / "backend" / "app" / "artifacts"


def build_rows_aqi(
    chem: dict[datetime, dict[str, float]],
    met: dict[datetime, dict[str, float]],
    history_hours: int = 24,
) -> tuple[list[list[float]], list[int], list[int], list[datetime], list[int], list[int]]:
    """Rows for direct-AQI training.

    Returns (X, y_cpcb, y_epa, stamps, persistence_baseline, computed_baseline)
    where both baselines are AQI integers for the same target hours:
      - persistence_baseline: CPCB AQI of the origin hour held flat
      - computed_baseline: AQI recomputed from target-hour co-pollutants with
        the ORIGIN pm2.5 standing in for target pm2.5 (no-ML upper bound)
    """
    X: list[list[float]] = []
    y_cpcb: list[int] = []
    y_epa: list[int] = []
    stamps: list[datetime] = []
    base_persist: list[int] = []
    base_computed: list[int] = []

    all_hours = sorted(chem.keys())
    if not all_hours:
        return X, y_cpcb, y_epa, stamps, base_persist, base_computed
    chem_min, chem_max = all_hours[0], all_hours[-1]

    origins = [h for h in all_hours if h.hour % 6 == 0]
    for origin in origins:
        hist_values: list[float | None] = []
        for lag in range(history_hours + 1):
            row = chem.get(origin - timedelta(hours=lag))
            hist_values.append(row.get("pm2_5") if row else None)
        from app.services.ml_features import history_features

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

            # ── Targets: AQI computed ONCE, from full target chemistry ──
            cpcb_t, epa_t = compute_aqi_targets({
                "pm25": truth_row.get("pm2_5"),
                "pm10": truth_row.get("pm10"),
                "no2": truth_row.get("no2"),
                "o3": truth_row.get("o3"),
                "so2": truth_row.get("so2"),
                "co": truth_row.get("co"),
            })

            # ── Features: v3 contract, target pm2_5 excluded by builder ──
            target_chem = {
                "no2": truth_row.get("no2"),
                "o3": truth_row.get("o3"),
                "pm10": truth_row.get("pm10"),
                "so2": truth_row.get("so2"),
                "co": truth_row.get("co"),
                "aod": truth_row.get("aerosol_optical_depth"),
                "dust": truth_row.get("dust"),
            }
            v2_feats = _v2_feats(
                lead_hours=lead,
                target_time=target,
                history=history_summary,
                origin_chem=origin_chem,
                target_chem=target_chem,
                weather=met_row,
            )
            extra = _extra_features(target, met_row)

            # Computed-no-ML baseline: origin pm2.5 stands in for target pm2.5.
            comp_cpcb, comp_epa = compute_aqi_targets({
                "pm25": origin_row.get("pm2_5"),
                "pm10": truth_row.get("pm10"),
                "no2": truth_row.get("no2"),
                "o3": truth_row.get("o3"),
                "so2": truth_row.get("so2"),
                "co": truth_row.get("co"),
            })
            persist_cpcb, _ = compute_aqi_targets({
                "pm25": origin_row.get("pm2_5"),
                "pm10": origin_row.get("pm10"),
                "no2": origin_row.get("no2"),
                "o3": origin_row.get("o3"),
                "so2": origin_row.get("so2"),
                "co": origin_row.get("co"),
            })

            X.append(v2_feats + extra)
            y_cpcb.append(cpcb_t)
            y_epa.append(epa_t)
            stamps.append(target)
            base_persist.append(persist_cpcb)
            base_computed.append(comp_cpcb)

    return X, y_cpcb, y_epa, stamps, base_persist, base_computed


def _v2_feats(**kwargs: Any) -> list[float]:
    """Lazy import shim so the module import stays cheap."""
    from app.services.ml_features import build_pm25_features_v2

    return build_pm25_features_v2(**kwargs)


def _aqi_metrics(
    y_true: list[int], y_pred: list[int], persist: list[int], computed: list[int], leads: list[int]
) -> dict[str, Any]:
    n = max(1, len(y_true))
    errs = [p - t for p, t in zip(y_pred, y_true)]
    mae = sum(abs(e) for e in errs) / n
    rmse = math.sqrt(sum(e * e for e in errs) / n)
    mean_t = sum(y_true) / n
    sse = sum((t - mean_t) ** 2 for t in y_true)
    r2 = 1.0 - sum(e * e for e in errs) / sse if sse > 0 else float("nan")

    p_errs = [abs(b - t) for b, t in zip(persist, y_true)]
    c_errs = [abs(b - t) for b, t in zip(computed, y_true)]

    # Band accuracy: exact CPCB category match and ±1 band
    def band(aqi: int) -> int:
        return min(5, aqi // 50 if aqi < 301 else 4 + min(2, (aqi - 301) // 100 + 1)) if aqi > 0 else 0

    cat_true = [band(t) for t in y_true]
    exact = sum(1 for p, t in zip((band(p) for p in y_pred), cat_true) if p == t)
    within1 = sum(1 for p, t in zip((band(p) for p in y_pred), cat_true) if abs(p - t) <= 1)

    by_lead: dict[str, dict[str, float]] = {}
    for lo, hi in ((1, 12), (13, 24), (25, 48), (49, 72)):
        idx = [i for i, lead in enumerate(leads) if lo <= lead <= hi]
        if idx:
            sub_errs = [abs(y_pred[i] - y_true[i]) for i in idx]
            by_lead[f"{lo}-{hi}h"] = {
                "aqi_mae": round(sum(sub_errs) / len(sub_errs), 2),
                "n": len(idx),
            }

    return {
        "aqi_mae": round(mae, 2),
        "aqi_rmse": round(rmse, 2),
        "aqi_r2": round(r2, 4),
        "n": len(y_true),
        "persistence_mae": round(sum(p_errs) / len(p_errs), 2),
        "computed_pipeline_mae": round(sum(c_errs) / len(c_errs), 2),
        "skill_vs_persistence": round(1.0 - mae / (sum(p_errs) / len(p_errs)), 4) if any(p_errs) else None,
        "skill_vs_computed": round(1.0 - mae / (sum(c_errs) / len(c_errs)), 4) if any(c_errs) else None,
        "band_exact_pct": round(100.0 * exact / n, 2),
        "band_within1_pct": round(100.0 * within1 / n, 2),
        "by_lead": by_lead,
    }


def _predict_with(model: Any, X: list[list[float]], idx: list[int]) -> list[int]:
    raw = model.predict([X[i] for i in idx])
    return [int(round(min(max(float(v), 0.0), 500.0))) for v in raw]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="18 months, no grid")
    parser.add_argument("--months", type=int, default=48)
    parser.add_argument("--no-grid", action="store_true")
    args = parser.parse_args()
    if args.quick:
        args.months = 18
        args.no_grid = True

    end_date = date.today() - timedelta(days=5)
    start_date = end_date - timedelta(days=args.months * 30 + 10)
    print(f"v4 window: {start_date} .. {end_date} ({args.months} months)", flush=True)

    t0 = time.time()
    chem, met = load_history(start_date, end_date, cache_dir=_ROOT / "data_cache")
    print(f"loaded {len(chem)} chem / {len(met)} met hours in {time.time()-t0:.0f}s", flush=True)
    if len(chem) < 24 * 90:
        print("insufficient history; aborting", flush=True)
        return 1

    t0 = time.time()
    X, y_cpcb, y_epa, stamps, base_persist, base_computed = build_rows_aqi(chem, met)
    print(f"built {len(X)} rows ({len(V3_FEATURE_NAMES)} features) in {time.time()-t0:.0f}s", flush=True)
    if len(X) < 20_000:
        print("insufficient rows; aborting", flush=True)
        return 1

    time_order = sorted(range(len(stamps)), key=lambda i: stamps[i])
    n = len(stamps)
    holdout_start = int(n * 0.85)
    holdout_idx = time_order[holdout_start:]
    train_pool = time_order[:holdout_start]
    # Recover each row's lead (origin+lead construction) from the 6-hourly grid.
    true_leads = _recompute_leads(chem, stamps)
    winter_flags = [s.month in (11, 12, 1, 2) for s in stamps]

    # ── CPCB head ──────────────────────────────────────────────────────────
    print("\n=== CPCB head: FULL (all seasons) ===", flush=True)
    full_res = _train_model(X, [float(v) for v in y_cpcb], train_pool, holdout_idx, "cpcb-full", grid_search=not args.no_grid)
    w_train = [i for i in train_pool if winter_flags[i]]
    w_test = [i for i in holdout_idx if winter_flags[i]]
    nw_train = [i for i in train_pool if not winter_flags[i]]
    nw_test = [i for i in holdout_idx if not winter_flags[i]]

    w_res = full_res
    if len(w_train) >= 5000 and len(w_test) >= 100:
        print(f"=== CPCB WINTER train={len(w_train)} test={len(w_test)} ===", flush=True)
        w_res = _train_model(X, [float(v) for v in y_cpcb], w_train, w_test, "cpcb-winter", grid_search=not args.no_grid)
    nw_res = full_res
    if len(nw_train) >= 5000 and len(nw_test) >= 100:
        print(f"=== CPCB NON-WINTER train={len(nw_train)} test={len(nw_test)} ===", flush=True)
        nw_res = _train_model(X, [float(v) for v in y_cpcb], nw_train, nw_test, "cpcb-nonwinter", grid_search=not args.no_grid)

    # Pooled per-row prediction via seasonal dispatch
    pred_map: dict[int, int] = {}
    for i, p in zip(w_res["test_idx"], w_res["preds"]):
        pred_map[i] = int(p)
    for i, p in zip(nw_res["test_idx"], nw_res["preds"]):
        pred_map[i] = int(p)

    pooled_idx = sorted(holdout_idx, key=lambda i: stamps[i])
    y_true_p = [y_cpcb[i] for i in pooled_idx]
    y_pred_p = [pred_map.get(i, int(full_res["preds"][full_res["test_idx"].index(i)])) for i in pooled_idx]
    persist_p = [base_persist[i] for i in pooled_idx]
    computed_p = [base_computed[i] for i in pooled_idx]
    leads_p = [true_leads[i] for i in pooled_idx]

    cpcb_metrics = _aqi_metrics(y_true_p, y_pred_p, persist_p, computed_p, leads_p)
    print(f"\nCPCB POOLED: {json.dumps({k: v for k, v in cpcb_metrics.items() if k != 'by_lead'}, indent=2)}", flush=True)

    # Winter-only slice of the pooled predictions
    w_slice = [i for i in pooled_idx if winter_flags[i] and i in pred_map]
    if len(w_slice) >= 100:
        winter_metrics = _aqi_metrics(
            [y_cpcb[i] for i in w_slice],
            [pred_map[i] for i in w_slice],
            [base_persist[i] for i in w_slice],
            [base_computed[i] for i in w_slice],
            [true_leads[i] for i in w_slice],
        )
        print(f"CPCB WINTER SLICE: aqi_mae={winter_metrics['aqi_mae']} computed_pipeline_mae={winter_metrics['computed_pipeline_mae']}", flush=True)
    else:
        winter_metrics = {}

    # ── EPA head ────────────────────────────────────────────────────────────
    print("\n=== EPA head (full model) ===", flush=True)
    epa_res = _train_model(X, [float(v) for v in y_epa], train_pool, holdout_idx, "epa-full", grid_search=not args.no_grid)
    epa_pred = _predict_with(epa_res["model"], X, holdout_idx)
    epa_metrics = _aqi_metrics(
        [y_epa[i] for i in holdout_idx],
        epa_pred,
        [base_persist[i] for i in holdout_idx],
        [base_computed[i] for i in holdout_idx],
        [true_leads[i] for i in holdout_idx],
    )
    print(f"EPA FULL: aqi_mae={epa_metrics['aqi_mae']}", flush=True)

    # ── Acceptance gates ────────────────────────────────────────────────────
    # The winter gate needs ≥100 winter rows in the holdout; a short window's
    # trailing 15% can contain none (e.g. an 18-month run ending in summer).
    # That is reported as None (n/a) rather than folded in as a failure — the
    # full-window run must still clear it.
    winter_evaluable = bool(winter_metrics) and winter_metrics.get("n", 0) >= 100
    gates = {
        "pooled_aqi_mae_lt_20": cpcb_metrics["aqi_mae"] < 20.0,
        "winter_aqi_mae_lt_12": (winter_metrics["aqi_mae"] < 12.0) if winter_evaluable else None,
        "band_within1_gt_80": cpcb_metrics["band_within1_pct"] > 80.0,
        "not_worse_than_computed": cpcb_metrics["aqi_mae"] <= cpcb_metrics["computed_pipeline_mae"] * 1.10,
        "winter_gate_evaluable": winter_evaluable,
    }
    hard_gates = [v for k, v in gates.items() if v is not None and k != "winter_gate_evaluable"]
    accepted = all(hard_gates)
    print("\n=== ACCEPTANCE GATES ===", flush=True)
    for k, v in gates.items():
        print(f"  {k}: {'PASS' if v is True else ('n/a' if v is None else 'FAIL')}", flush=True)
    print(f"  overall: {'ACCEPTED' if accepted else 'REJECTED — computed path stays primary'}", flush=True)

    # ── Persist ─────────────────────────────────────────────────────────────
    import joblib

    _ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    meta = {
        "model_type": "HistGradientBoostingRegressor direct AQI (v4, seasonal sub-models)",
        "model_version": f"v4-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "feature_names": V3_FEATURE_NAMES,
        "target": "CPCB 2014 AQI at target hour, computed once from CAMS concentrations at training time",
        "target_unit": "AQI points (0-500)",
        "secondary_target": "US EPA AQI at target hour",
        "window": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        "sub_models": {
            "winter": {"seasons": "Nov-Feb", "params": w_res["params"]},
            "non_winter": {"seasons": "Mar-Oct", "params": nw_res["params"]},
            "full": {"seasons": "all", "params": full_res["params"]},
        },
        "cpcb_metrics": cpcb_metrics,
        "winter_metrics": winter_metrics,
        "epa_metrics": epa_metrics,
        "acceptance_gates": gates,
        "accepted": accepted,
        "leakage_controls": [
            "no pm2_5/us_aqi at target hour in features (builder excludes pm2_5 by construction)",
            "AQI targets derived from concentrations only at TRAINING time",
            "walk-forward folds; holdout never trained on",
            "early_stopping=False",
            "meteorology from HRES historical-forecast archive (serving-consistent)",
        ],
    }
    artifact = {
        "model_winter": w_res["model"],
        "model_non_winter": nw_res["model"],
        "model_full": full_res["model"],
        "model_epa": epa_res["model"],
        "feature_names": V3_FEATURE_NAMES,
        "metadata": meta,
    }
    out = _ARTIFACT_DIR / "aqi_v4.joblib"
    joblib.dump(artifact, out)
    print(f"\nartifact written: {out} (accepted={accepted})", flush=True)
    return 0


def _recompute_leads(chem: dict[datetime, dict[str, float]], stamps: list[datetime]) -> list[int]:
    """Recover each row's lead by re-walking the 6-hourly origin grid."""
    all_hours = sorted(chem.keys())
    origins = {h for h in all_hours if h.hour % 6 == 0}
    leads: list[int] = []
    for target in stamps:
        lead = 72
        for back in range(1, 73):
            candidate = target - timedelta(hours=back)
            if candidate in origins:
                lead = back
                break
        leads.append(lead)
    return leads


if __name__ == "__main__":
    raise SystemExit(main())
