"""
Hindcast Validation vs CAMS Reanalysis
======================================
Answers "how accurate is it?" with numbers produced by code, not assertions.

Protocol (anti-leakage rules)
-----------------------------
1.  ANCHOR WINDOWS IN THE PAST — windows ending ≥ 3 days ago, so no evaluated
    hour overlaps the live forecast horizon.
2.  ANALYSIS METEOROLOGY — analysis-mode meteorology for the historical
    window: the best available proxy for the weather a real-time run would
    have ingested at those instants.
3.  LEAK-FREE INITIALIZATION — the anchor PM2.5 (hour 0) is the LAST CAMS value
    BEFORE the window opens. Every evaluated hour is a genuine +1..+72 h
    projection from that anchor.
4.  ML OFF, PLUME OFF, NUDGING OFF —
      * ML off: the trained model was fitted on CAMS, so scoring it against
        CAMS would measure the training set, not forecast skill.
      * plume off: FIRMS has no historical archive on this tier — hindcasts run
        smoke-free rather than with invented fires.
      * nudging off: no observational correction after the hour-0 anchor, and
        the anchor itself predates the window.
      * coupling runs as in production: the aerosol→PBL feedback is part of
        the model under test, not an external input.

The verifier and the target are different upstreams — meteorology from the
forecast/analysis API, verification truth from the air-quality archive API.
The model never sees the verification series as an input.
"""
from __future__ import annotations

import math
import random
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx

_OPEN_METEO_ANALYSIS_URL = "https://api.open-meteo.com/v1/forecast"
_OPEN_METEO_CAMS_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
_TARGET_LAT = 28.6139
_TARGET_LON = 77.2090

_MIN_LEAD_DAYS = 3   # anchor at least this many days before "now"
_WINDOW_HOURS = 72
_MIN_WINDOW_COVERAGE = 0.85   # fraction of hours with valid CAMS PM2.5
_STRIDE_DAYS = 5              # window starts every N days
_MAX_WINDOWS = 8              # ~5 weeks of hindcast coverage per run

_LEAD_LABELS = (6, 24, 48, 72)

_MET_FIELDS = (
    "temperature_1000hPa",
    "temperature_925hPa",
    "boundary_layer_height",
    "shortwave_radiation",
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "wind_speed_10m",
    "wind_direction_10m",
)


# ── Data acquisition ─────────────────────────────────────────────────────────


_MET_ARCHIVE_START_CACHE: str | None = None


