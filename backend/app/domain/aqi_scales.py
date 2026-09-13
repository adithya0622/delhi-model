"""AQI scales and unit-aware sub-index arithmetic.
Pure arithmetic with no third-party imports, so the most demo-critical and
historically most bug-prone part of the system can be unit-tested without the
HTTP stack, the cache, or pydantic. `realtime_service` re-exports everything
here, so existing call sites are unchanged.

This lives in `domain/` for the same reason `species.py` does: it was previously
defined inside `services/realtime_service.py`, which imports `httpx` and
`cachetools` at module scope. That meant `_sub_index` -- the function that
reported clean air as "Severe" for months -- could not be tested at all without
installing a web client.

External concentrations passed here always use the application's canonical
unit, ug/m3. Conversion to each standard's published AQI input unit happens
inside `_aqi_input`: CPCB uses mg/m3 for CO; current US EPA uses ug/m3 for PM,
ppm for CO, and ppb for O3/NO2/SO2.

Their category bands differ too: EPA breaks at 150 where CPCB breaks at 200, and
the names differ. An EPA AQI of 150 is "Unhealthy for Sensitive Groups", not
CPCB's "Moderate". Mixing the tables mislabels the entire 101-200 range, so `_cat`
takes the same `mode` flag as `_sub_index` and callers must pass it through.
"""

import math
from collections.abc import Iterable

from app.domain.units import (
    EPA_AQI_UNIT_LABELS,
    canonical_parameter,
    epa_aqi_input,
    from_ug_m3,
)

EPA_MODE_NAMES = {"epa", "nowcast", "us_epa"}
EPA_STANDARD = "US EPA AQI Scale (2024)"
CPCB_STANDARD = "CPCB National AQI (2014)"

# ── CPCB AQI breakpoints (conc_lo, conc_hi, idx_lo, idx_hi) ───────────────────
# PM in µg/m³, CO in mg/m³ (the CPCB table's own unit; canonical inputs are
# converted at the calculation boundary).
_BP: dict[str, list[tuple]] = {
    "pm25": [(0,30,0,50),(30,60,51,100),(60,90,101,200),
             (90,120,201,300),(120,250,301,400),(250,500,401,500)],
    "pm10": [(0,50,0,50),(50,100,51,100),(100,250,101,200),
             (250,350,201,300),(350,430,301,400),(430,600,401,500)],
    "o3":   [(0,50,0,50),(50,100,51,100),(100,168,101,200),
             (168,208,201,300),(208,748,301,400),(748,1000,401,500)],
    "no2":  [(0,40,0,50),(40,80,51,100),(80,180,101,200),
             (180,280,201,300),(280,400,301,400),(400,800,401,500)],
    "so2":  [(0,40,0,50),(40,80,51,100),(80,380,101,200),
             (380,800,201,300),(800,1600,301,400),(1600,2000,401,500)],
    "co":   [(0,1,0,50),(1,2,51,100),(2,10,101,200),
             (10,17,201,300),(17,34,301,400),(34,50,401,500)],
}

# ── Current US EPA breakpoints ────────────────────────────────────────────────
# EPA AQS source: https://aqs.epa.gov/aqsweb/documents/codetables/aqi_breakpoints.csv
# PM2.5 uses the breakpoints effective May 6, 2024. Units below match AirNow's
# public concentration calculator: PM in ug/m3, CO in ppm, other gases in ppb.
#
# IMPORTANT: these segments are intentionally NON-contiguous. See _sub_index --
# truncation to _PRECISION is what closes the gaps, and omitting it is what made
# a PM10 reading of 54.5 µg/m³ report as AQI 500.
_BP_EPA: dict[str, list[tuple]] = {
    "pm25": [(0,9.0,0,50),(9.1,35.4,51,100),(35.5,55.4,101,150),
             (55.5,125.4,151,200),(125.5,225.4,201,300),(225.5,325.4,301,500)],
    "pm10": [(0,54,0,50),(55,154,51,100),(155,254,101,150),
             (255,354,151,200),(355,424,201,300),(425,604,301,500)],
    # 8-hour ozone AQI. EPA switches to the 1-hour series above AQI 300; this
    # application does not claim a >300 ozone sub-index without that separate
    # averaging series, so values above 200 ppb remain capped at 300.
    "o3":   [(0,54,0,50),(55,70,51,100),(71,85,101,150),
             (86,105,151,200),(106,200,201,300)],
    "no2":  [(0,53,0,50),(54,100,51,100),(101,360,101,150),
             (361,649,151,200),(650,1249,201,300),(1250,2049,301,500)],
    # 1-hour SO2 determines AQI through 200. Higher bands require a 24-hour
    # average, which a latest-value station payload cannot provide.
    "so2":  [(0,35,0,50),(36,75,51,100),(76,185,101,150),
             (186,304,151,200)],
    "co":   [(0,4.4,0,50),(4.5,9.4,51,100),(9.5,12.4,101,150),
             (12.5,15.4,151,200),(15.5,30.4,201,300),(30.5,50.4,301,500)],
}

