# NCR·72 — forecast console (React)

The production operator console for the Delhi-NCR 72-hour coupled AQI forecast. It is
a faithful React port of the vanilla prototype in [`../frontend-web/`](../frontend-web/):
the copy, the design tokens, and the layout are carried over verbatim — this is a
re-platforming onto a typed component tree and a live data layer, **not** a restyle.

It talks to the same FastAPI backend as the Streamlit app (`../frontend/app.py`), which
is left untouched. Both front-ends can run at once.

---

## Run it

### Dev (hot reload)

```bash
npm install
npm run dev
```

Open **http://localhost:5173/console/** — note the `/console/` path (see *base path*
below). The dev server proxies `/api` → `http://localhost:8000`, so start the backend
too:

```bash
python -m uvicorn app.main:app --app-dir ../backend --host 127.0.0.1 --port 8000
```

### Production build

```bash
npm run build      # tsc -b (strict typecheck) && vite build → dist/
```

The backend serves `dist/` at **http://localhost:8000/console/** (same origin as the
API, so no CORS). `/` on the backend redirects there. See the root
[`README.md`](../README.md) and [`Dockerfile.backend`](../Dockerfile.backend) for the
build-and-serve wiring; the container builds this directory in a Node stage and points
the backend at it with `CONSOLE_DIST_DIR`.

---

## The load-bearing constraints

These are product requirements, not style preferences. They are enforced in code and
must survive any refactor:

