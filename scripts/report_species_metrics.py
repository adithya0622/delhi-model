"""Full per-species error metrics (MAE / MSE / RMSE / R2 / bias) + AQI sub-index dominance.

Recomputes the 48-origin holdout forecasts from the existing per-species
checkpoints (no training) and writes finetune_metrics_full.json with the
quantities the main trainer does not store:

  * mse, bias (mean error, pred - truth; sign says over/under-prediction)
  * bias and RMSE by lead-time bucket (0-23h, 24-47h, 48-71h)
  * per-species CPCB sub-index dominance: the fraction of holdout hours where
    that pollutant's sub-index IS the max that sets the official AQI - the
    decision-relevant statistic for how much CO's residual error matters.

Read-only wrt finetune_metrics.json (the gates file): a separate artifact is
written so serving semantics are untouched.
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
sys.path.insert(0, str(_ROOT / "backend"))
sys.path.insert(0, str(_ROOT / "scripts"))

from finetune_chronos2_delhi import (  # noqa: E402
    AQI_KEY, CONTEXT_HOURS, HORIZON, SPECIES, build_arrays, eval_species,
    largest_hourly_run, metrics_for_species,
)
from train_pm25_v3 import load_history  # noqa: E402
from app.domain.aqi_scales import _sub_index  # noqa: E402
from app.services.ml_features import compute_aqi_targets  # noqa: E402

OUT_DIR = _ROOT / "backend" / "app" / "artifacts" / "chronos2_delhi"
EVAL_ORIGINS = 48
MONTHS = 48
THREADS = 8
# Species whose checkpoint was trained in log1p space (must match the trainer
# invocation that produced the checkpoint: --log-target co). eval_species
# inverts with expm1 BEFORE metrics, keeping scores in real ug/m3.
LOG_SPECIES = {"co"}


def _bucket_stats(arrays, species, origins, forecasts, lo_h, hi_h) -> dict:
    truth, pred = [], []
    for o in origins:
        if o not in forecasts:
            continue
        for h in range(lo_h, min(hi_h, HORIZON)):
            tv = float(arrays[species][o + h])
            if math.isfinite(tv):
                truth.append(tv)
                pred.append(float(forecasts[o][h]))
    t = np.asarray(truth, dtype=np.float64)
    p = np.asarray(pred, dtype=np.float64)
    if len(t) == 0:
        return {"n": 0}
    err = p - t
    return {
        "n": int(len(t)),
        "mae": round(float(np.mean(np.abs(err))), 3),
        "bias": round(float(np.mean(err)), 3),
        "rmse": round(float(math.sqrt(np.mean(err**2))), 3),
    }


def full_block(arrays, species, origins, forecasts) -> dict:
    truth, pred = [], []
    for o in origins:
        if o not in forecasts:
            continue
        t = arrays[species][o : o + HORIZON]
        p = forecasts[o]
        for h in range(HORIZON):
            tv = float(t[h])
            if math.isfinite(tv):
                truth.append(tv)
                pred.append(float(p[h]))
    t = np.asarray(truth, dtype=np.float64)
    p = np.asarray(pred, dtype=np.float64)
    err = p - t
    sse = float(np.sum((t - t.mean()) ** 2))
    rmse = float(math.sqrt(np.mean(err**2)))
    block = {
        "n": int(len(t)),
        "mae": round(float(np.mean(np.abs(err))), 3),
        "mse": round(float(np.mean(err**2)), 3),
        "rmse": round(rmse, 3),
        "r2": round(1.0 - float(np.sum(err**2)) / sse if sse > 0 else float("nan"), 4),
        "bias": round(float(np.mean(err)), 3),
        "mean_truth": round(float(t.mean()), 3),
        "p05_truth": round(float(np.percentile(t, 5)), 3),
        "p95_truth": round(float(np.percentile(t, 95)), 3),
        "bias_by_lead": {
            "h00_23": _bucket_stats(arrays, species, origins, forecasts, 0, 24),
            "h24_47": _bucket_stats(arrays, species, origins, forecasts, 24, 48),
            "h48_71": _bucket_stats(arrays, species, origins, forecasts, 48, 72),
        },
    }
    return block


def subindex_dominance(arrays, stamps, origins, forecasts_by_species) -> dict:
    """For each species: fraction of fully-observed hours whose CPCB sub-index is the AQI max."""
    wins = {s: 0 for s in SPECIES}
    total = 0
    for o in origins:
        if any(o not in forecasts_by_species.get(s, {}) for s in SPECIES):
            continue
        for h in range(HORIZON):
            conc, ok = {}, True
            for s in SPECIES:
                tv = float(arrays[s][o + h])
                if not math.isfinite(tv):
                    ok = False
                    break
                conc[AQI_KEY[s]] = tv
            if not ok:
                continue
            subs = {AQI_KEY[s]: _sub_index(AQI_KEY[s], conc[AQI_KEY[s]], "instant") for s in SPECIES}
            if not subs:
                continue
            total += 1
            best_s = max(subs, key=lambda k: subs[k])
            for s in SPECIES:
                if AQI_KEY[s] == best_s:
                    wins[s] += 1
    return {
        AQI_KEY[s]: {"wins": wins[s], "share": round(wins[s] / total, 4) if total else None}
        for s in SPECIES
    } | {"total_hours": total}


def main() -> None:
    import torch

    torch.set_num_threads(THREADS)

    end = datetime(2026, 9, 12)
    start = end - timedelta(days=int(MONTHS * 30.44))
    chem, met = load_history(start.date(), end.date(), cache_dir=_ROOT / "data_cache")
    stamps_full, arrays, cam_extra, met_arrays = build_arrays(chem, met)
    r0, r1 = largest_hourly_run(stamps_full)
    stamps = stamps_full[r0:r1]
    arrays = {s: a[r0:r1] for s, a in arrays.items()}
    cam_extra = {c: a[r0:r1] for c, a in cam_extra.items()}
    met_arrays = {m: a[r0:r1] for m, a in met_arrays.items()}
    n_total = len(stamps)

    holdout_idx = next(
        i for i, t in enumerate(stamps) if t >= stamps[-1] - timedelta(days=30.44 * 12)
    )
    pool = [i for i in range(CONTEXT_HOURS + HORIZON, n_total - HORIZON, 96) if i >= holdout_idx]
    picks = np.linspace(0, len(pool) - 1, EVAL_ORIGINS).round().astype(int)
    origins = [pool[k] for k in dict.fromkeys(picks)]
    print(f"{n_total} stamps; {len(origins)} eval origins from {stamps[origins[0]].date()}", flush=True)

    report: dict = {
        "generated_at": datetime.now().isoformat(),
        "note": "full error metrics incl. MSE/bias + lead-time buckets + AQI sub-index dominance; "
                "checkpoints unchanged; companion to finetune_metrics.json (gates live there)",
        "holdout_start": str(stamps[holdout_idx].date()),
        "eval_origins": len(origins),
        "horizon": HORIZON,
        "species": {},
    }

    all_preds: dict[str, dict[int, np.ndarray]] = {}
    for s in SPECIES:
        ckpt = OUT_DIR / f"species_{s}"
        t0 = time.time()
        preds = eval_species(ckpt, s, origins, stamps, arrays, cam_extra, met_arrays,
                             log_target=s in LOG_SPECIES)
        if not preds:
            print(f"[{s}] no forecasts - skipped", flush=True)
            continue
        blk = full_block(arrays, s, origins, preds)
        report["species"][s] = blk
        all_preds[s] = preds
        print(
            f"[{s}] MAE={blk['mae']} MSE={blk['mse']} RMSE={blk['rmse']} R2={blk['r2']} "
            f"bias={blk['bias']} ({time.time() - t0:.0f}s)",
            flush=True,
        )

    if len(all_preds) == len(SPECIES):
        report["aqi_subindex_dominance"] = subindex_dominance(arrays, stamps, origins, all_preds)
        print("sub-index dominance:", json.dumps(report["aqi_subindex_dominance"]), flush=True)

    tmp = OUT_DIR / "finetune_metrics_full.json.tmp"
    tmp.write_text(json.dumps(report, indent=2), encoding="utf-8")
    tmp.replace(OUT_DIR / "finetune_metrics_full.json")
    print(f"wrote {OUT_DIR / 'finetune_metrics_full.json'}", flush=True)


if __name__ == "__main__":
    main()