# ── Category bands ────────────────────────────────────────────────────────────

AQI_CATEGORIES = [
    (0,   50,  "Good",         "#009966"),
    (51,  100, "Satisfactory", "#ffde33"),
    (101, 200, "Moderate",     "#ff9933"),
    (201, 300, "Poor",         "#cc0033"),
    (301, 400, "Very Poor",    "#660099"),
    (401, 500, "Severe",       "#7e0023"),
]

# US EPA category bands. These are NOT the CPCB bands: the boundaries differ
# (EPA breaks at 150, CPCB at 200) and so do the names. Applying CPCB labels to
# an EPA-scale number mislabels the whole 101-200 range -- an EPA AQI of 150 is
# "Unhealthy for Sensitive Groups", not CPCB's "Moderate". Since `nowcast` mode
# computes sub-indices from `_BP_EPA`, it must be labelled with this table.
AQI_CATEGORIES_EPA = [
    (0,   50,  "Good",                           "#009966"),
    (51,  100, "Moderate",                       "#ffde33"),
    (101, 150, "Unhealthy for Sensitive Groups", "#ff9933"),
    (151, 200, "Unhealthy",                      "#cc0033"),
    (201, 300, "Very Unhealthy",                 "#660099"),
    (301, 500, "Hazardous",                      "#7e0023"),
]

# EPA reporting precision: concentration must be truncated to this many decimals
# before breakpoint lookup, otherwise readings land in the gaps between segments.
_PRECISION: dict[str, int] = {
    "pm25": 1, "pm10": 0, "o3": 0, "no2": 0, "so2": 0, "co": 1,
}


def _cat(aqi: int, mode: str = "instant") -> tuple[str, str]:
    """
    AQI value -> (category label, hex colour).

    `mode` must match breakpoint table. Default is current US EPA AQI; `instant`
    retains CPCB compatibility for explicit callers.
    """
    table = AQI_CATEGORIES_EPA if mode in EPA_MODE_NAMES else AQI_CATEGORIES
    for lo, hi, label, color in table:
        if lo <= aqi <= hi:
            return label, color
    return table[-1][2], table[-1][3]


def _truncate(value: float, decimals: int) -> float:
    """Truncate (never round up) to a fixed number of decimals, per EPA method."""
    factor = 10 ** decimals
    return math.floor(value * factor) / factor


def _normalise_param(param: str) -> str:
    """OpenAQ reports PM2.5 as 'pm25' or 'pm2.5' depending on endpoint."""
    return canonical_parameter(param)


def _aqi_input(param: str, concentration_ug_m3: float, mode: str) -> tuple[float, str]:
    """Convert canonical ug/m3 into the selected standard's published unit."""
    pollutant = _normalise_param(param)
    if mode in EPA_MODE_NAMES:
        converted = epa_aqi_input(pollutant, concentration_ug_m3)
        if converted is None:
            raise ValueError(f"unsupported EPA pollutant: {param}")
        value, unit = converted
        return value, EPA_AQI_UNIT_LABELS[unit]
    if pollutant == "co":
        value = from_ug_m3(pollutant, concentration_ug_m3, "mg/m3")
        if value is None:
            raise ValueError("CO conversion failed")
        return value, "mg/m³"
    return concentration_ug_m3, "µg/m³"


