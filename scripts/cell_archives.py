"""Parameterized CAMS/HRES archive loading for arbitrary coordinates.

Why
---
The published Chronos-2 evaluation is anchored to the single CAMS cell
containing the Delhi city point (28.6139, 77.2090) — the series the six
specialists were trained on (``scripts/train_pm25_v3.py::load_history``).
To score each NCR station against truth at its OWN coordinates (the chosen,
leak-free basis), this module fetches the SAME Open-Meteo archive variables
for any (lat, lon), reusing the existing fetch/merge machinery so the data
contract is byte-identical to training.

The CAMS grid (empirically determined 2026-09-17)
--------------------------------------------------
Open-Meteo's CAMS archive serves 0.4-degree (~40 km) cells whose boundaries
sit at 0.4*k + 0.2 for integer k. Verified by fetching 1-day pm2_5 series
around the city point:

  * lon 77.009 .. 77.359 identical to the city series; 76.909 and 77.409+ differ
    -> lon cell [77.0, 77.4)
  * lat 28.6639 .. 28.9639 identical; 28.5639 and 29.0139 differ
    -> lat cell [28.6, 29.0)

So: ``cell_key(lat, lon) = (floor((lat-0.2)/0.4), floor((lon-0.2)/0.4))`` and
any interior point of a cell returns the same series. The 50 NCR stations fall
into 5 distinct cells; the city cell (28.6-29.0 N, 77.0-77.4 E) holds ~35 of
them and is exactly the cell the specialists were trained on.

Caching
-------
Archives are cached as ``cams_cell_<lat>_<lon>_<a>_<b>.json`` and
``met_cell_<lat>_<lon>_<a>_<b>.json`` under ``data_cache/`` (same 90-day
chunking as training). A failed chunk writes ``*.FAILED.marker`` so runs are
resumable and failures stay visible.

Usage:
    python scripts/cell_archives.py probe            # verify grid formula
    python scripts/cell_archives.py cells            # print station grouping
    python scripts/cell_archives.py fetch            # fetch non-city cell archives
    python scripts/cell_archives.py fetch --months 4 # smoke fetch
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "backend"))
sys.path.insert(0, str(_ROOT / "scripts"))

import train_pm25_v3 as tv3  # noqa: E402  (reuses _fetch_archive / _dateranges / vars / _merge)

from app.services.realtime_service import DELHI_NCR_STATIONS  # noqa: E402

_CACHE_DIR = _ROOT / "data_cache"
_COVER_MONTHS = 14                     # 12-month holdout + 720 h context + 72 h horizon
_COVER_DAYS = int(_COVER_MONTHS * 30.44)
_GRID_STEP = 0.4
_GRID_OFFSET = 0.2
_CITY = (28.6139, 77.2090)
# (71, 192): lat [28.6, 29.0), lon [77.0, 77.4) — the specialists' training cell.
_CITY_KEY = (math.floor((_CITY[0] - _GRID_OFFSET) / _GRID_STEP),
             math.floor((_CITY[1] - _GRID_OFFSET) / _GRID_STEP))


def cell_key(lat: float, lon: float) -> tuple[int, int]:
    """(lat_band, lon_band) of the 0.4-degree CAMS cell containing the point."""
    return (
        math.floor((float(lat) - _GRID_OFFSET) / _GRID_STEP),
        math.floor((float(lon) - _GRID_OFFSET) / _GRID_STEP),
    )


def cell_center(key: tuple[int, int]) -> tuple[float, float]:
    """Interior representative point of a cell (its lower edge + 0.2)."""
    return (
        round(_GRID_OFFSET + key[0] * _GRID_STEP + _GRID_STEP / 2, 4),
        round(_GRID_OFFSET + key[1] * _GRID_STEP + _GRID_STEP / 2, 4),
    )


# ----------------------------------------------------------------- fetching --
def cell_cache_paths(lat: float, lon: float, a: date, b: date) -> tuple[Path, Path]:
    tag = f"{lat:.4f}_{lon:.4f}_{a.isoformat()}_{b.isoformat()}"
    return (
        _CACHE_DIR / f"cams_cell_{tag}.json",
        _CACHE_DIR / f"met_cell_{tag}.json",
    )


async def _fetch_one_cell(
    client: httpx.AsyncClient,
    lat: float,
    lon: float,
    a: date,
    b: date,
) -> tuple[bool, str]:
    """Fetch one 90-day chem+met chunk for one cell; cache both. True on success."""
    cfile, mfile = cell_cache_paths(lat, lon, a, b)
    fail_c = cfile.with_suffix(".FAILED.marker")
    fail_m = mfile.with_suffix(".FAILED.marker")
    if cfile.is_file() and mfile.is_file():
        return True, "cached"
    try:
        c_hourly = await tv3._fetch_archive(client, tv3._CAMS, tv3._CHEM_VARS, a, b, lat=lat, lon=lon)
        m_hourly = await tv3._fetch_archive(client, tv3._HRES, tv3._MET_VARS, a, b, lat=lat, lon=lon)
        cfile.write_text(json.dumps(c_hourly), encoding="utf-8")
        mfile.write_text(json.dumps(m_hourly), encoding="utf-8")
        fail_c.unlink(missing_ok=True)
        fail_m.unlink(missing_ok=True)
        return True, "fetched"
    except Exception as exc:  # noqa: BLE001 - record and let the caller decide
        if not cfile.is_file():
            fail_c.write_text(f"{type(exc).__name__}: {exc}", encoding="utf-8")
        if not mfile.is_file():
            fail_m.write_text(f"{type(exc).__name__}: {exc}", encoding="utf-8")
        return False, f"{type(exc).__name__}: {exc}"[:160]


def _fetch_cell_range(lat: float, lon: float, days: int, concurrency: int = 4) -> dict:
    """Fetch ``days`` of chem+met archives for one cell, 90-day chunks, bounded."""
    end = date(2026, 9, 12)
    start = end - timedelta(days=days)
    chunks = list(tv3._dateranges(start, end))

    async def _guarded(client, la, lo, a, b, sem):
        async with sem:
            ok, note = await _fetch_one_cell(client, la, lo, a, b)
        return ok, note, (a, b)

    async def _run() -> list:
        results = []
        limits = httpx.Limits(max_connections=concurrency)
        sem = asyncio.Semaphore(concurrency)
        async with httpx.AsyncClient(timeout=90.0, limits=limits) as client:
            tasks = [asyncio.create_task(_guarded(client, lat, lon, a, b, sem)) for a, b in chunks]
            for fut in asyncio.as_completed(tasks):
                ok, note, span = await fut
                results.append((span, ok, note))
        return results

    t0 = time.time()
    results = asyncio.run(_run())
    ok = sum(1 for _, o, _ in results if o)
    return {
        "lat": lat,
        "lon": lon,
        "chunks_ok": ok,
        "chunks_total": len(results),
        "failed": [(str(a), str(b), n) for (a, b), o, n in results if not o],
        "seconds": round(time.time() - t0, 1),
    }


def merge_hourly(store: dict, hourly: dict) -> None:
    """Merge one Open-Meteo hourly payload into a stamp->row dict.

    Mirrors the nested _merge inside train_pm25_v3.load_history exactly
    (same _VAR_RENAME renames, same fromisoformat stamps, same None skip).
    """
    times = hourly.get("time") or []
    for i, stamp in enumerate(times):
        try:
            key = datetime.fromisoformat(stamp)
        except ValueError:
            continue
        row = store.setdefault(key, {})
        for var, values in hourly.items():
            if var == "time":
                continue
            value = values[i] if i < len(values) else None
            if value is not None:
                row[tv3._VAR_RENAME.get(var, var)] = float(value)


def merge_cell_history(lat: float, lon: float, days: int) -> tuple[dict, dict]:
    """Merge cached cell chunks into (chem, met) dicts exactly like load_history."""
    end = date(2026, 9, 12)
    start = end - timedelta(days=days)
    chem: dict[datetime, dict[str, float]] = {}
    met: dict[datetime, dict[str, float]] = {}
    for a, b in tv3._dateranges(start, end):
        cfile, mfile = cell_cache_paths(lat, lon, a, b)
        if not (cfile.is_file() and mfile.is_file()):
            raise FileNotFoundError(f"cell ({lat}, {lon}) chunk {a}..{b} missing — fetch first")
        merge_hourly(chem, json.loads(cfile.read_text(encoding="utf-8")))
        merge_hourly(met, json.loads(mfile.read_text(encoding="utf-8")))
    return chem, met


# ------------------------------------------------------------------- probe --
def _probe_series(lat: float, lon: float) -> list[float | None]:
    """One-day hourly CAMS pm2_5 at a point (no cache; tiny request)."""

    async def _run() -> list[float | None]:
        async with httpx.AsyncClient(timeout=60.0) as client:
            payload = await client.get(
                tv3._CAMS,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "hourly": "pm2_5",
                    "start_date": "2026-09-10",
                    "end_date": "2026-09-11",
                    "timezone": "Asia/Kolkata",
                },
            )
            payload.raise_for_status()
            return (payload.json().get("hourly") or {}).get("pm2_5") or []

    return asyncio.run(_run())


def probe_cells() -> dict:
    """Verify the discovered grid formula with fresh boundary requests."""
    lat0, lon0 = _CITY
    base = _probe_series(lat0, lon0)
    checks: dict[str, dict] = {}

    def _check(name: str, la: float, lo: float, expect_same: bool) -> None:
        ser = _probe_series(la, lo)
        same = ser == base
        checks[name] = {
            "point": [la, lo],
            "identical_to_base": same,
            "expected_same_cell": expect_same,
            "ok": same == expect_same,
        }
        print(f"  {name:<26} ({la:.4f}, {lo:.4f}) identical={same} expected={expect_same} "
              f"{'OK' if same == expect_same else 'MISMATCH'}", flush=True)

    # Inside the city cell (should match).
    _check("center (28.8, 77.2)", 28.8, 77.2, True)
    _check("S-in-cell (28.65)", 28.65, lon0, True)
    _check("W-in-cell (77.05)", lat0, 77.05, True)
    _check("E-in-cell (77.35)", lat0, 77.35, True)
    # Outside (should differ).
    _check("S-out (28.55)", 28.55, lon0, False)
    _check("E-out (77.45)", lat0, 77.45, False)
    _check("W-out (76.95)", lat0, 76.95, False)
    n_bad = sum(1 for c in checks.values() if not c["ok"])
    print(f"  formula check: {len(checks) - n_bad}/{len(checks)} OK")
    return {"all_ok": n_bad == 0, "checks": checks}


def distinct_cells(stations: list[dict] | None = None) -> dict[tuple[int, int], list[dict]]:
    """Group stations into their true CAMS cells: {cell_key: [station dicts]}."""
    stations = stations if stations is not None else DELHI_NCR_STATIONS
    cells: dict[tuple[int, int], list[dict]] = {}
    for st in stations:
        cells.setdefault(cell_key(float(st["lat"]), float(st["lon"])), []).append(st)
    return cells


# -------------------------------------------------------------------- main --
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("probe", help="verify the 0.4-degree grid formula")
    sub.add_parser("cells", help="print the station -> cell grouping")

    p_fetch = sub.add_parser("fetch", help="fetch non-city cell archives")
    p_fetch.add_argument("--months", type=int, default=_COVER_MONTHS)
    p_fetch.add_argument("--cells", type=str, default=None,
                         help="semicolon-separated 'lat,lon' pairs; default: all non-city cell centers")
    p_fetch.add_argument("--concurrency", type=int, default=4)

    args = parser.parse_args()

    if args.cmd == "probe":
        report = probe_cells()
        return 0 if report["all_ok"] else 1

    if args.cmd == "cells":
        cells = distinct_cells()
        print(f"{len(cells)} distinct CAMS cells for {sum(len(v) for v in cells.values())} stations:\n")
        for key in sorted(cells):
            la, lo = cell_center(key)
            names = [s["name"] for s in cells[key]]
            tag = "  <- CITY CELL (specialists' training cell)" if key == _CITY_KEY else ""
            print(f"  cell {key} center ({la:.2f}, {lo:.2f})  n={len(names):2d}{tag}")
            print(f"    {', '.join(names)}\n")
        return 0

    days = int(args.months * 30.44)
    if args.cells:
        points = [tuple(float(x) for x in pair.split(",")) for pair in args.cells.split(";")]
    else:
        points = []
        for key in sorted(distinct_cells()):
            if key == _CITY_KEY:
                continue  # city cell: reuse the existing training-point archives
            points.append(cell_center(key))
    print(f"fetching {len(points)} non-city cells x {args.months} months (chem+met)...", flush=True)
    failures = []
    for lat, lon in points:
        res = _fetch_cell_range(lat, lon, days, concurrency=args.concurrency)
        print(
            f"  cell ({lat:.4f}, {lon:.4f}): {res['chunks_ok']}/{res['chunks_total']} chunks "
            f"in {res['seconds']}s" + (f"  FAILED={res['failed']}" if res["failed"] else ""),
            flush=True,
        )
        if res["failed"]:
            failures.append(res)
    if failures:
        print(f"\n{len(failures)} cell(s) with failed chunks — rerun to retry (resumable).")
        return 1
    print("\nall cells cached.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