- **AQI is `max(sub-indices)`, never an average — anywhere.** The hero binds
  `hour.aqi` (the backend's headline, which is the max), and the sub-index list marks
  the dominant pollutant. The copy under it says so explicitly. See
  [`Hero.tsx`](src/components/Hero.tsx).
- **No fabricated accuracy numbers.** No MAE, R², "% accurate", or "validated against"
  appears, because no withheld-data backtest exists in this repo. The footer states
  this outright ([`Footer.tsx`](src/components/Footer.tsx)). Every number rendered is
  either model output or a live upstream reading, and is labelled as one or the other.
- **Sample data is always labelled as synthetic.** The fallback bundle is never dressed
  up as a real day — the banner calls the weather and the fires "hand-built"
  ([`SampleBanner.tsx`](src/components/SampleBanner.tsx)).
- **Live stations and fire detections are never faked.** When FIRMS returns nothing, the
  plume map draws only the reference wind/rings and says "nothing is inferred where
  FIRMS reports nothing" ([`PlumeMap.tsx`](src/components/PlumeMap.tsx)). When the live
  station feed fails, the panel shows the error — it does not invent readings.

---

## Data flow

[`useForecastData`](src/hooks/useForecastData.ts) owns all fetching and is **live-first
with a labelled sample fallback**:

1. Health → 72-hour forecast (`getForecast({})`, no coordinates → backend default of
   Delhi-ITO). On success the boot overlay lifts and the modelled panels (inversion,
   plume) are fetched live.
2. If the **live forecast** fails, the console loads the sample bundle
   (`public/sample-forecast.json`) and swaps *only the modelled panels* (forecast /
   inversion / plume) to the labelled sample. It then shows the sample banner.
3. **Live station observations are attempted in both modes** — a sample forecast never
   fabricates a live network, so the station grid is always the real feed (or a visible
   error).
4. `?sample=november|august` forces sample mode for the modelled panels without ever
   touching the live forecast, while still showing the live station grid. The two
   scenarios are swapped from a cached bundle with no refetch, and the choice is
   mirrored into the URL.

Each in-flight run uses one `AbortController`; a new run or an unmount aborts the
previous one. The forecast-failure branch checks `signal.aborted` **before** falling
back, so a self-aborted request (unmount, refresh) never spuriously trips sample mode —
only a genuine backend error does.

Rail feed LEDs (`met` / `obs` / `fire`) derive from panel status: `on` when the live
panel loaded, `off` on error, `pending` while loading, `sample` when the modelled feed
is showing sample data.

---

## Stack & non-obvious decisions

| Choice | Why |
|---|---|
| **Vite + React 19 + TS (strict)** | `verbatimModuleSyntax`, `erasableSyntaxOnly`, `noUnusedLocals/Parameters`. `npm run build` typechecks before bundling. |
| **Tailwind CSS v4, no config file** | `@import "tailwindcss"` + `@theme inline` in [`index.css`](src/index.css). The ported prototype styles live in [`styles/tokens.css`](src/styles/tokens.css) + [`styles/console.css`](src/styles/console.css) as semantic classes; Tailwind is used sparingly alongside them. |
| **shadcn-idiom primitives (CVA + `cn()`), scoped to three** | Only `Button`, `Skeleton`, `PanelMessage` in [`components/ui/`](src/components/ui/). They are thin CVA wrappers mapped onto the ported semantic classes — not a full shadcn install. Everything else is a plain semantic component. |
| **`base: '/console/'`** in [`vite.config.ts`](vite.config.ts) | Emitted asset URLs become `/console/…` so they resolve under the backend's StaticFiles mount without a rebuild. The sample URL uses `import.meta.env.BASE_URL`, so it works in dev (`/`) and prod (`/console/`). |
| **Hand-rolled SVG + Canvas visualisations** | No charting library. The atmosphere cross-section is SVG ([`Atmosphere.tsx`](src/components/Atmosphere.tsx)); the plume transport map is Canvas ([`PlumeMap.tsx`](src/components/PlumeMap.tsx)). The atmosphere splits a memoised static layer from a cheap cursor layer so 72-hour scrubbing stays at 60 fps. |
| **`framer-motion` present but unused** | Matches the prototype: entrance motion is hand-rolled CSS + `IntersectionObserver` in [`App.tsx`](src/App.tsx), gated on `prefers-reduced-motion`. The dependency is declared but tree-shaken out of the bundle. |
| **IBM Plex via Google Fonts CDN** | `<link>` in [`index.html`](index.html). The backend relaxes CSP for `/console` only to allow `fonts.googleapis.com` / `fonts.gstatic.com` (`CONSOLE_CSP` in `backend/app/core/security.py`). |
| **Client-derived AQI colour ramp** | A tuned dark-ground ramp in [`lib/aqi.ts`](src/lib/aqi.ts), **not** the backend's `color` field. Categories map to CPCB bands (50/100/200/300/400/500). |

The AQI accent (`--live`) is written to `document.documentElement` from the cursor
hour's category, so the whole console shifts hue as you scrub.

---

## Accessibility & motion

- The atmosphere chart is the scrubber: `role="slider"`, named via
  `aria-labelledby`, with `aria-valuemin/max/now` and a descriptive `aria-valuetext`
  ("hour +6, AQI 214, Very Poor"). `←`/`→` step an hour, `PgUp`/`PgDn` step six.
- All entrance animation is gated on `prefers-reduced-motion` via
  [`useReducedMotion`](src/hooks/useReducedMotion.ts); when reduced, `data-anim="off"`
  disables the reveal transitions and the content is shown immediately.
- Responsive breakpoints at 1080 px and 720 px are carried over from the prototype.

---

## Layout

```
src/
  App.tsx                 composition + IntersectionObserver reveals + --live accent
  main.tsx                React root (StrictMode)
  index.css               Tailwind v4 entry + @theme
  hooks/
    useForecastData.ts    live-first fetch orchestration + sample fallback + feeds
    useCursor.ts          72-hour cursor: play/scrub/keyboard, 9 s sweep
    useReducedMotion.ts   prefers-reduced-motion
  lib/
    api.ts                /api/v1 clients, per-endpoint timeouts, sample loader
    types.ts              wire types (mirror backend Pydantic schemas)
    aqi.ts                CPCB categories + tuned colour ramp
    format.ts             clocks, lead labels, compass, number formats
    utils.ts              cn()
  components/
    Rail.tsx  Hero.tsx  Atmosphere.tsx  Readouts.tsx  CouplingLoop.tsx
    InversionStrip.tsx  PlumeMap.tsx  Stations.tsx  Footer.tsx
    HazeField.tsx  Boot.tsx  SampleBanner.tsx
    ui/ button.tsx  skeleton.tsx  panel-message.tsx
  styles/
    tokens.css            design tokens ported from the prototype
    console.css           semantic component styles ported from the prototype
public/
  sample-forecast.json    labelled fallback bundle (november + august scenarios)
```
