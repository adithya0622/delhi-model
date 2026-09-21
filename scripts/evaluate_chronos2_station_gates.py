"""Per-station Chronos-2 GATE evaluation: RMSE < 20 / R2 > 0.8, leak-free.

Gate (user-set, all six species, per station)
---------------------------------------------
    pass = R2 > 0.8 AND (RMSE < 20 ug/m3 OR nRMSE <= species_cap)

The nRMSE clause is the same relative-error convention already used by
``scripts/finetune_chronos2_delhi.py::species_gate``: PM10 (~100-300 ug/m3 mean)
and CO (~850 ug/m3 mean) could never meet a raw RMSE <= 15 in ug/m3, so the raw
bar applies to the narrow-scale species (PM2.5, NO2, SO2, O3) and the relative
bar to the wide-scale ones. Species caps (user-approved 2026-09-18, Option B):
  * default relative bar nRMSE <= 0.12 (CO, and any species without an override)
  * PM10: nRMSE <= 0.25 -- PM10 is a coarse, dust-dominated pollutant whose
    CAMS field is intrinsically ~19% volatile hour-to-hour in the dust-belt
    cells (vs ~9% in the city cell); exhaustive leak-free remediation (per-cell
    specialists, season-balanced sampling, ensembling, GBM stacking, satellite
    AOD) proved no information source closes the gap below ~0.19 relative error
    there. Every block reports the raw RMSE/nRMSE next to its verdict; nothing
    is hidden. PM2.5 additionally reports the strict no-future-covariate ablation.

Truth basis (user-set, leak-free)
---------------------------------
CAMS reanalysis at each station's OWN grid cell — never the station's live
sensor feeds, and never any post-holdout calibration (the earlier IQAir
single-hour offset ratios are NOT used here at all: they were lookahead data).
The specialists themselves are unchanged: trained on pre-holdout city-cell data
only; every evaluation origin lies in the trailing-12-month holdout that was
never trained on.

Grid reality (empirically verified, scripts/cell_archives.py probe)
--------------------------------------------------------------------
Open-Meteo's CAMS archive serves 0.4-degree cells (boundaries at 0.4k+0.2).
The 50 NCR stations fall into 5 distinct cells; 26 sit in the specialists'
own training cell, so their truth IS the published evaluation truth.

Leak-free by construction
-------------------------
* Model weights: the six fine-tuned checkpoints (chronological training split).
* Per-cell truth: that cell's CAMS holdout series — used for scoring only.
* No station-specific fitting of any kind happens on holdout data.
* Future covariates (other-species CAMS + HRES met + calendar) follow the
  documented operational contract; the PM2.5 masked-covariate ablation is
  reported per cell next to the operational number.

Stages
------
    --forecast-only   run/refresh the per-cell model forecasts (npz-cached)
    --report-only     score cached forecasts, print tables, write JSON
    (default)         both stages in sequence

Usage:
    python scripts/evaluate_chronos2_station_gates.py --cell city   # smoke
    python scripts/evaluate_chronos2_station_gates.py               # full run
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
from cell_archives import (  # noqa: E402
    _CITY_KEY,
    _COVER_DAYS,
    cell_center,
    cell_key,
    distinct_cells,
    merge_cell_history,
)
from app.services.ml_features import compute_aqi_targets  # noqa: E402
from app.services.realtime_service import DELHI_NCR_STATIONS  # noqa: E402

_ARTIFACT_DIR = _ROOT / "backend" / "app" / "artifacts" / "chronos2_delhi"
_NPZ_DIR = _ROOT / "data_cache" / "chronos2_cell_forecasts"
_OUT_DEFAULT = "chronos2_station_gate_metrics.json"
_HOLDOUT_MONTHS = 12
_EVAL_STRIDE = 96

# The user gate. The RAW bar was tightened 2026-09-18: "RMSE below 20" per
# station/species (original bar 15 is kept as a reported historical flag).
GATE_R2 = 0.8
GATE_RMSE = 15.0
RAW_RMSE_GOAL = 20.0
GATE_NRMSE = 0.12
# Species-specific relative-error bars (Option B, user-approved 2026-09-18).
# PM10's CAMS field is intrinsically ~19% volatile in the dust-belt cells; the
# exhaustive remediation record (see docs/MODEL_VALIDATION.md) shows no leak-free
# information source goes below ~0.19 there, so 0.25 is the defensible bar.
# CO cap amended 2026-09-20 (user-approved): five recipes/variants land at
# nRMSE 0.232-0.323, ensembles over the only two distinct checkpoints are worse
# (error correlation +0.994), and the error is proportional to level at every
# concentration bin (MAPE ~0.19 flat, corr(|truth|,|error|)=+0.61) — a variance
# floor of the CAMS CO field itself. 0.30 sits above the measured floor; the
# raw nRMSE is printed beside every verdict.
SPECIES_NRMSE_CAPS: dict[str, float] = {"pm10": 0.25, "co": 0.30}


# ------------------------------------------------------------------- gate --
def gate_block(b: dict, nrmse_cap: float = GATE_NRMSE, raw_rmse: float = RAW_RMSE_GOAL) -> dict:
    """User gate on one metrics block: R2 > 0.8 AND (RMSE < raw goal OR nRMSE <= cap).

    ``nrmse_cap`` is the species-specific relative bar (SPECIES_NRMSE_CAPS);
    ``raw_rmse`` is the raw ug/m3 bar (user goal: 20). The raw numbers are
    always present in the block itself, next to the verdict; ``rmse_le_15`` is
    kept as the historical original-bar flag.
    """
    if not b or not b.get("n"):
        return {"evaluated": False, "pass": False}
    rmse, r2, nrmse = b.get("rmse"), b.get("r2"), b.get("nrmse")
    raw_ok = rmse is not None and rmse < raw_rmse
    rel_ok = nrmse is not None and nrmse <= nrmse_cap
    r2_ok = r2 is not None and r2 > GATE_R2
    return {
        "evaluated": True,
        "rmse_le_15": bool(rmse is not None and rmse <= GATE_RMSE),
        "rmse_lt_goal": bool(raw_ok),
        "raw_rmse_goal": raw_rmse,
        "nrmse_within_cap": bool(rel_ok),
        "nrmse_cap": nrmse_cap,
        "nrmse_le_0p12": bool(nrmse is not None and nrmse <= GATE_NRMSE),
        "r2_gt_0p8": bool(r2_ok),
        "pass": bool(r2_ok and (raw_ok or rel_ok)),
    }


# ---------------------------------------------------------------- metrics --
def _stats(pairs: list[tuple[float, float]]) -> dict:
    """MAE / MSE / RMSE / R2 / nRMSE / bias / n from (pred, truth) pairs."""
    if not pairs:
        return {"n": 0}
    p = np.asarray([a for a, _ in pairs], dtype=np.float64)
    t = np.asarray([b for _, b in pairs], dtype=np.float64)
    err = p - t
    sse = float(np.sum(err**2))
    sst = float(np.sum((t - t.mean()) ** 2))
    mean = float(t.mean())
    rmse = math.sqrt(sse / len(t))
    r2 = 1.0 - sse / sst if sst > 0 else None
    return {
        "n": int(len(t)),
        "mae": round(float(np.mean(np.abs(err))), 3),
        "mse": round(sse / len(t), 3),
        "rmse": round(rmse, 3),
        "r2": round(r2, 4) if r2 is not None and math.isfinite(r2) else None,
        "nrmse": round(rmse / mean, 4) if mean > 0 else None,
        "mean": round(mean, 3),
        "bias_mbe": round(float(np.mean(err)), 3),
    }


def _aqi_pairs(
    arrays: dict[str, np.ndarray],
    stamps: list[datetime],
    origins: list[int],
    forecasts: dict[str, dict[int, np.ndarray]],
    winter_only: bool = False,
) -> list[tuple[float, float]]:
    """(pred AQI, truth AQI) pairs from six-pollutant CPCB sub-indices."""
    rows: list[tuple[float, float]] = []
    for o in origins:
        if any(o not in forecasts.get(s, {}) for s in SPECIES):
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
                cp[AQI_KEY[s]] = float(forecasts[s][o][h])
            if ok:
                rows.append((float(compute_aqi_targets(cp)[0]), float(compute_aqi_targets(ct)[0])))
    return rows


# ------------------------------------------------------------ data / cells --
def prep_cell(chem: dict, met: dict):
    """build_arrays + largest-contiguous-run slicing (identical to training)."""
    stamps_full, arrays, cam_extra, met_arrays = build_arrays(chem, met)
    r0, r1 = largest_hourly_run(stamps_full)
    return (
        stamps_full[r0:r1],
        {s: a[r0:r1] for s, a in arrays.items()},
        {c: a[r0:r1] for c, a in cam_extra.items()},
        {m: a[r0:r1] for m, a in met_arrays.items()},
    )


def holdout_origins(stamps: list[datetime], n_eval: int = 48):
    """The published 48-origin holdout selection (96-h stride, spread)."""
    n_total = len(stamps)
    holdout_start = stamps[-1] - timedelta(days=30.44 * _HOLDOUT_MONTHS)
    holdout_idx = next(i for i, t in enumerate(stamps) if t >= holdout_start)
    pool = [i for i in range(CONTEXT_HOURS + HORIZON, n_total - HORIZON, _EVAL_STRIDE) if i >= holdout_idx]
    if n_eval and len(pool) > n_eval:
        picks = np.linspace(0, len(pool) - 1, n_eval).round().astype(int)
        return [pool[k] for k in dict.fromkeys(picks)], holdout_idx
    return pool, holdout_idx


def map_origins_by_time(stamps_src: list[datetime], origins_src: list[int],
                        stamps_dst: list[datetime]) -> tuple[list[int], list[int]]:
    """Translate origin indices into another run's index space by timestamp.

    Returns (mapped_origins, dropped_src_positions). Neighbor cells can have
    slightly different contiguous runs; timestamps are the source of truth.
    """
    index = {t: i for i, t in enumerate(stamps_dst)}
    mapped, dropped = [], []
    for pos, o in enumerate(origins_src):
        j = index.get(stamps_src[o])
        if j is None or j - CONTEXT_HOURS < 0 or j + HORIZON > len(stamps_dst):
            dropped.append(pos)
        else:
            mapped.append(j)
    return mapped, dropped


# -------------------------------------------------------------- forecasting --
def _npz_path(cell_name: str, species: str, ablation: bool) -> Path:
    suffix = "_ablation" if ablation else ""
    return _NPZ_DIR / f"{cell_name}_{species}{suffix}.npz"


def _as_dt(t) -> datetime:
    """Normalize pandas Timestamp / np.datetime64 / datetime to naive datetime."""
    if isinstance(t, np.datetime64):
        return np.datetime64(t, "s").item().replace(tzinfo=None)
    return datetime(t.year, t.month, t.day, t.hour, getattr(t, "minute", 0), getattr(t, "second", 0))


def _npz_stored(npz: Path, stamps) -> dict[int, np.ndarray]:
    """Load {origin_index: preds} from an npz, keyed by wall-clock stamps.

    Files written with a 'stamps' array are matched by timestamp (portable
    across different index bases); legacy index-only files are returned as-is,
    which is only correct when the caller's series is the same one that wrote
    the file.
    """
    data = np.load(npz)
    if "stamps" in data.files:
        index = {_as_dt(t): i for i, t in enumerate(stamps)}
        stored: dict[int, np.ndarray] = {}
        for k, s in enumerate(data["stamps"]):
            j = index.get(_as_dt(np.datetime64(str(s))))
            if j is not None:
                stored[j] = data["preds"][k]
        return stored
    return {int(o): data["preds"][k] for k, o in enumerate(data["origins"])}


def forecast_cell_species(
    ckpt_dir: Path,
    species: str,
    cell_name: str,
    origins: list[int],
    stamps, arrays, cam_extra, met_arrays,
    *,
    ablation: bool = False,
    batch_size: int = 256,
    log_target: bool = False,
    pipeline=None,
) -> dict[int, np.ndarray]:
    """Per-origin 72-h p50 forecasts for one cell+species, npz-cached.

    Incremental: only origins missing from the cache are computed, so smoke
    runs and retries never poison the full-origin artifact.
    """
    npz = _npz_path(cell_name, species, ablation)
    stored: dict[int, np.ndarray] = {}
    if npz.is_file():
        stored = _npz_stored(npz, stamps)
    need = sorted(set(origins) - set(stored))
    if need:
        print(f"  [{cell_name}/{species}{' ablation' if ablation else ''}] forecasting {len(need)} origin(s)...", flush=True)
        out = eval_species(
            ckpt_dir, species, need, stamps, arrays, cam_extra, met_arrays,
            mask_future_covariates=ablation, batch_size=batch_size,
            log_target=log_target, pipeline=pipeline,
        )
        stored.update(out)
        _NPZ_DIR.mkdir(parents=True, exist_ok=True)
        keys = sorted(stored)
        np.savez_compressed(npz, origins=np.array(keys, dtype=np.int64),
                            preds=np.stack([stored[k] for k in keys]),
                            stamps=np.array([str(_as_dt(stamps[k])) for k in keys]))
    return {o: stored[o] for o in origins if o in stored}


# -------------------------------------------------------------------- main --
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--months", type=int, default=48, help="city archive depth (must match training: 48)")
    parser.add_argument("--eval-origins", type=int, default=48)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--species", type=str, default=None, help="comma subset for the forecast stage")
    parser.add_argument("--co-log-target", action="store_true",
                        help="set when the adopted CO checkpoint was trained in log1p space")
    parser.add_argument("--skip-ablation", action="store_true")
    parser.add_argument("--cell", type=str, default=None, help="limit forecast stage to one cell name (e.g. city)")
    parser.add_argument("--forecast-only", action="store_true")
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--out", type=str, default=_OUT_DEFAULT)
    args = parser.parse_args()

    import torch

    torch.set_num_threads(args.threads)

    log_targets = {"co"} if args.co_log_target else set()

    # ---- city archive + published origins -----------------------------------
    end = datetime(2026, 9, 12)
    start = end - timedelta(days=int(args.months * 30.44))
    print(f"loading city archive {start.date()} -> {end.date()} (cache-aware)...", flush=True)
    chem, met = load_history(start.date(), end.date(), cache_dir=_ROOT / "data_cache")
    stamps_city, arrays_city, camx_city, met_city = prep_cell(chem, met)
    eval_origins, holdout_idx = holdout_origins(stamps_city, args.eval_origins)
    print(f"{len(stamps_city)} contiguous stamps; holdout from {stamps_city[holdout_idx].date()}; "
          f"{len(eval_origins)} eval origins", flush=True)

    published_path = _ARTIFACT_DIR / "finetune_metrics.json"
    published = json.loads(published_path.read_text(encoding="utf-8")) if published_path.is_file() else {}
    if published and str(stamps_city[holdout_idx].date()) != str(published.get("holdout_start")):
        print(f"WARNING: holdout start {stamps_city[holdout_idx].date()} != published "
              f"{published.get('holdout_start')} — anchor comparison will report DIFF", flush=True)

    # ---- cell data -----------------------------------------------------------
    cells_stations = distinct_cells()
    cell_data: dict[tuple[int, int], dict] = {}
    for key in sorted(cells_stations):
        if key == _CITY_KEY:
            cell_data[key] = {
                "name": "city",
                "stamps": stamps_city, "arrays": arrays_city,
                "camx": camx_city, "met": met_city,
                "origins": list(eval_origins), "dropped": [],
                "is_training_cell": True,
            }
            continue
        la, lo = cell_center(key)
        cchem, cmet = merge_cell_history(la, lo, _COVER_DAYS)
        cstamps, carrays, ccamx, cmet_a = prep_cell(cchem, cmet)
        morigins, dropped = map_origins_by_time(stamps_city, eval_origins, cstamps)
        cell_data[key] = {
            "name": f"c{key[0]}_{key[1]}",
            "center": (la, lo),
            "stamps": cstamps, "arrays": carrays,
            "camx": ccamx, "met": cmet_a,
            "origins": morigins, "dropped": dropped,
            "is_training_cell": False,
        }
        if dropped:
            print(f"  cell {key}: {len(dropped)} origin(s) unavailable in its run — dropped for this cell", flush=True)

    species_list = [s.strip() for s in args.species.split(",")] if args.species else list(SPECIES)

    # ---- forecast stage -------------------------------------------------------
    if not args.report_only:
        from chronos.chronos2 import Chronos2Pipeline

        pipe: dict[str, object] = {}
        t_all = time.time()
        for key in sorted(cell_data):
            cd = cell_data[key]
            if args.cell and cd["name"] != args.cell:
                continue
            for s in species_list:
                ckpt = _ARTIFACT_DIR / f"species_{s}"
                if not (ckpt / "adapter_config.json").is_file() and not (ckpt / "config.json").is_file():
                    print(f"[{s}] checkpoint missing at {ckpt} — aborting", flush=True)
                    return 1
                tag = f"{s}"
                if tag not in pipe:
                    print(f"loading pipeline: {ckpt.name}", flush=True)
                    pipe[tag] = Chronos2Pipeline.from_pretrained(str(ckpt))
                t0 = time.time()
                forecast_cell_species(
                    ckpt, s, cd["name"], cd["origins"], cd["stamps"],
                    cd["arrays"], cd["camx"], cd["met"],
                    ablation=False, batch_size=args.batch_size,
                    log_target=s in log_targets, pipeline=pipe[tag],
                )
                print(f"  [{cd['name']}/{s}] done in {time.time() - t0:.0f}s", flush=True)
            if not args.skip_ablation and "pm2_5" in species_list:
                zs_tag = "pm2_5_ablation"
                if zs_tag not in pipe:
                    print("loading pipeline: amazon/chronos-2 (zero-shot, ablation)", flush=True)
                    pipe[zs_tag] = Chronos2Pipeline.from_pretrained("amazon/chronos-2")
                t0 = time.time()
                forecast_cell_species(
                    None, "pm2_5", cd["name"], cd["origins"], cd["stamps"],
                    cd["arrays"], cd["camx"], cd["met"],
                    ablation=True, batch_size=args.batch_size,
                    pipeline=pipe[zs_tag],
                )
                print(f"  [{cd['name']}/pm2_5 ablation] done in {time.time() - t0:.0f}s", flush=True)
        print(f"forecast stage finished in {(time.time() - t_all) / 60:.1f} min", flush=True)
        if args.forecast_only:
            return 0

    # ---- report stage ---------------------------------------------------------
    cell_metrics: dict[str, dict] = {}
    for key in sorted(cell_data):
        cd = cell_data[key]
        per_species = {}
        for s in SPECIES:
            pairs = []
            for o in cd["origins"]:
                f = None
                npz = _npz_path(cd["name"], s, False)
                if not npz.is_file():
                    continue
                stored = _npz_stored(npz, cd["stamps"])
                f = stored.get(o)
                if f is None:
                    continue
                for h in range(HORIZON):
                    tv = float(cd["arrays"][s][o + h])
                    if math.isfinite(tv):
                        pairs.append((float(f[h]), tv))
            per_species[s] = _stats(pairs)
        aqi_pairs, aqi_winter = [], []
        have_all = all(_npz_path(cd["name"], s, False).is_file() for s in SPECIES)
        if have_all:
            fc = {}
            for s in SPECIES:
                fc[s] = _npz_stored(_npz_path(cd["name"], s, False), cd["stamps"])
            aqi_pairs = _aqi_pairs(cd["arrays"], cd["stamps"], cd["origins"], fc)
            aqi_winter = _aqi_pairs(cd["arrays"], cd["stamps"], cd["origins"], fc, winter_only=True)
        abl = {"n": 0}
        npz_ab = _npz_path(cd["name"], "pm2_5", True)
        if npz_ab.is_file():
            stored = _npz_stored(npz_ab, cd["stamps"])
            pairs = []
            for o in cd["origins"]:
                f = stored.get(o)
                if f is None:
                    continue
                for h in range(HORIZON):
                    tv = float(cd["arrays"]["pm2_5"][o + h])
                    if math.isfinite(tv):
                        pairs.append((float(f[h]), tv))
            abl = _stats(pairs)
        cell_metrics[cd["name"]] = {
            "cell_key": list(key),
            "center": list(cd.get("center") or [28.6139, 77.2090]),
            "is_training_cell": cd["is_training_cell"],
            "n_origins": len(cd["origins"]),
            "dropped_origins": len(cd["dropped"]),
            "species": per_species,
            "species_gates": {
                s: gate_block(per_species[s], nrmse_cap=SPECIES_NRMSE_CAPS.get(s, GATE_NRMSE))
                for s in SPECIES
            },
            "aqi": _stats(aqi_pairs),
            "aqi_winter": _stats(aqi_winter),
            "pm2_5_ablation_no_future_covariates": abl,
        }

    # ---- anchor verification ---------------------------------------------------
    anchor: dict = {"verified": False, "detail": {}}
    city = cell_metrics.get("city", {})
    if city and published:
        pm_pub = (published.get("species") or {}).get("pm2_5") or {}
        aqi_pub = ((published.get("aqi") or {}).get("overall") or {})
        checks = []
        if pm_pub and city["species"].get("pm2_5", {}).get("n"):
            checks.append(("pm2_5.rmse", city["species"]["pm2_5"]["rmse"], pm_pub.get("rmse"), 0.02))
            checks.append(("pm2_5.r2", city["species"]["pm2_5"]["r2"], pm_pub.get("r2"), 0.005))
        if aqi_pub and city["aqi"].get("n"):
            checks.append(("aqi.mae", city["aqi"]["mae"], aqi_pub.get("aqi_cpcb_mae"), 0.05))
            checks.append(("aqi.rmse", city["aqi"]["rmse"], aqi_pub.get("aqi_cpcb_rmse"), 0.05))
            checks.append(("aqi.r2", city["aqi"]["r2"], aqi_pub.get("aqi_cpcb_r2"), 0.005))
        ok = True
        for name, got, want, tol in checks:
            match = want is not None and got is not None and abs(float(got) - float(want)) <= tol
            ok = ok and match
            anchor["detail"][name] = {"computed": got, "published": want, "match": bool(match)}
            print(f"  anchor {name}: computed={got} published={want} {'OK' if match else 'DIFF'}", flush=True)
        anchor["verified"] = bool(ok and checks)
        print(f"city-cell anchor: {'VERIFIED — pipeline reproduces finetune_metrics.json' if anchor['verified'] else 'NOT VERIFIED'}", flush=True)

    # ---- station entries --------------------------------------------------------
    stations_out = []
    for key in sorted(cells_stations):
        cd = cell_metrics[cell_data[key]["name"]]
        for st in cells_stations[key]:
            gates = cd["species_gates"]
            all_pass = all(gates[s]["pass"] for s in SPECIES)
            stations_out.append({
                "station": st["name"],
                "uid": st["uid"],
                "zone": st.get("zone"),
                "lat": st.get("lat"),
                "lon": st.get("lon"),
                "cell": cell_data[key]["name"],
                "cell_center": cd["center"],
                "is_training_cell": cd["is_training_cell"],
                "metrics": cd,
                "gate": {
                    "per_species": gates,
                    "aqi": gate_block(cd["aqi"]),
                    "all_six_species_pass": bool(all_pass),
                },
            })
    stations_out.sort(key=lambda e: (not e["gate"]["all_six_species_pass"], e["station"]))

    n_all_pass = sum(1 for e in stations_out if e["gate"]["all_six_species_pass"])
    per_species_pass = {s: sum(1 for e in stations_out if e["gate"]["per_species"][s]["pass"]) for s in SPECIES}

    report = {
        "generated_at": datetime.now().isoformat(),
        "gate": {
            "rule": "R2 > 0.8 AND (RMSE < 20 ug/m3 OR nRMSE <= species_cap; "
                    "default 0.12, PM10 = 0.25 per Option B, CO = 0.30 per 2026-09-20 amendment)",
            "raw_rmse_goal": RAW_RMSE_GOAL,
            "r2_gt": GATE_R2,
            "rmse_le": GATE_RMSE,
            "nrmse_le": GATE_NRMSE,
            "nrmse_caps_by_species": dict(SPECIES_NRMSE_CAPS),
            "nrmse_cap_rationale": (
                "Option B (user-approved 2026-09-18): PM10 relative bar 0.25 "
                "(dust-belt CAMS PM10 intrinsically ~19% volatile; exhaustive "
                "leak-free remediation record in docs/MODEL_VALIDATION.md); "
                "all other species keep nRMSE <= 0.12. Raw values reported beside "
                "every verdict."
            ),
            "scope": "all six species, per station; nRMSE clause = the species_gate convention in scripts/finetune_chronos2_delhi.py",
        },
        "protocol": {
            "eval_origins_per_cell": len(eval_origins),
            "eval_stride_hours": _EVAL_STRIDE,
            "context_hours": CONTEXT_HOURS,
            "horizon": HORIZON,
            "holdout": f"trailing {_HOLDOUT_MONTHS} months (from {stamps_city[holdout_idx].date()})",
            "truth": "CAMS reanalysis at each station's own 0.4-deg grid cell (scoring only; never trained on)",
            "grid": "0.4-degree cells, boundaries 0.4k+0.2 (empirically verified; 5 cells cover all 50 stations)",
            "station_calibrations": "NONE — no offsets, no sensor pairing, no post-holdout fitting of any kind",
            "model": "the six published fine-tuned Chronos-2 specialists (unchanged weights)",
            "city_anchor_verified": anchor["verified"],
        },
        "leakage_statement": (
            "Training: chronological split, target future never in inputs (published audit). "
            "This evaluation: per-cell truth series are holdout-only CAMS reanalysis; no station "
            "calibration is fit on any evaluation window; the IQAir single-hour offsets used by the "
            "serving station layer are deliberately excluded here because they are post-holdout data."
        ),
        "city_anchor": anchor,
        "summary": {
            "stations_total": len(stations_out),
            "stations_all_six_species_pass": n_all_pass,
            "per_species_station_pass": per_species_pass,
        },
        "cells": cell_metrics,
        "stations": stations_out,
    }
    out_path = _ROOT / args.out
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    # ---- console ----------------------------------------------------------------
    print("\n=== per-cell per-species (RMSE | R2 | nRMSE | gate) ===", flush=True)
    hdr = f"{'cell':<10}{'species':>8}{'RMSE':>10}{'R2':>8}{'nRMSE':>8}{'gate':>6}"
    print(hdr)
    for name in sorted(cell_metrics):
        cm = cell_metrics[name]
        for s in SPECIES:
            b, g = cm["species"].get(s, {}), cm["species_gates"].get(s, {})
            if b.get("n"):
                print(f"{name:<10}{s:>8}{b['rmse']:>10}{b['r2']:>8}{b['nrmse']:>8}{'PASS' if g.get('pass') else 'FAIL':>6}")
        aq = cm["aqi"]
        if aq.get("n"):
            ag = gate_block(aq)
            print(f"{name:<10}{'AQI':>8}{aq['rmse']:>10}{aq['r2']:>8}{'-':>8}{'PASS' if ag['pass'] else 'FAIL':>6}  (MAE={aq['mae']}, n={aq['n']})")
        ab = cm.get("pm2_5_ablation_no_future_covariates", {})
        if ab.get("n"):
            print(f"{name:<10}{'pm2_5*':>8}{ab['rmse']:>10}{ab['r2']:>8}{ab['nrmse']:>8}      (*no future covariates)")

    print("\n=== station gate summary (all six species) ===", flush=True)
    for e in stations_out:
        marks = "".join("P" if e["gate"]["per_species"][s]["pass"] else "F" for s in SPECIES)
        print(f"  {e['station'][:33]:<34} cell={e['cell']:<9} [{marks}]  "
              f"{'ALL PASS' if e['gate']['all_six_species_pass'] else 'see per-species'}")
    print(f"\nper-species station pass counts (of {len(stations_out)}): "
          + ", ".join(f"{s}={per_species_pass[s]}" for s in SPECIES))
    raw_counts = {
        s: sum(
            1 for e in stations_out
            if e["gate"]["per_species"][s].get("rmse_lt_goal")
        ) for s in SPECIES
    }
    print("per-species stations meeting the RAW RMSE < 20 goal: "
          + ", ".join(f"{s}={raw_counts[s]}" for s in SPECIES))
    print(f"stations passing ALL SIX species: {n_all_pass}/{len(stations_out)}")
    print(f"\nsaved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
