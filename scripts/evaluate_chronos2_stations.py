"""Per-station Chronos-2 metrics: MAE / MSE / RMSE / R2 for all NCR stations.

What this does
--------------
The six fine-tuned Chronos-2 specialists (backend/app/artifacts/chronos2_delhi/,
scripts/finetune_chronos2_delhi.py) are trained on (and therefore predict) the
CAMS 0.25-degree cell that contains Delhi — a city-scale average. The production
serving layer (backend/app/services/station_forecast_service.py) turns that ONE
city forecast into N station forecasts by multiplying the concentrations with
each station's offset ratio (measured openaq-vs-cams where available, IQAir
live single-hour fallback, catalog ``aqi_factor`` prior otherwise).

This script runs the SAME protocol as the published evaluation
(finetune_metrics.json: 48 holdout origins every 96 h over the trailing 12
months, 720-h context, 72-h horizon, p50) for every species checkpoint, applies
the production station calibration, and scores the result against the CAMS
reanalysis truth at the city cell. Truth is the SAME series the specialists were
trained on — this measures the spatial-scaling layer's fidelity to the CAMS
cell, NOT ground-truth station sensor skill.

Per station and per species: MAE, MSE, RMSE, R2, bias (MBE) + n, plus the
six-pollutant CPCB AQI (max-of-sub-indices, same breakpoint tables as serving)
with a winter slice. A city-cell reference row (all ratios 1.0) must reproduce
the published finetune_metrics.json numbers exactly — that row is the sanity
anchor proving this pipeline matches the official evaluation.

Usage (from the repo root):
    python scripts/evaluate_chronos2_stations.py                 # all 51 stations
    python scripts/evaluate_chronos2_stations.py --quick         # 12 stations
    python scripts/evaluate_chronos2_stations.py --out chronos2_station_metrics.json
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
sys.path.insert(0, str(_ROOT / "backend"))
sys.path.insert(0, str(_ROOT / "scripts"))

from train_pm25_v3 import load_history  # noqa: E402

from finetune_chronos2_delhi import (  # noqa: E402
    AQI_KEY,
    CONTEXT_HOURS,
    HORIZON,
    SPECIES,
    _WINTER_MONTHS,
    build_arrays,
    eval_species,
    largest_hourly_run,
)
from app.services.ml_features import compute_aqi_targets  # noqa: E402
from app.services.station_forecast_service import station_offsets_for  # noqa: E402
from app.services.realtime_service import DELHI_NCR_STATIONS  # noqa: E402

_EVAL_ORIGINS = 48          # identical to the published evaluation
_EVAL_STRIDE = 96           # hours between holdout origins (identical)
_HOLDOUT_MONTHS = 12
_CACHE_DIR = _ROOT / "data_cache"
_ARTIFACT_DIR = _ROOT / "backend" / "app" / "artifacts" / "chronos2_delhi"
_OUT_DEFAULT = "chronos2_station_metrics.json"


# --------------------------------------------------------------- metric core --
def _stats(pairs: list[tuple[float, float]]) -> dict:
    """MAE / MSE / RMSE / R2 / bias / n from (pred, truth) pairs."""
    if not pairs:
        return {"n": 0}
    p = np.asarray([a for a, _ in pairs], dtype=np.float64)
    t = np.asarray([b for _, b in pairs], dtype=np.float64)
    err = p - t
    sse = float(np.sum(err**2))
    sst = float(np.sum((t - t.mean()) ** 2))
    r2 = 1.0 - sse / sst if sst > 0 else None
    return {
        "n": int(len(t)),
        "mae": round(float(np.mean(np.abs(err))), 3),
        "mse": round(sse / len(t), 3),
        "rmse": round(math.sqrt(sse / len(t)), 3),
        "r2": round(r2, 4) if r2 is not None and math.isfinite(r2) else None,
        "bias_mbe": round(float(np.mean(err)), 3),
    }


def _station_ratios(station: dict) -> tuple[dict[str, float], dict[str, str]]:
    """Per-species ratio + basis label from the production offset resolver.

    Keys are the trainer's species names (pm2_5 …) mapped onto the serving
    catalog's canonical keys (pm25 …) via AQI_KEY.
    """
    resolved = station_offsets_for(station["uid"])
    ratios, basis = {}, {}
    for s in SPECIES:
        entry = resolved.get(AQI_KEY[s]) or {}
        r = entry.get("ratio")
        if isinstance(r, (int, float)) and math.isfinite(float(r)) and 0.2 <= float(r) <= 5.0:
            ratios[s] = float(r)
            basis[s] = str(entry.get("basis") or "unknown")
        else:  # degenerate artifact value -> catalog prior, labelled honestly
            ratios[s] = float(station.get("aqi_factor") or 1.0)
            basis[s] = "catalog_prior_fallback"
    return ratios, basis


def metrics_for_station(
    arrays: dict[str, np.ndarray],
    stamps: list[datetime],
    origins: list[int],
    forecasts_by_species: dict[str, dict[int, np.ndarray]],
    ratios: dict[str, float],
    *,
    aqi: bool = True,
    winter_only: bool = False,
) -> dict:
    """Score ratio-scaled forecasts for one station against the CAMS-cell truth.

    The truth is never scaled — it is the CAMS cell the specialists were trained
    on, exactly as in the published evaluation.
    """
    per_species: dict[str, dict] = {}
    for s in SPECIES:
        pairs: list[tuple[float, float]] = []
        for o in origins:
            f = forecasts_by_species.get(s, {}).get(o)
            if f is None:
                continue
            for h in range(HORIZON):
                tv = float(arrays[s][o + h])
                if math.isfinite(tv):
                    pairs.append((float(f[h]) * float(ratios[s]), tv))
        per_species[s] = _stats(pairs)

    aqi_block: dict = {}
    if aqi:
        rows: list[tuple[float, float]] = []
        for o in origins:
            if any(o not in forecasts_by_species.get(s, {}) for s in SPECIES):
                continue
            if winter_only and stamps[o].month not in _WINTER_MONTHS:
                continue
            for h in range(HORIZON):
                ct, cp, ok = {}, {}, True
                for s in SPECIES:
                    tv = float(arrays[s][o + h])
                    if not math.isfinite(tv):
                        ok = False
                        break
                    ct[AQI_KEY[s]] = tv
                    cp[AQI_KEY[s]] = float(forecasts_by_species[s][o][h]) * float(ratios[s])
                if ok:
                    rows.append((float(compute_aqi_targets(cp)[0]), float(compute_aqi_targets(ct)[0])))
        aqi_block = _stats(rows)
    return {"species": per_species, "aqi": aqi_block}


# ----------------------------------------------------------------------- main --
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--months", type=int, default=48, help="archive depth (must match training: 48)")
    parser.add_argument("--eval-origins", type=int, default=_EVAL_ORIGINS)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=256, help="matches the published eval_species default")
    parser.add_argument("--quick", action="store_true", help="12 stations only (fast sanity pass)")
    parser.add_argument("--out", type=str, default=_OUT_DEFAULT)
    args = parser.parse_args()

    import torch

    torch.set_num_threads(args.threads)

    end = datetime(2026, 9, 12)
    start = end - timedelta(days=int(args.months * 30.44))
    print(f"loading archive {start.date()} -> {end.date()} (cache-aware)...", flush=True)
    chem, met = load_history(start.date(), end.date(), cache_dir=_CACHE_DIR)
    stamps_full, arrays, cam_extra, met_arrays = build_arrays(chem, met)

    # Same largest-contiguous-run restriction as training/eval — every array
    # must be sliced identically so origin indices line up.
    r0, r1 = largest_hourly_run(stamps_full)
    stamps = stamps_full[r0:r1]
    arrays = {s: a[r0:r1] for s, a in arrays.items()}
    cam_extra = {c: a[r0:r1] for c, a in cam_extra.items()}
    met_arrays = {m: a[r0:r1] for m, a in met_arrays.items()}
    n_total = len(stamps)
    print(f"{n_total} contiguous hourly stamps ({stamps[0]} .. {stamps[-1]})", flush=True)

    holdout_start = stamps[-1] - timedelta(days=30.44 * _HOLDOUT_MONTHS)
    holdout_idx = next(i for i, t in enumerate(stamps) if t >= holdout_start)

    eval_pool = [i for i in range(CONTEXT_HOURS + HORIZON, n_total - HORIZON, _EVAL_STRIDE) if i >= holdout_idx]
    if args.eval_origins and len(eval_pool) > args.eval_origins:
        picks = np.linspace(0, len(eval_pool) - 1, args.eval_origins).round().astype(int)
        eval_origins = [eval_pool[k] for k in dict.fromkeys(picks)]
    else:
        eval_origins = eval_pool
    print(
        f"eval origins={len(eval_origins)} from {stamps[eval_origins[0]].date()} "
        f"to {stamps[eval_origins[-1]].date()} (protocol identical to finetune_metrics.json)",
        flush=True,
    )

    # ---- one batched Chronos-2 pass per species on the CITY cell -------------
    forecasts: dict[str, dict[int, np.ndarray]] = {}
    for s in SPECIES:
        t0 = time.time()
        ckpt = _ARTIFACT_DIR / f"species_{s}"
        if not (ckpt / "adapter_config.json").is_file() and not (ckpt / "config.json").is_file():
            print(f"[{s}] checkpoint missing at {ckpt} — aborting", flush=True)
            return 1
        forecasts[s] = eval_species(
            ckpt, s, eval_origins, stamps, arrays, cam_extra, met_arrays,
            batch_size=args.batch_size,
        )
        print(f"[{s}] {len(forecasts[s])} origin forecasts in {time.time() - t0:.0f}s", flush=True)

    # ---- city-cell reference row (ratios 1.0) --------------------------------
    ref = metrics_for_station(arrays, stamps, eval_origins, forecasts, {s: 1.0 for s in SPECIES})
    print("\ncity-cell reference (must match finetune_metrics.json):", flush=True)
    for s in SPECIES:
        b = ref["species"][s]
        print(f"  {s:6s} MAE={b['mae']} MSE={b['mse']} RMSE={b['rmse']} R2={b['r2']}", flush=True)
    print(f"  AQI overall: {ref['aqi']}", flush=True)

    # ---- per-station scoring -------------------------------------------------
    stations = DELHI_NCR_STATIONS[:12] if args.quick else DELHI_NCR_STATIONS
    print(f"\nscoring {len(stations)} stations (pure post-scaling, no extra model calls)...", flush=True)

    entries = []
    for st in stations:
        ratios, basis = _station_ratios(st)
        m = metrics_for_station(arrays, stamps, eval_origins, forecasts, ratios)
        winter = metrics_for_station(arrays, stamps, eval_origins, forecasts, ratios, winter_only=True)
        entries.append({
            "station": st["name"],
            "uid": st["uid"],
            "zone": st.get("zone"),
            "lat": st.get("lat"),
            "lon": st.get("lon"),
            "ratios": {s: round(ratios[s], 4) for s in SPECIES},
            "ratio_basis": basis,
            "aqi_factor": st.get("aqi_factor"),
            "metrics": m,
            "winter_aqi": winter["aqi"],
        })
    entries.sort(key=lambda e: (e["metrics"]["aqi"].get("mae", math.inf), e["station"]))

    # Pooled per-species stats across ALL stations (concatenated pairs).
    pooled: dict[str, dict] = {s: {"_pairs": []} for s in SPECIES}
    for st in stations:
        ratios, _ = _station_ratios(st)
        for s in SPECIES:
            pairs = []
            for o in eval_origins:
                f = forecasts.get(s, {}).get(o)
                if f is None:
                    continue
                for h in range(HORIZON):
                    tv = float(arrays[s][o + h])
                    if math.isfinite(tv):
                        pairs.append((float(f[h]) * ratios[s], tv))
            pooled.setdefault(s, {"_pairs": []})["_pairs"].extend(pairs)
    pooled_out = {s: _stats(v["_pairs"]) for s, v in pooled.items()}

    report = {
        "generated_at": datetime.now().isoformat(),
        "model": "Chronos-2 LoRA fine-tuned specialists (six, covariate-aware)",
        "protocol": {
            "eval_origins": len(eval_origins),
            "eval_stride_hours": _EVAL_STRIDE,
            "context_hours": CONTEXT_HOURS,
            "horizon": HORIZON,
            "holdout": f"trailing {_HOLDOUT_MONTHS} months (from {stamps[holdout_idx].date()})",
            "truth": "CAMS reanalysis at the Delhi city cell (the training target series)",
            "station_layer": "production station_forecast_service offsets (measured / IQAir live / catalog prior)",
        },
        "city_cell_reference": ref,
        "pooled_all_stations": pooled_out,
        "stations": entries,
    }
    out_path = _ROOT / args.out
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    # ---- console tables ------------------------------------------------------
    hdr = f"{'station':<36}{'MAE':>8}{'MSE':>10}{'RMSE':>8}{'R2':>8}{'bias':>8}{'n':>7}   (CPCB AQI)"
    print("\n" + hdr)
    print("-" * len(hdr))
    for e in entries:
        a = e["metrics"]["aqi"]
        if not a.get("n"):
            continue
        print(
            f"{e['station'][:35]:<36}{a['mae']:>8}{a['mse']:>10}{a['rmse']:>8}"
            f"{a['r2'] if a['r2'] is not None else float('nan'):>8.4f}"
            f"{a['bias_mbe']:>8}{a['n']:>7}"
        )
    print("\npooled per-species across all stations (MAE / MSE / RMSE / R2):")
    for s in SPECIES:
        b = pooled_out.get(s, {})
        if b.get("n"):
            print(
                f"  {s:6s} MAE={b['mae']:>9} MSE={b['mse']:>11} RMSE={b['rmse']:>9} "
                f"R2={b['r2'] if b['r2'] is not None else 'nan'}  n={b['n']}"
            )
    print(f"\nsaved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
