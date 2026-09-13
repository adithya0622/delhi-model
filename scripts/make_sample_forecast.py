"""Generate the console's offline sample data — run:  python scripts/make_sample_forecast.py

Writes `frontend-web/sample-forecast.json`, which the console falls back to when
the backend or its upstreams are unreachable (a hackathon venue's wifi, say).

The important property of this file: **the numbers are model output, not
invented.** Only the network transport is stubbed. `build_72h_forecast`,
`compute_inversion_series`, `compute_plume_vectors`, the box model, the Picard
feedback loop and the CPCB scale all run exactly as they do in production — the
same functions the API calls. What is synthetic is the *input*: a hand-built
meteorological profile in place of Open-Meteo, and a hand-placed set of fire
detections in place of NASA FIRMS.

So the console's sample mode shows "what this model does given this weather",
which is honest, and it is badged as synthetic in the UI. It is NOT a forecast of
any real day, and nothing here may ever be quoted as an accuracy figure.

Two scenarios are emitted because one is not enough to show the physics:

  august    — monsoon. Deep mixing, brisk ventilation, no fires. The regime the
              model is usually demoed in, and the boring one.
  november  — the regime the problem statement is actually graded on: a nocturnal
              inversion intensifying over three nights, a collapsing mixed layer,
              and Punjab/Haryana stubble smoke advecting in on the 850 hPa wind.

Stubbing is done by injecting a fake `httpx` into `sys.modules` (the physics
modules import it *locally* inside their fetch functions, on purpose, which is
what makes this possible) and by replacing the two FIRMS/wind fetchers on
`plume_advection` with coroutines returning fixed payloads.
"""
import asyncio
import json
import random
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "backend"))

# ── Stub the network before anything imports it ───────────────────────────────
# Holds the met payload the fake client answers with; rebound per scenario.
_CURRENT_MET: dict = {}


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload

    @property
    def text(self):
        return ""


class _FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, params=None, headers=None, **kwargs):
        return _FakeResponse(_CURRENT_MET)


_fake_httpx = types.ModuleType("httpx")
_fake_httpx.AsyncClient = _FakeAsyncClient
_fake_httpx.HTTPError = type("HTTPError", (Exception,), {})
_fake_httpx.HTTPStatusError = type("HTTPStatusError", (_fake_httpx.HTTPError,), {})
sys.modules.setdefault("httpx", _fake_httpx)

from app.domain.species import Pollutant                     # noqa: E402
from app.physics import plume_advection                      # noqa: E402
from app.physics.inversion_engine import compute_inversion_series  # noqa: E402
from app.services.aqi_service import build_72h_forecast      # noqa: E402


# ── Synthetic meteorology ─────────────────────────────────────────────────────
# 24-hour diurnal shapes, tiled across three days with a per-day trend. The
# August profile is the one `scripts/verify/calib.py` calibrates against; the
# November profile is the same shape it uses for the inversion episode, made
# progressively more stagnant so the console has an intensifying event to show.

_AUG = {
    "pbl": [350, 320, 300, 290, 300, 400, 650, 900, 1200, 1500, 1800, 2100,
            2300, 2400, 2300, 2000, 1600, 1100, 700, 500, 430, 400, 380, 360],
    "sol": [0, 0, 0, 0, 0, 0, 60, 220, 420, 600, 740, 820,
            830, 760, 620, 430, 220, 60, 0, 0, 0, 0, 0, 0],
    "wnd": [1.6, 1.5, 1.4, 1.4, 1.5, 1.8, 2.2, 2.6, 3.0, 3.4, 3.8, 4.0,
            4.2, 4.2, 4.0, 3.4, 2.8, 2.2, 1.9, 1.8, 1.7, 1.7, 1.6, 1.6],
    # T1000 (°C) and the 925-1000 hPa difference. Monsoon air is well mixed, so
    # dT stays negative all day — no inversion anywhere in this scenario.
    "t1000": [27.5, 27.1, 26.8, 26.6, 26.5, 26.8, 27.6, 28.8, 30.2, 31.6, 32.8, 33.7,
              34.2, 34.3, 33.9, 33.0, 31.8, 30.4, 29.4, 28.8, 28.4, 28.1, 27.9, 27.7],
    "dt": [-2.0, -2.2, -2.4, -2.5, -2.4, -2.2, -2.6, -3.6, -5.0, -6.2, -7.0, -7.6,
           -7.9, -7.8, -7.4, -6.6, -5.4, -4.0, -3.0, -2.6, -2.3, -2.1, -2.0, -2.0],
    "start": "2025-08-18T00:00",
    # Monsoon: fields are wet, nothing is burning.
    "fires": [],
    "wind850": (3.6, 1.8),   # southeasterly monsoon flow, away from Punjab
}

