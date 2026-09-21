"""Distribution diagnostics for the training archive species (CO/PM10/PM2.5).

Explains why an absolute RMSE is large for a species: RMSE is in the species'
own units, so it inherits that species' scale and tail. This prints, per
species, mean/median/p95/p99/max, tail ratios, coefficient of variation, and
the RMSE a *perfect-mean* predictor would score (the honest "is this RMSE
actually skill?" reference).

The cached CAMS chunks are column-oriented: one dict with a 'time' list plus
one list per species under its Open-Meteo name (carbon_monoxide, pm10, ...).

Usage:
    python scripts/manual/species_distribution.py                 # all cached chunks
    python scripts/manual/species_distribution.py --chunks 6      # first N chunks
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_CACHE = _ROOT / "data_cache"

# local key -> Open-Meteo CAMS archive field name
SPECIES = {
    "pm2_5": "pm2_5",
    "pm10": "pm10",
    "no2": "nitrogen_dioxide",
    "o3": "ozone",
    "so2": "sulphur_dioxide",
    "co": "carbon_monoxide",
}


def numeric(seq: object) -> list[float]:
    if not isinstance(seq, list):
        return []
    return [float(v) for v in seq if isinstance(v, (int, float)) and math.isfinite(float(v))]


def series_from_chunk(raw: dict, field: str) -> list[float]:
    """One species' hourly values from a column-oriented cached CAMS chunk."""
    if field in raw:
        return numeric(raw[field])
    for key in ("hours", "hourly", "data"):
        rows = raw.get(key)
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            out = []
            for row in rows:
                value = row.get(field)
                if isinstance(value, (int, float)):
                    out.append(float(value))
                else:
                    inner = row.get("pollutants") or row.get("values") or {}
                    if isinstance(inner, dict) and isinstance(inner.get(field), (int, float)):
                        out.append(float(inner[field]))
            return out
    return []


def stats(values: list[float]) -> dict[str, float]:
    vals = sorted(values)
    n = len(vals)
    if not n:
        return {"n": 0}
    mean = sum(vals) / n
    med = statistics.median(vals)
    p95 = vals[min(n - 1, int(0.95 * n))]
    p99 = vals[min(n - 1, int(0.99 * n))]
    peak = vals[-1]
    mean_only_rmse = math.sqrt(sum((v - mean) ** 2 for v in vals) / n)
    return {
        "n": n,
        "mean": round(mean, 1),
        "median": round(med, 1),
        "p95": round(p95, 1),
        "p99": round(p99, 1),
        "max": round(peak, 1),
        "p99_over_median": round(p99 / med, 2) if med > 0 else None,
        "max_over_median": round(peak / med, 2) if med > 0 else None,
        "cv": round(statistics.pstdev(vals) / mean, 3) if mean > 0 else None,
        "mean_only_rmse": round(mean_only_rmse, 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chunks", type=int, default=0, help="use first N chunks (0 = all)")
    args = parser.parse_args()

    chunks = sorted(_CACHE.glob("cams_*.json"))
    if args.chunks:
        chunks = chunks[: args.chunks]
    if not chunks:
        print(f"no cams_*.json under {_CACHE}")
        return 1

    probe = json.loads(chunks[0].read_text(encoding="utf-8"))
    print(f"chunks: {len(chunks)} (first: {chunks[0].name})")
    print(f"chunk keys: {list(probe)[:8]}\n")

    collected: dict[str, list[float]] = {s: [] for s in SPECIES}
    for path in chunks:
        raw = json.loads(path.read_text(encoding="utf-8"))
        for local, field in SPECIES.items():
            collected[local].extend(series_from_chunk(raw, field))

    hdr = (f"{'species':<8}{'n':>8}{'mean':>10}{'median':>9}{'p95':>10}{'p99':>10}"
           f"{'max':>10}{'p99/med':>9}{'max/med':>9}{'CV':>7}{'std-only RMSE':>15}")
    print(hdr)
    print("-" * len(hdr))
    for local in SPECIES:
        st = stats(collected[local])
        if not st.get("n"):
            print(f"{local:<8}{'0':>8}  (field not found in cache)")
            continue
        print(f"{local:<8}{st['n']:>8}{st['mean']:>10}{st['median']:>9}{st['p95']:>10}"
              f"{st['p99']:>10}{st['max']:>10}{st['p99_over_median']:>9}"
              f"{st['max_over_median']:>9}{st['cv']:>7}{st['mean_only_rmse']:>15}")
    print("\nRMSE is in each species' own units. 'std-only RMSE' is the error a constant")
    print("'predict the mean' model scores, i.e. the species' own spread - an RMSE near")
    print("it means little skill, well below it means real skill. 'max/med' > ~10 flags a")
    print("heavy right tail, where a few episode hours dominate the squared error.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())