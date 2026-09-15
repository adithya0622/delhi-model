"""Preflight the Kaggle WRF-Chem notebook's upstream dependencies.

Reads the run configuration straight out of
``scripts/wrfchem/kaggle_wrfchem_run.ipynb`` (START/END, versions, domain
sizes, EDGAR sector map) and HEAD-checks every URL the notebook will fetch, so
a dead link or a missing FIRMS key is found in a minute instead of three hours
into a Kaggle session. Nothing is downloaded and no compiler is needed.

Usage:
    python scripts/wrfchem/preflight.py             # check everything
    python scripts/wrfchem/preflight.py --quiet     # failures only
    python scripts/wrfchem/preflight.py --no-edgar  # skip the 62 sector files

Exit code 0 = every hard dependency answered; 1 = at least one is missing.
FIRMS is a soft dependency: without the key the notebook still runs, it just
skips fire injection (which is the whole point for a stubble window), so a
missing key is reported as a warning.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_NOTEBOOK = _ROOT / "scripts" / "wrfchem" / "kaggle_wrfchem_run.ipynb"
_ENV_PATH = _ROOT / ".env"

_EDGAR_BASE = "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/EDGAR/datasets/v81_FT2022_AP_new"
_WORLDPOP = (
    "https://data.worldpop.org/GIS/Population/Global_2000_2020_1km_UNadj/"
    "2020/IND/ind_ppp_2020_1km_Aggregated_UNadj.tif"
)
_JASPER = "https://github.com/mdadams/jasper/archive/refs/tags/version-1.900.1.zip"
_GEOG = "https://www2.mmm.ucar.edu/wrf/src/wps_files/geog_low_res_mandatory.tar.gz"


def notebook_config() -> dict[str, object]:
    """Extract the notebook's CFG literals (single source of truth for URLs)."""
    source = "".join(
        "".join(cell.get("source", []))
        for cell in json.loads(_NOTEBOOK.read_text(encoding="utf-8"))["cells"]
    )
    cfg: dict[str, object] = {}
    for key, pattern in (
        ("START", r'"START":\s*"([^"]+)"'),
        ("END", r'"END":\s*"([^"]+)"'),
        ("DX_D01", r'"DX_D01":\s*(\d+)'),
        ("DX_D02", r'"DX_D02":\s*(\d+)'),
        ("WRF_VER", r'"WRF_VER":\s*"([^"]+)"'),
        ("WPS_VER", r'"WPS_VER":\s*"([^"]+)"'),
    ):
        match = re.search(pattern, source)
        if not match:
            raise SystemExit(f"could not read {key} from {_NOTEBOOK.name}")
        cfg[key] = int(match.group(1)) if key.startswith("DX") else match.group(1)

    # SECTORS = { "CO": ["ENE", ...], ... } — evaluated, not re-typed, so the
    # preflight cannot drift from the notebook.
    block = re.search(r"SECTORS\s*=\s*(\{.*?\n\})", source, re.S)
    if not block:
        raise SystemExit("could not find the SECTORS map in the notebook")
    cfg["SECTORS"] = ast.literal_eval(block.group(1))
    return cfg


def gfs_urls(start: str, end: str) -> list[str]:
    """The notebook's 6-hourly GFS analysis files over the run window."""
    t = datetime.strptime(start, "%Y-%m-%d_%H")
    t_end = datetime.strptime(end, "%Y-%m-%d_%H")
    urls = []
    while t <= t_end:
        urls.append(
            f"https://noaa-gfs-bdp-pds.s3.amazonaws.com/gfs.{t:%Y%m%d}/"
            f"{t:%H}/atmos/gfs.t{t:%H}z.pgrb2.0p25.anl"
        )
        t += timedelta(hours=6)
    return urls


def head(url: str, timeout: float = 25.0) -> tuple[bool, int, str]:
    """HEAD one URL -> (ok, content_length, detail)."""
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "ncr72-preflight"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return True, int(response.headers.get("Content-Length") or 0), ""
    except urllib.error.HTTPError as exc:
        return False, 0, f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001 - offline/DNS/TLS all mean "not usable"
        return False, 0, type(exc).__name__


def firms_key() -> str:
    """FIRMS_API_KEY from the environment, else from the repo .env."""
    if os.environ.get("FIRMS_API_KEY", "").strip():
        return os.environ["FIRMS_API_KEY"].strip()
    if _ENV_PATH.is_file():
        for line in _ENV_PATH.read_text(encoding="utf-8", errors="ignore").splitlines():
            match = re.match(r"^\s*FIRMS_API_KEY\s*=\s*(.*)$", line)
            if match:
                return match.group(1).strip().strip('"\'')
    return ""