_NOV = {
    "pbl": [180, 165, 155, 150, 150, 155, 170, 220, 350, 550, 750, 900,
            980, 980, 880, 650, 400, 260, 220, 200, 195, 190, 185, 182],
    "sol": [0, 0, 0, 0, 0, 0, 0, 80, 240, 400, 520, 570,
            540, 430, 270, 100, 0, 0, 0, 0, 0, 0, 0, 0],
    "wnd": [0.8, 0.7, 0.7, 0.6, 0.6, 0.7, 0.8, 1.0, 1.4, 1.9, 2.3, 2.6,
            2.7, 2.6, 2.2, 1.6, 1.1, 0.9, 0.8, 0.8, 0.7, 0.7, 0.7, 0.7],
    "t1000": [12.4, 11.8, 11.3, 10.9, 10.6, 10.4, 10.6, 12.0, 15.2, 18.6, 21.4, 23.4,
              24.4, 24.6, 23.8, 21.8, 19.0, 16.6, 15.2, 14.4, 13.8, 13.3, 12.9, 12.6],
    # Nocturnal inversion: dT positive overnight, deeply negative at midday.
    "dt": [2.6, 2.9, 3.2, 3.4, 3.5, 3.4, 2.8, 1.5, -1.4, -4.0, -6.2, -7.4,
           -7.9, -7.6, -6.4, -4.2, -1.5, 0.7, 1.7, 2.1, 2.3, 2.4, 2.5, 2.6],
    "start": "2025-11-06T00:00",
    # Filled by _burning_belt() below: a detection field, not a handful of pins.
    # FIRMS routinely reports hundreds of VIIRS detections across Punjab and
    # Haryana on a single early-November day, and the plume share the model
    # produces is meaningless if the input pretends there are seven fires.
    "fires": None,
    "wind850": (2.9, -3.1),  # northwesterly: Punjab -> Delhi, the transport case
}


def _burning_belt(n: int = 220, seed: int = 20251106) -> list[dict]:
    """A deterministic pseudo-FIRMS detection field over the stubble belt.

    Detections are scattered along the Punjab/Haryana agricultural band with
    FRP drawn from a long-tailed distribution, which is the shape VIIRS actually
    reports: many small field-scale burns and a few large ones. `source_state` is
    assigned by the module's own classifier so it agrees with production.
    """
    rng = random.Random(seed)
    fires = []
    for _ in range(n):
        # The belt runs WNW-ESE; follow it and scatter across its width.
        lon = rng.uniform(74.4, 77.0)
        lat_centre = plume_advection._PBHR_LAT_AT_REF + \
            (lon - plume_advection._PBHR_LON_REF) * -plume_advection._PBHR_SLOPE
        lat = lat_centre + rng.gauss(0.0, 0.34)
        if not (28.9 <= lat <= 31.4):
            continue
        # Long tail: most burns modest, a few intense.
        frp = round(6.0 + rng.paretovariate(1.5) * 9.0, 1)
        if frp > 340.0:
            frp = round(rng.uniform(120.0, 340.0), 1)
        hour = rng.choice(["06:12", "06:14", "10:48", "21:36"])
        fires.append({
            "lat": round(lat, 4),
            "lon": round(lon, 4),
            "frp_mw": frp,
            "source_state": plume_advection._state_from_coords(lat, lon),
            "detected_at": "2025-11-06T%s:00+00:00" % hour,
            "confidence": rng.choice(["h", "h", "n", "n", "l"]),
        })
    return fires

# Per-day multipliers. Day 1 is the baseline; the November episode tightens as
# the anticyclone settles in, which is what makes the third night the worst.
_NOV_DAY = [
    {"pbl": 1.00, "wnd": 1.00, "inv": 1.00},
    {"pbl": 0.92, "wnd": 0.88, "inv": 1.28},
    {"pbl": 0.86, "wnd": 0.78, "inv": 1.52},
]
_AUG_DAY = [
    {"pbl": 1.00, "wnd": 1.00, "inv": 1.00},
    {"pbl": 1.04, "wnd": 1.06, "inv": 1.00},
    {"pbl": 0.97, "wnd": 0.94, "inv": 1.00},
]


def _build_met(spec: dict, day_mods: list[dict]) -> dict:
    """Expand a 24-hour shape into a 72-hour Open-Meteo-shaped payload."""
    t0 = datetime.fromisoformat(spec["start"])
    times, pbl, sol, wnd_kmh, t1000, t925 = [], [], [], [], [], []

    for d, mod in enumerate(day_mods):
        for h in range(24):
            times.append((t0 + timedelta(hours=24 * d + h)).strftime("%Y-%m-%dT%H:%M"))
            pbl.append(round(spec["pbl"][h] * mod["pbl"], 1))
            sol.append(float(spec["sol"][h]))
            # Open-Meteo reports wind_speed_10m in km/h; the service divides by 3.6.
            wnd_kmh.append(round(spec["wnd"][h] * mod["wnd"] * 3.6, 2))

            base_t = spec["t1000"][h]
            dt = spec["dt"][h]
            # Only amplify the inversion (positive dT); scaling the daytime
            # superadiabatic lapse would be physically meaningless.
            dt_scaled = dt * mod["inv"] if dt > 0 else dt
            t1000.append(round(base_t, 2))
            t925.append(round(base_t + dt_scaled, 2))

    return {
        "hourly": {
            "time": times,
            "boundary_layer_height": pbl,
            "shortwave_radiation": sol,
            "wind_speed_10m": wnd_kmh,
            "temperature_1000hPa": t1000,
            "temperature_925hPa": t925,
        }
    }


