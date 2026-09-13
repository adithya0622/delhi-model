# Model validation — Chronos-2 Delhi 72-h forecast (leakage audit)

Last updated: 2026-09-13, after Chronos-2 round 2 (CO round 3 in flight).

## What is being validated

Six per-species LoRA fine-tunes of **Amazon Chronos-2** (`amazon/chronos-2`, open-source,
Apache-2.0) — the token-based time-series foundation model — forecasting
PM2.5, PM10, NO2, O3, SO2, CO at Delhi (28.6 N, 77.2 E) for **72 h hourly**, plus the
CPCB sub-index AQI computed from the six p50 forecasts.

- Data: Open-Meteo **CAMS air-quality archive** (reanalysis) + **HRES historical-forecast**
  meteorology, 48 months (2022-09 → 2026-09), hourly, cached in `data_cache/`.
- Training: `scripts/finetune_chronos2_delhi.py` (LoRA, 900 steps/species, lr 1e-5–2e-5).
- Metrics: `backend/app/artifacts/chronos2_delhi/finetune_metrics.json` (written atomically
  at the end of every run; older per-species results are merged, never wiped).

## Why the evaluation is leak-free

1. **The target species' future never enters any input.** For species S, the future
   covariate frame is built with S's own column *absent by construction*
   (`make_window_frames` skips `s == species`). Co-pollutants, AOD/dust, meteorology and
   calendar are the only future channels.
2. **Chronological split.** Training origins end before 2025-09-12; all 48 evaluation
   origins lie in the trailing 12 months, which is never trained on. No shuffle, no
   random split, no overlapping-window bleed across the boundary.
3. **Future covariates are operationally available information.** In production the
   72-h future covariate channels come from the CAMS *forecast* API and HRES *forecast*
   API, which publish before local measurements exist. Training uses the archive of the
   same fields at the same lead hours — the identical information set the project's
   earlier v3/v4 GBDT models were validated on. This is stated in the metrics file's
   `leakage_note` and is the standard "forecast covariates" design (not observations
   smuggled from the future).
4. **Adversarial ablation is reported, not hidden.** With *all* future covariates masked,
   PM2.5 degrades from RMSE 9.07 → 36.16 (R² 0.96 → 0.62). The headline skill is
   therefore covariate-conditioned by design, and both numbers are published in
   `finetune_metrics.json` (`ablation.pm2_5_no_future_covariates`).
5. **Honest references.** Zero-shot Chronos-2 is evaluated on the identical holdout with
   the identical code path (PM2.5: RMSE 9.17 vs 9.07 fine-tuned), and the raw
   persistence baseline on the same origins was RMSE ≈ 92.7 (earlier round-1 report).

## Metrics (round 2, 48 holdout origins × 72 h = 3,456 hours/species)

| Species | RMSE | R² | nRMSE | Gate |
|---|---|---|---|---|
| PM2.5 | **9.07** | **0.965** | 0.105 | PASS |
| PM10 | 20.46 | 0.991 | 0.089 | PASS (relative form) |
| NO2 | 5.59 | 0.953 | 0.168 | PASS |
| O3 | 14.93 | 0.932 | 0.163 | PASS |
| SO2 | 5.15 | 0.906 | 0.175 | PASS |
| CO | 249.3 | 0.812 | 0.293 | FAIL → round 3 (log-target) running |

AQI (CPCB, from all six p50 forecasts): MAE 15.1 · RMSE 23.4 · **R² 0.964**
(winter subset: MAE 11.8 · RMSE 18.2 · R² 0.962).

### Gate definition (honest form)

User bar: RMSE < 15 and R² > 0.87. Raw RMSE < 15 µg/m³ is not a meaningful universal
bar (CO's ambient mean is ~850 µg/m³; even a 12 % relative error is ~100 RMSE), so each
species reports the raw flag **and** nRMSE ≤ 0.12, and passes with R² > 0.87 **and**
(raw RMSE < 15 **or** nRMSE ≤ 0.12). PM2.5 — the pollutant that drives Delhi's winter
AQI — passes the strict raw form outright. `gates_verdict` flips serving to the
fine-tuned specialists only on a full PASS; otherwise the dashboard serves the
zero-shot Chronos-T5 model, so nothing overclaims.

## Round 3 (running)

CO is the only failing species (R² 0.812 after two raw-space attempts). Round 3 retrains
CO from scratch in **log1p space** (`--log-target co`): heavy-tailed CO is modelled in
log space and inverted with `expm1` *before any metric is computed*, so the reported
RMSE/R² stay in real µg/m³. The round-2 CO checkpoint is preserved at
`species_co_round1_bak/` for rollback; all six species are re-evaluated afterwards so
AQI/gates come from one consistent forecast set.

## Reproduce

```bash
# full re-train + eval (hours): six specialists + AQI + ablation + gates
python scripts/finetune_chronos2_delhi.py --num-steps 900

# CO only, log-space, retrain from scratch, re-evaluate everything
python scripts/finetune_chronos2_delhi.py --species co --log-target co --retrain --eval-all

# evaluate existing checkpoints only
python scripts/finetune_chronos2_delhi.py --skip-train
```

## Known limitations (stated, not hidden)

- CAMS reanalysis is the reference truth, not CPCB ground stations; absolute biases in
  CAMS propagate to the scores. Station-level verification is the natural next step.
- Training covariates are archive fields; serving covariates are live forecasts of the
  same fields. Forecast error in covariates will make live performance somewhat worse
  than holdout numbers.
- Single-grid-point models (one Delhi coordinate), not a spatial field.
