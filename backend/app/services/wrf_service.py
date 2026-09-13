"""WRF-Chem offline reference adapter (offline runs, live comparison).

Why offline: a live WRF-Chem run needs Linux HPC or a free Kaggle/Colab
session (see ``scripts/wrfchem/kaggle_wrfchem_run.ipynb``), ERA5/GFS boundary
data, FINN/EDGAR emissions and hours per 72h window. The API keeps serving the
seconds-return surrogate while WRF-Chem runs offline as the high-fidelity
reference for the same validation windows. When ``WRF_OUTPUT_DIR`` points at
a directory of wrfout_* NetCDF files, this module lists runs, extracts the
Delhi-point PM2.5 series and scores it against the CAMS reanalysis used by the
hindcast backtest; otherwise every accessor raises a 501-class
``RuntimeError`` with the setup steps instead of pretending.

Extraction notes: real WRF-Chem v4.x wrfout carries PM2.5 in ``PM2_5_DRY``
which the registry (Registry/registry.chem) declares in **native µg m⁻³** —
read directly, no density conversion (applying the µg/kg mixing-ratio
conversion here inflated values ~1000×). Some configurations also write a
pre-diagnosed ``PM25_TOT``. ``extract_delhi_pm25_series`` prefers the latter
and otherwise takes the near-surface (first model) layer of ``PM2_5_DRY``.
"""

from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DELHI_LAT, _DELHI_LON = 28.6139, 77.2090


def wrf_output_dir() -> Path | None:
    """Configured WRF-Chem output directory, or None when unset."""
    raw = os.environ.get("WRF_OUTPUT_DIR", "").strip()
    if not raw:
        return None
    return Path(raw)


def wrf_status() -> dict[str, Any]:
    """Machine-readable WRF-Chem availability for /validation/wrf-status."""
    directory = wrf_output_dir()
    if directory is None:
        return {
            "available": False,
            "reason": "WRF_OUTPUT_DIR is not set; WRF-Chem runs offline on HPC, not in this container",
            "setup": [
                "Install WRF-Chem v4.x + WPS on Linux HPC",
                "Domains: outer 12km IGP, inner 4km/1.3km NCR nest",
                "Boundary: ERA5/GFS; emissions: FINN fire + EDGAR/SAFAR; chemistry: MOZART/MOSAIC",
                "Point WRF_OUTPUT_DIR at the wrfout NetCDF directory and re-query",
            ],
        }
    files = sorted(directory.glob("wrfout_*")) if directory.is_dir() else []
    return {
        "available": bool(files),
        "output_dir": str(directory),
        "runs": [f.name for f in files[:50]],
        "run_count": len(files),
        "reason": None if files else f"no wrfout_* files in {directory}",
    }


def _require_xarray() -> Any:
    try:
        import xarray as xr  # optional dep, offline analysis only
        return xr
    except ImportError as exc:
        raise RuntimeError(
            "xarray/netCDF4 not installed; WRF-Chem comparison runs offline, not in the serving container"
        ) from exc


def extract_delhi_pm25_series(run_path: Path) -> tuple[list[dict[str, Any]], str]:
    """Surface PM2.5 [µg/m³] at the Delhi point from one wrfout file.

    Prefers a pre-diagnosed ``PM25_TOT``; otherwise reads ``PM2_5_DRY`` —
    declared in the WRF v4.6.0 registry with units "ug m^-3" — taking the
    near-surface (first model) layer. Times are UTC ISO strings.
    Raises RuntimeError with a precise reason instead of returning junk.
    """
    xr = _require_xarray()
    if not run_path.is_file():
        raise RuntimeError(f"WRF run not found: {run_path}")
    try:
        ds = xr.open_dataset(run_path, decode_times=False)
    except Exception as exc:
        raise RuntimeError(f"cannot open {run_path.name} as NetCDF: {exc}") from exc

    try:
        lat2d = ds["XLAT"].isel(Time=0)
        lon2d = ds["XLONG"].isel(Time=0)
        dist2 = (lat2d - _DELHI_LAT) ** 2 + (lon2d - _DELHI_LON) ** 2
        iy, ix = divmod(int(dist2.argmin()), int(dist2.sizes["west_east"]))

        times: list[str] = []
        for raw in ds["Times"].values:
            chars = bytes(raw).decode("ascii", errors="ignore") if raw.ndim else str(raw)
            stamp = chars.strip()
            try:
                times.append(datetime.strptime(stamp, "%Y-%m-%d_%H:%M:%S").replace(tzinfo=timezone.utc).isoformat())
            except ValueError:
                times.append(stamp)

        if "PM25_TOT" in ds.data_vars:
            series = ds["PM25_TOT"][:, :, iy, ix].sum(dim="bottom_top", skipna=True)
            method = "PM25_TOT (pre-diagnosed), summed over column"
        elif "PM2_5_DRY" in ds.data_vars:
            # Registry v4.6.0: PM2_5_DRY is a GOCART diagnostic in native ug m^-3
            # (mixing-ratio + rho conversion would inflate ~1000x). Take the
            # near-surface layer as the surface concentration.
            series = ds["PM2_5_DRY"][:, 0, iy, ix]
            method = "PM2_5_DRY near-surface layer (native ug/m-3, registry-verified)"
        else:
            raise RuntimeError(
                f"{run_path.name}: no PM25_TOT or PM2_5_DRY — is this a WRF-Chem run?"
            )
        values = [None if not math.isfinite(float(v)) else round(float(v), 2) for v in series.values]
        return [
            {"time": t, "pm25_ug_m3": v}
            for t, v in zip(times, values)
        ], method
    finally:
        ds.close()


