# SIH judge demo script — NCR·72 coupled AQI system

A ~10-minute walkthrough. Every step maps a problem-statement phrase to a
screen, an endpoint, and a measured number. Numbers cited here are measured on
disk (see `PROBLEM_STATEMENT_COMPLIANCE.md` and `docs/MODEL_VALIDATION.md`);
re-verify any of them with the commands shown.

**Before the judges arrive (5 min):** start the backend
(`python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000`),
open `http://127.0.0.1:8000/console/`, let it warm up once (~30–60 s), and
confirm `GET /api/v1/health` returns `{"status":"ok"}`. Keep `docs/` open in a
browser tab for the evidence trail.

---

## Beat 1 — The hook: the coupled loop (2 min)

PS phrase: *"critical, dynamic feedback loop between the weather and pollutants"*

1. Console → **Atmospheric Dynamics / Coupling Loop panel**.
2. Say: "Most AQI dashboards show a number. Ours simulates the loop that makes
   the number: inversion traps pollution, aerosols dim sunlight, dimming cools
   the surface, cooling flattens the boundary layer, which traps more pollution
   — and slows the wind too."
3. Point at the loop's nodes rendered live per hour: ΔT inversion → PBL
   suppression → AOD → shortwave loss → surface cooling → wind perturbation.
   "Each hour is solved as a fixed point until the loop converges — that's the
   two-way feedback the problem statement asks for, and it's pinned by 34 unit
   tests against a no-feedback counterfactual."

Evidence: `GET /api/v1/forecast/72hr` (returns per-hour coupling fields);
`backend/tests/test_coupling.py` + `test_wind_feedback.py`.

## Beat 2 — Inversion tracking (1 min)

PS phrase: *"explicitly track atmospheric inversion strength"*

1. Console → **Inversion strip** (72-h ΔT / PBL / amplification bands).
2. Say: "ΔT between 925 and 1000 hPa is our inversion lid meter: above 1.5 °C
   weak, 3.5 moderate, 6 strong — with the AQI amplification factor each band
   implies tonight."

Evidence: `GET /api/v1/inversion/status`.

## Beat 3 — Stubble-burning plumes (2 min)

PS phrase: *"predict how stubble-burning plumes will disperse under prevailing weather conditions"*

1. Console → **Plume map**.
2. Say: "NASA FIRMS fire detections right now, each advected forward 72 hours
   on the 850 hPa forecast winds — Lagrangian trajectories, Gaussian dispersion,
   and the arriving smoke enters the residual layer and fumigates to the
   surface when the morning boundary layer grows into it. The map is empty when
   there are no fires: we never fake data."
3. If judges ask about emissions: "FRP → combustion rate (Wooster 2005) →
   crop-residue emission factors; the transport-layer loading is what survives
   into the forecast; the surface feel depends on Delhi's own mixing depth."

Evidence: `GET /api/v1/plume/vectors`.

## Beat 4 — The token foundation model (2 min)

PS instruction (judge): *"open-source model that uses tokens, forecast all six pollutants 72 h"*

1. Say: "Amazon Chronos — Apache-2.0 — treats forecasting as language
   modeling: values are quantised into a 4096-token vocabulary and a T5
   transformer autoregressively generates the next 72 hourly tokens per
   pollutant. We fine-tuned six LoRA specialists on 4 years of CAMS+HRES
   archive with each pollutant's own future structurally excluded from its
   inputs."
2. Read the leaderboard off `GET /api/v1/forecast/chronos-status`:
   persistence ~104 → Chronos-T5 zero-shot 96.9 → Chronos-2 zero-shot 83.3 →
   **fine-tuned specialists 15.1 AQI MAE** (R² 0.96) on the identical leak-free
   holdout.
3. Anti-cheat moment (judges love this): "Mask every future covariate and PM2.5
   degrades from RMSE 9.1 to 36.2 — the ablation is published in
   `finetune_metrics.json`, not hidden. And the dashboard refuses to serve the
   fine-tuned model unless six species pass their gates — the gate is a serving
   switch, not a label."

Evidence: `GET /api/v1/forecast/72hr-chronos`; `docs/MODEL_VALIDATION.md`.

## Beat 5 — Validation honesty (2 min)

PS phrase: *"high-accuracy, actionable insights"* + judge skepticism

1. Say: "Everything is scored, and the truth hierarchy is declared: CAMS
   reanalysis for archives, real CPCB surface sensors for ground truth."
2. November 2025 stubble episode, CPCB sensor truth: "our archived replay
   without fire emissions fails there — MAE 136, bias −135. That's the
   problem statement's motivation, demonstrated by our own endpoint. The live
   path fixes it with real-time fire injection, and the ML layers trained on
   the fire-affected archive score winter AQI MAE 11.8."
3. Operational cross-check: IITM SAFAR/EWS — "an actual operational WRF-Chem
   for this domain, ingested keylessly at `/api/v1/validation/safar` — plus our
   own WRF-Chem build for the same domain on free Kaggle compute
   (`scripts/wrfchem/kaggle_wrfchem_run.ipynb`), scored by
   `/api/v1/validation/wrf-compare`."

## Beat 6 — Actionable layer (1 min)

Console → **Exposure tracker** → enter activity.
"Personalized inhaled dose, cigarette equivalence, and the optimal 72-h
activity window — that's the 'actionable' half of the statement. Plus
multilingual voice health assistant (EN/HI/TA)."

Evidence: `POST /api/v1/exposure/calculate`.

## Close (30 s)

"Four model layers (physics, GBDT, direct-AQI, token foundation model), one
coupled core, every claim measured and every failure published. The compliance
matrix maps each problem-statement sentence to code and numbers."

---

## One-command re-verification

```bash
curl -s http://127.0.0.1:8000/api/v1/forecast/chronos-status | head -c 600
curl -s "http://127.0.0.1:8000/api/v1/validation/cpcb?dates=2025-11-10" | head -c 400
curl -s http://127.0.0.1:8000/api/v1/inversion/status | head -c 400
curl -s http://127.0.0.1:8000/api/v1/plume/vectors | head -c 400
cd backend && python -m pytest tests -q   # 285 tests
```

## If a live upstream fails mid-demo

- FIRMS empty → the map says "no fires detected" (correct behavior — September
  is not fire season; say so, it demonstrates the no-synthetic-data policy).
- Any forecast endpoint 502 → the consensus/dashboard degrades with a labelled
  banner; rerun after a few seconds (rate limit is 20–30/min per IP).
