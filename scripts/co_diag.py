"""CO ensemble + error-structure diagnostic (city cell).

Questions this answers, in order:
1. Do the four independent CO checkpoints (serving + linear/round1/round2
   backups from the earlier recipe attempts) have decorrelated errors, and does
   any leak-free blend improve the raw RMSE? (Pre-declared primary: equal-weight
   4-way average. Train-origin-selected weights secondary. Oracle = info only.)
2. What is CO's error STRUCTURE — is relative error uniform across seasons and
   truth levels (a volatility floor, like PM10's dust belt), or concentrated
   somewhere a targeted fix could reach?

Gate math context: the cap is nRMSE <= 0.12 (RMSE ~102 for this series, mean
851.5). An equal-weight k-model blend of equal-RMSE models with average error
correlation rho scales RMSE by sqrt((1+(k-1)rho)/k); with k=4 and rho=0 —
PERFECT decorrelation — 249.5 -> 124.7 (nRMSE 0.147), still above the cap. So
the ensemble can improve the raw number but mathematically cannot flip the
gate; this script quantifies both.

Leak-free protocol: any weight selection uses TRAIN-period origins only
(regular stride, strictly pre-holdout); the holdout oracle is printed for
information only. Forecasts are cached stamp-keyed to data_cache/.

Usage:  python scripts/co_diag.py
"""

from __future__ import annotations

import json
import math
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "backend"))

from train_pm25_v3 import load_history  # noqa: E402
from finetune_chronos2_delhi import (  # noqa: E402
    CONTEXT_HOURS,
    HORIZON,
    REGULAR_SAMPLE_STRIDE,
    build_arrays,
    eval_species,
    largest_hourly_run,
)
from evaluate_chronos2_station_gates import _ARTIFACT_DIR, holdout_origins  # noqa: E402

MODELS = {
    "serving": _ARTIFACT_DIR / "species_co",
    "linear_bak": _ARTIFACT_DIR / "species_co_linear_bak",
    "round1_bak": _ARTIFACT_DIR / "species_co_round1_bak",
    "round2_bak": _ARTIFACT_DIR / "species_co_round2_bak",
}
CACHE_NPZ = _ROOT / "data_cache" / "city_co_diag.npz"
N_TRAIN_EVAL = 96
WINTER_MONTHS = (11, 12, 1, 2)
DUST_MONTHS = (3, 4, 5, 6)


