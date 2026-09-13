# Build the production frontend for the Delhi-NCR coupled AQI forecast

You are working in the repository at `D:\SIH`. A previous agent built and audited the
backend (FastAPI physics service) and a vanilla HTML/CSS prototype of the console. Your
job is to build the **real, production frontend as a React app** and wire it to the
backend. You have npm access and a component-generator MCP (shadcn and/or 21st.dev
Magic); use them. This is a handoff — read before you write.

## 0. Read these first (do not skip)

Read these files in full before writing any code. They encode decisions you must not
re-derive or contradict:

- `frontend-web/index.html` — the **complete design structure and copy** of the console. Port this to React; do not invent new sections or new wording. Every heading, lede and footer paragraph here was written to be factually honest — reuse the text verbatim.
- `frontend-web/styles.css` — the **design system**: color tokens, the CPCB AQI color ramp, typography scale, responsive breakpoints (1080px, 720px), and the full `prefers-reduced-motion` handling. Port these tokens into your Tailwind theme / CSS variables. Do not restyle from scratch.
- `frontend-web/sample-forecast.json` — a **real payload** you will bind to and fall back to. Open it to see the exact data shape. It is genuine model output over synthetic weather, badged as sample — never present it as a real forecast or an accuracy figure.
- `backend/app/schemas/forecast.py` — the **API contract** (field names, types, ranges). Generate your TypeScript types from this.
- `backend/app/api/v1/endpoints.py` — the endpoints and their query params.
- `backend/app/core/config.py` — CORS `allowed_origins` (currently only `http://localhost:8501`).
- `backend/app/main.py` — where you will mount the built app.
- `AUDIT.md` — the project's ethos, especially the "what this model is / is not" framing. Absorb the honesty rules; they are load-bearing.
- `README.md` — how to run the stack.

## 1. What the product is (so your microcopy is accurate)

A 72-hour air-quality forecast for Delhi NCR. Its differentiator is **two-way coupling**:
polluted air is not just a passive result of shallow, stagnant weather — the aerosol
dims the surface, cools it, and makes the boundary layer shallower still, concentrating
the pollution further. Each forecast hour is solved as a **fixed point** (Picard
iteration, 0.6 under-relaxation, max 12 iterations), so the meteorology and chemistry are
mutually consistent, not sequential guesses. Stubble-fire smoke from Punjab/Haryana is
transported on the 850 hPa wind; its contribution is measured as the **difference between
two full model runs** (with and without the fires), not by subtracting a plume's own
concentration.

The headline AQI follows **CPCB National AQI (2014): AQI = max(sub-indices)**, never an
average. Category thresholds are 50/100/200/300/400/500 (Good, Satisfactory, Moderate,
Poor, Very Poor, Severe).

## 2. Tech stack

- **Vite + React 18 + TypeScript.** Build in a new folder: `D:\SIH\webapp`. Leave `frontend-web` (the vanilla prototype) and the Streamlit app untouched.
- **Tailwind CSS + shadcn/ui**, set up via shadcn's official Vite guide. Pin a Tailwind version that builds cleanly with your shadcn version.
- **Framer Motion** for animation (entrance reveals, number count-ups, scrub transitions). Everything must be gated behind `prefers-reduced-motion`.
- **lucide-react** for icons. **IBM Plex Mono** for all data/numerals/labels, **IBM Plex Sans** for prose, **IBM Plex Sans Condensed** where the prototype uses it (already loaded via Google Fonts in `index.html`).
- Hand-rolled **SVG and Canvas** for the signature visualizations. Do **not** use a charting library for the atmospheric cross-section or the plume map — they are bespoke.

## 3. How to use the component-generator MCP

- Use the **shadcn MCP** (or `npx shadcn@latest init` then `add`) for the accessible primitives you actually need: `button`, `card`, `tabs` (scenario switcher), `tooltip`, `skeleton` (loading), `badge`. The MCP and the CLI produce identical output; if no MCP is connected, the CLI is fine.
- Use **21st.dev Magic** (`/ui`) only for generic chrome if you want a faster start. Magic needs a 21st.dev API key.
- Do **not** expect any generator to produce the signature pieces. The **atmospheric cross-section, the coupling-loop diagram, and the NW-India plume map are hand-coded** — that is where the "built by the best team" quality has to come from, and it is exactly what a component generator cannot make. Generators are for the chrome around them.

