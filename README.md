# Delhi NCR AQI Forecasting System

> **72-hour coupled AQI forecast** for Delhi NCR: a prognostic two-reservoir column
> model driven by live meteorology, with real aerosol→radiation→boundary-layer
> feedback and NASA FIRMS stubble-plume transport, behind a live station dashboard.

## What it does

- 🌡️ **Inversion engine** — ΔT = T(925 hPa) − T(1000 hPa), lapse rate, severity bands, and the resulting suppression of mixing depth
- 📦 **Prognostic column model** — mixed layer + residual layer with an explicit mass budget, so a lid that holds overnight actually accumulates pollution and a collapsing lid strands mass aloft
- 🔄 **Two-way coupling** — PM2.5 → AOD → surface shortwave loss → cooling → shallower boundary layer → higher PM2.5, closed by Picard iteration and reported hour by hour. The loop also reaches the wind: cooled, stabilised air mixes momentum down more slowly, the surface flow weakens (capped at −30%), and ventilation lengthens — reported per hour as `wind_effective_ms` and rendered as the coupling loop's final node
- 🔥 **Plume transport** — NASA FIRMS detections, FRP-derived emissions, hourly 850 hPa trajectories, and smoke attribution by a no-smoke counterfactual run
- 📊 **CPCB AQI** — official 2014 sub-index methodology for PM2.5, PM10, O3, NO2, SO2, CO (US EPA breakpoints + NowCast available for the live panel)
- 🖥️ **Operator console** — a React front-end at `/console` with a 72-hour scrubber over an atmosphere cross-section, the two-way coupling loop, the stubble-plume map, and the live station grid; falls back to a clearly-labelled synthetic sample when the live forecast is unreachable
- 🔒 **Hardened** — API-key auth on mutation, per-endpoint rate limits, strict CSP, non-root containers
- 🐳 **One-command deploy** — `docker-compose up`

**What it is not:** there is no horizontal grid, no advection of the urban pollutant
field, no gas-phase chemical mechanism, and no WRF-Chem. It is a single-column
surrogate, chosen so the forecast returns in seconds against live data. Its accuracy
against CAMS reanalysis is measured and reported below; accuracy against CPCB
ground truth is quantified by the archived-window endpoint `/api/v1/validation/cpcb`
but not yet pooled over a full seasonal cycle.

---

## Quickstart

### Prerequisites
- Docker ≥ 24.0 and Docker Compose ≥ 2.20
- Two free API keys (see below). Both are issued instantly and neither costs anything.

### 1. Clone & configure

```bash
git clone <repo-url> delhi-aqi
cd delhi-aqi
cp .env.example .env
```

Edit `.env`:

```bash
APP_API_KEY=your-strong-random-key-here     # python -c "import secrets; print(secrets.token_urlsafe(32))"
OPENAQ_API_KEY=your-openaq-key              # https://explore.openaq.org/register
FIRMS_API_KEY=your-nasa-firms-key           # https://firms.modaps.eosdis.nasa.gov/api/area/
```

Both data keys are **required for the features that depend on them**, and the code
degrades honestly rather than inventing data:

- Without `OPENAQ_API_KEY`, every `/realtime/*` endpoint returns `502` — OpenAQ v3
  rejects unauthenticated requests, and only the retired v2 API was open.
- Without `FIRMS_API_KEY`, `/plume/vectors` returns an **empty** hotspot list and the
  dashboard says so. There is no synthetic fire generator; one existed and was
  deleted, because fabricated detections on a map are indistinguishable from
  observations to whoever is reading the screen.

### 2. Launch

```bash
docker-compose up --build
```

Wait ~60 s for the backend healthcheck, then open:

| Service | URL |
|---------|-----|
| **Console** (React) | http://localhost:8000/console — also where `/` redirects |
| **Dashboard** (Streamlit) | http://localhost:8501 |
| **API docs** | http://localhost:8000/docs |
| **Health check** | http://localhost:8000/api/v1/health |

The console is built inside the backend image (a Node stage compiles `webapp/`, the
runtime stage serves the static bundle at `/console`) and is same-origin with the API,
so it needs no CORS or extra service. The Streamlit dashboard remains available in
parallel.

### 3. Stop

```bash
docker-compose down
```

---

## Local Development (no Docker)

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Terminal 1 — backend
cd backend
uvicorn app.main:app --reload --port 8000

# Terminal 2 — Streamlit dashboard
cd frontend
streamlit run app.py --server.port 8501