# ── Scenario assembly ─────────────────────────────────────────────────────────

async def _make_scenario(spec: dict, day_mods: list[dict]) -> tuple[dict, dict, dict]:
    """Run the real pipeline over synthetic input. Returns (forecast, inversion, plume)."""
    global _CURRENT_MET
    _CURRENT_MET = _build_met(spec, day_mods)

    fires = [dict(f) for f in (spec["fires"] if spec["fires"] is not None else _burning_belt())]
    wind_series = [tuple(spec["wind850"])] * 72

    async def _fake_wind_series():
        return wind_series

    async def _fake_firms():
        return fires

    plume_advection._fetch_850hpa_wind_series = _fake_wind_series
    plume_advection._fetch_firms_hotspots = _fake_firms

    # The real production entry point, over the real physics.
    forecast = await build_72h_forecast(28.6139, 77.2090, "Delhi-ITO")

    inversion_raw = compute_inversion_series(_CURRENT_MET)
    inversion = [
        {"timestamp": t, **s}
        for t, s in zip(_CURRENT_MET["hourly"]["time"][:len(inversion_raw)], inversion_raw)
    ]

    plume = await plume_advection.compute_plume_vectors()
    plume["timestamp"] = _CURRENT_MET["hourly"]["time"][0]

    return forecast, inversion, plume


def _summarise(label: str, forecast: dict, inversion: list[dict], plume: dict) -> None:
    hours = forecast["forecast_hours"]
    aqis = [h["aqi"] for h in hours]
    supp = [h["pbl_suppression_pct"] for h in hours]
    pm25 = [
        next(s["concentration"] for s in h["sub_indices"] if s["pollutant"] == Pollutant.PM25)
        for h in hours
    ]
    invs = sum(1 for s in inversion if s["inversion_present"])
    plume_share = max(h["plume_contribution"] for h in hours)

    print("  %-28s AQI %3d-%3d (mean %3.0f) | PM2.5 %3.0f-%3.0f | supp max %4.1f%% "
          "| inv hrs %2d | plume max %4.1f%% | fires %d"
          % (label, min(aqis), max(aqis), sum(aqis) / len(aqis),
             min(pm25), max(pm25), max(supp), invs, 100 * plume_share,
             plume["hotspot_count_total"]))

    # Guard the invariant the hour-0 nudge fix established, on every hour.
    for i, h in enumerate(hours):
        top = max(s["sub_index"] for s in h["sub_indices"])
        assert h["aqi"] == top, "hour %d: aqi %d != max(sub_indices) %d" % (i, h["aqi"], top)
        assert 0 <= h["aqi"] <= 500, "hour %d: AQI out of range" % i
        assert h["aerosol_dt_surface_c"] <= 0, "hour %d: aerosol warmed the surface" % i
        assert 1 <= h["feedback_iterations"] <= 12, "hour %d: bad iteration count" % i


async def main() -> int:
    scenarios = []

    print("Running the real forecast pipeline over synthetic meteorology:")
    for sid, label, blurb, spec, mods in [
        ("november", "November inversion episode",
         "Three intensifying nocturnal inversions, a mixed layer collapsing to the "
         "150 m floor, and Punjab/Haryana stubble smoke arriving on the 850 hPa "
         "northwesterly. This is the regime the forecast exists for.",
         _NOV, _NOV_DAY),
        ("august", "August monsoon",
         "Deep afternoon mixing to ~2.4 km, brisk ventilation and no field burning. "
         "The feedback is real but small — which is the correct answer for monsoon.",
         _AUG, _AUG_DAY),
    ]:
        forecast, inversion, plume = await _make_scenario(spec, mods)
        _summarise(label, forecast, inversion, plume)
        scenarios.append({
            "id": sid,
            "label": label,
            "blurb": blurb,
            "forecast": forecast,
            "inversion": inversion,
            "plume": plume,
        })

    payload = {
        "kind": "sample",
        "generated_by": "scripts/make_sample_forecast.py",
        "note": (
            "Model output over SYNTHETIC meteorology and synthetic fire detections. "
            "The physics, coupling loop and CPCB scale are the production code paths; "
            "the weather and the fires are hand-built. Not a forecast of any real "
            "day, and not a validation of accuracy."
        ),
        "scenarios": scenarios,
    }

    out = _ROOT / "frontend-web" / "sample-forecast.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    # Enum members are `str` subclasses, so json serialises them as their values.
    out.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print("\n  wrote %s (%.0f KB)" % (out.relative_to(_ROOT), out.stat().st_size / 1024))
    print("  every hour satisfies aqi == max(sub_indices); aerosol cooling only.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