## 4. Design direction: "atmospheric instrument"

Dark haze-blue ground, the feel of a scientific instrument, not a SaaS dashboard. The
signature element is a **vertical cross-section of the atmosphere across 72 hours**.

Port these tokens from `styles.css` (full set is there; core shown here):

- Grounds: `--abyss #070C12`, `--deep #0A1119`, `--slab #0F1922`, `--slab-hi #14212C`
- Hairlines: `rgba(140,163,182,.13)` / `.26`
- Text: `--bone #E9F0F6`, `--mist #8CA3B6`, `--mist-dim #5C7183`
- **CPCB AQI ramp (the only saturated color on the page):** `#4FB477` `#9FC93C` `#EFC02D` `#F2892F` `#E8503C` `#C0356A` for Good → Severe. (Severe is pushed toward magenta on purpose; CPCB's maroon is illegible on this ground.)

Rules that keep it from looking templated:

- The AQI ramp is the **only** saturated color. Fire hotspots reuse the ramp's orange. Everything else is the blue-grey scale.
- **No radial gauge**, no generic "big number in a colored circle." The hero is a large monospace numeral with its sub-indices beside it; the *instrument* is the cross-section.
- One signature element, done exceptionally, beats five decorated cards. The signature is the cross-section.
- Intentional typography and generous negative space. Data in mono, prose in sans.
- Consider reading the `frontend-design` skill if available for more on avoiding templated defaults.

## 5. Screens and components (port the structure from `index.html`)

1. **Instrument rail** (top): brand, three upstream feed LEDs (open-meteo / openaq / firms) reflecting live status, timestamp, refresh.
2. **Sample-data banner**: hidden normally; shown, impossible to miss, when running on `sample-forecast.json`, with a scenario switcher (November episode / August monsoon).
3. **Hero readout**: station + coords, giant AQI numeral, category, dominant pollutant, valid time, lead time; and the CPCB sub-index list (index + concentration per pollutant). Footnote: the headline is the *maximum* sub-index, not an average.
4. **Signature — the atmosphere** (the centerpiece): a single SVG holding both the cross-section **and** the AQI ribbon on a shared x-axis so they can never drift out of alignment. The cross-section shows: the mixed-layer slab following `pbl_height_m`; a hatched "depth removed by aerosol" band between `pbl_height_met_m` (met-model depth) and `pbl_height_m` (coupled, shallower) — **this band is the visual of the two-way coupling and is the most important mark on the page**; per-hour haze density tracking PM2.5 concentration; inversion ticks colored by severity. Below it, the 72-bar AQI ribbon colored by the ramp.
5. **72-hour scrub interaction**: dragging anywhere on the field, plus keyboard (←/→ = 1 hour, PgUp/PgDn = 6, Home/End), moves a cursor that drives **every readout on the page**. Add an autoplay "Sweep 72 h" and a "Now" button. Keep it 60fps (split static render from cursor render). The SVG is `role="slider"` with proper aria values.
6. **Cursor-driven readouts**: mixing depth (with met-model depth), depth removed %, column AOD, surface shortwave forcing (W/m²), wind (m/s + direction at 850 hPa), ΔT 925–1000 hPa with inversion state.
7. **Coupling / feedback loop panel**: PM2.5 → AOD → shortwave withheld → surface cooling → shallower mixing depth → back to PM2.5, showing the Picard iteration count to converge. Include the note about the night-time thermal-memory term keeping the loop closed when shortwave is zero (text is in `index.html`).
8. **Inversion strip**: a compact 72-hour strip of ΔT between 925 and 1000 hPa, plus stats (ΔT now, severity, lapse rate, hours with a lid).
9. **Plume map** (Canvas, no tile server): a bespoke map over roughly lon [73.6, 78.4] × lat [27.9, 31.7] with a graticule, the Punjab/Haryana divider drawn from the repo's own geometry (`lat = 29.90 − 0.353·(lon − 75.20)`), Delhi rings, fire hotspots sized by √FRP in the ramp's orange, fading trajectories, and an 850 hPa wind arrow. Stats: detections, share of AQI now, peak share, wind.
10. **Live station grid**: CPCB stations via OpenAQ, worst-first, each with AQI/category/color.
11. **Footer**: the "what this model is / what it is not / interfaces" columns — copy verbatim from `index.html`.
12. **Boot overlay**: staged loading (reach api → meteorology + coupled column → inversion → fire → stations) since the forecast is a real multi-second integration.

## 6. Data layer

- Endpoints (all under `/api/v1`): `GET /forecast/72hr?lat&lon&station_name&base_aqi`, `GET /inversion/status`, `GET /plume/vectors`, `GET /health`, `GET /realtime/overview`, `GET /realtime/stations`, `GET /realtime/station/{uid}`.
- Generate TypeScript types from `schemas/forecast.py`. Key object `HourlyForecast` has: `timestamp, aqi, category, dominant_pollutant, sub_indices[{pollutant, concentration, sub_index, category}], pbl_height_m, inversion_delta_t, wind_speed_ms, wind_direction_deg, pbl_height_met_m, pbl_suppression_pct, aerosol_optical_depth, aerosol_sw_forcing_w_m2, aerosol_dt_surface_c, feedback_iterations, plume_contribution`.
- **Dev:** configure a **Vite proxy** so `/api` → `http://localhost:8000` (avoids CORS in dev).
- **Fallback:** copy `frontend-web/sample-forecast.json` into `webapp/public/`. Fetch the live endpoints with `AbortController` timeouts (~60s for the slow forecast). On any failure, load the sample, show the "Sample data" banner + scenario switcher, and support a `?sample=november` / `?sample=august` query override for demos. Per-panel loading skeletons and error states, not one global spinner.
- The realtime endpoints returning **502 without an API key**, and an **empty hotspot list without a FIRMS key**, are **designed behavior, not bugs** — render them as "feed unavailable", never as fabricated data.

## 7. Backend wiring (the only backend changes you may make)

- Add `http://localhost:5173` to `allowed_origins` in `config.py` (or via env) for dev.
- After `npm run build`, mount `webapp/dist` in `backend/app/main.py` as StaticFiles at **`/console`**, with a `/` redirect to it. Keep the app a single Uvicorn worker (the service uses an in-process cache).
- Update `README.md` and `docker-compose` so the build + serve step is reproducible.

## 8. Hard constraints (do not violate)

- **Do not modify** anything under `backend/app/physics`, `backend/app/services`, or the schemas' meaning. Frontend + the CORS/StaticFiles wiring only. The physics was carefully audited; leave it alone.
- **Never display a fabricated accuracy number** (MAE, R², "% variance explained", "N% accurate"). No withheld-data backtest exists in this repo. Every number in the UI is either model output or a live upstream reading, and must be labeled as one or the other. The footer already says this — keep it true.
- **AQI = max(sub-indices)**, never an average, anywhere in the UI or its logic.
- Do not fake live stations or synthetic fires as real data (see §6).
- **Never commit `.env` or secrets.** Before any commit, run `git diff --cached --name-only | grep -x ".env"` and confirm it returns nothing.

## 9. Definition of done

- `npm run build` succeeds; `npm run dev` works against the running backend via the proxy.
- The console binds to all live endpoints, with per-panel loading/error states, and falls back cleanly to the sample with a visible badge when the backend is down.
- The atmospheric cross-section, scrub interaction (pointer + touch + keyboard), coupling loop, inversion strip, plume map, and station grid all work and stay aligned on the shared time axis.
- Animations are smooth and fully disabled under `prefers-reduced-motion`.
- Responsive at the 1080px and 720px breakpoints.
- No fabricated accuracy numbers anywhere; all copy honest and mostly ported from `index.html`.
- Accessibility: the scrubber is keyboard-operable with correct aria; color is never the only signal.
- The built app is served at `/console` from FastAPI, and Streamlit + the backend still run.

Work autonomously through all of it. When you hit a genuine fork (e.g. Tailwind v3 vs v4
for your shadcn version), pick the choice most likely to build cleanly and keep going.
