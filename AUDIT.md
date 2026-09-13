# Code Audit — Delhi NCR AQI Forecasting System

**Audited:** 22 August 2026 · **Scope:** `D:\SIH` (3,271 lines of project code, excluding `.venv`)
**Method:** full read of backend + frontend, plus numerical re-execution of the physics and AQI math.

> ## ⚠ Read this first: sections 1–6 are the AS-FOUND record, not current state
>
> Everything below section 1 describes the code **as it was on 22 August 2026,
> before any fixes**. It is kept unedited on purpose: it is the evidence trail for
> what was wrong and why, and rewriting it would destroy the only record of the
> reasoning. Do not quote it as a description of the code that exists now.
>
> **What has changed since is in [§7 Remediation log](#7-remediation-log).** Every
> confirmed defect in §4 has been fixed, the feedback described in §2 has been
> rebuilt as a real fixed-point solver, and the fabricated accuracy claims in §5
> have been deleted from every document that carried them. The scorecard in §6 is
> re-scored at the end of §7.
>
> For current architecture read `ARCHITECTURE.md`; for current scope and
> limitations read the "What it is not" section of `README.md`.

---

## 1. What the program actually does

Strip away the documentation and the system is two cleanly separated halves.

**The live half works and is genuinely good.** `realtime_service.py` pulls real monitoring
stations from OpenAQ v3 across a Delhi NCR bounding box, paginating up to 500 locations. It
discards any station whose last reading is older than 24 hours, fetches sensors concurrently
behind a semaphore of 8 with `return_exceptions=True` so one dead sensor cannot collapse the
batch, converts µg/m³ concentrations to CPCB 2014 sub-indices, and takes the maximum sub-index as
the station AQI. Results are cached in a `TTLCache` behind an `asyncio.Lock` to prevent thundering
herds. The Streamlit dashboard renders this as a dark Folium map with AQI-scaled markers, a gauge,
pollutant chips, and a ranked station table. This part is real, defensible engineering.

**The forecast half is a parameterised point surrogate, not a coupled model.** The entire
"coupling" reduces to one scalar. `inversion_engine.py` computes ΔT = T(925 hPa) − T(1000 hPa)
from Open-Meteo, classifies it None/Weak/Moderate/Strong, and derives
`aqi_amplification_factor = 1200 / PBL_height`. `aqi_service.build_72h_forecast` then multiplies a
hardcoded diurnal emission profile by that one number, adds a stubble-plume term, overwrites O3
with a solar×NOx formula, applies an "aerosol feedback" correction, and converts to CPCB
sub-indices for each of 72 hours. There is no grid, no advection of the urban pollutant field, no
chemistry solver, and no WRF-Chem.

To be fair, `ARCHITECTURE.md` states this openly: *"a physics-informed surrogate model — not a
full chemistry transport model."* That is an honest and reasonable 5-day trade-off. The problem is
what happens underneath.

---

## 2. The central finding: the two-way feedback computes to zero

This is the project's headline novelty — the thing the problem statement is built around — and it
does not function. The defect is four lines in `aqi_service.py`:

```python
amp        = inv["aqi_amplification_factor"]   # from OBSERVED Open-Meteo PBL
feedback_pbl = _suppressed_pbl(adjusted_delta_t)   # from SYNTHETIC exp(-0.35·ΔT) formula
feedback_amp = _aqi_amplification(adjusted_delta_t, feedback_pbl)
extra_amp    = max(0, feedback_amp - amp)      # differencing two DIFFERENT quantities
```

`amp` and `feedback_amp` are not the same quantity measured before and after a perturbation. They
come from two unrelated PBL estimates. Subtracting them measures the disagreement between
Open-Meteo and a hand-fitted exponential, not the effect of aerosols. I ran the numbers:

| Observed PBL | PM2.5 | `amp` | `fb_amp` | `extra` | Net multiplier |
|---|---|---|---|---|---|
| 400 m (strong inversion) | 300 | 1.50 | 1.50 | **0.00** | **1.000** |
| 800 m | 300 | 1.50 | 1.25 | **0.00** | **1.000** |
| 1200 m | 300 | 1.00 | 1.25 | 0.25 | 1.123 |
| 2000 m (clean, well-mixed) | **15** | 0.60 | 1.01 | 0.41 | **1.206** |

Read the first two rows and the last together. Whenever the observed PBL is at or below 800 m —
precisely the trapped, inverted, high-pollution regime the problem statement exists to model —
`amp` is already clamped at its 1.50 ceiling, so `extra_amp` is **exactly zero** and the feedback
does nothing at all. Meanwhile in a clean 2000 m afternoon at 15 µg/m³, the "aerosol feedback"
happily applies a 1.21× boost.

**The feedback is strongest when the air is cleanest and vanishes entirely when the air is
dirtiest.** It is not merely weak; it is anti-correlated with the physics it claims to represent.

Two further problems compound it. Across the full PM2.5 range the aerosol term moves the result by
only ~10% (1.206 → 1.323 from 15 to 300 µg/m³), while the spurious formula-mismatch term
contributes 20–40% — so the artifact dominates the signal. And `_aerosol_radiation_feedback`
applies shortwave cooling unconditionally, including at 02:00 when there is no shortwave radiation
to block.

There is also no *meteorological* output from the feedback. The problem statement asks how trapped
pollutants "subsequently alter local weather conditions." The code computes `dt_surface` — a
surface temperature change — and then discards it. It is never returned, never displayed, never
fed to wind. The `pbl_height_m` in the response is the synthetic `_suppressed_pbl()` value, not a
modified observation. So the chemistry→meteorology direction produces no observable output at all.

---

## 3. The seasonal de-tuning trap

This is the most important thing to understand about the codebase's history, and it explains
almost every other defect.

Four comments, read together, tell the story:

```python
# _aqi_amplification:   "Relaxed for summer/monsoon: Cap at 1.5x to prevent artificial spikes."
# compute_inversion_series: "Enforce monsoon/summer diurnal PBL limits (1000m - 2500m day, ~800m night)"
# _base_emissions_diurnal:  "Lower baseline for summer/monsoon (~15-30 µg/m³ PM2.5)"
# _synthetic_hotspots:      "Return empty list ... disable mock winter wave"
```

The model was over-predicting in August, so it was progressively damped until the numbers looked
plausible today. Every one of those four changes disabled a winter mechanism the problem statement
is graded on:

- `max(pbl, 800.0)` floors the PBL at 800 m. Delhi's November nocturnal boundary layer is
  genuinely 100–250 m. That floor throws away the dominant winter signal.
- Capping amplification at 1.5× discards the rest of it. Uncapped, a 150 m PBL gives 8× enhancement;
  the code reports 1.5×. This is the single line most responsible for the broken feedback.
- Dropping the PM2.5 baseline to 15 µg/m³ is a summer number; Delhi's winter baseline is 5–10× higher.
- Returning `[]` from `_synthetic_hotspots()` with `FIRMS_API_KEY` unset means **there is currently
  no fire data of any kind.** Every plume list is empty, the map shows "No active fire hotspots",
  and `plume_contribution` is 0.0 for all 72 hours.

The trap: each change was locally sensible and made the dashboard look right on the day it was
made. Collectively they removed the physics being evaluated. Any further "make the numbers look
right in August" fix will make this worse.

**The way out is not to re-tune. It is to add a historical replay mode.** Open-Meteo's archive API
is free and needs no key; FIRMS has an archive endpoint. Pass a target date through the pipeline
and you can run the model on, say, 5 November 2025 — real inversion, real fires, real observed AQI
to compare against. That single change lets you demonstrate winter behaviour in August *and* gives
you the validation harness you currently lack. It is the highest-leverage five days of work
available.

---

## 4. Confirmed defects

Each of these was verified by executing the code path, not by inspection alone.

### 4.1 EPA breakpoint gaps return a false "Severe" — demo-breaking

`_BP_EPA` in `realtime_service.py` transcribes EPA tables as integer-bounded segments, leaving
numeric gaps between them (pm10 `54 → 55`, pm25 `12.0 → 12.1`, no2 `53 → 54`, and so on).
`_sub_index` falls through every segment and hits `return 500`:

| Pollutant | Concentration | Returned AQI |
|---|---|---|
| PM10 | 54.5 µg/m³ | **500 — "Severe"** |
| PM10 | 154.5 µg/m³ | **500 — "Severe"** |
| PM2.5 | 12.05 µg/m³ | **500 — "Severe"** |
| PM2.5 | 35.45 µg/m³ | **500 — "Severe"** |
| NO2 | 53.5 µg/m³ | **500 — "Severe"** |

A PM10 reading of 54.5 µg/m³ is clean air reported as maximum severity. Since AQI is the max over
sub-indices, one station landing in a gap turns that station dark red, and because
`fetch_city_overview` averages station AQIs, it drags the citywide number up too. This is live in
"EPA NowCast" mode in the sidebar right now. Fix by making segments continuous and clamping
above-range values rather than defaulting to 500.

### 4.2 Diurnal profile is shifted 5 hours

Open-Meteo is called with `timezone=Asia/Kolkata`, so returned timestamps are already IST. The code
then adds five more hours:

```python
hour_local = (dt.hour + 5) % 24  # IST offset
```

The result is that the morning rush multiplier (1.8×) is applied at 02:00–05:00, the evening peak
(2.0×) at 11:00–15:00, and actual rush hours get 1.0×. Only 2 of 24 hours are correct. Every
diurnal claim the dashboard makes is currently wrong by five hours. One-character-class fix: drop
the `+ 5`.

### 4.3 Plume emission constant is ~9 orders of magnitude too small

```python
Q = frp_mw * 50.0  # µg/s
```

1 MW of fire radiative power is 1 MJ/s; with a PM2.5 emission coefficient of ~0.015 kg/MJ that is
~1.5 × 10¹⁰ µg/s per MW, against the code's 5 × 10¹ µg/s. Computed contributions:

| FRP | Distance | σ_y | σ_z | PM2.5 contribution |
|---|---|---|---|---|
| 200 MW | 250 km | 16.3 km | 13.3 km | 3.97 × 10⁻⁶ µg/m³ |
| 1000 MW | 150 km | 11.0 km | 9.0 km | 4.36 × 10⁻⁵ µg/m³ |

The `min(C, 200.0)` saturation cap can never bind — it is roughly 10⁷ times above anything the
function can produce. So even with FIRMS enabled, stubble burning would contribute nothing
measurable. Note also that Pasquill-Gifford σ curves are calibrated to ~20 km and are being
extrapolated to 250 km, where they are not valid; a box or puff model is the appropriate choice at
that range.

### 4.4 Plume geometry ignores wind direction

`_advect_plume` correctly advects each hotspot forward using time-varying 850 hPa winds, and
`_arrival_time` correctly checks proximity to Delhi. But the concentration call throws that away:

```python
dist_to_delhi = _haversine(hs["lat"], hs["lon"], _DELHI_LAT, _DELHI_LON)
pm25 = _gaussian_concentration(hs["frp_mw"], dist_to_delhi, wind_speed)
```

It uses straight-line distance, so a fire whose plume blows *away* from Delhi contributes exactly
as much as one blowing toward it. The crosswind σ_y term is computed but no crosswind offset is
ever applied. The trajectory work is sound; it just is not connected to the dose calculation.

### 4.5 `docker-compose up` fails

`realtime_service.py` imports `cachetools`, which is absent from `requirements.txt`. The documented
one-command deploy will not start. `python-dotenv` is likewise missing (imported by
`test_openaq_live.py`). Also `Dockerfile.backend` runs `uvicorn --workers 2`, and the `TTLCache` is
per-process — two workers means two divergent caches and doubled OpenAQ traffic.

### 4.6 Smaller items

- **`ponytail:` appears in 8 comments** across six files (`inversion_engine.py`,
  `plume_advection.py` ×2, `aqi_service.py` ×2, `realtime_service.py`, `config.py`,
  `endpoints.py`). Clearly a botched find-and-replace. A judge reading the source will notice.
- **No git repository.** `git log` fails — five days of hackathon work with no version control and
  no way to revert a bad change.
- **The `test_*.py` files are not tests.** They are five manual print-and-eyeball scripts with no
  assertions on any physics. `test_accuracy.py` measures no accuracy; it prints ten stations.
  `test_scrape.py` still scrapes aqicn.org, contradicting `project_summary.txt`'s claim that all
  WAQI code was "completely purged." The absence of real tests is why §4.1 and §4.2 survived.
- **`POST /ingest/observation` does nothing.** It validates and returns 202; there is no
  persistence and no assimilation, despite "accepted for assimilation."
- **Docs contradict code.** `.env.example` says OpenAQ needs no key, but `_openaq_locations`
  raises `ValueError` without one. It also still documents a `WAQI_TOKEN` that no longer exists.
  `API.md` advertises `aqi_amplification_factor: 2.85` and a 2–4× severity table that the 1.5× cap
  makes unreachable, and omits the `base_aqi` parameter and all four `/realtime/*` endpoints.
- **`_state_from_coords` is wrong.** The first branch `if lon < 75.5: return "Punjab"` captures
  most of Rajasthan and Gujarat; the Haryana branch is partly unreachable.
- **Hardcoded "113"** in the dashboard caption (`Active Live Stations: {n} / 113`) is a magic
  number no longer derived from anything.
- **`min(aqi, 500)` is applied but never `max(aqi, 0)`** — harmless today, but the schema declares
  `ge=0`, so a negative product would 500 the endpoint rather than clamp.

---

## 5. The credibility risk — read this before fixing any code

`ARCHITECTURE.md` makes these specific quantitative claims:

> ±15–20% MAE vs CPCB stations · Persistence baseline ±35–40% MAE · captures ~80% of AQI variance
> · Calibration basis: Delhi IGI Airport radiosonde archive (2018–2023), SAFAR-IITM PBL measurements
> · feedback coefficients are calibrated to IGI Airport radiosonde data and SAFAR observational records
> · Full iterative convergence adds <2% accuracy improvement

I grepped the entire project for `MAE`, `backtest`, `validat`, `rmse`, `r2_score`, `archive`,
`era5`, and `historical`. **There is no validation code, no backtest, no error metric, and no
historical or reanalysis data access anywhere in the repository.** No radiosonde archive is
present or fetched. No SAFAR data is present or fetched. Nothing computes an MAE against anything.

Every one of those numbers is invented, and several are load-bearing: the "<2% improvement"
sentence is used to justify the single Picard iteration, and the "calibrated to radiosonde data"
comment justifies the `exp(-0.35·ΔT)` decay constant. The `0.35`, the `-35.0` W/m² per AOD, the
`0.4` feedback coefficient, and the `50.0` µg/s per MW are all unsourced free parameters presented
as calibrated values.

This is a larger risk to your score than any bug on this list. A bug is a bug; a fabricated
validation table is a credibility failure, and it is the first thing a domain judge will probe —
"show me your validation" has no good answer right now. Two of the claims are also
self-contradicting in ways a careful reader will catch: a model whose amplification is capped at
1.5× cannot reproduce the 2–4× behaviour `API.md` tabulates.

Delete the unsupported numbers today. Replace them with an honest statement of what is
parameterised and what is fitted. Then earn real numbers with a backtest — you have OpenAQ history
available and it is a day's work.

---

## 6. Scorecard against the problem statement

| Requirement | Status | Notes |
|---|---|---|
| 72-hour AQI outlook | **Met** | 72 hourly steps, correct structure, clean schema |
| Real-time dashboard, user-friendly | **Met** | Genuinely strong; live OpenAQ, map, gauge, timeline |
| Explicitly track inversion strength | **Met, damped** | ΔT / PBL / severity / amplification panel exists; values flattened by the 1.5× cap and 800 m floor |
| Delhi NCR focus | **Met** | Bbox-validated throughout |
| PM2.5, PM10, O3, NO2, SO2, CO sub-indices | **Met** | CPCB 2014 breakpoints correct in `aqi_service`; EPA variant broken (§4.1) |
| Met → chemistry link | **Partial** | Single scalar amplification; no dispersion of the urban field |
| Ground-level O3 modelled | **Partial** | `_photochemical_o3` is a solar×NOx heuristic, no photochemistry; overwrites rather than augments |
| Stubble plume dispersion | **Partial** | Trajectories are correct and drawn on the map; dose is ~10⁻⁶ µg/m³ and direction-blind. No fires at all with FIRMS key unset |
| Inversion × external spike interaction | **Not met** | The product of a capped 1.5× and a ~zero plume term is ~zero |
| Two-way meteorology ↔ chemistry feedback | **Not met** | Computes to exactly 0 whenever PBL ≤ 800 m; sign-inverted; no met field is altered or returned |
| Temperature and wind in the feedback loop | **Not met** | ΔT_surface computed then discarded; wind never responds to chemistry |
| High-resolution | **Not met** | Single-point model at ~11 km driving data; no grid, no downscaling, no spatial AQI field |
| WRF-Chem or similar coupled framework | **Not met** | Not used. Defensible as a deliberate trade-off *if* stated plainly |

Roughly: the dashboard and observational pipeline are strong, the diagnostics are present but
muted, and the coupled-physics core — the actual subject of the problem statement — is not
currently working.

---

## 7. Remediation log

This section replaces the five-day plan that used to sit here. The plan was
superseded: the work was not staged across days, it was carried out in one pass,
so a schedule would be a fiction. What follows is what actually changed, keyed to
the finding it closes.

### 7.1 The central finding (§2) — the feedback now computes something

The four-line mismatched subtraction is gone. `aqi_service._solve_coupled_hour`
now solves each hour as a genuine fixed point:

```
h  ──▶  box_model.step on a CLONE  ──▶  PM2.5  ──▶  AOD  ──▶  ΔSW  ──▶  ΔT_sfc
                                                                          │
        h_new = pbl_from_stability(h_baseline, ΔT_sfc) ◀────────────────────┘
        under-relax by 0.6, repeat until |Δh| < 1 m, then commit ONE real step
```

Both sides of the comparison come from `pbl_from_stability()`, which is the
identity map at zero cooling — so the baseline and perturbed depths are produced
by the same function and their difference is a feedback signal rather than the
disagreement between two parameterisations. Picard iteration with 0.6
under-relaxation, 1 m tolerance, cap of 12; typical cost is 1–6 iterations.

The audit's specific complaints, each closed:

| §2 complaint | Now |
|---|---|
| `extra_amp` is exactly 0 whenever PBL ≤ 800 m | The 1.5× cap is no longer on the mechanism at all — concentration comes from a prognostic mass budget, not a multiplier |
| Feedback strongest in clean air, zero in dirty air | Reversed and measured: +2.2% PM2.5 in August, +6.0% in a November episode (`scripts/verify/attrib.py`) |
| Shortwave cooling applied at 02:00 | `shortwave_reduction` multiplies by the actual incoming flux, so it returns exactly 0.0 at night. Night-time feedback now arrives through an 8-hour surface thermal memory instead, which is the physical route |
| `dt_surface` computed then discarded | Returned as `aerosol_dt_surface_c`, alongside `pbl_height_met_m`, `pbl_suppression_pct`, `aerosol_optical_depth`, `aerosol_sw_forcing_w_m2` and `feedback_iterations`, and plotted on the dashboard |
| `pbl_height_m` was the synthetic fallback, not a modified observation | `pbl_height_m` is the post-feedback depth and `pbl_height_met_m` the unperturbed met value, so the suppression is visible as a difference between two returned numbers |

Also replaced, and not on the original list: the steady-state
`emissions × amplification` formulation itself. It cannot represent accumulation —
it gives the same answer at hour 1 and hour 9 of an inversion. The state variable
is now column mass in a two-reservoir column (mixed layer + residual layer), so a
persistent lid accumulates, a collapsing lid strands mass aloft, and a growing lid
entrains it back down as the observed morning fumigation peak. That path
dependence is the thing the problem statement is actually about.

### 7.2 The seasonal de-tuning trap (§3) — undamped, not re-tuned

All four damping changes were removed rather than adjusted:

- The `max(pbl, 800.0)` floor is gone. The floor is now `PBL_MIN_M = 150.0`, which
  is a physical limit (below that a uniformly-mixed box stops meaning anything),
  not a seasonal fudge.
- The 1.5× amplification cap survives only as a *reported diagnostic* bounded to
  [0.25, 6.0]. Nothing multiplies a concentration by it.
- The hardcoded summer PM2.5 baseline is now a CPCB monthly climatology, so August
  and November differ because the month differs.
- `_synthetic_hotspots()` was deleted outright rather than left returning `[]`. No
  FIRMS key means an empty hotspot list and a dashboard that says so.

`scripts/verify/calib.py` is the check that the de-tuning did not come back:
August PM2.5 19/28/41 µg/m³ (min/mean/max) with AQI 46–127; November 96/221/342
with AQI 220–437. The seasonal contrast is now produced by the model rather than
edited into it, and nothing saturates at AQI 500.

The audit's recommendation of a historical replay mode is **not implemented**. It
remains the right next move and the honest statement is that it is absent — see
§7.6.

### 7.3 Confirmed defects (§4) — all closed

| Finding | Fix |
|---|---|
| §4.1 EPA gaps return a false 500 "Severe" | Segments made continuous; above-range values clamp to 500 instead of falling through to it. EPA results are labelled with EPA category names, since EPA breaks at 150 and CPCB at 200 — the two tables are not interchangeable |
| §4.2 Diurnal profile shifted 5 hours | `+ 5` removed. Open-Meteo is queried with `timezone=Asia/Kolkata`, so the hour is already IST; the docstring now says so to stop it being re-added |
| §4.3 Plume emission ~9 orders of magnitude too small | Replaced with the standard FRP chain: 0.368 kg dry matter/MJ (Wooster 2005) × 8.5 g PM2.5/kg (Andreae & Merlet, crop residue) = 3.13 g/s per MW. Dispersion switched to `max(Pasquill-Gifford, Heffter 1965)` because P-G extrapolated to 300 km gives a 9 km plume and makes an entire burning region invisible |
| §4.4 Plume geometry ignores wind direction | Dose is computed from the advected trajectory's closest approach, projected onto each hourly *segment* rather than sampled at waypoints. Verified: 328 µg/m² aimed at Delhi, 0.0 blowing away, 0.0 perpendicular |
| §4.5 `docker-compose up` fails | `cachetools` and `python-dotenv` added to `requirements.txt`; `--workers 1` set with the reason in a comment |
| §4.6 `ponytail:` in 8 comments | All replaced |
| §4.6 No git repository | Initialised; baseline committed before any fix so every change is revertable |
| §4.6 `test_*.py` are not tests | Moved to `scripts/manual/` under honest names (`check_*.py`), and `test_scrape.py` deleted along with the WAQI scraping it did. Real assertions live in `backend/tests/` and `scripts/verify/` |
| §4.6 Docs contradict code | `.env.example`, `README.md`, `API.md`, `ARCHITECTURE.md` and `project_summary.txt` rewritten; `WAQI_TOKEN` and the "no key needed" claim for OpenAQ removed; the three dead knobs (`RATE_LIMIT`, `REDIS_URL`, `SECRET_KEY`) deleted with a note saying nothing read them |
| §4.6 `_state_from_coords` is wrong | Rewritten as priority-ordered rectangles that return "Unknown" instead of guessing "UP" |
| §4.6 Hardcoded "113" | Removed; the denominator is whatever was actually returned |
| §4.6 `min(aqi, 500)` without `max(aqi, 0)` | Both bounds applied |
| §4.6 `POST /ingest/observation` does nothing | Still does nothing — but it no longer claims otherwise, in `API.md` or `SECURITY.md` |

Seven further defects surfaced during the documentation pass and were fixed at the
same time, none of them in the original audit: `.env` was resolved relative to the
working directory rather than the file, so launching uvicorn from the repo root
loaded no configuration; `pydantic-settings` defaulted to `extra="forbid"`, so a
single unrelated line in `.env` took the whole backend down on the first request;
the API key was compared with `==`, which leaks it to a timing attack; a
placeholder key was accepted as valid, meaning any deployment that forgot to set
`APP_API_KEY` trusted a credential published in `.env.example`; `script-src 'self'`
blocked Swagger UI's CDN bundle, so `/docs` rendered blank while two documents told
the reader to open it; the Redis container exposed a port for a service nothing
connected to; and `__all__` in `schemas/forecast.py` named a class that does not
exist, which would have raised `AttributeError` on any star-import.

### 7.4 The credibility risk (§5) — every fabricated number deleted

The invented figures (±15–20% MAE, ±35–40% persistence baseline, ~80% of variance,
"calibrated to IGI Airport radiosonde archive 2018–2023", "SAFAR-IITM PBL
measurements", "<2% accuracy improvement") are gone from `ARCHITECTURE.md`,
`API.md` and the source comments that carried them.

They were not quietly removed. Each document now names the claim it used to make
and says it was invented — a deletion is invisible in a diff-less read, and a judge
who saw an earlier copy deserves an explanation rather than a silent correction.

`ARCHITECTURE.md` now opens with: no error figure is quoted anywhere in this
document, the constants are hand-set to reproduce the order of magnitude and
diurnal shape of CPCB climatology, and any MAE or R² claim about this system would
be fabricated unless produced by code in `backend/tests/` or `scripts/verify/`
against data the model never saw.

The verification that does exist is behavioural, and is labelled as such in every
file that mentions it: `calib.py` (diurnal and seasonal shape), `attrib.py`
(feedback strength by disabled-leg counterfactual), `plumecheck.py` (emission
chain, σy growth, direction-awareness, segment-aware closest approach, FIRMS
parsing for both VIIRS and MODIS layouts), `windcheck.py` (the wind sign
convention end to end, including three prescribed-wind trajectories). Each runs
from any working directory and exits non-zero on failure. **None of them measures
accuracy.** The correct answer to "what is your MAE" is still "we have not measured
it", and that sentence is now written in `README.md` and `ARCHITECTURE.md` rather
than being something a judge has to extract.

### 7.5 Re-scored against the problem statement

Changes from §6 in bold.

| Requirement | Was | Now |
|---|---|---|
| 72-hour AQI outlook | Met | Met |
| Real-time dashboard | Met | Met |
| Track inversion strength | Met, damped | **Met** — 800 m floor and 1.5× cap removed, so winter values express |
| Delhi NCR focus | Met | Met |
| Six-pollutant sub-indices | Met | Met — EPA variant fixed |
| Met → chemistry link | Partial | **Met** — prognostic column with entrainment, stranding and wind-dependent ventilation, not a scalar |
| Ground-level O3 | Partial | Partial — still a diagnostic, not a photochemical mechanism. It is no longer a bare solar × NOx product: it is regional background + in-situ production − NO titration, and it reads the *post-aerosol* shortwave flux, so smoke suppresses ozone and a collapsing lid raises PM2.5 and destroys O3 at the same time. There is nothing for it to overwrite — the box model deliberately does not carry O3, whose lifetime is too short and which is produced in situ rather than emitted |
| Stubble plume dispersion | Partial | **Met** — literature emission chain, direction-aware dose, elevated-background coupling, counterfactual attribution |
| Inversion × external spike interaction | Not met | **Met** — measured at +6.8% PM2.5 / +10 AQI daily mean / +18 max hourly ΔAQI for a November episode with a plume |
| Two-way met ↔ chemistry feedback | Not met | **Met** — closed fixed point, six diagnostic fields returned, plotted |
| Temperature and wind in the loop | Not met | **Met** — ΔT_surface is computed, returned and plotted, and feeds back through the PBL. The wind leg is now closed as well (`inversion_engine.wind_perturbation` + a lagged wind memory in the integrators): dimming cools the surface, the boundary layer stabilises, the 10 m wind drops, and the box model ventilates more slowly — raising PM2.5. Pinned differentially in `backend/tests/test_wind_feedback.py` |
| High-resolution | Not met | **Not met** — single column. Unchanged and stated plainly |
| WRF-Chem or similar | Not met | **Not met** — deliberate trade-off, stated plainly in three documents |

### 7.6 What is still open

Named here so nothing on this list has to be discovered by a judge.

1. **No accuracy measurement.** No backtest against withheld observations exists.
   This is the largest remaining gap and the audit's §3 recommendation — historical
   replay via Open-Meteo's archive API and the FIRMS archive — is still the way to
   close it, since it would unlock both a winter demo in August and a validation
   harness in one change.
2. **No spatial field.** One column for the whole NCR. The map interpolates live
   station observations; it does not display a forecast field, because there is not
   one to display.
3. **No gas-phase chemistry.** O3 is diagnosed, not solved. NOx, SO2 and CO are
   transported and deposited but do not react with each other.
4. **Ingestion is a no-op.** `POST /ingest/observation` validates and returns 202.
   There is no store and no assimilation.
5. **Emission fluxes are hand-set.** `box_model.SPECIES` carries scalar fluxes
   chosen to reproduce climatological magnitude, not a gridded inventory.
6. **Single-process state.** Response cache and rate limiter are both in-memory,
   which is why `--workers 1`. Moving both to Redis is the prerequisite for scaling
   out, and Redis is currently not in the stack at all.

### 7.7 The regression suite, and the three defects it exposed

The behavioural scripts in §7.4 check that the physics is alive; they do not pin
its edges. A proper unit suite now lives in `backend/tests/` — **149 assertions
across six files**, run by `python backend/tests/run_without_pytest.py` (an
`importlib` runner, because `pip install pytest` cannot reach the index from this
sandbox; the files are ordinary `test_*.py` and run under real pytest unchanged):

| File | Tests | What it pins |
|---|---:|---|
| `test_aqi_scales.py` | 16 | CPCB/EPA breakpoint tables, the EPA gap-truncation that used to return a false "Severe", CPCB contiguous-bounds deviation and its measured 4-AQI-point cost |
| `test_box_model.py` | 24 | Exact mass conservation on lid collapse, path dependence, ventilation, the "a collapsing lid is not a piston" invariant, plume-as-background |
| `test_coupling.py` | 20 | The four two-way-feedback claims of §2, differentially against the no-feedback counterfactual; the Picard loop commits exactly one step to the budget |
| `test_diurnal_seasonal.py` | 21 | No IST double-offset (rush at 07–10/17–22, not 02:00), PM not collapsing overnight like traffic, November ≈ 3.3× August at identical meteorology |
| `test_inversion_kernels.py` | 33 | Severity bands incl. the boundary, the shortwave term exactly zero at night, surface-memory decay, the sign trap in `pbl_from_stability` |
| `test_plume.py` | 35 | FRP chain (3.13 g/s/MW), wind sign convention end to end, FIRMS parsing by header for VIIRS *and* MODIS, segment-aware closest approach |

Writing the suite is what turned up the following, none of which was in the
original audit and one of which the audit's own remediation had **wrongly reported
as fixed**:

| Finding | Fix |
|---|---|
| `inversion_present` disagreed with `severity` at exactly the threshold. The flag was recomputed as `delta_t > weak` while `_classify_inversion` treats the band as inclusive (`delta_t < weak → "None"`), so ΔT = 1.5 rendered a "Weak" badge with the flag `False`. Live-facing via `frontend/app.py`. | The flag is now *derived* from `severity` (`severity != "None"`), so the whole class of disagreement is impossible |
| `_state_from_coords` never actually returned "Unknown". §7.3 above recorded it as "rewritten to return 'Unknown' instead of guessing", but the rectangles were open to the south and west, so `(0, 0)` came back "Rajasthan" and `(28.6, 90)` came back "Uttar Pradesh". Worse, the Punjab/Haryana split was a latitude step, not the real diagonal border, so Sangrur, Patiala and Barnala — three of the highest fire-count districts in the country — were labelled Haryana, while Sriganganagar and Hanumangarh (the exact Punjab-vs-Rajasthan mislabel §4.6 claimed to have closed) were labelled Punjab. | Rajasthan is now claimed first, the PB/HR border is a diagonal, and a source-bbox guard makes the "Unknown" contract true. Correct on all 35 interior-district test points; the earlier claim in §7.3 was aspirational and is corrected here rather than left standing |
| Dead `import statistics` in `realtime_service.py` (never referenced) | Removed, along with the now-unused `math` import left behind by the `aqi_scales` extraction |

Two stale docstrings were also corrected in place: `_gaussian_concentration`
claimed to feed the API's per-plume display value, but nothing calls it
(`compute_plume_vectors` divides the column loading by the layer depth itself); and
the vertical-trapping comment cited a ~30 km crossover where the arithmetic gives
7.9 km. Neither changed behaviour — but a comment that misstates the code is the
seed of the next §5, so both were fixed while the tests were open on them.

One structural change made the suite possible at all: the pure scale arithmetic
was extracted to **`app/domain/aqi_scales.py`** (no third-party imports), and
`realtime_service` re-exports it under the original names so every call site is
unchanged. Before this, `_sub_index` — the function that reported clean air as
"Severe" for months — could not be imported for testing without `httpx` and the
whole HTTP stack. It now tests on the standard library alone.

### 7.8 The live boot, and the defect only a live anchor could reveal

Everything above was verified without a network: the 149-test suite and the four
`scripts/verify` harnesses run on the standard library, and the sandbox cannot
`pip install` or reach the live upstreams. To close that last gap the system was
booted for real elsewhere — actual `pydantic`/`httpx`/`fastapi`, `uvicorn` up,
`/api/v1/forecast/72hr` hit against live Open-Meteo and a live OpenAQ anchor. It
booted clean, returned 72 hours with every coupling field populated, no
AQI-500 saturation, feedback converging in 1–6 iterations — the physics held on
live data exactly as the offline checks predicted.

But the live run exposed one defect that **no offline test could have caught**,
and the reason it was invisible is the interesting part. The hour-0 observational
nudge — which biases the opening of the forecast toward the live station reading —
lived entirely inside `build_72h_forecast`, an `async` function that calls
Open-Meteo, so no unit test touched it; and it is a no-op (`scale = 1.0`) whenever
no live anchor is supplied, which is the regime every test and every harness runs
in. So the bug sat in a blind spot that was blind in two independent ways at once.

The defect: the nudge multiplied the **headline AQI** by its correction weight but
left the concentrations and their sub-indices raw. CPCB AQI is *defined* as
`max(sub-indices)`, so with a live anchor present the headline and its own
breakdown disagreed — the live hour 0 reported **AQI 64 over a PM2.5 sub-index of
~158**, a green gauge sitting above orange pollutant bars, and `aqi != max(sub-indices)`
in the response contract.

The fix moves the correction into **concentration space**: solve for the column
scale that reproduces the observed AQI (`_conc_scale_for_target_aqi`, a bisection —
AQI is monotone in a uniform scale), apply it with the same e-folding decay, then
derive AQI, sub-indices and the dominant pollutant from the *same* corrected
concentrations. `aqi == max(sub-indices)` now holds by construction. The
photochemical O3 diagnostic is deliberately **not** scaled — it is set from
shortwave each hour, not accumulated as a load the station reading constrains.

`test_hour0_nudge.py` (10 assertions, a **seventh** file — the suite is now **159
tests**) pins the invariant and the extracted helpers, so the nudge math is no
longer untestable behind an async network call. The no-anchor path is provably
untouched: `calib.py` and `attrib.py` print numbers identical to §7.4 to the last
digit, because `scale = 1.0` makes `_scale_conc` the identity.

---

## Appendix — one housekeeping note

`OPENAQ_API_KEY` in `.env` is a live key. `.gitignore` correctly excludes `.env`, so it is not at
risk of being committed — but since the file was read during this audit, rotating it is cheap
hygiene. It is a free read-only key, so the exposure is low.
