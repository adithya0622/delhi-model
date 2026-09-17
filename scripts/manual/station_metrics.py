"""Per-station hindcast metrics for every station in the NCR inventory.

Runs the production physics-only 72-h hindcast (the same protocol as
GET /api/v1/validation/backtest: analysis meteorology, leak-free hour-0 anchor,
ML/plume/nudging off, coupling on) at each station's own coordinates, scores it
against the CAMS reanalysis PM2.5 series at those coordinates, and reports
MAE, MSE, RMSE, bias (MBE), Pearson r, R^2 and Nash-Sutcliffe per station.

Usage (from the repo root):
    python scripts/manual/station_metrics.py                 # all 50 stations
    python scripts/manual/station_metrics.py --n 12 --max-windows 3
    python scripts/manual/station_metrics.py --out station_metrics.json

Notes
-----
* Truth is the CAMS reanalysis at the station point, not the CPCB sensor; this
  measures spatial consistency of the coupled model, not ground-truth skill.
* Windows are the most recent `--max-windows` 72-h spans ending >= 3 days ago
  (analysis-archive depth limits how far back this can reach).
* Concurrency is bounded so the Open-Meteo APIs are not hammered.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "backend"))

from app.services.backtest_service import run_hindcast_backtest  # noqa: E402
from app.services.realtime_service import DELHI_NCR_STATIONS  # noqa: E402


def derived(metrics: dict) -> dict:
    """Add MSE and R^2 (squared Pearson r) to a compute_metrics block."""
    out = dict(metrics)
    rmse = metrics.get("rmse_ug_m3")
    r = metrics.get("pearson_r")
    if rmse is not None:
        out["mse_ug_m3"] = round(float(rmse) ** 2, 2)
    out["r2"] = round(float(r) ** 2, 3) if r is not None else None
    return out


async def one(station: dict, sem: asyncio.Semaphore, max_windows: int) -> dict:
    name = str(station.get("name", station.get("uid")))
    lat, lon = float(station["lat"]), float(station["lon"])
    async with sem:
        t0 = time.time()
        try:
            report = await asyncio.wait_for(
                run_hindcast_backtest(
                    max_windows=max_windows,
                    lat=lat,
                    lon=lon,
                    station_name=name,
                ),
                timeout=240,
            )
        except Exception as exc:  # noqa: BLE001 - record and keep going
            return {
                "station": name, "uid": station.get("uid"), "lat": lat, "lon": lon,
                "zone": station.get("zone"), "ok": False,
                "error": f"{type(exc).__name__}: {exc}"[:180],
                "seconds": round(time.time() - t0, 1),
            }
    if not report.get("available"):
        return {
            "station": name, "uid": station.get("uid"), "lat": lat, "lon": lon,
            "zone": station.get("zone"), "ok": False,
            "error": str(report.get("reason"))[:180],
            "seconds": round(time.time() - t0, 1),
        }
    pooled = derived(report["pooled"])
    return {
        "station": name, "uid": station.get("uid"), "lat": lat, "lon": lon,
        "zone": station.get("zone"), "ok": True,
        "windows": len(report.get("windows", [])),
        "seconds": round(time.time() - t0, 1),
        "n": pooled.get("n"),
        "mae_ug_m3": pooled.get("mae_ug_m3"),
        "mse_ug_m3": pooled.get("mse_ug_m3"),
        "rmse_ug_m3": pooled.get("rmse_ug_m3"),
        "bias_mbe_ug_m3": pooled.get("mbe_ug_m3"),
        "pearson_r": pooled.get("pearson_r"),
        "r2": pooled.get("r2"),
        "nash_sutcliffe_e": pooled.get("nash_sutcliffe_e"),
        "mean_obs_ug_m3": pooled.get("mean_obs_ug_m3"),
        "mean_pred_ug_m3": pooled.get("mean_pred_ug_m3"),
        "mae_skill_vs_persistence": (report.get("skill_vs_persistence") or {}).get("mae_skill_score"),
        "bootstrap_mae_ci95": pooled.get("bootstrap_mae_ci95"),
    }


async def main_async(args: argparse.Namespace) -> list[dict]:
    sem = asyncio.Semaphore(args.concurrency)
    stations = DELHI_NCR_STATIONS[: args.n] if args.n else list(DELHI_NCR_STATIONS)
    print(f"running {len(stations)} station hindcasts "
          f"({args.max_windows} x 72 h windows each, concurrency {args.concurrency})")
    return list(await asyncio.gather(*(one(s, sem, args.max_windows) for s in stations)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=0, help="limit to first N stations (0 = all)")
    parser.add_argument("--max-windows", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--out", default="station_metrics.json")
    args = parser.parse_args()

    results = asyncio.run(main_async(args))
    ok = [r for r in results if r.get("ok")]
    bad = [r for r in results if not r.get("ok")]

    def key(r: dict):
        m = r.get("mae_ug_m3")
        return (math.inf if m is None else float(m), r["station"])

    ok.sort(key=key)
    out_path = _ROOT / args.out
    out_path.write_text(json.dumps({"generated": results}, indent=2), encoding="utf-8")

    hdr = (f"{'station':<34}{'n':>5}{'MAE':>8}{'MSE':>10}{'RMSE':>8}"
           f"{'bias':>8}{'r':>7}{'R2':>7}{'NSE':>8}")
    print("\n" + hdr)
    print("-" * len(hdr))
    for r in ok:
        print(f"{r['station'][:33]:<34}{r['n']:>5}{r['mae_ug_m3']:>8}{r['mse_ug_m3']:>10}"
              f"{r['rmse_ug_m3']:>8}{r['bias_mbe_ug_m3']:>8}{r['pearson_r']:>7}"
              f"{r['r2']:>7}{r['nash_sutcliffe_e']:>8}")
    if bad:
        print(f"\n{len(bad)} station(s) failed:")
        for r in bad:
            print(f"  x {r['station']}: {r.get('error')}")
    print(f"\nsaved: {out_path}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())