def firms_probe(day: str, key: str) -> dict[str, object]:
    """Detections in the stubble belt for the run window's first day."""
    box = "73,26.5,82.5,33"
    out: dict[str, object] = {}
    for source in ("VIIRS_SNPP_SP", "MODIS_SP"):
        url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{source}/{box}/3/{day}"
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                body = response.read().decode("utf-8", "replace")
            rows = max(0, len(body.strip().splitlines()) - 1)
            out[source] = rows if "Invalid" not in body[:200] else f"rejected: {body[:80]!r}"
        except Exception as exc:  # noqa: BLE001
            out[source] = f"error: {type(exc).__name__}"
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quiet", action="store_true", help="print failures and the verdict only")
    parser.add_argument("--no-edgar", action="store_true", help="skip the 62 EDGAR sector files")
    parser.add_argument("--workers", type=int, default=8, help="parallel HEAD requests (default 8)")
    args = parser.parse_args()

    cfg = notebook_config()
    sectors = cfg["SECTORS"]  # type: ignore[assignment]
    print(f"notebook : {_NOTEBOOK.name}")
    print(f"window   : {cfg['START']} -> {cfg['END']} UTC (6-hourly GFS analyses)")
    print(f"domains  : {cfg['DX_D01']} m / {cfg['DX_D02']} m, WRF {cfg['WRF_VER']} + WPS {cfg['WPS_VER']}")
    print(f"EDGAR    : {sum(len(v) for v in sectors.values())} sector files across {len(sectors)} species")

    targets: list[tuple[str, str]] = []
    for url in gfs_urls(str(cfg["START"]), str(cfg["END"])):
        targets.append(("GFS", url))
    targets += [
        ("WRF source", f"https://codeload.github.com/wrf-model/WRF/tar.gz/refs/tags/{cfg['WRF_VER']}"),
        ("WPS source", f"https://codeload.github.com/wrf-model/WPS/tar.gz/refs/tags/{cfg['WPS_VER']}"),
        ("jasper", _JASPER),
        ("WPS geography", _GEOG),
        ("WorldPop", _WORLDPOP),
    ]
    if not args.no_edgar:
        for species, sector_list in sectors.items():  # type: ignore[union-attr]
            for sector in sector_list:
                targets.append(
                    (
                        "EDGAR",
                        f"{_EDGAR_BASE}/{species}/{sector}/emi_nc/"
                        f"v8.1_FT2022_AP_{species}_2022_{sector}_emi_nc.zip",
                    )
                )

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        results = list(pool.map(lambda item: (item[0], item[1]) + head(item[1]), targets))

    failures = [r for r in results if not r[2]]
    by_group: dict[str, list[tuple[bool, int]]] = {}
    for group, _url, ok, size, _detail in results:
        by_group.setdefault(group, []).append((ok, size))

    print("\n-- upstream check " + "-" * 46)
    for group, entries in by_group.items():
        ok_n = sum(1 for ok, _ in entries if ok)
        total_mb = sum(size for _, size in entries) / 1e6
        status = "OK " if ok_n == len(entries) else "FAIL"
        print(f"  {status} {group:<14} {ok_n}/{len(entries)} reachable, {total_mb:,.0f} MB")
    if failures and not args.quiet:
        print("\n  unreachable:")
        for group, url, _ok, _size, detail in failures:
            print(f"    x [{group}] {detail} {url}")

    key = firms_key()
    print("\n-- FIRMS fire injection " + "-" * 40)
    if not key:
        print("  WARN FIRMS_API_KEY not found (env or .env) - the notebook will skip fires.")
        print("       Add it as a Kaggle Secret named FIRMS_API_KEY before the run.")
    else:
        day = str(cfg["START"]).replace("_", " ").split()[0]
        for source, value in firms_probe(day, key).items():
            print(f"  OK   {source:<14} {value} detections on {day} (day_range 3)")

    gfs_mb = sum(size for ok, size in by_group.get("GFS", []) if ok) / 1e6
    print("\n-- verdict " + "-" * 55)
    if failures:
        print(f"  NO-GO: {len(failures)} unreachable URL(s). Fix these before spending a session.")
    else:
        print("  GO: every hard dependency answered.")
    print(f"  GFS download in-session: ~{gfs_mb / 1e3:.1f} GB, plus WRF build and wrfout.")
    print("  expected Kaggle wall clock: compile 50-80 min + WPS/real ~25 min + chemi ~10 min + 72 h run ~2 h")
    print("  after the run: download wrfout_delhi.tar.gz -> scripts/wrfchem/fetch_wrfout.py <tar> --set")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