def _sub_index(param: str, conc: float, mode: str = "instant") -> int:
    """
    Concentration -> AQI sub-index by linear interpolation within a breakpoint
    segment. Uses EPA breakpoints for nowcast mode, CPCB for instant mode.

    Returns 0 for unknown/negative input. Only returns 500 when the reading is
    genuinely at or above the top of the scale -- never as a fall-through for a
    value that failed to match a segment.
    """
    p = _normalise_param(param)
    bps = (_BP_EPA if mode in EPA_MODE_NAMES else _BP).get(p)
    if not bps or conc is None:
        return 0
    try:
        canonical = float(conc)
    except (TypeError, ValueError):
        return 0
    if canonical < 0 or math.isnan(canonical) or math.isinf(canonical):
        return 0

    c, _unit = _aqi_input(p, canonical, mode)

    # EPA requires truncation to reporting precision before lookup.
    if mode in EPA_MODE_NAMES:
        c = _truncate(c, _PRECISION.get(p, 0))

    if c <= bps[0][0]:
        return bps[0][2]
    if c >= bps[-1][1]:
        return bps[-1][3]          # genuinely off the top of the scale

    for lo, hi, ilo, ihi in bps:
        if lo <= c <= hi:
            if hi == lo:
                return ihi
            return round(ilo + (ihi - ilo) * (c - lo) / (hi - lo))

    # Safety net: value fell in a gap between published segments (should be
    # unreachable after truncation). Snap UP to the next segment's floor rather
    # than defaulting to 500 -- the old behaviour reported clean air as Severe.
    for lo, _hi, ilo, _ihi in bps:
        if c < lo:
            return ilo
    return bps[-1][3]


def _conc_to_aqi(
    concentrations: dict[str, float], mode: str = "instant"
) -> tuple[int, str]:
    """
    Returns (AQI, dominant_pollutant) from a dict of concentration readings.
    Uses CPCB breakpoints for instant mode, EPA breakpoints for nowcast mode.
    """
    sub_indices = {}
    for param, conc in concentrations.items():
        if conc is not None and conc >= 0:
            si = _sub_index(param, conc, mode)
            if si > 0:
                sub_indices[_normalise_param(param)] = si
    if not sub_indices:
        return 0, "unknown"
    dominant = max(sub_indices, key=sub_indices.get)
    return min(max(sub_indices.values()), 500), dominant


def aqi_standard(mode: str) -> str:
    return EPA_STANDARD if mode in EPA_MODE_NAMES else CPCB_STANDARD


def aqi_method(mode: str) -> str:
    if mode == "nowcast":
        return "EPA breakpoints; PM NowCast; latest hourly gases"
    if mode in EPA_MODE_NAMES:
        return "EPA breakpoints; PM NowCast; CO/O3 8-hour rolling; NO2/SO2 hourly"
    return "CPCB breakpoints applied to latest/forecast hourly concentrations"


def epa_nowcast(values: Iterable[float | None], minimum_hours: int = 2) -> float | None:
    """EPA NowCast concentration from newest-first hourly values."""
    clean = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number) and number >= 0:
            clean.append(number)
    if not clean:
        return None
    if len(clean) < minimum_hours:
        return sum(clean) / len(clean)
    maximum, minimum = max(clean), min(clean)
    weight = max(0.5, minimum / maximum) if maximum > 0 else 1.0
    denominator = sum(weight**i for i in range(len(clean)))
    return sum((weight**i) * value for i, value in enumerate(clean)) / denominator


def rolling_mean(values: Iterable[float | None], window: int) -> float | None:
    """Mean of finite non-negative values in the newest-first window."""
    clean = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number) and number >= 0:
            clean.append(number)
        if len(clean) >= window:
            break
    return sum(clean) / len(clean) if clean else None


def aqi_input_details(param: str, concentration_ug_m3: float, mode: str) -> tuple[float, str]:
    """Public wrapper for auditable API fields."""
    value, unit = _aqi_input(param, concentration_ug_m3, mode)
    precision = _PRECISION.get(_normalise_param(param), 2) if mode in EPA_MODE_NAMES else 3
    return round(value, precision), unit