def _hour_key(stamp: str) -> str:
    """Normalise any ISO-ish stamp to 'YYYY-MM-DDTHH' so wrfout times
    ('2025-11-10T00:00:00+00:00'), CAMS archive times ('2025-11-10T00:00') and
    surrogate rows all pair on the same key. Unparseable stamps pair on their
    own raw value, which simply never matches — the honest outcome.
    """
    return str(stamp)[:13]


def compare_surrogate_to_wrf(run_id: str, surrogate: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Score WRF-Chem (and optionally the surrogate) against CAMS truth.

    ``surrogate`` is an optional list of ``{time, pm25_ug_m3}`` rows (e.g. from a
    saved hindcast). When absent, WRF is scored against the CAMS reanalysis
    archive alone — the same independent upstream the backtest uses — so the
    endpoint always reports a defensible intercomparison, never a fabricated one.
    """
    directory = wrf_output_dir()
    if directory is None:
        raise RuntimeError("WRF-Chem reference unavailable: WRF_OUTPUT_DIR is not set")
    target = directory / run_id
    wrf_rows, method = extract_delhi_pm25_series(target)

    wrf_by_time = {
        _hour_key(row["time"]): row["pm25_ug_m3"]
        for row in wrf_rows
        if row["pm25_ug_m3"] is not None
    }
    cams_rows = {_hour_key(k): v for k, v in _fetch_cams_series(sorted(wrf_by_time)).items()}

    pairs = []
    for stamp, wrf_val in sorted(wrf_by_time.items()):
        cams_val = cams_rows.get(stamp)
        if cams_val is None:
            continue
        pairs.append((wrf_val, cams_val))

    report: dict[str, Any] = {
        "run_id": run_id,
        "extraction_method": method,
        "wrf_hours": len(wrf_by_time),
        "matched_hours": len(pairs),
        "note": "pair with CPCB truth in validation_service before quoting skill against ground monitors",
    }
    if surrogate:
        surr_by_time = {
            _hour_key(r["time"]): r["pm25_ug_m3"]
            for r in surrogate
            if r.get("pm25_ug_m3") is not None
        }
        surr_pairs = [(surr_by_time[t], w) for t, w in sorted(wrf_by_time.items()) if t in surr_by_time]
        report["surrogate_vs_wrf"] = _metric_block([p[0] for p in surr_pairs], [p[1] for p in surr_pairs], "surrogate", "WRF-Chem")
    if pairs:
        report["wrf_vs_cams"] = _metric_block(
            [p[0] for p in pairs], [p[1] for p in pairs], "WRF-Chem", "CAMS reanalysis"
        )
    if not pairs and not surrogate:
        report["available"] = False
        report["reason"] = "no overlapping hours between wrfout times and CAMS archive"
    else:
        report["available"] = True
    return report


def _metric_block(a: list[float], b: list[float], a_name: str, b_name: str) -> dict[str, Any]:
    """Shared metric arithmetic for a paired series comparison."""
    n = len(a)
    if n == 0:
        return {"n": 0}
    mae = sum(abs(x - y) for x, y in zip(a, b)) / n
    rmse = math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)) / n)
    mean_a = sum(a) / n
    mean_b = sum(b) / n
    var_a = sum((x - mean_a) ** 2 for x in a)
    var_b = sum((y - mean_b) ** 2 for y in b)
    cov = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
    r = cov / math.sqrt(var_a * var_b) if var_a > 0 and var_b > 0 else None
    nse = 1.0 - sum((x - y) ** 2 for x, y in zip(a, b)) / var_b if var_b > 0 else None
    return {
        "n": n,
        "left": a_name,
        "right": b_name,
        "mae_ug_m3": round(mae, 3),
        "rmse_ug_m3": round(rmse, 3),
        "pearson_r": round(r, 4) if r is not None else None,
        "nash_sutcliffe": round(nse, 4) if nse is not None else None,
        "mean_left_ug_m3": round(mean_a, 2),
        "mean_right_ug_m3": round(mean_b, 2),
    }


def _fetch_cams_series(times: list[str]) -> dict[str, float]:
    """CAMS reanalysis PM2.5 at the Delhi point for the given UTC ISO hours.

    Uses the Open-Meteo air-quality archive — the same independent truth
    upstream as the hindcast backtest. Keyless; network failures raise so the
    caller can report unavailability honestly rather than comparing to NaNs.
    """
    import httpx

    if not times:
        return {}
    start = min(times)[:13]
    end = max(times)[:13]
    response = httpx.get(
        "https://air-quality-api.open-meteo.com/v1/air-quality",
        params={
            "latitude": _DELHI_LAT,
            "longitude": _DELHI_LON,
            "hourly": "pm2_5",
            "start_hour": f"{start}:00",
            "end_hour": f"{end}:00",
            "timezone": "UTC",
        },
        timeout=30.0,
    )
    response.raise_for_status()
    hourly = response.json().get("hourly", {})
    return {
        stamp: float(v)
        for stamp, v in zip(hourly.get("time", []), hourly.get("pm2_5", []))
        if v is not None
    }


def compare_against_wrf(run_id: str) -> dict[str, Any]:
    """Inspect one WRF-Chem run's variables (requires NetCDF stack)."""
    status = wrf_status()
    if not status.get("available"):
        raise RuntimeError(f"WRF-Chem reference unavailable: {status.get('reason')}")
    xr = _require_xarray()
    directory = wrf_output_dir()
    target = directory / run_id
    if not target.is_file():
        raise RuntimeError(f"WRF run not found: {run_id}")
    ds = xr.open_dataset(target, decode_times=False)
    try:
        vars_present = sorted(map(str, ds.data_vars))
    finally:
        ds.close()
    return {"run_id": run_id, "variables": vars_present, "note": "pair with CPCB truth in validation_service before quoting skill"}
