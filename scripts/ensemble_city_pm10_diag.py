"""City PM10 ensemble diagnostic (goal: raw RMSE < 20 ug/m3).

The dust-focus city retrain trial scored 21.87 vs serving 20.596 (rejected
alone), but it is a second INDEPENDENTLY-TRAINED model (different sampling
recipe). If its errors are decorrelated from the serving model's, a fixed
blend could clear RMSE < 20 where neither model does alone.

Leak-free protocol
------------------
* The blend weight is selected on TRAIN-period origins only (regular-stride
  origins strictly before the holdout), never on the holdout.
* The PRIMARY verdict uses the pre-declared 50/50 blend (no selection at all).
* The holdout-optimal ("oracle") weight is printed for information only —
  adopting it would be selection leakage.
* Forecasts are cached to npz so this expensive step never reruns.

Usage:  python scripts/ensemble_city_pm10_diag.py
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

SERVING_CKPT = _ARTIFACT_DIR / "species_pm10"
TRIAL_CKPT = _ROOT / "backend" / "app" / "artifacts" / "chronos2_trials" / "city_pm10_focus" / "species_pm10"
CACHE_NPZ = _ROOT / "data_cache" / "city_pm10_ensemble_diag.npz"
N_TRAIN_EVAL = 96  # train origins to score for weight selection (eval-cost bound)


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
    train_pool = list(range(CONTEXT_HOURS + HORIZON, holdout_idx - HORIZON, REGULAR_SAMPLE_STRIDE))
    train_origins = train_pool[-N_TRAIN_EVAL:]
    print(f"holdout origins={len(eval_origins)}; train-eval origins={len(train_origins)} "
          f"(last {stamps[train_origins[0]]} -> {stamps[train_origins[-1]]})", flush=True)

    if CACHE_NPZ.exists():
        print(f"loading cached forecasts from {CACHE_NPZ.name} ...", flush=True)
        z = np.load(CACHE_NPZ, allow_pickle=True)
        stamp_keys = [str(s) for s in z["stamps"]]
        idx_of = {stamps[i]: i for i in range(len(stamps))}
        serve_fc = {i: z["serving"][k] for k, i in idx_of.items() if str(stamps[i]) in stamp_keys}
        trial_fc = {i: z["trial"][k] for k, i in idx_of.items() if str(stamps[i]) in stamp_keys}
    else:
        print("evaluating SERVING checkpoint (holdout + train-eval origins)...", flush=True)
        serve_all = eval_species(SERVING_CKPT, "pm10", eval_origins + train_origins,
                                 stamps, arrays, cam_extra, met_arrays)
        print("evaluating TRIAL (dust-focus) checkpoint ...", flush=True)
        trial_all = eval_species(TRIAL_CKPT, "pm10", eval_origins + train_origins,
                                 stamps, arrays, cam_extra, met_arrays)
        serve_fc = dict(serve_all)
        trial_fc = dict(trial_all)
        # cache: stamp-keyed rows, aligned
        common = [i for i in eval_origins + train_origins if i in serve_fc and i in trial_fc]
        CACHE_NPZ.parent.mkdir(parents=True, exist_ok=True)
        np.savez(CACHE_NPZ,
                 stamps=np.array([stamps[i] for i in common], dtype=object),
                 is_holdout=np.array([i in set(eval_origins) for i in common]),
                 serving=np.stack([serve_fc[i] for i in common]),
                 trial=np.stack([trial_fc[i] for i in common]))
        print(f"cached {len(common)} origin forecasts -> {CACHE_NPZ.name}", flush=True)

    hold_set = set(eval_origins)
    ho = [i for i in sorted(set(serve_fc) & set(trial_fc)) if i in hold_set]
    tr = [i for i in sorted(set(serve_fc) & set(trial_fc)) if i not in hold_set]
    print(f"scorable: holdout={len(ho)} train={len(tr)}", flush=True)

    def rmse_of(w: float, origins: list[int]) -> float:
        errs: list[float] = []
        for o in origins:
            t = arrays["pm10"][o: o + HORIZON]
            p = w * serve_fc[o] + (1.0 - w) * trial_fc[o]
            for h in range(HORIZON):
                tv = float(t[h])
                if math.isfinite(tv):
                    errs.append(float(p[h]) - tv)
        e = np.asarray(errs)
        return float(math.sqrt(np.mean(e ** 2)))

    # --- weight selection on TRAIN origins only (leak-free) ---
    grid = [round(w, 2) for w in np.arange(0.0, 1.0001, 0.05)]
    train_curve = [(w, rmse_of(w, tr)) for w in grid]
    w_star, train_best = min(train_curve, key=lambda x: x[1])
    print("\ntrain-origin blend curve (w = weight on SERVING):", flush=True)
    print("  " + "  ".join(f"{w:.2f}:{r:.2f}" for w, r in train_curve), flush=True)
    print(f"selected w*={w_star:.2f} (train rmse {train_best:.3f})", flush=True)

    # --- holdout verdicts ---
    serve_rmse = rmse_of(1.0, ho)
    trial_rmse = rmse_of(0.0, ho)
    half_rmse = rmse_of(0.5, ho)
    star_rmse = rmse_of(w_star, ho)
    oracle_w, oracle_rmse = min(((w, rmse_of(w, ho)) for w in grid), key=lambda x: x[1])

    print("\n==== HOLDOUT VERDICTS (identical 48 origins) ====", flush=True)
    print(f"serving alone            : rmse={serve_rmse:.3f}", flush=True)
    print(f"trial alone              : rmse={trial_rmse:.3f}", flush=True)
    print(f"50/50 blend (PRIMARY)    : rmse={half_rmse:.3f}  -> {'CLEARS <20' if half_rmse < 20 else 'misses 20'}", flush=True)
    print(f"w*={w_star:.2f} blend (train-sel): rmse={star_rmse:.3f}  -> {'CLEARS <20' if star_rmse < 20 else 'misses 20'}", flush=True)
    print(f"oracle w={oracle_w:.2f} (info only): rmse={oracle_rmse:.3f}", flush=True)
    ea, eb = _err_pairs(serve_fc, trial_fc, arrays, ho)
    err_corr = float(np.corrcoef(ea, eb)[0, 1])
    print(f"error correlation (holdout, per-hour pooled): {err_corr:+.3f}", flush=True)
    print(f"elapsed {(time.time() - t0) / 60:.1f} min", flush=True)

    out = {
        "serving_rmse": serve_rmse, "trial_rmse": trial_rmse,
        "blend50_rmse": half_rmse, "w_star": w_star, "w_star_rmse": star_rmse,
        "oracle_w": oracle_w, "oracle_rmse": oracle_rmse,
        "holdout_origins": [int(stamps[i].timestamp()) for i in ho],
    }
    print(json.dumps(out), flush=True)
    return 0


def _err_pairs(fa: dict, fb: dict, arrays: dict, origins: list[int]):
    ea, eb = [], []
    for o in origins:
        t = arrays["pm10"][o: o + HORIZON]
        for h in range(HORIZON):
            tv = float(t[h])
            if math.isfinite(tv):
                ea.append(float(fa[o][h]) - tv)
                eb.append(float(fb[o][h]) - tv)
    return np.asarray(ea), np.asarray(eb)


if __name__ == "__main__":
    raise SystemExit(main())
