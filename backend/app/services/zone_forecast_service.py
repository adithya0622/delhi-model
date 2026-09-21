"""Per-zone Chronos forecasts with measured model selection (station layer v2).

Why zones: CAMS ground truth exists per ~0.25° cell, not per sensor — Delhi NCR
occupies 7 distinct cells. Each zone therefore gets its OWN model invocation
with its OWN 14-day cell history as the token context, so the seven zones
produce genuinely different forecast curves. All 50 stations inherit their
zone's curve (same cell ⇒ same ground truth), then keep their measured station
anchor (IQAir live / catalog prior) for within-zone differentiation — labeled
honestly, never blended silently.

Model selection is measured, not asserted: the three open-source serving
variants (fine-tuned Chronos-2 specialists gated by their acceptance gates,
zero-shot Chronos-2, zero-shot Chronos-T5) are raced per zone against a
recent CAMS archive holdout (backtest windows before the forecast origin);
the variant with the lowest AQI MAE on THAT zone's own holdout is selected
and the per-zone decision is recorded in the response artifact.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from app.services.chronos_context import (
    HORIZON_HOURS,
    build_history_series,
    fetch_cams_context,
    fetch_met_context,
    _cams_covariate_split,
    _split_covariates,
)
from app.services.chronos_forecast_service import (
    chronos_model_status,
    finetuned_serving_ready,
    predict_72hr_chronos,
    predict_72hr_chronos2_finetuned,
    predict_72hr_chronos_c2,
    serving_model,
)
from app.services.realtime_service import DELHI_NCR_STATIONS
from app.services.station_forecast_service import (
    calibrate_station,
    load_offsets,
    station_offsets_for,
    station_hour_aqi,
)

_ZONE_ARTIFACTS_DIR = Path(__file__).resolve().parents[1] / "artifacts" / "zone_forecasts"
_ZONE_TTL = timedelta(hours=3)
# Backtest: rolling origins over the trailing archive, 72 h rollout each,
# exactly the holdout protocol used for the city-level metrics.
_BT_ORIGINS = 3
_BT_SPACING_H = 72
_MIN_VALID_RATIO = 0.5  # a zone needs ≥50% valid hourly points to serve

_MODEL_TO_SKEY = {
    "pm2_5": "pm25", "pm10": "pm10", "no2": "no2",
    "so2": "so2", "co": "co", "o3": "o3",
}


# ── Zone geometry: stations → CAMS cells ────────────────────────────────────

def zone_cells() -> dict[tuple[float, float], list[dict[str, Any]]]:
    """Group the 50 stations by their ~0.25° CAMS cell (7 zones for Delhi NCR)."""
    cells: dict[tuple[float, float], list[dict[str, Any]]] = {}
    for st in DELHI_NCR_STATIONS:
        key = (int(st["lat"] * 4) / 4.0, int(st["lon"] * 4) / 4.0)
        cells.setdefault(key, []).append(st)
    return dict(sorted(cells.items()))


def zone_id_for(cell: tuple[float, float]) -> str:
    return f"z{cell[0]:.2f}_{cell[1]:.2f}".replace(".", "p", 1).replace(".", "")


def zone_for_station(station: dict[str, Any]) -> tuple[float, float]:
    return (int(station["lat"] * 4) / 4.0, int(station["lon"] * 4) / 4.0)


# ── Scoring: AQI MAE of a 72-h rollout vs CAMS truth (same code as training) ─

def _hour_aqi_from_conc(conc: dict[str, float]) -> float | None:
    # translate model keys (pm2_5…) → station keys (pm25…) for station_hour_aqi
    sconc = {_MODEL_TO_SKEY[k]: v for k, v in conc.items() if k in _MODEL_TO_SKEY}
    try:
        aqi = float(station_hour_aqi(sconc)["aqi"])
    except Exception:
        return None
    # aqi == 0 means no species could score (all missing/non-finite) — that is
    # NOT a zero-AQI hour; report None so the MAE skips it honestly.
    return aqi if aqi > 0 else None


def _rollout_aqi_mae(
    hours: list[dict[str, Any]], truth: list[tuple[datetime, dict[str, float]]]
) -> float | None:
    """MAE over hours where both forecast p50s and CAMS truth exist."""
    truth_map = {ts: conc for ts, conc in truth}
    errs: list[float] = []
    for h in hours:
        conc = {
            k: v.get("p50") if isinstance(v, dict) else v
            for k, v in (h.get("pollutants") or {}).items()
        }
        conc = {k: float(v) for k, v in conc.items() if v is not None}
        if not conc:
            continue
        ts = datetime.fromisoformat(str(h["timestamp"]))
        t = truth_map.get(ts)
        if not t:
            continue
        aqi_f = _hour_aqi_from_conc(conc)
        aqi_t = _hour_aqi_from_conc(t)
        if aqi_f is None or aqi_t is None:
            continue
        errs.append(abs(aqi_f - aqi_t))
    return sum(errs) / len(errs) if len(errs) >= 24 else None


def _truth_pairs(
    cams_hourly: dict[str, list], start: datetime, end: datetime
) -> list[tuple[datetime, dict[str, float]]]:
    """CAMS concentration tuples for [start, end) — the backtest truth."""
    times = cams_hourly.get("time") or []
    var_map = {
        "pm2_5": "pm2_5", "pm10": "pm10", "no2": "nitrogen_dioxide",
        "so2": "sulphur_dioxide", "o3": "ozone", "co": "carbon_monoxide",
    }
    out: list[tuple[datetime, dict[str, float]]] = []
    for i, stamp in enumerate(times):
        try:
            ts = datetime.fromisoformat(str(stamp))
        except ValueError:
            continue
        if not (start <= ts < end):
            continue
        conc: dict[str, float] = {}
        for mkey, var in var_map.items():
            vals = cams_hourly.get(var) or []
            raw = vals[i] if i < len(vals) else None
            try:
                if raw is not None and float(raw) >= 0:
                    conc[mkey] = float(raw)
            except (TypeError, ValueError):
                pass
        if conc:
            out.append((ts, conc))
    return out


# ── One variant's forecast for one zone (runs the real Chronos machinery) ────

async def _zone_forecast_variant(
    variant: str,
    lat: float,
    lon: float,
    forecast_times: list[str],
    origin: datetime,
    num_samples: int,
) -> tuple[list[dict[str, Any]] | None, str]:
    """Run one serving variant at (lat, lon). Returns (hours, reason)."""
    cams_hourly = await fetch_cams_context(lat, lon)
    history = build_history_series(cams_hourly, origin)
    valid_pm25 = [v for v in history["pm2_5"] if v is not None]
    if len(valid_pm25) < 120:
        return None, f"insufficient zone context ({len(valid_pm25)} valid PM2.5 hours)"

    try:
        if variant == "chronos2_ft":
            met_hourly = await fetch_met_context(lat, lon)
            covariates = _split_covariates(met_hourly, origin)
            covariates.update(_cams_covariate_split(cams_hourly, origin))
            hours, status = predict_72hr_chronos2_finetuned(
                history, covariates, {"hourly": {"time": forecast_times}}, lat=lat, lon=lon
            )
        elif variant == "chronos2":
            met_hourly = await fetch_met_context(lat, lon)
            covariates = _split_covariates(met_hourly, origin)
            covariates.update(_cams_covariate_split(cams_hourly, origin))
            hours, status = predict_72hr_chronos_c2(
                history, {"hourly": {"time": forecast_times}}, covariates
            )
        elif variant == "t5":
            hours, status = predict_72hr_chronos(
                history, {"hourly": {"time": forecast_times}}, num_samples=num_samples
            )
        else:
            return None, f"unknown variant {variant}"
    except Exception as exc:  # network or inference failure → variant loses, run continues
        return None, f"{type(exc).__name__}: {exc}"

    if hours is None:
        return None, str(status.get("reason", "inference failed"))
    return hours, ""


# ── Model selection per zone ─────────────────────────────────────────────────

def _candidate_variants() -> list[str]:
    """Variants actually available right now (gates respected for the ft one)."""
    cands = ["chronos2", "t5"]
    if serving_model() == "chronos2_ft" and finetuned_serving_ready():
        cands.insert(0, "chronos2_ft")
    return cands


async def select_zone_model(
    lat: float,
    lon: float,
    forecast_times: list[str],
    origin: datetime,
    num_samples: int,
) -> dict[str, Any]:
    """Race the available variants on this zone's own CAMS holdout windows.

    Backtest protocol: _BT_ORIGINS rolling origins spaced 72 h apart, each
    rolling 72 h forward; the winner is the lowest AQI MAE across pooled
    windows. Ties/insufficient data → prefer the city-level serving_model().
    """
    cams_bt = await fetch_cams_context(lat, lon, past_days=21)
    variants = _candidate_variants()
    results: dict[str, dict[str, Any]] = {}

    for variant in variants:
        maes: list[float] = []
        for w in range(_BT_ORIGINS):
            bt_origin = origin - timedelta(hours=(w + 1) * _BT_SPACING_H)
            bt_times = [(bt_origin + timedelta(hours=h)).isoformat() for h in range(HORIZON_HOURS)]
            hours, reason = await _zone_forecast_variant(
                variant, lat, lon, bt_times, bt_origin, num_samples
            )
            if hours is None:
                results.setdefault(variant, {"errors": []})["errors"].append(
                    f"w{w}: {reason}"
                )
                break
            truth = _truth_pairs(
                cams_bt, bt_origin, bt_origin + timedelta(hours=HORIZON_HOURS)
            )
            mae = _rollout_aqi_mae(hours, truth)
            if mae is None:
                results.setdefault(variant, {"errors": []})["errors"].append(f"w{w}: unscorable")
                break
            maes.append(mae)
        if maes:
            results[variant] = {
                "aqi_mae": sum(maes) / len(maes),
                "windows_scored": len(maes),
                "window_maes": maes,
            }

    scored = {v: r for v, r in results.items() if "aqi_mae" in r}
    winner = min(scored, key=lambda v: scored[v]["aqi_mae"]) if scored else serving_model()
    return {
        "zone_candidates": variants,
        "zone_scores": results,
        "zone_winner": winner,
        "selection": "measured_per_zone_backtest" if scored else "fallback_city_default",
    }


# ── Zone artifacts (cache the per-zone forecasts for the TTL) ────────────────

def _artifact_path(zone: str) -> Path:
    return _ZONE_ARTIFACTS_DIR / f"{zone}.json"


def _load_zone_artifact(zone: str) -> dict[str, Any] | None:
    p = _artifact_path(zone)
    if not p.is_file():
        return None
    try:
        art = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    gen = art.get("computed_at")
    if not gen:
        return None
    try:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(gen)
    except ValueError:
        return None
    return art if age <= _ZONE_TTL else None


def _save_zone_artifact(zone: str, art: dict[str, Any]) -> None:
    _ZONE_ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    _artifact_path(zone).write_text(
        json.dumps(art, ensure_ascii=False), encoding="utf-8"
    )


# ── Per-zone forecast (context → selection → serving variant) ────────────────

async def forecast_zone(
    cell: tuple[float, float],
    stations: list[dict[str, Any]],
    forecast_times: list[str],
    origin: datetime,
    num_samples: int,
) -> dict[str, Any]:
    """One zone: its own model invocation, own selection race, own artifact.

    The zone context is fetched at the zone cell's representative point
    (mean station coordinates inside the cell); the serving variant is the
    zone's own backtest winner.
    """
    zone = zone_id_for(cell)
    cached = _load_zone_artifact(zone)
    if cached is not None:
        return cached

    lat = round(sum(s["lat"] for s in stations) / len(stations), 4)
    lon = round(sum(s["lon"] for s in stations) / len(stations), 4)

    selection = await select_zone_model(
        lat, lon, forecast_times, origin, num_samples
    )
    variant = selection["zone_winner"]
    hours, reason = await _zone_forecast_variant(
        variant, lat, lon, forecast_times, origin, num_samples
    )
    valid = sum(
        1 for h in (hours or []) if (h.get("pollutants") or {})
    ) if hours else 0
    art: dict[str, Any] = {
        "zone": zone,
        "cell": {"lat": lat, "lon": lon},
        "station_uids": [s["uid"] for s in stations],
        "station_count": len(stations),
        "variant": variant,
        "selection": selection,
        "valid_hours": valid,
        "sufficient": valid >= HORIZON_HOURS * _MIN_VALID_RATIO,
        "reason": reason,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "hourly": hours or [],
    }
    if art["sufficient"]:
        _save_zone_artifact(zone, art)
    return art


# ── All-zones orchestration + station assembly (endpoint-facing) ────────────

async def build_zone_station_layer(
    forecast_times: list[str],
    origin: datetime,
    num_samples: int,
) -> dict[str, Any] | None:
    """Run every zone's own Chronos invocation concurrently, then assemble the
    per-station layer from each station's ZONE curve (not a city curve) plus
    its measured anchor. Returns None when the grid is unusable so the endpoint
    can degrade to the previous city-offset layer honestly.
    """
    if len(forecast_times) < HORIZON_HOURS:
        return None
    cells = zone_cells()
    if not cells:
        return None

    results = await asyncio.gather(
        *(
            forecast_zone(cell, sts, forecast_times, origin, num_samples)
            for cell, sts in cells.items()
        ),
        return_exceptions=True,
    )

    zone_arts: list[dict[str, Any]] = []
    failures: list[str] = []
    ok_by_uid: dict[str, dict[str, Any]] = {}
    for (cell, sts), res in zip(cells.items(), results):
        zid = zone_id_for(cell)
        if isinstance(res, BaseException):
            failures.append(f"{zid}: {type(res).__name__}: {res}")
            continue
        if not res.get("sufficient"):
            failures.append(f"{zid}: {res.get('reason') or 'insufficient valid hours'}")
            continue
        zone_arts.append(res)
        for st in sts:
            ok_by_uid[st["uid"]] = {"zone": res, "station": st}

    if not zone_arts:
        return None

    artifact = load_offsets()
    stations_out: list[dict[str, Any]] = []
    for uid, pair in ok_by_uid.items():
        st = pair["station"]
        zone = pair["zone"]
        offsets = station_offsets_for(uid, artifact)
        calibrated = calibrate_station(st, zone["hourly"], offsets)
        calibrated["zone_id"] = zone["zone"]
        calibrated["zone_variant"] = zone["variant"]
        stations_out.append(calibrated)

    ranked = sorted(
        stations_out, key=lambda s: (s["current"] or {}).get("aqi_cpcb") or 0, reverse=True
    )
    distinct_curves = len(
        {
            json.dumps(
                [
                    (h.get("timestamp"), (h.get("concentrations") or {}).get("pm25"))
                    for h in s["hourly"][:6]
                ]
            )
            for s in stations_out
        }
    )
    return {
        "method": "per-zone Chronos: each CAMS-cell zone runs its own model invocation on its own cell history; per-zone serving variant chosen by measured backtest (AQI MAE on the zone's own CAMS holdout); stations inherit their zone curve and keep their measured anchor (labeled basis)",
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "zone_count": len(zone_arts),
        "zones": [
            {
                "zone": z["zone"],
                "cell": z["cell"],
                "station_count": z["station_count"],
                "variant": z["variant"],
                "selection": z["selection"],
                "valid_hours": z["valid_hours"],
            }
            for z in zone_arts
        ],
        "zone_failures": failures,
        "station_count": len(stations_out),
        "distinct_zone_curves": distinct_curves,
        "stations_measured": sum(1 for s in stations_out if s["offset_basis"] == "measured"),
        "stations_iqair_live": sum(1 for s in stations_out if s["offset_basis"] == "iqair_live"),
        "stations_catalog_prior": sum(
            1 for s in stations_out if s["offset_basis"] == "catalog_prior"
        ),
        "most_polluted": [s["uid"] for s in ranked[:3]],
        "cleanest": [s["uid"] for s in ranked[-3:]],
        "stations": stations_out,
    }
