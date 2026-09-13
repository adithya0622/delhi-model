"""Head-to-head evaluation: Chronos-T5 vs Chronos-2 on the identical holdout.

Both open-source foundation models are scored on the SAME chronological holdout
origins (trailing 12 months of the 48-month CAMS archive, origins every 96 h)
with the SAME metric code used by the trainer:

  * Chronos-T5 (amazon/chronos-t5-small): univariate per pollutant, autoregressive
    72 h rollout from a 168 h context. Zero-shot base weights (the fine-tuned
    variant is scored by train_chronos_delhi_72h.py itself after each stage).
  * Chronos-2 (amazon/chronos-2): native multivariate (all six pollutants in one
    task) with HRES meteorology as past + future-known covariates, zero-shot —
    this pip build exposes no fine-tune entry point for it.

Outputs `model_comparison.json` next to the T5 artifact with per-species
MAE/RMSE/R2, six-pollutant CPCB AQI MAE (the headline), flat persistence on the
identical origins, and the winner declaration. Also merges the comparison into
chronos_metrics.json so /forecast/chronos-status serves it immediately.

Usage:
    python scripts/evaluate_chronos_models.py            # full holdout (90 origins)
    python scripts/evaluate_chronos_models.py --origins 30   # faster pass
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "backend"))
sys.path.insert(0, str(_ROOT / "scripts"))

from train_chronos_delhi_72h import (  # noqa: E402
    FORECAST_HORIZON,
    SERVING_CONTEXT_HOURS,
    SPECIES,
    _C2_COVARIATES,
    _C2_MODEL_IDS,
    _flat_persistence,
    _metric_block,
    build_series,
)
from train_pm25_v3 import load_history  # noqa: E402

_ARTIFACT_DIR = _ROOT / "backend" / "app" / "artifacts" / "chronos_72h"
_METRICS_JSON = _ARTIFACT_DIR / "chronos_metrics.json"
_COMPARISON_JSON = _ARTIFACT_DIR / "model_comparison.json"


def _predict_t5(pipeline, arrays, origins, num_samples):
    import torch

    out = {s: {} for s in SPECIES}
    for n, i in enumerate(origins):
        ctx = np.stack([arrays[s][i - SERVING_CONTEXT_HOURS : i] for s in SPECIES])
        with torch.no_grad():
            samples = pipeline.predict(
                torch.from_numpy(ctx),
                prediction_length=FORECAST_HORIZON,
                num_samples=num_samples,
                limit_prediction_length=False,
            )
        for k, s in enumerate(SPECIES):
            out[s][str(i)] = samples[k].median(dim=0).values.numpy().astype(np.float64)
        if (n + 1) % 25 == 0:
            print(f"    t5 {n + 1}/{len(origins)}", flush=True)
    return out


def _predict_c2(pipeline_c2, met, arrays, stamps, origins):
    import torch

    forecasts = {s: {} for s in SPECIES}
    q_levels = list(getattr(pipeline_c2, "quantiles", [0.1, 0.5, 0.9]))
    i50 = q_levels.index(0.5)

    inputs = []
    for i in origins:
        target = np.stack([arrays[s][i - SERVING_CONTEXT_HOURS : i] for s in SPECIES])
        past_cov, fut_cov = {}, {}
        for cov in _C2_COVARIATES:
            past_vals = np.asarray(
                [met.get(stamps[i - k], {}).get(cov, np.nan) for k in range(SERVING_CONTEXT_HOURS, 0, -1)],
                dtype=np.float32,
            )
            fut_vals = np.asarray(
                [met.get(stamps[i + k], {}).get(cov, np.nan) for k in range(1, FORECAST_HORIZON + 1)],
                dtype=np.float32,
            )
            for arr in (past_vals, fut_vals):
                mask = np.isnan(arr)
                if mask.any():
                    fill = float(np.nanmean(arr)) if (~mask).any() else 0.0
                    arr[mask] = fill
            past_cov[cov] = torch.from_numpy(past_vals)
            fut_cov[cov] = torch.from_numpy(fut_vals)
        if np.isnan(target).any():
            target = np.nan_to_num(target, nan=float(np.nanmean(target)))
        inputs.append({
            "target": torch.from_numpy(target),
            "past_covariates": past_cov,
            "future_covariates": fut_cov,
        })

    print(f"    c2 predicting {len(inputs)} origins (multivariate + covariates)...", flush=True)
    with torch.no_grad():
        outputs = pipeline_c2.predict(inputs, prediction_length=FORECAST_HORIZON)
    for n, i in enumerate(origins):
        pred = outputs[n]
        for k, s in enumerate(SPECIES):
            forecasts[s][str(i)] = pred[k, i50].numpy().astype(np.float64)
    return forecasts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origins", type=int, default=90, help="number of holdout origins to score")
    parser.add_argument("--samples", type=int, default=12, help="T5 sample paths per forecast")
    parser.add_argument("--months", type=int, default=48)
    args = parser.parse_args()

    import torch
    from chronos import ChronosPipeline

    torch.set_num_threads(8)

    from chronos.chronos2 import Chronos2Pipeline

    end = datetime(2026, 9, 12)
    start = end - timedelta(days=int(args.months * 30.44))
    print(f"loading archive {start.date()} -> {end.date()} (cache-aware)...", flush=True)
    chem, met = load_history(start.date(), end.date(), cache_dir=_ROOT / "data_cache")
    stamps, arrays = build_series(chem)

    all_origins = [i for i in range(SERVING_CONTEXT_HOURS, len(stamps) - FORECAST_HORIZON) if i % 96 == 0]
    holdout_start = stamps[-1] - timedelta(days=365)
    origins = [i for i in all_origins if stamps[i] >= holdout_start][-args.origins:]
    print(f"scoring {len(origins)} identical holdout origins from {stamps[origins[0]].date()}", flush=True)

    results: dict[str, dict] = {}

    # ── Chronos-T5 (zero-shot base weights) ─────────────────────────────────
    print("== chronos-t5-small (zero-shot) ==", flush=True)
    t5 = ChronosPipeline.from_pretrained("amazon/chronos-t5-small", device_map="cpu", torch_dtype=torch.float32)
    t5_block = _metric_block(arrays, stamps, origins, _predict_t5(t5, arrays, origins, args.samples),
                             persistence=_flat_persistence(arrays, origins))
    results["chronos_t5_small_zero_shot"] = t5_block
    print(f"  AQI MAE: {t5_block['aqi']['overall']['aqi_cpcb_mae']}", flush=True)
    del t5

    # ── Chronos-2 (zero-shot, multivariate + covariates) ────────────────────
    print("== chronos-2 (zero-shot, covariates) ==", flush=True)
    pipeline_c2 = None
    for model_id in _C2_MODEL_IDS:
        try:
            pipeline_c2 = Chronos2Pipeline.from_pretrained(model_id)
            print(f"  loaded {model_id}", flush=True)
            break
        except Exception as exc:
            print(f"  id '{model_id}' unavailable: {type(exc).__name__}", flush=True)
    if pipeline_c2 is not None:
        c2_block = _metric_block(arrays, stamps, origins,
                                 _predict_c2(pipeline_c2, met, arrays, stamps, origins), persistence=None)
        c2_block["framework"] = "chronos-2 (universal; multivariate + met covariates) — ZERO-SHOT"
        results["chronos2_zero_shot"] = c2_block
        print(f"  AQI MAE: {c2_block['aqi']['overall']['aqi_cpcb_mae']}", flush=True)
    else:
        results["chronos2_zero_shot"] = None
        print("  chronos-2 unavailable — comparison limited to T5 vs persistence", flush=True)

    # ── Winner declaration ──────────────────────────────────────────────────
    def _aqi(block):
        return (block or {}).get("aqi", {}).get("overall", {}).get("aqi_cpcb_mae", float("inf"))

    cands = {k: _aqi(v) for k, v in results.items() if v}
    winner = min(cands, key=cands.get) if cands else None
    comparison = {
        "generated_at": datetime.now().isoformat(),
        "holdout_origins": len(origins),
        "holdout_start": str(stamps[origins[0]].date()),
        "identical_origins": True,
        "results": results,
        "aqi_mae_leaderboard": dict(sorted(cands.items(), key=lambda kv: kv[1])),
        "winner_by_aqi_mae": winner,
        "note": "T5 fine-tuned variant is scored inside train_chronos_delhi_72h.py; the trainer exports the better of its own two stages",
    }
    _ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    _COMPARISON_JSON.write_text(json.dumps(comparison, indent=2), encoding="utf-8")
    print(f"wrote {_COMPARISON_JSON}", flush=True)

    # Merge into chronos_metrics.json so chronos-status serves the comparison.
    if _METRICS_JSON.is_file():
        metrics = json.loads(_METRICS_JSON.read_text(encoding="utf-8"))
        metrics["chronos2_zero_shot"] = results.get("chronos2_zero_shot")
        metrics["model_comparison"] = {
            "aqi_mae_leaderboard": comparison["aqi_mae_leaderboard"],
            "winner_by_aqi_mae": winner,
            "identical_origins": True,
        }
        _METRICS_JSON.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        print("merged into chronos_metrics.json", flush=True)


if __name__ == "__main__":
    main()