async def _probe_met_archive_start() -> str | None:
    """
    First hour (IST) for which the analysis API serves BOTH pressure-level
    temperatures — the shallowest-depth fields this backtest depends on.
    Probed once per process and cached; the archive start moves by at most a
    day between runs.

    The forecast/analysis API serves a much shorter history than the CAMS
    air-quality archive, so the oldest hindcast window must be clamped to
    THIS date, not to the CAMS start.
    """
    global _MET_ARCHIVE_START_CACHE
    if _MET_ARCHIVE_START_CACHE is not None:
        return _MET_ARCHIVE_START_CACHE
    params = {
        "latitude": _TARGET_LAT,
        "longitude": _TARGET_LON,
        "hourly": "temperature_1000hPa,temperature_925hPa",
        "past_days": 45,
        "forecast_days": 0,
        "timezone": "Asia/Kolkata",
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(_OPEN_METEO_ANALYSIS_URL, params=params)
            r.raise_for_status()
            hourly = r.json().get("hourly", {})
    except httpx.HTTPError:
        return None
    times = hourly.get("time", [])
    t1000 = hourly.get("temperature_1000hPa") or []
    t925 = hourly.get("temperature_925hPa") or []
    for i, stamp_s in enumerate(times):
        a = t1000[i] if i < len(t1000) else None
        b = t925[i] if i < len(t925) else None
        if a is not None and b is not None:
            _MET_ARCHIVE_START_CACHE = stamp_s
            return stamp_s
    return None


async def fetch_cams_history(days_back: int = 45) -> dict[str, list]:
    """Hourly CAMS reanalysis PM2.5 (IST) for the last `days_back` days."""
    params = {
        "latitude": _TARGET_LAT,
        "longitude": _TARGET_LON,
        "hourly": "pm2_5",
        "past_days": days_back,
        "forecast_days": 0,
        "timezone": "Asia/Kolkata",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(_OPEN_METEO_CAMS_URL, params=params)
        r.raise_for_status()
        hourly = r.json().get("hourly", {})
    return {"time": hourly.get("time", []), "pm25": hourly.get("pm2_5", [])}


async def fetch_analysis_met(start_stamp: str, window_hours: int = _WINDOW_HOURS) -> dict[str, Any]:
    """
    Analysis-mode meteorology for the 72 h window opening at `start_stamp`
    (an IST-stamped hour string, e.g. "2026-09-04T00:00" — both Open-Meteo
    APIs stamp their `time` arrays in the requested timezone, so IST strings
    are the interchange format end-to-end and no UTC offset arithmetic can
    drift). Returns the exact payload shape `build_72h_forecast` consumes.

    `past_hours` is measured BACK FROM NOW by the API, so it must cover the
    whole distance from the present to the window start, plus buffer.
    """
    now_ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    # IST stamps are tz-naive by construction (the timezone lives in the label);
    # compare against a naive "now in IST".
    start_dt = datetime.fromisoformat(start_stamp)
    now_ist = now_ist.replace(tzinfo=None)
    hours_back = int((now_ist - start_dt).total_seconds() // 3600) + 48
    past_hours = max(window_hours, hours_back)
    params = {
        "latitude": _TARGET_LAT,
        "longitude": _TARGET_LON,
        "hourly": ",".join(_MET_FIELDS),
        "past_hours": past_hours,
        "forecast_days": 0,
        "timezone": "Asia/Kolkata",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(_OPEN_METEO_ANALYSIS_URL, params=params)
        r.raise_for_status()
        payload = r.json()
    hourly = payload.get("hourly", {})
    times = hourly.get("time", [])
    if len(times) < window_hours:
        raise RuntimeError(f"analysis met returned only {len(times)} hours")
    index = {t: i for i, t in enumerate(times)}
    if start_stamp not in index:
        raise RuntimeError(f"analysis met window does not cover {start_stamp}")
    i0 = index[start_stamp]
    if i0 + window_hours > len(times):
        raise RuntimeError("analysis met series ends inside the requested window")
    window = {"time": times[i0 : i0 + window_hours]}
    for name in _MET_FIELDS:
        series = hourly.get(name) or []
        window[name] = series[i0 : i0 + window_hours]
    return {
        "hourly": window,
        "hourly_units": payload.get("hourly_units", {}),
        "weather_source": "open-meteo-analysis",
        "profile_source": "reanalysis",
        "provider_failures": [],
        "current": {},
    }


# ── Metrics ──────────────────────────────────────────────────────────────────


def _finite_pairs(
    obs: list[float | None], pred: list[float | None]
) -> tuple[list[float], list[float]]:
    o, p = [], []
    for a, b in zip(obs, pred):
        if a is not None and b is not None and math.isfinite(a) and math.isfinite(b):
            o.append(float(a))
            p.append(float(b))
    return o, p


def _pearson(o: list[float], p: list[float]) -> float | None:
    n = len(o)
    if n < 3:
        return None
    mo, mp = sum(o) / n, sum(p) / n
    cov = sum((a - mo) * (b - mp) for a, b in zip(o, p))
    vo = sum((a - mo) ** 2 for a in o)
    vp = sum((b - mp) ** 2 for b in p)
    if vo <= 0 or vp <= 0:
        return None
    return cov / math.sqrt(vo * vp)


def compute_metrics(obs: list[float | None], pred: list[float | None]) -> dict[str, Any]:
    o, p = _finite_pairs(obs, pred)
    n = len(o)
    if n == 0:
        return {"n": 0}
    err = [b - a for a, b in zip(o, p)]
    mbe = sum(err) / n
    mae = sum(abs(e) for e in err) / n
    rmse = math.sqrt(sum(e * e for e in err) / n)
    r = _pearson(o, p)
    # Nash-Sutcliffe model efficiency: 1.0 is perfect, 0.0 matches the
    # observed-mean climatology, negative is worse than climatology.
    denom = sum((a - mo) ** 2 for a, mo in ((a, sum(o) / n) for a in o))
    nse = 1.0 - sum(e * e for e in err) / denom if denom > 0 else None
    return {
        "n": n,
        "mbe_ug_m3": round(mbe, 2),
        "mae_ug_m3": round(mae, 2),
        "rmse_ug_m3": round(rmse, 2),
        "pearson_r": round(r, 3) if r is not None else None,
        "nash_sutcliffe_e": round(nse, 3) if nse is not None else None,
        "mean_obs_ug_m3": round(sum(o) / n, 1),
        "mean_pred_ug_m3": round(sum(p) / n, 1),
    }


def _bootstrap_mae_ci(
    obs: list[float | None], pred: list[float | None], n_boot: int = 1000, seed: int = 42
) -> dict[str, float] | None:
    """
    Percentile bootstrap CI on MAE. Resampling preserves the (obs, pred) PAIR:
    breaking the pairing (resampling each side independently) would manufacture
    correlation that the forecast did not earn.
    """
    o, p = _finite_pairs(obs, pred)
    n = len(o)
    if n < 8:
        return None
    rng = random.Random(seed)
    maes = []
    for _ in range(n_boot):
        idx = [rng.randrange(n) for _ in range(n)]
        maes.append(sum(abs(p[i] - o[i]) for i in idx) / n)
    maes.sort()
    return {
        "lo": round(maes[int(0.025 * n_boot)], 2),
        "hi": round(maes[int(0.975 * n_boot) - 1], 2),
    }


# ── The hindcast runner ──────────────────────────────────────────────────────


async def run_hindcast_backtest(
    max_windows: int = _MAX_WINDOWS,
    stride_days: int = _STRIDE_DAYS,
    lat: float = _TARGET_LAT,
    lon: float = _TARGET_LON,
    station_name: str = "Delhi-ITO (hindcast)",
) -> dict[str, Any]:
    """
    Run `max_windows` 72 h hindcast windows ending ≥ 3 days ago, score PM2.5
    against CAMS reanalysis, and return pooled + per-lead metrics, persistence
    skill and a paired bootstrap CI.
    """
    # Late import keeps the validation module importable without the app stack
    # and the physics import graph acyclic.
    from app.services.aqi_service import build_72h_forecast

    # Work in IST-stamped hour strings end-to-end: both Open-Meteo APIs stamp
    # their `time` arrays in the requested timezone (Asia/Kolkata), so string
    # stamps are unambiguous — no UTC offset arithmetic to drift.
    now_ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    latest_end = now_ist - timedelta(days=_MIN_LEAD_DAYS)
    latest_start_day = (latest_end - timedelta(hours=_WINDOW_HOURS)).date()

    def stamp(day: date, hour: int = 0) -> str:
        return f"{day:%Y-%m-%d}T{hour:02d}:00"

    cams = await fetch_cams_history(
        days_back=min(45, _MIN_LEAD_DAYS + stride_days * max_windows + 5)
    )
    cams_index = {t: i for i, t in enumerate(cams["time"])}

    def cams_at(stamp_s: str) -> float | None:
        i = cams_index.get(stamp_s)
        if i is None or i >= len(cams["pm25"]):
            return None
        v = cams["pm25"][i]
        return float(v) if v is not None else None

    # The analysis archive serves a limited depth of pressure-level fields
    # (observed ~23 days at the time of writing). Probe the actual coverage
    # instead of assuming, and clamp the oldest window to it.
    met_start_stamp = await _probe_met_archive_start()
    archive_start = met_start_stamp or (cams["time"][0] if cams["time"] else None)
    if archive_start is None:
        return {
            "available": False,
            "reason": "analysis meteorology archive unreachable or empty",
            "protocol": "physics-only hindcast vs CAMS reanalysis; see module docstring",
        }
    met_probe_start = datetime.fromisoformat(archive_start).date()
    usable_days = (latest_start_day - met_probe_start).days
    if usable_days < 0:
        return {
            "available": False,
            "reason": (
                f"analysis meteorology archive starts {archive_start}; not enough "
                f"history for a {72} h window ending {_MIN_LEAD_DAYS} days ago"
            ),
            "protocol": "physics-only hindcast vs CAMS reanalysis; see module docstring",
        }

    start_stamps: list[str] = []
    day = latest_start_day
    while len(start_stamps) < max_windows and day >= met_probe_start:
        start_stamps.append(stamp(day))
        day -= timedelta(days=stride_days)
    start_stamps.reverse()   # oldest first

    windows = []
    pooled_obs: list[float | None] = []
    pooled_pred: list[float | None] = []
    pooled_base: list[float | None] = []
    by_lead: dict[int, dict[str, list]] = {
        h: {"o": [], "p": [], "b": []} for h in _LEAD_LABELS
    }

    for start_s in start_stamps:
        try:
            met = await fetch_analysis_met(start_s)
        except (RuntimeError, httpx.HTTPError):
            continue
        times = met["hourly"]["time"]

        # Leak-free anchor: the LAST CAMS value BEFORE the window opens.
        start_dt = datetime.fromisoformat(start_s)
        anchor_stamp = (start_dt - timedelta(hours=1)).strftime("%Y-%m-%dT%H:00")
        anchor_pm25 = cams_at(anchor_stamp)
        if anchor_pm25 is None:
            continue

        try:
            result = await build_72h_forecast(
                lat,
                lon,
                station_name,
                live_pm25=anchor_pm25,        # hours 1..72 remain projections
                met_data_override=met,
                plume_override={"hotspots": [], "plumes": []},
                use_ml=False,
            )
        except (ValueError, RuntimeError, httpx.HTTPError):
            continue

        obs = [cams_at(t) for t in times]
        if sum(v is not None for v in obs) < _MIN_WINDOW_COVERAGE * _WINDOW_HOURS:
            continue

        pred: list[float | None] = []
        for h in result["forecast_hours"]:
            si = next(
                (s for s in h["sub_indices"] if s["pollutant"] == "PM2.5"),
                None,
            )
            pred.append(float(si["concentration"]) if si else None)

        wm = compute_metrics(obs, pred)
        if wm.get("n", 0) < _MIN_WINDOW_COVERAGE * _WINDOW_HOURS:
            continue

        # Persistence baseline for this window: hour i predicted as the
        # observed anchor. A forecast is only informative if it beats the
        # claim "the next 72 hours look like right now".
        for i in range(_WINDOW_HOURS):
            pooled_base.append(anchor_pm25 if obs[i] is not None else None)
            lead = min([h for h in _LEAD_LABELS if i < h] or [_WINDOW_HOURS])
            if obs[i] is not None and lead in by_lead:
                by_lead[lead]["b"].append(anchor_pm25)

        pooled_obs.extend(obs)
        pooled_pred.extend(pred)
        for i, (v, p) in enumerate(zip(obs, pred)):
            if v is None or p is None:
                continue
            lead = min([h for h in _LEAD_LABELS if i < h] or [_WINDOW_HOURS])
            if lead in by_lead:
                by_lead[lead]["o"].append(v)
                by_lead[lead]["p"].append(p)

        windows.append({"start_ist": times[0], "anchor_pm25_ug_m3": anchor_pm25, **wm})

    if not windows:
        return {
            "available": False,
            "reason": "no usable hindcast windows (upstream coverage or API failure)",
            "protocol": "physics-only hindcast vs CAMS reanalysis; see module docstring",
        }

    persistence_metrics = compute_metrics(pooled_obs, pooled_base)
    model_metrics = compute_metrics(pooled_obs, pooled_pred)
    mae_model = float(model_metrics["mae_ug_m3"])
    mae_base = float(persistence_metrics.get("mae_ug_m3", 0.0))
    skill = round(1.0 - mae_model / mae_base, 3) if mae_base > 0 else None

    return {
        "available": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "location": {"lat": lat, "lon": lon},
        "protocol": {
            "truth": "CAMS global reanalysis PM2.5 (Open-Meteo air-quality archive)",
            "meteorology": "analysis-mode meteorology for the hindcast window",
            "windows": len(windows),
            "window_hours": _WINDOW_HOURS,
            "stride_days": stride_days,
            "min_lead_days": _MIN_LEAD_DAYS,
            "exclusions": [
                "trained ML model off: fitted on CAMS, scoring it here would report training fit, not skill",
                "plume transport off: FIRMS provides no historical archive at this tier; no synthetic fires",
                "observational nudging off after the hour-0 anchor; the anchor predates the window",
                "coupling runs as in production — aerosol→PBL feedback is part of the model under test",
            ],
        },
        "pooled": {
            **model_metrics,
            "bootstrap_mae_ci95": _bootstrap_mae_ci(pooled_obs, pooled_pred),
        },
        "skill_vs_persistence": {
            "persistence": persistence_metrics,
            "model": model_metrics,
            "mae_skill_score": skill,
            "interpretation": (
                "positive: the coupled model beats the 'next 72 h = now' baseline"
                if skill is not None and skill > 0
                else "non-positive: persistence is a harder baseline than expected"
            ),
        },
        "by_lead": {
            f"+{h}h": compute_metrics(by_lead[h]["o"], by_lead[h]["p"])
            for h in _LEAD_LABELS
        },
        "windows": windows,
        "honesty_note": (
            "CAMS is an independent dataset, but it is a model reanalysis, not a "
            "surface observation network. These figures quantify skill against "
            "CAMS, not against CPCB ground truth."
        ),
    }
