"""Per-cell Chronos-2 specialist fine-tuning (leak-free), one species at a time.

Why
---
The six published specialists were trained only on the city cell's CAMS/HRES
series. Non-city cells inherit the city model's forecasts, which under-fits
their local levels and dynamics (e.g. south-central PM10 mean ~412 ug/m3 vs
the city cell's ~229). This script trains a dedicated specialist per cell on
that cell's own data with the EXACT city training recipe (same window maker,
strides, covariates, LoRA settings - train_species/eval_species take the cell's
arrays as parameters, so the recipe transfers 1:1), then evaluates on the
identical 48-origin holdout protocol used by evaluate_chronos2_station_gates.py.

Leak-free guarantees (same as the published run):
  * chronological split: training origins end strictly before the 12-month
    holdout; the holdout is never trained on
  * target species' future never enters any input channel
  * future covariates = other-species CAMS + AOD/dust + HRES met + calendar
    (the documented operational contract)

Adoption rule (serving stays honest):
  * the per-cell npz forecast cache is overwritten ONLY if the specialist's
    holdout RMSE beats the inherited (city-model) forecast on the same origins;
    otherwise nothing is overwritten and the old numbers stand
  * the city cell is never touched (its specialists are the published ones)

Usage:
    python scripts/finetune_chronos2_cells.py --species pm10 --cells c70_192,c70_191,c70_193
    python scripts/finetune_chronos2_cells.py --species pm10 --cells c70_192 --num-steps 30
"""

from __future__ import annotations

import argparse
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

from cell_archives import cell_cache_paths, merge_hourly  # noqa: E402
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
from evaluate_chronos2_station_gates import _NPZ_DIR, _stats, gate_block  # noqa: E402

SPECIES = ("pm2_5", "pm10", "no2", "o3", "so2", "co")

CELL_CENTERS = {
    "city": (28.6139, 77.2090),
    "c70_192": (28.4, 77.2),
    "c70_191": (28.4, 76.8),
    "c70_193": (28.4, 77.6),
    "c71_193": (28.8, 77.6),
}

_OUT_DEFAULT = _ROOT / "chronos2_cell_finetune_report.json"


def load_cell_history(lat: float, lon: float, start: datetime, end: datetime) -> tuple[dict, dict]:
    """Merge all cached 90-day chunks for one cell into (chem, met) stamp->row dicts."""
    chem: dict = {}
    met: dict = {}
    day = start
    while day <= end:
        chunk_end = min(day + timedelta(days=89), end)
        cfile, mfile = cell_cache_paths(lat, lon, day.date(), chunk_end.date())
        if not (cfile.is_file() and mfile.is_file()):
            raise FileNotFoundError(
                f"cell ({lat}, {lon}) chunk {day.date()}..{chunk_end.date()} missing - run "
                f"'python scripts/cell_archives.py fetch --months 48' first"
            )
        merge_hourly(chem, json.loads(cfile.read_text(encoding="utf-8")))
        merge_hourly(met, json.loads(mfile.read_text(encoding="utf-8")))
        day = chunk_end + timedelta(days=1)
    return chem, met


