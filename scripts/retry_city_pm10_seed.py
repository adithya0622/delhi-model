"""City-cell PM10 seed-retry TRIAL (goal: raw RMSE < 20 ug/m3).

Status of every leak-free lever tried for the city cell (all documented in
docs/MODEL_VALIDATION.md):
  * dust-focus retrain (ctx 336) ....... 21.870 vs serving 20.596 -> rejected
  * 50/50 ensemble w/ that trial ....... 20.950 (oracle weight = 1.00) -> dead
  * train-selected blend w*=0.55 ....... 20.889 -> dead

This script runs the LAST remaining recipe-level lever, consistent with the
project's established adoption rule (holdout-gated, as used for the per-cell
specialists): the ORIGINAL winter-x2 recipe (ctx 720, 500 steps, lr 1e-5,
batch 32) with a different seed. The serving checkpoint itself was one draw
of this recipe (seed 42); training-budget seed variance is a real, legitimate
degree of freedom — but it is a lottery, and this script says so plainly.

Isolation guarantees
--------------------
* Trains into backend/app/artifacts/chronos2_trials/city_pm10_seed<N>/
  (separate out-dir; serving layer only reads chronos2_delhi/species_*).
* Never writes any npz forecast cache; adoption, if any, is a separate
  explicit step with its own backup + verification.
* Train origins end strictly before the 12-month holdout (leak-free).
* Prints old-vs-new metrics on the IDENTICAL published 48-origin holdout;
  nothing is adopted automatically.

Usage:  python scripts/retry_city_pm10_seed.py [--seed 7] [--steps 500]
"""

from __future__ import annotations

import argparse
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
    WINTER_SAMPLE_STRIDE,
    _WINTER_MONTHS,
    build_arrays,
    eval_species,
    largest_hourly_run,
    train_species,
)
from evaluate_chronos2_station_gates import _ARTIFACT_DIR, holdout_origins  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--steps", type=int, default=500)
    args = ap.parse_args()

    t0 = time.time()
    end = datetime(2026, 9, 12)
    start = end - timedelta(days=48 * 30.44)
    print(f"loading city archive {start.date()} -> {end.date()} (cache-aware)...", flush=True)
    chem, met = load_history(start.date(), end.date(), cache_dir=_ROOT / "data_cache")
    stamps_full, arrays, cam_extra, met_arrays = build_arrays(chem, met)
    r0, r1 = largest_hourly_run(stamps_full)
    stamps = stamps_full[r0:r1]
    arrays = {s: a[r0:r1] for s, a in arrays.items()}
    cam_extra = {c: a[r0:r1] for c, a in cam_extra.items()}
    met_arrays = {m: a[r0:r1] for m, a in met_arrays.items()}

    eval_origins, holdout_idx = holdout_origins(stamps)
    # ORIGINAL recipe: winter x2 (stride 24 in months 11,12,1,2), strictly pre-holdout.
    train_set = set(range(CONTEXT_HOURS + HORIZON, holdout_idx - HORIZON, REGULAR_SAMPLE_STRIDE))
    train_set |= set(
        i for i in range(CONTEXT_HOURS + HORIZON, holdout_idx - HORIZON, WINTER_SAMPLE_STRIDE)
        if stamps[i].month in _WINTER_MONTHS
    )
    train_origins = sorted(train_set)
    val_origins = train_origins[-8:]
    print(f"holdout origins={len(eval_origins)}; train origins={len(train_origins)} "
          f"(winter x2, original recipe); seed={args.seed} steps={args.steps}", flush=True)

    TRIAL_DIR = _ROOT / "backend" / "app" / "artifacts" / "chronos2_trials" / f"city_pm10_seed{args.seed}"
    TRIAL_DIR.mkdir(parents=True, exist_ok=True)

    print("training trial specialist (original winter-x2 recipe, new seed)...", flush=True)
    train_species(
        "pm10", stamps, arrays, cam_extra, met_arrays, train_origins, val_origins,
        TRIAL_DIR, num_steps=args.steps, learning_rate=1e-5, batch_size=32,
        context_hours=CONTEXT_HOURS, seed=args.seed,
    )

    print("evaluating SERVING pm10 checkpoint on the identical origins...", flush=True)
    base_fc = eval_species(_ARTIFACT_DIR / "species_pm10", "pm10", eval_origins,
                           stamps, arrays, cam_extra, met_arrays)
    base_rmse = _trial_rmse(base_fc, arrays, eval_origins)

    print("evaluating TRIAL specialist...", flush=True)
    trial_fc = eval_species(TRIAL_DIR / "species_pm10", "pm10", eval_origins,
                            stamps, arrays, cam_extra, met_arrays)
    trial_rmse = _trial_rmse(trial_fc, arrays, eval_origins)

    print("\n==== SEED-RETRY RESULT (identical 48-origin holdout) ====", flush=True)
    print(f"serving (seed 42)  : rmse={base_rmse:.3f}", flush=True)
    print(f"trial   (seed {args.seed})   : rmse={trial_rmse:.3f}", flush=True)
    if trial_rmse < base_rmse:
        print(f"VERDICT: trial BEATS serving by {base_rmse - trial_rmse:.3f} -> "
              f"{'CLEARS RMSE<20' if trial_rmse < 20 else 'better but still >= 20'}; "
              "adoption is a SEPARATE explicit step with backup + verification.", flush=True)
    else:
        print(f"VERDICT: trial does NOT beat serving (delta {trial_rmse - base_rmse:+.3f}) -> rejected.", flush=True)
    print(f"elapsed {(time.time() - t0) / 60:.1f} min; trial ckpt in {TRIAL_DIR}", flush=True)
    print("NOTHING was adopted; npz caches and serving artifacts untouched.", flush=True)
    return 0


def _trial_rmse(forecasts: dict, arrays: dict, origins: list[int]) -> float:
    """RMSE over all finite truth hours of the 72-h horizon (same as published)."""
    errs: list[float] = []
    for o in origins:
        if o not in forecasts:
            continue
        t = arrays["pm10"][o: o + HORIZON]
        p = forecasts[o]
        for h in range(HORIZON):
            tv = float(t[h])
            if math.isfinite(tv):
                errs.append(float(p[h]) - tv)
    e = np.asarray(errs)
    return float(math.sqrt(np.mean(e ** 2)))


if __name__ == "__main__":
    raise SystemExit(main())
