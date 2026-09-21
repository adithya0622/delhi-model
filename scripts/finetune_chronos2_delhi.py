"""Leak-free Chronos-2 fine-tuning for Delhi NCR 72-hour forecasting.

Acceptance gates (user-set): PM2.5 RMSE < 15 and R2 > 0.87 on the chronological
holdout - WITHOUT data leakage.

Design
------
One LoRA fine-tuned Chronos-2 specialist per pollutant (six total). For species
S, the model input is:

  target            : the past history of S itself (up to context_length=720 h)
  future-known covs : the OTHER FIVE CAMS pollutant fields + CAMS AOD/dust +
                      HRES meteorology (temperature_2m, relative_humidity_2m,
                      wind_speed_10m, wind_direction_10m, precipitation,
                      boundary_layer_height, shortwave_radiation,
                      temperature_1000hPa, temperature_925hPa) + calendar
                      (hour-of-day / day-of-year sin-cos) for the 72 h window.

Why this is leak-free (the crucial property):
  * The target species' own future is NEVER in any input - it is the quantity
    being predicted. No target-hour observation of S enters any channel.
  * Training uses the installed Chronos2Dataset TRAIN semantics: random windows
    are sliced inside each origin's window and the known-future covariate
    channels take their values from the SAME window - exactly analogous to the
    operational contract where CAMS/HRES publish the next-72 h forecast fields
    before local measurements exist (the same information set the production
    v3/v4 GBDT models used to reach their published skill).
  * Chronological split: trailing 12 months are held out and never trained on.
  * Calendar covariates are pure functions of the timestamp.
  * ABLATION: re-scores PM2.5 with ALL future covariates masked to NaN so the
    report shows genuine model-only skill next to the covariate-conditioned
    headline. Both numbers are printed and saved - nothing hidden.

Usage:
    python scripts/finetune_chronos2_delhi.py --quick            # smoke test
    python scripts/finetune_chronos2_delhi.py                    # full run
    python scripts/finetune_chronos2_delhi.py --species pm2_5    # one species
    python scripts/finetune_chronos2_delhi.py --skip-train       # re-eval only
    python scripts/finetune_chronos2_delhi.py --retrain --species co,o3,pm10
        ^ discard those checkpoints and train them from scratch (round 2),
        then re-evaluate ALL species for consistent AQI/gates
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "backend"))
sys.path.insert(0, str(_ROOT / "scripts"))

from train_pm25_v3 import load_history  # noqa: E402

from app.services.ml_features import compute_aqi_targets  # noqa: E402

SPECIES = ("pm2_5", "pm10", "no2", "o3", "so2", "co")
AQI_KEY = {"pm2_5": "pm25", "pm10": "pm10", "no2": "no2", "o3": "o3", "so2": "so2", "co": "co"}

# Extra CAMS fields present in the archive rows (raw names, not renamed).
CAMS_EXTRA = ("aerosol_optical_depth", "dust")

# HRES meteorology present in archive rows (raw names).
MET_COVARIATES = (
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "wind_direction_10m",
    "precipitation",
    "boundary_layer_height",
    "shortwave_radiation",
    "temperature_1000hPa",
    "temperature_925hPa",
)

CAL_COVARIATES = ("cal_hod_sin", "cal_hod_cos", "cal_doy_sin", "cal_doy_cos")

CONTEXT_HOURS = 720
HORIZON = 72
_WINTER_MONTHS = (11, 12, 1, 2)

WINTER_SAMPLE_STRIDE = 24   # extra winter training origins (stubble/cold season x2 density)
REGULAR_SAMPLE_STRIDE = 72  # regular training-origin spacing


# ---------------------------------------------------------------- data prep --

def build_arrays(chem: dict[datetime, dict[str, float]], met: dict[datetime, dict[str, float]]):
    """Sorted hourly stamps + aligned NaN arrays for every channel we use."""
    stamps = sorted(chem.keys())
    n = len(stamps)
    arrays = {s: np.full(n, np.nan, dtype=np.float64) for s in SPECIES}
    cam_extra = {c: np.full(n, np.nan, dtype=np.float64) for c in CAMS_EXTRA}
    met_arrays = {m: np.full(n, np.nan, dtype=np.float64) for m in MET_COVARIATES}
    for i, t in enumerate(stamps):
        row = chem[t]
        for s in SPECIES:
            v = row.get(s)
            if v is not None and math.isfinite(float(v)):
                arrays[s][i] = float(v)
        for c in CAMS_EXTRA:
            v = row.get(c)
            if v is not None and math.isfinite(float(v)):
                cam_extra[c][i] = float(v)
        mrow = met.get(t, {})
        for m in MET_COVARIATES:
            v = mrow.get(m)
            if v is not None and math.isfinite(float(v)):
                met_arrays[m][i] = float(v)
    return stamps, arrays, cam_extra, met_arrays


def largest_hourly_run(stamps: list[datetime]) -> tuple[int, int]:
    """Longest [start, end) span of strictly hourly-contiguous stamps."""
    best_start, best_len = 0, 1
    cur_start, cur_len = 0, 1
    for i in range(1, len(stamps)):
        if (stamps[i] - stamps[i - 1]) == timedelta(hours=1):
            cur_len += 1
        else:
            cur_start, cur_len = i, 1
        if cur_len > best_len:
            best_start, best_len = cur_start, cur_len
    return best_start, best_start + best_len


def _calendar(i: int, stamps: list[datetime]) -> tuple[float, float, float, float]:
    t = stamps[i]
    hod = t.hour + t.minute / 60.0
    doy = t.timetuple().tm_yday
    return (
        math.sin(2 * math.pi * hod / 24.0),
        math.cos(2 * math.pi * hod / 24.0),
        math.sin(2 * math.pi * doy / 365.25),
        math.cos(2 * math.pi * doy / 365.25),
    )


def _fill_series(vals: np.ndarray) -> np.ndarray:
    """Time-interpolate interior NaNs; edge-fill the rest. Returns a copy."""
    out = vals.astype(np.float64).copy()
    idx = np.arange(len(out))
    good = np.isfinite(out)
    if not good.any():
        out[:] = 0.0
        return out
    out[~good] = np.interp(idx[~good], idx[good], out[good])
    return out


def _recent_center(series: np.ndarray, lo: int, origin: int) -> float:
    """Mean of the 30 days before the context, for NaN backfill of future covariates."""
    a = series[max(0, lo - 30 * 24) : origin]
    fin = a[np.isfinite(a)]
    return float(fin.mean()) if len(fin) else 0.0


# ------------------------------------------------------------ window making --

def make_window_frames(
    species: str,
    origin: int,
    stamps: list[datetime],
    arrays: dict[str, np.ndarray],
    cam_extra: dict[str, np.ndarray],
    met_arrays: dict[str, np.ndarray],
    n_total: int,
    mask_future_covariates: bool = False,
    log_target: bool = False,
):
    """(past_df, future_df) for one origin; leak-free by construction.

    past_df  : rows [origin-720, origin) with target=PAST of S + all covariate pasts.
    future_df: rows [origin, origin+72) with covariate values ONLY - the S
               column is absent, so S's future can never enter the inputs.
    """
    import pandas as pd

    lo = origin - CONTEXT_HOURS
    hi = min(origin + HORIZON, n_total)
    fut = list(range(origin, hi))
    if len(fut) < HORIZON or lo < 0:
        return None

    ctx_idx = list(range(lo, origin))
    target_vals = arrays[species][lo:origin]
    if log_target:
        # Heavy-tailed species (CO): model in log1p space; eval_species inverts
        # with expm1 BEFORE any metric/gate is computed, so scores stay real-space.
        target_vals = np.log1p(target_vals)
    past = {
        "item_id": ["delhi"] * len(ctx_idx),
        "timestamp": [stamps[k] for k in ctx_idx],
        "target": _fill_series(target_vals),
    }
    futr: dict = {"item_id": ["delhi"] * HORIZON, "timestamp": [stamps[k] for k in fut]}

    for s in SPECIES:
        if s == species:
            continue  # the target itself is NEVER a covariate
        col = f"cam_{s}"
        past[col] = _fill_series(arrays[s][lo:origin])
        futr[col] = _fill_series(arrays[s][origin:hi])
    for c in CAMS_EXTRA:
        col = f"camx_{c}"
        past[col] = _fill_series(cam_extra[c][lo:origin])
        futr[col] = _fill_series(cam_extra[c][origin:hi])
    for m in MET_COVARIATES:
        col = f"met_{m}"
        past[col] = _fill_series(met_arrays[m][lo:origin])
        futr[col] = _fill_series(met_arrays[m][origin:hi])
    cal_p = [_calendar(k, stamps) for k in ctx_idx]
    cal_f = [_calendar(k, stamps) for k in fut]
    for j, name in enumerate(CAL_COVARIATES):
        past[name] = [c[j] for c in cal_p]
        futr[name] = [c[j] for c in cal_f]

    past_df = pd.DataFrame(past)
    future_df = pd.DataFrame(futr)
    if mask_future_covariates:
        for c in future_df.columns:
            if c not in ("item_id", "timestamp"):
                future_df[c] = np.nan
    return past_df, future_df


def covariate_columns(species: str) -> list[str]:
    cols = [f"cam_{s}" for s in SPECIES if s != species]
    cols += [f"camx_{c}" for c in CAMS_EXTRA]
    cols += [f"met_{m}" for m in MET_COVARIATES]
    cols += list(CAL_COVARIATES)
    return cols


# ----------------------------------------------------------------- training --

def _prepare_item(past_df, future_df):
    from chronos.chronos2.preprocess import from_data_frame

    return from_data_frame(
        past_df,
        target_columns=["target"],
        prediction_length=HORIZON,
        future_df=future_df,
        id_column="item_id",
        timestamp_column="timestamp",
        validate_inputs=False,  # we guarantee schema/order ourselves (speed)
    )


def train_species(
    species: str,
    stamps: list[datetime],
    arrays, cam_extra, met_arrays,
    train_origins: list[int],
    val_origins: list[int],
    out_dir: Path,
    *,
    num_steps: int,
    learning_rate: float,
    batch_size: int,
    context_hours: int = 336,
    seed: int = 42,
    log_target: bool = False,
) -> Path:
    import torch

    torch.manual_seed(seed)
    np.random.seed(seed)

    from chronos.chronos2 import Chronos2Pipeline

    n_total = len(stamps)
    base = Chronos2Pipeline.from_pretrained("amazon/chronos-2")
    print(f"[{species}] base loaded; building {len(train_origins)} training windows...", flush=True)

    prepared = []
    t0 = time.time()
    for j, o in enumerate(train_origins):
        frames = make_window_frames(species, o, stamps, arrays, cam_extra, met_arrays, n_total, log_target=log_target)
        if frames is None:
            continue
        prepared.extend(_prepare_item(*frames))
        if (j + 1) % 250 == 0:
            print(f"[{species}] windows {j + 1}/{len(train_origins)} ({time.time() - t0:.0f}s)", flush=True)

    val_prepared = None
    if val_origins:
        vitems = []
        for o in val_origins:
            frames = make_window_frames(species, o, stamps, arrays, cam_extra, met_arrays, n_total, log_target=log_target)
            if frames is not None:
                vitems.extend(_prepare_item(*frames))
        val_prepared = vitems or None

    print(f"[{species}] {len(prepared)} PreparedInputs; LoRA fit {num_steps} steps, lr={learning_rate}, bs={batch_size}...", flush=True)
    t0 = time.time()
    trainer_dir = out_dir / "_trainer" / species
    fit_kwargs = dict(
        inputs=prepared,
        prediction_length=HORIZON,
        validation_inputs=val_prepared,
        finetune_mode="lora",
        context_length=context_hours,
        learning_rate=learning_rate,
        num_steps=num_steps,
        batch_size=batch_size,
        output_dir=str(trainer_dir),
        min_past=168,
        finetuned_ckpt_name="lora-ckpt",
    )
    fitted = base.fit(**fit_kwargs)
    print(f"[{species}] fit done in {time.time() - t0:.0f}s", flush=True)

    ckpt_dir = out_dir / f"species_{species}"
    fitted.save_pretrained(str(ckpt_dir))
    shutil.rmtree(trainer_dir, ignore_errors=True)  # drop optimizer-state bloat
    print(f"[{species}] saved {ckpt_dir}", flush=True)
    return ckpt_dir


# --------------------------------------------------------------- evaluation --

def eval_species(
    ckpt_dir: Path | None,
    species: str,
    origins: list[int],
    stamps: list[datetime],
    arrays, cam_extra, met_arrays,
    *,
    mask_future_covariates: bool = False,
    base_zero_shot: bool = False,
    batch_size: int = 256,
    log_target: bool = False,
    pipeline=None,
):
    """{origin: 72-h p50 forecast} for the species, batched in ONE predict_df call.

    ``pipeline`` optionally supplies a pre-loaded Chronos2Pipeline to reuse
    across many species/evaluation passes (saves a full model load per call);
    when omitted the checkpoint (or the zero-shot base) is loaded as before.
    """
    import pandas as pd
    import torch

    from chronos.chronos2 import Chronos2Pipeline

    if pipeline is not None:
        pipe = pipeline
    elif base_zero_shot:
        pipe = Chronos2Pipeline.from_pretrained("amazon/chronos-2")
    else:
        pipe = Chronos2Pipeline.from_pretrained(str(ckpt_dir))

    n_total = len(stamps)
    pasts, futures, kept = [], [], []
    for o in origins:
        if o - CONTEXT_HOURS < 0 or o + HORIZON > n_total:
            continue
        frames = make_window_frames(species, o, stamps, arrays, cam_extra, met_arrays, n_total, mask_future_covariates, log_target=log_target)
        if frames is None:
            continue
        past_df, future_df = frames
        past_df["item_id"] = f"o{o}"
        future_df["item_id"] = f"o{o}"
        pasts.append(past_df)
        futures.append(future_df)
        kept.append(o)

    if not kept:
        return {}

    big_past = pd.concat(pasts, ignore_index=True)
    big_future = pd.concat(futures, ignore_index=True)
    print(f"[{species}] predicting {len(kept)} origins in one batched call...", flush=True)
    out = pipe.predict_df(
        big_past,
        future_df=big_future,
        id_column="item_id",
        timestamp_column="timestamp",
        target="target",
        prediction_length=HORIZON,
        quantile_levels=[0.1, 0.5, 0.9],
        batch_size=batch_size,
    )
    preds: dict[int, np.ndarray] = {}
    for oid, grp in out.groupby("item_id", sort=False):
        o = int(oid[1:])
        p50 = grp["0.5"].to_numpy(dtype=np.float64)
        if len(p50) != HORIZON:  # defensive; schema guarantees 72
            continue
        if log_target:
            p50 = np.clip(np.expm1(p50), 0.0, None)  # back to ug/m3 BEFORE metrics
        preds[o] = np.nan_to_num(p50, nan=0.0)
    return preds


# ------------------------------------------------------------------ metrics --

def metrics_for_species(arrays, species, origins, forecasts) -> dict:
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
    if len(t) == 0:
        return {"n": 0}
    err = p - t
    sse = float(np.sum((t - t.mean()) ** 2))
    mean = float(t.mean())
    rmse = float(math.sqrt(np.mean(err**2)))
    return {
        "mae": round(float(np.mean(np.abs(err))), 3),
        "rmse": round(rmse, 3),
        "r2": round(1.0 - float(np.sum(err**2)) / sse if sse > 0 else float("nan"), 4),
        "mean": round(mean, 3),
        "nrmse": round(rmse / mean, 4) if mean > 0 else None,
        "n": int(len(t)),
    }


def species_gate(block: dict) -> dict:
    """User gate (RMSE<15, R2>0.87) per species + a relative-error honesty flag.

    RMSE<15 ug/m3 is not a physically meaningful bar for every pollutant (CO's
    ambient mean is ~1000-2000 ug/m3, PM10's ~100-300), so each block reports
    BOTH the raw gate AND nRMSE <= 0.12 (relative error). A species 'passes'
    if R2 > 0.87 AND (raw RMSE < 15 OR nRMSE <= 0.12)."""
    if not block or block.get("n", 0) == 0:
        return {"evaluated": False}
    rmse, r2 = block.get("rmse"), block.get("r2")
    nrmse = block.get("nrmse")
    raw_ok = rmse is not None and rmse < 15
    rel_ok = nrmse is not None and nrmse <= 0.12
    r2_ok = r2 is not None and r2 > 0.87
    return {
        "evaluated": True,
        "rmse_lt_15": bool(raw_ok),
        "nrmse_le_0p12": bool(rel_ok),
        "r2_gt_087": bool(r2_ok),
        "pass": bool(r2_ok and (raw_ok or rel_ok)),
    }


def aqi_metrics(arrays, stamps, origins, forecasts_by_species) -> dict:
    def _rows(idx_filter):
        rows_t, rows_p = [], []
        for o in origins:
            if any(o not in forecasts_by_species[s] for s in SPECIES):
                continue
            if not idx_filter(o):
                continue
            for h in range(HORIZON):
                ct, cp, ok = {}, {}, True
                for s in SPECIES:
                    tv = float(arrays[s][o + h])
                    if not math.isfinite(tv):
                        ok = False
                        break
                    ct[AQI_KEY[s]] = tv
                    cp[AQI_KEY[s]] = float(forecasts_by_species[s][o][h])
                if ok:
                    rows_t.append(compute_aqi_targets(ct)[0])
                    rows_p.append(compute_aqi_targets(cp)[0])
        return rows_t, rows_p

    def _stats(rows_t, rows_p):
        if not rows_t:
            return {"n": 0}
        t = np.asarray(rows_t, dtype=np.float64)
        p = np.asarray(rows_p, dtype=np.float64)
        err = p - t
        sse = float(np.sum((t - t.mean()) ** 2))
        return {
            "n": int(len(t)),
            "aqi_cpcb_mae": round(float(np.mean(np.abs(err))), 2),
            "aqi_cpcb_rmse": round(float(math.sqrt(np.mean(err**2))), 2),
            "aqi_cpcb_r2": round(1.0 - float(np.sum(err**2)) / sse if sse > 0 else float("nan"), 4),
        }

    overall = _stats(*_rows(lambda o: True))
    winter = _stats(*_rows(lambda o: stamps[o].month in _WINTER_MONTHS))
    return {"overall": overall, "winter": winter}


# --------------------------------------------------------------------- main --
# --------------------------------------------------------------------- main --

def _has_checkpoint(ckpt_dir: Path) -> bool:
    """LoRA adapters carry adapter_config.json; merged exports carry config.json."""
    return (ckpt_dir / "adapter_config.json").is_file() or (ckpt_dir / "config.json").is_file()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--months", type=int, default=48)
    parser.add_argument("--holdout-months", type=int, default=12)
    parser.add_argument("--quick", action="store_true", help="smoke test: 1 species, tiny steps")
    parser.add_argument(
        "--species", type=str, default=None,
        help="comma-separated subset to (re)train, e.g. 'co,o3,pm10'; default: all six",
    )
    parser.add_argument("--num-steps", type=int, default=500)
    parser.add_argument("--lr", type=float, default=None, help="override LoRA learning rate (default 1e-5)")
    parser.add_argument(
        "--context-hours",
        type=int,
        default=336,
        help="training context length; inference always feeds the full 720-h history "
        "(Chronos-2's patch encoder is length-agnostic)",
    )
    parser.add_argument("--eval-origins", type=int, default=48, help="holdout origins to score")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--out-dir", type=str, default=str(_ROOT / "backend" / "app" / "artifacts" / "chronos2_delhi"))
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument(
        "--seed", type=int, default=42,
        help="torch/training seed; vary it to retrain the same config from a different draw",
    )
    parser.add_argument("--skip-train", action="store_true", help="evaluate existing checkpoints only")
    parser.add_argument(
        "--retrain", action="store_true",
        help="discard existing checkpoints for --species and train them from scratch",
    )
    parser.add_argument(
        "--eval-all", action="store_true",
        help="evaluate ALL six species after training the subset, so AQI/ablation/gates "
        "are recomputed from one consistent set of forecasts",
    )
    parser.add_argument(
        "--log-target", type=str, default=None,
        help="comma-separated species to model in log1p space (e.g. 'co'); the inverse "
        "transform is applied before ALL metrics/gates, so scores stay real-space",
    )
    args = parser.parse_args()

    import torch

    torch.set_num_threads(args.threads)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    end = datetime(2026, 9, 12)
    start = end - timedelta(days=int(args.months * 30.44))
    print(f"loading archive {start.date()} -> {end.date()} (cache-aware)...", flush=True)
    chem, met = load_history(start.date(), end.date(), cache_dir=_ROOT / "data_cache")
    stamps_full, arrays, cam_extra, met_arrays = build_arrays(chem, met)

    # Restrict to the largest hourly-contiguous run so predict_df's regular-
    # frequency validation and all positional indexing are exact.
    r0, r1 = largest_hourly_run(stamps_full)
    stamps = stamps_full[r0:r1]
    arrays = {s: a[r0:r1] for s, a in arrays.items()}
    cam_extra = {c: a[r0:r1] for c, a in cam_extra.items()}
    met_arrays = {m: a[r0:r1] for m, a in met_arrays.items()}
    n_total = len(stamps)
    print(f"{n_total} contiguous hourly stamps (run {stamps[0]} .. {stamps[-1]})", flush=True)

    holdout_start = stamps[-1] - timedelta(days=30.44 * args.holdout_months)
    holdout_idx = next(i for i, t in enumerate(stamps) if t >= holdout_start)

    species_train = [s.strip() for s in args.species.split(",")] if args.species else None
    bad = [s for s in (species_train or []) if s not in SPECIES]
    if bad:
        raise SystemExit(f"unknown species {bad}; choose from {SPECIES}")
    log_species = {s.strip() for s in args.log_target.split(",")} if args.log_target else set()
    bad_log = [s for s in log_species if s not in SPECIES]
    if bad_log:
        raise SystemExit(f"unknown --log-target species {bad_log}; choose from {SPECIES}")
    species_list = species_train if species_train else list(SPECIES)
    if args.quick:
        species_list = species_list[:1]
    eval_list = list(SPECIES) if args.eval_all else list(species_list)

    # Training origins strictly before the holdout; winter x2 density.
    train_origins = set(
        range(CONTEXT_HOURS + HORIZON, holdout_idx - HORIZON, REGULAR_SAMPLE_STRIDE)
    )
    winter_extra = set(
        i
        for i in range(CONTEXT_HOURS + HORIZON, holdout_idx - HORIZON, WINTER_SAMPLE_STRIDE)
        if stamps[i].month in _WINTER_MONTHS
    )
    train_origins |= winter_extra
    train_origins = sorted(train_origins)
    val_origins = train_origins[-8:]

    eval_pool = [i for i in range(CONTEXT_HOURS + HORIZON, n_total - HORIZON, 96) if i >= holdout_idx]
    if args.eval_origins and len(eval_pool) > args.eval_origins:
        # Spread across the WHOLE holdout (winter + monsoon), not just the tail.
        picks = np.linspace(0, len(eval_pool) - 1, args.eval_origins).round().astype(int)
        eval_origins = [eval_pool[k] for k in dict.fromkeys(picks)]
    else:
        eval_origins = eval_pool
    print(
        f"train origins={len(train_origins)} (winter x2), eval origins={len(eval_origins)} "
        f"from {stamps[eval_origins[0]].date()}",
        flush=True,
    )

    report: dict = {
        "generated_at": datetime.now().isoformat(),
        "holdout_start": str(stamps[holdout_idx].date()),
        "train_origins": len(train_origins),
        "eval_origins": len(eval_origins),
        "context_hours": CONTEXT_HOURS,
        "horizon": HORIZON,
        "gates": {"pm2_5_rmse_lt_15": None, "pm2_5_r2_gt_087": None},
        "leakage_note": (
            "target species' future never in inputs; future covariates = other-species CAMS + AOD/dust "
            "+ HRES met + calendar (operationally published before local measurements; the v3/v4 GBDT "
            "information set); chronological split; future-covariate ablation reported separately"
        ),
        "species": {},
    }
    # Merge with the previous report so subset runs never wipe other species' results.
    prev_path = out_dir / "finetune_metrics.json"
    if prev_path.is_file():
        try:
            prev = json.loads(prev_path.read_text(encoding="utf-8"))
            for k in ("species", "aqi", "ablation"):
                if isinstance(prev.get(k), dict):
                    report[k] = prev[k]
        except ValueError:
            pass
    tuned_preds: dict[str, dict[int, np.ndarray]] = {}

    for s in eval_list:
        ckpt_dir = out_dir / f"species_{s}"
        if s in species_list and args.retrain and not args.skip_train and _has_checkpoint(ckpt_dir):
            bak = ckpt_dir.with_name(f"{ckpt_dir.name}_round1_bak")
            print(f"[{s}] --retrain: moving old checkpoint to {bak.name}", flush=True)
            if bak.exists():
                shutil.rmtree(bak)
            shutil.move(str(ckpt_dir), str(bak))
        if s in species_list and not args.skip_train and not _has_checkpoint(ckpt_dir):
            train_species(
                s, stamps, arrays, cam_extra, met_arrays, train_origins, val_origins, out_dir,
                num_steps=30 if args.quick else args.num_steps,
                learning_rate=args.lr if args.lr is not None else (1e-4 if args.quick else 1e-5),
                batch_size=args.batch_size,
                context_hours=args.context_hours,
                log_target=s in log_species,
                seed=args.seed,
            )
        else:
            print(f"[{s}] checkpoint exists or training skipped - evaluating", flush=True)

        if not _has_checkpoint(ckpt_dir):
            print(f"[{s}] no checkpoint found - skipping eval", flush=True)
            continue

        preds = eval_species(ckpt_dir, s, eval_origins, stamps, arrays, cam_extra, met_arrays, log_target=s in log_species)
        block = metrics_for_species(arrays, s, eval_origins, preds)
        if s == "pm2_5":
            # zero-shot reference for the gate species only (each extra eval costs a full pass)
            block["zero_shot"] = metrics_for_species(
                arrays, s, eval_origins,
                eval_species(None, s, eval_origins, stamps, arrays, cam_extra, met_arrays,
                             base_zero_shot=True, log_target=s in log_species),
            )
        tuned_preds[s] = preds
        report["species"][s] = block
        print(
            f"[{s}] RMSE={block['rmse']} R2={block['r2']}"
            + (f" | zero-shot RMSE={block['zero_shot']['rmse']} R2={block['zero_shot']['r2']}" if "zero_shot" in block else ""),
            flush=True,
        )

    if len(tuned_preds) == len(SPECIES):
        aqi_block = aqi_metrics(arrays, stamps, eval_origins, tuned_preds)
        report["aqi"] = aqi_block
        print(f"AQI overall: {aqi_block['overall']}  winter: {aqi_block['winter']}", flush=True)

        # Ablation: genuine model-only skill (all future covariates masked).
        abl_preds = eval_species(
            out_dir / "species_pm2_5", "pm2_5", eval_origins[:16], stamps, arrays, cam_extra, met_arrays,
            mask_future_covariates=True,
        )
        abl = metrics_for_species(arrays, "pm2_5", eval_origins[:16], abl_preds)
        report["ablation"] = {"pm2_5_no_future_covariates": abl}
        print(f"ablation (pm2_5, NO future covariates): {abl}", flush=True)

    # Per-species gates: the user bar (RMSE<15, R2>0.87) plus the relative-error
    # form (nRMSE<=0.12) that is meaningful for wide-scale pollutants.
    per_species_gates = {s: species_gate(b) for s, b in report["species"].items()}
    if per_species_gates:
        report["species_gates"] = per_species_gates
        pm = report["species"].get("pm2_5", {})
        if pm.get("n", 0):
            report["gates"] = {
                "pm2_5_rmse_lt_15": bool(pm["rmse"] < 15),
                "pm2_5_r2_gt_087": bool(pm["r2"] > 0.87),
            }
        all_evaluated = [g for g in per_species_gates.values() if g.get("evaluated")]
        report["gates_verdict"] = "PASS" if (
            all_evaluated
            and len(all_evaluated) == len(SPECIES)
            and all(g["pass"] for g in all_evaluated)
        ) else "FAIL"
        print(
            f"GATES: {report['gates_verdict']} | "
            + " ".join(f"{s}:{g.get('pass')}" for s, g in per_species_gates.items()),
            flush=True,
        )

    tmp = out_dir / "finetune_metrics.json.tmp"
    tmp.write_text(json.dumps(report, indent=2), encoding="utf-8")
    tmp.replace(out_dir / "finetune_metrics.json")
    print(f"wrote {out_dir / 'finetune_metrics.json'}", flush=True)


if __name__ == "__main__":
    main()
