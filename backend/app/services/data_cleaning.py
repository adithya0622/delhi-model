"""Quality gates for external observation and meteorology data.

Rows are rejected, never silently imputed. Returned audit counts make training
data reproducible and prevent flagged, stale, malformed, duplicate, or
dimensionally incompatible provider rows from reaching a fitted model.
"""

from __future__ import annotations

import math
from collections import Counter
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any

from app.domain.units import canonical_parameter, to_ug_m3

_LOCAL_TIME = timezone(timedelta(hours=5, minutes=30))
_MAX_UG_M3 = {
    "pm25": 1_000.0,
    "pm10": 3_000.0,
    "o3": 2_000.0,
    "no2": 4_000.0,
    "so2": 5_000.0,
    "co": 100_000.0,
}


def _timestamp(raw: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(_LOCAL_TIME)
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def clean_openaq_hourly(
    rows: list[dict[str, Any]],
    *,
    pollutant: str = "pm25",
    minimum_coverage_pct: float = 75.0,
) -> tuple[list[dict[str, Any]], dict[str, int | float]]:
    """Clean OpenAQ hourly rows into one canonical observation per local hour."""
    wanted = canonical_parameter(pollutant)
    rejected: Counter[str] = Counter()
    by_hour: dict[datetime, list[float]] = {}

    for row in rows:
        parameter = row.get("parameter") or {}
        actual = canonical_parameter(parameter.get("name") or wanted)
        if actual != wanted:
            rejected["wrong_pollutant"] += 1
            continue
        if (row.get("flagInfo") or {}).get("hasFlags"):
            rejected["flagged"] += 1
            continue
        coverage = (row.get("coverage") or {}).get("percentCoverage")
        if coverage is not None:
            parsed_coverage = _number(coverage)
            if parsed_coverage is None or parsed_coverage < minimum_coverage_pct:
                rejected["low_coverage"] += 1
                continue
        period = row.get("period") or {}
        time_data = period.get("datetimeTo") or period.get("datetimeFrom") or {}
        timestamp = _timestamp(time_data.get("local") or time_data.get("utc"))
        if timestamp is None:
            rejected["invalid_timestamp"] += 1
            continue
        value = to_ug_m3(actual, row.get("value"), parameter.get("units"))
        if value is None:
            rejected["unsupported_unit_or_value"] += 1
            continue
        if value > _MAX_UG_M3.get(actual, 0.0):
            rejected["outside_physical_range"] += 1
            continue
        hour = timestamp.replace(minute=0, second=0, microsecond=0)
        by_hour.setdefault(hour, []).append(value)

    cleaned = [
        {
            "timestamp": hour.isoformat(),
            f"{wanted}_ug_m3": round(median(values), 4),
            "source_rows": len(values),
        }
        for hour, values in sorted(by_hour.items())
    ]
    duplicates = sum(len(values) - 1 for values in by_hour.values())
    return cleaned, {
        "rows_received": len(rows),
        "rows_accepted": sum(len(values) for values in by_hour.values()),
        "hours_retained": len(cleaned),
        "duplicate_rows_collapsed": duplicates,
        **dict(sorted(rejected.items())),
    }


def clean_hourly_weather(
    payload: dict[str, Any],
    required_fields: tuple[str, ...],
) -> tuple[list[dict[str, float | str]], dict[str, int]]:
    """Reject incomplete/non-finite hourly weather rows without interpolation."""
    hourly = payload.get("hourly") or {}
    timestamps = hourly.get("time") or []
    rejected: Counter[str] = Counter()
    clean: list[dict[str, float | str]] = []
    for index, stamp in enumerate(timestamps):
        row: dict[str, float | str] = {"timestamp": str(stamp)}
        valid = True
        for field in required_fields:
            values = hourly.get(field) or []
            value = _number(values[index] if index < len(values) else None)
            if value is None:
                rejected[f"missing_{field}"] += 1
                valid = False
                break
            row[field] = value
        if valid:
            clean.append(row)
    return clean, {
        "rows_received": len(timestamps),
        "rows_retained": len(clean),
        **dict(sorted(rejected.items())),
    }
