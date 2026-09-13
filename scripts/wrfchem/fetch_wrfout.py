"""Validate a downloaded WRF-Chem tarball and wire WRF_OUTPUT_DIR.

The last step of the free-Kaggle WRF-Chem plan: untar the wrfout archive the
notebook produces, verify the files actually contain what
``backend/app/services/wrf_service.py`` reads (Delhi-covering grid, PM2.5
chemistry variables, a time dimension), then optionally set ``WRF_OUTPUT_DIR``
in the backend .env.

Usage:
    python scripts/wrfchem/fetch_wrfout.py wrfout_delhi.tar.gz            # validate only
    python scripts/wrfchem/fetch_wrfout.py wrfout_delhi.tar.gz --set      # + write .env
    python scripts/wrfchem/fetch_wrfout.py wrfout_delhi.tar.gz --dest D:\\delhi-wrf
"""

from __future__ import annotations

import argparse
import re
import sys
import tarfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_ENV_PATH = _ROOT / ".env"
_DEFAULT_DEST = _ROOT / "data" / "wrfout"

# Delhi point the extractor targets (kept in sync with wrf_service.py).
_DELHI_LAT, _DELHI_LON = 28.6139, 77.2090
# Required variable for the Delhi-point PM2.5 extraction.
_PM_VARS = ("PM25_TOT", "PM2_5_DRY")


def _env_dir() -> Path:
    """Configured WRF_OUTPUT_DIR, or None when unset."""
    raw = ""
    if _ENV_PATH.is_file():
        for line in _ENV_PATH.read_text(encoding="utf-8", errors="ignore").splitlines():
            m = re.match(r"^\s*WRF_OUTPUT_DIR\s*=\s*(.*)$", line)
            if m:
                raw = m.group(1).strip().strip('"')
                break
    return Path(raw) if raw else _DEFAULT_DEST


def extract(tar_path: Path, dest: Path) -> list[Path]:
    """Untar into dest (flat), returning the wrfout file paths."""
    dest.mkdir(parents=True, exist_ok=True)
    if not tarfile.is_tarfile(tar_path):
        raise SystemExit(f"not a tar archive: {tar_path}")
    out: list[Path] = []
    with tarfile.open(tar_path) as tf:
        for member in tf.getmembers():
            if not member.isfile() or "wrfout" not in Path(member.name).name:
                continue
            # Flat extraction under dest; basename only — never trust archive paths.
            target = dest / Path(member.name).name
            with tf.extractfile(member) as src, open(target, "wb") as dst:
                shutil_copy(src, dst)
            out.append(target)
    if not out:
        raise SystemExit(f"no wrfout files found inside {tar_path}")
    return out


def shutil_copy(src, dst) -> None:  # small indirection keeps extract() readable
    import shutil

    shutil.copyfileobj(src, dst)


def validate(files: list[Path]) -> dict[str, object]:
    """Check the files against wrf_service's reader contract."""
    try:
        import numpy as np  # noqa: F401
        import xarray as xr
    except ImportError:
        print("xarray/netCDF4 not installed — skipping deep validation "
              "(pip install xarray netCDF4). Files extracted unvalidated.")
        return {"validated": False, "files": [str(f) for f in files]}

    report: dict[str, object] = {"validated": True, "files": [], "problems": []}
    problems: list[str] = []
    checked = 0
    for path in files[:3]:  # spot-check up to 3 files
        try:
            ds = xr.open_dataset(path, decode_times=False)
        except Exception as exc:
            problems.append(f"{path.name}: not readable as NetCDF ({exc})")
            continue
        try:
            names = set(map(str, ds.data_vars))
            missing = [v for v in _PM_VARS if v not in names]
            if not missing:
                pm_var = "PM25_TOT"
            elif "PM2_5_DRY" in names:
                pm_var = "PM2_5_DRY"
            else:
                problems.append(f"{path.name}: no PM25_TOT/PM2_5_DRY — is this a WRF-Chem run?")
                continue

            lat = ds["XLAT"].isel(Time=0)
            lon = ds["XLONG"].isel(Time=0)
            d2 = (lat - _DELHI_LAT) ** 2 + (lon - _DELHI_LON) ** 2
            nearest_deg = float(np.sqrt(float(d2.min())))
            if nearest_deg > 0.5:  # ~55 km; the domain must cover Delhi
                problems.append(f"{path.name}: nearest grid point {nearest_deg:.2f}° from Delhi — wrong domain?")

            n_times = int(ds.sizes.get("Time", 0))
            if n_times == 0:
                problems.append(f"{path.name}: Time dimension is empty")

            report["files"].append({
                "name": path.name,
                "pm_variable": pm_var,
                "times": n_times,
                "grid": [int(ds.sizes.get("south_north", 0)), int(ds.sizes.get("west_east", 0))],
                "delhi_nearest_deg": round(nearest_deg, 3),
                "size_mb": round(path.stat().st_size / 1e6, 1),
            })
            checked += 1
        finally:
            ds.close()
    if checked == 0:
        problems.append("no file passed validation")
    report["problems"] = problems
    return report


def set_env(directory: Path) -> None:
    """Set/replace WRF_OUTPUT_DIR in .env (creates the line when absent)."""
    lines: list[str] = []
    if _ENV_PATH.is_file():
        lines = _ENV_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
    replaced = False
    for i, line in enumerate(lines):
        if re.match(r"^\s*WRF_OUTPUT_DIR\s*=", line):
            lines[i] = f"WRF_OUTPUT_DIR={directory}"
            replaced = True
            break
    if not replaced:
        lines.append(f"WRF_OUTPUT_DIR={directory}")
    _ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f".env updated: WRF_OUTPUT_DIR={directory}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tarball", type=Path, help="wrfout tarball downloaded from Kaggle")
    parser.add_argument("--dest", type=Path, default=None, help="extraction directory (default: data/wrfout)")
    parser.add_argument("--set", action="store_true", help="write WRF_OUTPUT_DIR into .env after validation")
    args = parser.parse_args()

    dest = args.dest or _env_dir()
    print(f"extracting {args.tarball.name} -> {dest}")
    files = extract(args.tarball, dest)
    print(f"  {len(files)} wrfout files")

    report = validate(files)
    if report.get("validated"):
        for f in report["files"]:  # type: ignore[index]
            print(f"  OK {f['name']}: {f['pm_variable']} ×{f['times']}h grid={f['grid']} delhiΔ={f['delhi_nearest_deg']}° {f['size_mb']}MB")
        problems = report["problems"]  # type: ignore[index]
        if problems:
            print("\nPROBLEMS:")
            for p in problems:
                print(f"  ✗ {p}")
            return 1
        print("\nvalidation passed")
    if args.set:
        set_env(dest)
        print("\nrestart the backend, then:")
        print(f"  GET /api/v1/validation/wrf-status          -> available: true")
        print(f"  GET /api/v1/validation/wrf-compare?run={files[0].name}")
    else:
        print(f"\nadd to .env to enable comparison:\n  WRF_OUTPUT_DIR={dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
