"""City-cell PM10 season-focus retrain TRIAL (goal: raw RMSE < 20 ug/m3).

Why
---
The published city PM10 specialist (RMSE 20.457 on the 48-origin holdout) was
trained with the original recipe that oversamples WINTER x2. The per-cell work
showed season-balanced (dust-focus) sampling helps PM10 cells; the city cell
was never retried because it is hard-refused in finetune_chronos2_cells.py
(published specialists live there). This trial runs the ONE untried, leak-free
intervention that could plausibly close the 0.46 ug/m3 gap to the RMSE < 20 bar.

Isolation guarantees
--------------------
* Trains into backend/app/artifacts/chronos2_trials/city_pm10_focus/ (separate
  out-dir; the serving layer only reads chronos2_delhi/species_*).
* Never writes any npz forecast cache - adoption, if any, is a separate
  explicit step with its own backup + verification.
* Train origins end strictly before the 12-month holdout (leak-free as always).
* Prints old-vs-new metrics on the IDENTICAL published 48-origin holdout so the
  comparison is apples-to-apples; nothing is adopted automatically.

Usage:  python scripts/retrain_city_pm10_trial.py
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
    WINTER_SAMPLE_STRIDE,
    build_arrays,
    eval_species,
    largest_hourly_run,
    train_species,
)
from evaluate_chronos2_station_gates import _ARTIFACT_DIR, holdout_origins  # noqa: E402

FOCUS_MONTHS = {3, 4, 5, 6}          # dust season x2 (the untried recipe change)
TRIAL_DIR = _ROOT / "backend" / "app" / "artifacts" / "chronos2_trials" / "city_pm10_focus"
MONTHS = 48


def main() -> int:
    t0 = time.time()
    end = datetime(2026, 9, 12)
    start = end - timedelta(days=MONTHS * 30.44)
    print(f"loading city archive {start.date()} -> {end.date()} (cache-aware)...", flush=True)
    chem, met = load_history(start.date(), end.date(), cache_dir=_ROOT / "data_cache")
    stamps_full, arrays, cam_extra, met_arrays = build_arrays(chem, met)
    r0, r1 = largest_hourly_run(stamps_full)
    stamps = stamps_full[r0:r1]
    arrays = {s: a[r0:r1] for s, a in arrays.items()}
    cam_extra = {c: a[r0:r1] for c, a in cam_extra.items()}
    met_arrays = {m: a[r0:r1] for m, a in met_arrays.items()}
    print(f"series: {stamps[0]} -> {stamps[-1]} ({len(stamps)} h)", flush=True)

    eval_origins, holdout_idx = holdout_origins(stamps)
    print(f"published holdout origins: {len(eval_origins)} "
          f"(first {stamps[eval_origins[0]]}, holdout_idx={holdout_idx})", flush=True)

    # Train origins: regular stride + dust-season x2, all strictly pre-holdout.
    train_set = set(range(CONTEXT_HOURS + HORIZON, holdout_idx - HORIZON, REGULAR_SAMPLE_STRIDE))
    extra = set(
        i for i in range(CONTEXT_HOURS + HORIZON, holdout_idx - HORIZON, WINTER_SAMPLE_STRIDE)
        if stamps[i].month in FOCUS_MONTHS
    )
    train_set |= extra
    train_origins = sorted(train_set)
    val_origins = train_origins[-8:]
    print(f"train origins={len(train_origins)} (dust-focus x2), val={len(val_origins)}", flush=True)

    # --- baseline sanity: eval the SERVING checkpoint, must reproduce 20.457 ---
    serving_ckpt = _ARTIFACT_DIR / "species_pm10"
    print("evaluating SERVING pm10 checkpoint on the identical origins...", flush=True)
    base_fc = eval_species(serving_ckpt, "pm10", eval_origins, stamps, arrays, cam_extra, met_arrays)
    base_rmse = _trial_rmse(base_fc, arrays, eval_origins)
    print(f"SERVING baseline rmse={base_rmse:.3f} (published: 20.457)", flush=True)

    # --- trial training ---
    TRIAL_DIR.mkdir(parents=True, exist_ok=True)
    print(f"training trial specialist into {TRIAL_DIR} ...", flush=True)
    train_species(
        "pm10", stamps, arrays, cam_extra, met_arrays, train_origins, val_origins,
        TRIAL_DIR, num_steps=500, learning_rate=1e-5, batch_size=32, context_hours=336, seed=42,
    )
    print("evaluating TRIAL specialist...", flush=True)
    trial_fc = eval_species(TRIAL_DIR / "species_pm10", "pm10", eval_origins, stamps, arrays, cam_extra, met_arrays)
    trial_rmse = _trial_rmse(trial_fc, arrays, eval_origins)

    verdict = "BEATS baseline" if trial_rmse < base_rmse else "does NOT beat baseline"
    print(f"\n==== TRIAL RESULT ====", flush=True)
    print(f"serving baseline : rmse={base_rmse:.3f}", flush=True)
    print(f"dust-focus trial : rmse={trial_rmse:.3f}  ({verdict})", flush=True)
    print(f"RMSE<20 bar      : {'trial PASSES' if trial_rmse < 20 else 'trial MISSES'} "
          f"(baseline {'MISSES' if base_rmse >= 20 else 'PASSES'})", flush=True)
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