def main() -> int:
    t0 = time.time()
    end = datetime(2026, 9, 12)
    start = end - timedelta(days=48 * 30.44)
    chem, met = load_history(start.date(), end.date(), cache_dir=_ROOT / "data_cache")
    stamps_full, arrays, cam_extra, met_arrays = build_arrays(chem, met)
    r0, r1 = largest_hourly_run(stamps_full)
    stamps = stamps_full[r0:r1]
    arrays = {s: a[r0:r1] for s, a in arrays.items()}
    cam_extra = {c: a[r0:r1] for c, a in cam_extra.items()}
    met_arrays = {m: a[r0:r1] for m, a in met_arrays.items()}

    eval_origins, holdout_idx = holdout_origins(stamps)
    train_origins = list(range(CONTEXT_HOURS + HORIZON, holdout_idx - HORIZON, REGULAR_SAMPLE_STRIDE))[-N_TRAIN_EVAL:]

    names = list(MODELS)
    if CACHE_NPZ.exists():
        print(f"loading cached forecasts {CACHE_NPZ.name} ...", flush=True)
        z = np.load(CACHE_NPZ, allow_pickle=True)
        key_of = {stamps[i]: i for i in range(len(stamps))}
        fcs = {m: {key_of[str(s)]: z[m][k] for k, s in enumerate(z["stamps"]) if str(s) in key_of} for m in names}
        ho = [i for i in eval_origins if i in fcs[names[0]]]
        tr = [i for i in train_origins if i in fcs[names[0]]]
    else:
        fcs = {}
        for m in names:
            print(f"evaluating {m} ...", flush=True)
            fcs[m] = eval_species(MODELS[m], "co", eval_origins + train_origins,
                                  stamps, arrays, cam_extra, met_arrays)
        common = sorted(set(eval_origins + train_origins).intersection(*(set(fcs[m]) for m in names)))
        ho = [i for i in common if i in set(eval_origins)]
        tr = [i for i in common if i not in set(eval_origins)]
        CACHE_NPZ.parent.mkdir(parents=True, exist_ok=True)
        np.savez(CACHE_NPZ,
                 stamps=np.array([stamps[i] for i in common], dtype=object),
                 is_holdout=np.array([i in set(eval_origins) for i in common]),
                 **{m: np.stack([fcs[m][i] for i in common]) for m in names})
        print(f"cached {len(common)} origins -> {CACHE_NPZ.name}", flush=True)

    print(f"scorable: holdout={len(ho)} train={len(tr)}", flush=True)

    def err_vec(w_by_model: dict, origins: list[int]) -> np.ndarray:
        errs = []
        for o in origins:
            t = arrays["co"][o: o + HORIZON]
            p = sum(w * fcs[m][o] for m, w in w_by_model.items())
            for h in range(HORIZON):
                tv = float(t[h])
                if math.isfinite(tv):
                    errs.append(float(p[h]) - tv)
        return np.asarray(errs)

    def metrics(e: np.ndarray, origins: list[int]) -> dict:
        tv = np.concatenate([arrays["co"][o: o + HORIZON] for o in origins]).astype(float)
        mask = np.isfinite(tv)
        t = tv[mask]
        rmse = float(math.sqrt(np.mean(e ** 2)))
        return {"rmse": rmse, "mae": float(np.mean(np.abs(e))),
                "r2": float(1 - np.sum(e ** 2) / np.sum((t - t.mean()) ** 2)),
                "nrmse": float(rmse / t.mean()), "bias": float(e.mean())}

    # --- individual models ---
    print("\n==== individual models (holdout, identical origins) ====", flush=True)
    ind = {m: metrics(err_vec({m: 1.0}, ho), ho) for m in names}
    for m, b in ind.items():
        print(f"{m:11s}: rmse={b['rmse']:7.1f} mae={b['mae']:7.1f} r2={b['r2']:.4f} "
              f"nrmse={b['nrmse']:.4f} bias={b['bias']:+7.1f}", flush=True)

    # --- error correlation matrix (holdout) ---
    E = {m: err_vec({m: 1.0}, ho) for m in names}
    print("\nerror correlation matrix (holdout):", flush=True)
    hdr = "          " + " ".join(f"{m[:8]:>9s}" for m in names)
    print(hdr, flush=True)
    for a in names:
        row = " ".join(f"{float(np.corrcoef(E[a], E[b])[0, 1]):+9.3f}" for b in names)
        print(f"{a:10s}{row}", flush=True)

    # --- blends ---
    print("\n==== blends (holdout) ====", flush=True)
    eq = {m: 1.0 / len(names) for m in names}
    b_eq = metrics(err_vec(eq, ho), ho)
    print(f"equal 4-way (PRIMARY) : rmse={b_eq['rmse']:7.1f} r2={b_eq['r2']:.4f} "
          f"nrmse={b_eq['nrmse']:.4f} {'CLEARS 0.12' if b_eq['nrmse'] <= 0.12 else 'misses 0.12 cap'}", flush=True)
    # train-selected nonneg least-squares-ish: grid over convex weights on train origins
    best_w, best_tr = None, None
    step = 0.10
    grids = [(a, b, c, round(1 - a - b - c, 4))
             for a in np.arange(0, 1.0001, step) for b in np.arange(0, 1.0001 - a, step)
             for c in np.arange(0, 1.0001 - a - b, step) if 1 - a - b - c >= -1e-9]
    for a, b, c, d in grids:
        w = dict(zip(names, (a, b, c, d)))
        r = float(math.sqrt(np.mean(err_vec(w, tr) ** 2)))
        if best_tr is None or r < best_tr:
            best_tr, best_w = r, w
    b_star = metrics(err_vec(best_w, ho), ho)
    ws = " ".join(f"{m}:{best_w[m]:.2f}" for m in names)
    print(f"train-selected blend  : rmse={b_star['rmse']:7.1f} r2={b_star['r2']:.4f} "
          f"nrmse={b_star['nrmse']:.4f}  (w: {ws}; train rmse {best_tr:.1f})", flush=True)
    oracle_w, oracle_r = None, None
    for a, b, c, d in grids:
        w = dict(zip(names, (a, b, c, d)))
        r = float(math.sqrt(np.mean(err_vec(w, ho) ** 2)))
        if oracle_r is None or r < oracle_r:
            oracle_r, oracle_w = r, w
    wo = " ".join(f"{m}:{oracle_w[m]:.2f}" for m in names)
    print(f"oracle (info only)    : rmse={oracle_r:7.1f}  (w: {wo})", flush=True)

    # --- error structure of the serving model ---
    print("\n==== serving-model error structure (volatility-floor analysis) ====", flush=True)
    def season_nrmse(months, label):
        sel = [o for o in ho if stamps[o].month in months]
        if not sel:
            print(f"{label:16s}: no origins", flush=True); return
        e = err_vec({"serving": 1.0}, sel)
        tv = np.concatenate([arrays["co"][o: o + HORIZON] for o in sel]).astype(float)
        mask = np.isfinite(tv)
        b = metrics(e[mask], sel)
        print(f"{label:16s}: rmse={b['rmse']:7.1f} nrmse={b['nrmse']:.4f} "
              f"bias={b['bias']:+7.1f} (origins={len(sel)})", flush=True)
    season_nrmse(WINTER_MONTHS, "winter")
    season_nrmse(DUST_MONTHS, "dust (Mar-Jun)")
    season_nrmse({7, 8, 9}, "monsoon")
    season_nrmse({10}, "october")
    season_nrmse(set(range(1, 13)) - set(WINTER_MONTHS) - set(DUST_MONTHS) - {7, 8, 9, 10}, "other")
    # relative error vs truth level: is the % error uniform (floor) or level-dependent (fixable)?
    tv = np.concatenate([arrays["co"][o: o + HORIZON] for o in ho]).astype(float)
    e = E["serving"]
    mask = np.isfinite(tv)
    t, ee = tv[mask], e[mask]
    print(f"corr(|truth|, |error|): {float(np.corrcoef(t, np.abs(ee))[0, 1]):+.3f}   "
          f"(high -> proportional error, i.e. floor-like)", flush=True)
    for lo, hi in ((0, 300), (300, 700), (700, 1200), (1200, 1e9)):
        sel = (t >= lo) & (t < hi)
        if sel.sum() > 20:
            rel = ee[sel] / np.maximum(t[sel], 1e-9)
            print(f"truth {lo:5.0f}-{hi:<8.0f}: n={int(sel.sum()):5d} mean_rel_err={rel.mean():+.3f} "
                  f"mape={float(np.mean(np.abs(rel))):.3f} rmse={float(math.sqrt(np.mean(ee[sel] ** 2))):7.1f}", flush=True)

    print(f"\nelapsed {(time.time() - t0) / 60:.1f} min", flush=True)
    out = {"individual": ind, "equal4": b_eq, "train_sel": {**b_star, "w": best_w},
           "oracle": {"rmse": oracle_r, "w": oracle_w}}
    print(json.dumps(out), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