def cell_holdout_origins(stamps: list[datetime], n_eval: int = 48):
    """48-origin spread over this cell's own 12-month holdout (same rule as city)."""
    n_total = len(stamps)
    holdout_start = stamps[-1] - timedelta(days=30.44 * 12)
    holdout_idx = next(i for i, t in enumerate(stamps) if t >= holdout_start)
    pool = [i for i in range(CONTEXT_HOURS + HORIZON, n_total - HORIZON, 96) if i >= holdout_idx]
    if n_eval and len(pool) > n_eval:
        picks = np.linspace(0, len(pool) - 1, n_eval).round().astype(int)
        return [pool[k] for k in dict.fromkeys(picks)], holdout_idx
    return pool, holdout_idx


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--species", type=str, default="pm10")
    parser.add_argument("--cells", type=str, default="c70_192,c70_191,c70_193",
                        help="comma-separated cell names (never 'city')")
    parser.add_argument("--season-focus", type=str, default="",
                        help="comma-separated months to oversample x2 pre-holdout "
                             "(e.g. '3,4,5,6' for dust season). Default '' keeps the "
                             "city recipe's winter x2 oversampling.")
    parser.add_argument("--months", type=int, default=48, help="archive depth per cell")
    parser.add_argument("--num-steps", type=int, default=600)
    parser.add_argument("--lr", type=float, default=3e-5)
    parser.add_argument("--context-hours", type=int, default=720)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--eval-origins", type=int, default=48)
    parser.add_argument("--eval-batch-size", type=int, default=256)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--skip-train", action="store_true", help="evaluate existing cell checkpoints only")
    parser.add_argument("--out", type=str, default=str(_OUT_DEFAULT))
    args = parser.parse_args()

    if args.species not in SPECIES:
        raise SystemExit(f"unknown species {args.species}")
    names = [c.strip() for c in args.cells.split(",")]
    if "city" in names:
        raise SystemExit("refusing to touch the city cell (published specialists live there)")
    bad = [c for c in names if c not in CELL_CENTERS or c == "city"]
    if bad:
        raise SystemExit(f"unknown cells {bad}; choose from {list(CELL_CENTERS)[1:]}")

    import torch

    torch.set_num_threads(args.threads)

    end = datetime(2026, 9, 12)
    start = end - timedelta(days=int(args.months * 30.44))
    city_ckpt = _ROOT / "backend" / "app" / "artifacts" / "chronos2_delhi" / f"species_{args.species}"

    report: dict = {
        "generated_at": datetime.now().isoformat(),
        "species": args.species,
        "config": {
            "num_steps": args.num_steps, "lr": args.lr,
            "context_hours": args.context_hours, "seed": args.seed,
            "batch_size": args.batch_size, "months": args.months,
            "season_focus": args.season_focus,
        },
        "cells": {},
    }
    out_path = Path(args.out)
    if out_path.is_file():
        # Merge into any existing report so chained per-cell invocations
        # don't clobber earlier cells' entries.
        try:
            prev = json.loads(out_path.read_text(encoding="utf-8"))
            report["cells"].update(prev.get("cells", {}))
        except (json.JSONDecodeError, OSError):
            pass

    for name in names:
        lat, lon = CELL_CENTERS[name]
        print(f"\n=== cell {name} ({lat}, {lon}) [{args.species}] ===", flush=True)
        chem, met = load_cell_history(lat, lon, start, end)
        stamps_full, arrays, cam_extra, met_arrays = build_arrays(chem, met)
        r0, r1 = largest_hourly_run(stamps_full)
        stamps = stamps_full[r0:r1]
        arrays = {s: a[r0:r1] for s, a in arrays.items()}
        cam_extra = {c: a[r0:r1] for c, a in cam_extra.items()}
        met_arrays = {m: a[r0:r1] for m, a in met_arrays.items()}
        n_total = len(stamps)
        truth = arrays[args.species]
        print(f"  {n_total} hourly stamps ({stamps[0]} .. {stamps[-1]}), "
              f"truth mean={np.nanmean(truth):.1f}", flush=True)

        eval_origins, holdout_idx = cell_holdout_origins(stamps, args.eval_origins)
        train_origins = set(range(CONTEXT_HOURS + HORIZON, holdout_idx - HORIZON, REGULAR_SAMPLE_STRIDE))
        focus_months = (
            {int(m) for m in args.season_focus.split(",") if m.strip()}
            if args.season_focus.strip() else set(_WINTER_MONTHS)
        )
        extra = set(
            i for i in range(CONTEXT_HOURS + HORIZON, holdout_idx - HORIZON, WINTER_SAMPLE_STRIDE)
            if stamps[i].month in focus_months
        )
        train_origins |= extra
        train_origins = sorted(train_origins)
        val_origins = train_origins[-8:]
        print(f"  train origins={len(train_origins)} (winter x2), eval origins={len(eval_origins)} "
              f"from {stamps[eval_origins[0]].date()}", flush=True)

        out_dir = _ROOT / "backend" / "app" / "artifacts" / "chronos2_cells" / f"{name}_{args.species}"
        ckpt_dir = out_dir / f"species_{args.species}"

        # -- score the INHERITED city-model forecast on this cell's truth ----
        print("  [inherit] scoring city-model forecasts against this cell's truth...", flush=True)
        inh = eval_species(
            city_ckpt, args.species, eval_origins, stamps, arrays, cam_extra, met_arrays,
            batch_size=args.eval_batch_size,
        )
        inh_pairs = [(float(inh[o][h]), float(truth[o + h]))
                     for o in eval_origins for h in range(HORIZON)
                     if math.isfinite(truth[o + h])]
        inh_stats = _stats(inh_pairs)
        print(f"  [inherit] RMSE={inh_stats['rmse']:.2f} R2={inh_stats['r2']:.4f} "
              f"nRMSE={inh_stats['nrmse']:.4f}", flush=True)

        # -- train the dedicated specialist -----------------------------------
        new = None
        if not args.skip_train:
            t0 = time.time()
            train_species(
                args.species, stamps, arrays, cam_extra, met_arrays,
                train_origins, val_origins, out_dir,
                num_steps=args.num_steps, learning_rate=args.lr,
                batch_size=args.batch_size, context_hours=args.context_hours,
                seed=args.seed,
            )
            print(f"  trained in {time.time() - t0:.0f}s", flush=True)
        if ckpt_dir.is_dir():
            new = eval_species(
                ckpt_dir, args.species, eval_origins, stamps, arrays, cam_extra, met_arrays,
                batch_size=args.eval_batch_size,
            )

        cell_entry: dict = {
            "cell": name,
            "center": [lat, lon],
            "n_train_origins": len(train_origins),
            "n_eval_origins": len(eval_origins),
            "truth_mean": round(float(np.nanmean(truth)), 2),
            "inherited_city_model": inh_stats,
        }

        if new is not None:
            new_pairs = [(float(new[o][h]), float(truth[o + h]))
                         for o in eval_origins for h in range(HORIZON)
                         if math.isfinite(truth[o + h])]
            new_stats = _stats(new_pairs)
            print(f"  [specialist] RMSE={new_stats['rmse']:.2f} R2={new_stats['r2']:.4f} "
                  f"nRMSE={new_stats['nrmse']:.4f}", flush=True)
            cell_entry["specialist"] = new_stats
            cell_entry["gate"] = gate_block({
                "rmse": new_stats["rmse"], "r2": new_stats["r2"], "nrmse": new_stats["nrmse"],
            })
            better = new_stats["rmse"] < inh_stats["rmse"]
            cell_entry["adopted"] = bool(better)
            if better:
                _NPZ_DIR.mkdir(parents=True, exist_ok=True)
                npz = _NPZ_DIR / f"{name}_{args.species}.npz"
                bak = npz.with_suffix(".npz.city_model_bak")
                if npz.is_file():
                    if bak.is_file():
                        bak.unlink()  # keep only the pre-adoption (city) baseline
                    npz.rename(bak)
                np.savez_compressed(
                    npz,
                    origins=np.array(sorted(eval_origins), dtype=np.int64),
                    preds=np.stack([new[o] for o in sorted(eval_origins)]),
                    stamps=np.array([str(stamps[o]) for o in sorted(eval_origins)]),
                )
                print(f"  ADOPTED: holdout RMSE improved ({inh_stats['rmse']:.2f} -> "
                      f"{new_stats['rmse']:.2f}); npz cache updated", flush=True)
            else:
                print(f"  NOT adopted: holdout did not improve "
                      f"({inh_stats['rmse']:.2f} -> {new_stats['rmse']:.2f})", flush=True)
        else:
            cell_entry["specialist"] = None
            cell_entry["adopted"] = None

        report["cells"][name] = cell_entry
        out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"\nwrote {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