# Terminal 3 — React console (optional; hot reload)
cd webapp
npm install
npm run dev                     # http://localhost:5173/console/  (proxies /api → :8000)
```

`.env` is located relative to the source tree, not the working directory, so the
backend finds it from either directory.

The React console can be run two ways: `npm run dev` for hot reload during development
(URL above), or `npm run build` to emit `webapp/dist`, which the backend then serves at
`http://localhost:8000/console`. See [webapp/README.md](webapp/README.md) for the
frontend's architecture and the constraints it enforces (AQI = max of sub-indices; no
fabricated accuracy figures; sample data always labelled).

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `APP_API_KEY` | Yes | Key for `POST /ingest/*` (X-API-Key header). Ingestion returns `503` while it is unset or still the placeholder |
| `ALLOWED_ORIGINS` | Yes | Comma-separated frontend origins for CORS |
| `OPENAQ_API_KEY` | Yes | Live station readings. `/realtime/*` returns `502` without it |
| `FIRMS_API_KEY` | For plume | Fire detections. Hotspot list is empty without it — never synthetic |
| `APP_ENV`, `APP_DEBUG` | No | Cosmetic; no behaviour is gated on these yet |

Open-Meteo needs no key, so the forecast and inversion endpoints work with none of
the above set.

---

## Project Structure

```
backend/app/
  main.py                    FastAPI app, CORS, security headers, /console static mount
  core/
    config.py                pydantic-settings env config
    security.py              API-key auth, CSP / secure headers
  physics/
    inversion_engine.py      ΔT, lapse rate, PBL suppression, aerosol radiative terms
    box_model.py             two-reservoir prognostic mixed/residual layer
    plume_advection.py       FIRMS ingest, hourly trajectories, column loading
  schemas/forecast.py        Pydantic I/O models
  services/
    aqi_service.py           72 h integration, Picard feedback loop, CPCB sub-indices
    realtime_service.py      OpenAQ v3 stations, CPCB + EPA AQI, TTL cache
  api/v1/endpoints.py        routes, rate limits
frontend/app.py              Streamlit dashboard (map, 72 h outlook, feedback, plume)
webapp/                      React operator console — served by the backend at /console
  src/                       components, hooks, lib (see webapp/README.md)
  public/sample-forecast.json  labelled synthetic fallback bundle
frontend-web/                the vanilla HTML/CSS prototype the console was ported from
scripts/
  verify/                    physics verification scripts (see below)
  manual/                    live-API smoke checks; not part of the test suite
```

---

## Verification

The physics is checked by scripts that print numbers you can argue with, not by
assertions of accuracy:

```bash
python scripts/verify/calib.py       # seasonal box-model behaviour, Aug vs Nov
python scripts/verify/attrib.py      # feedback strength with and without smoke
python scripts/verify/plumecheck.py  # plume emissions, geometry, monotonicity
python scripts/verify/windcheck.py   # wind convention and trajectory direction
```

### Measured accuracy (hindcast validation)

The forecast is scored by a leak-free backtest: 72-h windows anchored ≥3 days in
the past, driven by analysis meteorology, with the production physics integrator
and the ML model, plume transport and observational nudging switched off for
documented anti-leakage reasons (see `backend/app/services/backtest_service.py`).
Truth is CAMS reanalysis PM2.5 — an independent upstream from the meteorology feed.

Pooled over 4 windows (Aug 18 – Sep 4, 2026, 288 hours):

| Metric | Value |
|---|---|
| MAE | **24.96 µg/m³** (95% CI 22.8–26.8, paired bootstrap) |
| RMSE / Pearson r | 31.4 µg/m³ / 0.31 |
| MAE skill vs persistence | **+0.031** (beats "next 72 h = now") |
| +6 h lead | MAE 11.7 µg/m³, r 0.62 |

Caveats, stated plainly: CAMS is a reanalysis, not a surface network, so these
figures quantify skill against CAMS rather than against CPCB ground truth; the
window set covers the monsoon only, and the winter regime the forecast exists for
should be re-validated in November. The backtest already paid for itself by
catching a 50% monsoon background-calibration error, now fixed.

Live: `GET /api/v1/validation/backtest` (computed at startup, cached 6 h) and the
Validation Badge in the console. Full details:
[PROBLEM_STATEMENT_COMPLIANCE.md](PROBLEM_STATEMENT_COMPLIANCE.md).

---

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — physics, coupling loop, data flow, scope limits
- [API.md](API.md) — REST endpoint reference with cURL examples
- [SECURITY.md](SECURITY.md) — threat model and deployment hardening
- [AUDIT.md](AUDIT.md) — the code audit that drove the current round of fixes, with a remediation log
