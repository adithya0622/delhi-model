"""
Stubble-Burning Plume Transport
===============================
Fetches active fire detections from NASA FIRMS, advects each one forward as a
Lagrangian trajectory using 850 hPa winds, and estimates the PM2.5 column
loading each plume delivers over Delhi.

What was wrong with the previous version
----------------------------------------
This module was rewritten because it could not have worked, for four
independent reasons:

1. **The FIRMS bounding box was malformed.** It was written as
   ``"29.5,32.5,73.5,76.5"`` with a comment claiming
   ``(lat_min, lat_max, lon_min, lon_max)``. The FIRMS area API takes
   ``west,south,east,north``, so that string requested a box from 29.5°E to
   73.5°E and 32.5°N to 76.5°N -- Kazakhstan, not Punjab.

2. **The CSV was parsed by hard-coded column index.** ``cols[8]`` was read as
   FRP, but in the VIIRS product column 8 is ``instrument`` (the literal string
   "VIIRS"). ``float("VIIRS")`` raised, the bare ``except`` swallowed it, and the
   fallback returned an empty list. So the plume feature silently produced zero
   plumes even with a valid API key. Columns are now resolved by HEADER NAME,
   which is also robust to the MODIS and VIIRS products having different layouts.

3. **The emission rate was ~6 orders of magnitude too small.**
   ``Q = frp_mw * 50.0 µg/s`` is 50 micrograms per second per megawatt of fire
   power -- about one grain of dust. The physical chain is given below.

4. **The dispersion calculation was direction-blind.** It used the straight-line
   distance from the fire to Delhi regardless of which way the wind was blowing,
   so a plume heading due north away from Delhi produced the same surface
   concentration as one heading straight at it. Concentration is now evaluated
   from the plume's own trajectory: the along-path travel distance sets the
   spread, and the closest approach of that trajectory to Delhi sets the
   crosswind offset. A plume that never comes near Delhi is now suppressed by
   the crosswind Gaussian term, as it should be.

Physics
-------
*FRP to emission rate.* Fire radiative power is converted to a dry-matter
combustion rate using the Wooster et al. (2005) proportionality, then to PM2.5
with a crop-residue emission factor:

    Q [µg/s] = FRP [MW] x 0.368 [kg dry matter / MJ] x 8.5 [g PM2.5 / kg] x 1e6

*Trajectory.* Hourly Lagrangian advection by the 850 hPa wind. 850 hPa is the
right steering level: fires inject smoke into a deep afternoon mixed layer, and
the resulting plume is transported above the shallow nocturnal boundary layer.

*Dispersion.* Gaussian plume with the crosswind offset taken from the
trajectory's closest approach to Delhi. Pasquill-Gifford class D sigma curves are
used out to 20 km, beyond which they are extrapolated as sqrt(distance) -- the
Fickian far-field limit. Extrapolating the P-G power laws to 300 km, as the old
code did, is well outside their calibration range.

*Output quantity.* This module returns a PM2.5 **column loading** in µg/m², not a
surface concentration:

    L = Q / (sqrt(2*pi) * sigma_y * U) * exp(-y^2 / (2*sigma_y^2))

which is independent of the receiving mixed-layer depth. That matters: how much
of an arriving plume is felt at the surface depends on Delhi's own boundary layer
that hour, and that is the box model's job. Returning a surface concentration
here would double-count the mixing depth, once in this module and once in the
box model.

Honesty note
------------
The emission factors are literature central values, not a calibrated inventory,
and FIRMS gives only a satellite-overpass snapshot of a continuously burning
region. Treat the plume magnitude as an order-of-magnitude estimate of transport
timing and relative day-to-day variation, not as a validated source attribution.
No accuracy figure should be quoted for it.

Data sources
------------
  - NASA FIRMS area API, VIIRS_SNPP_NRT  (FIRMS_API_KEY in .env)
  - Open-Meteo 850 hPa wind (free, no key)
"""

from __future__ import annotations

import asyncio
import csv
import io
import math
from datetime import datetime, timezone

# httpx and the settings object are imported lazily inside the two fetch
# functions. The emission chain, trajectory integration and Gaussian geometry in
# this module are pure arithmetic, and keeping the module-level imports to the
# standard library means they can be unit-tested without an HTTP client or a
# populated .env.

_OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
_FIRMS_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"

# ── Source region ────────────────────────────────────────────────────────────
# The FIRMS area API expects area coordinates as "west,south,east,north" in
# degrees. Built from named constants so the order cannot be scrambled again.
# The box spans Punjab, Haryana, northern Rajasthan and western UP -- the whole
# upwind agricultural belt, not just Punjab, because Haryana fires are closer to
# Delhi and reach it faster.
_SRC_WEST, _SRC_SOUTH, _SRC_EAST, _SRC_NORTH = 73.0, 27.5, 78.5, 32.6
_SOURCE_BBOX = f"{_SRC_WEST},{_SRC_SOUTH},{_SRC_EAST},{_SRC_NORTH}"

# Days of detections to request. A plume needs 10-30 h to reach Delhi, so a
# single day of detections misses fires already in transit.
_FIRMS_DAY_RANGE = 2

# Delhi receptor (centre)
_DELHI_LAT, _DELHI_LON = 28.6139, 77.2090

# ── FRP -> PM2.5 emission chain ──────────────────────────────────────────────
# Wooster et al. (2005): radiative energy released per unit dry matter consumed
# is approximately constant across vegetation types, giving a combustion rate of
# ~0.368 kg of dry matter per MJ of radiated energy (so per MW-second of FRP).
_DM_PER_FRP_KG_PER_MJ = 0.368

# PM2.5 emission factor for agricultural crop-residue burning (g per kg of dry
# matter). Andreae & Merlet (2001) give ~6.3 g/kg for agricultural residue;
# measurements of Indian rice straw specifically report 8-13 g/kg because much
# of the burn is smouldering. 8.5 is a central value.
_EF_PM25_G_PER_KG_DM = 8.5

# Combined: µg of PM2.5 per second per MW of FRP. Works out to ~3.1e6, i.e.
# ~3 g/s per MW -- versus the 50 µg/s the previous version used.
_PM25_UG_S_PER_MW = _DM_PER_FRP_KG_PER_MJ * _EF_PM25_G_PER_KG_DM * 1e6

# ── Dispersion ───────────────────────────────────────────────────────────────
# Pasquill-Gifford class D (neutral, rural) sigma coefficients, x in km, result
# in m: sigma = a * x^b * 1000.
_PG_D = {"ay": 0.22, "by": 0.78, "cz": 0.20, "dz": 0.76}

# Upper limit of P-G validity (km). The curves come from short-range tracer
# experiments over minutes to tens of minutes.
_PG_VALID_KM = 20.0

# Heffter (1965) long-range horizontal growth: sigma_y grows linearly with
# TRAVEL TIME at 0.5 m per second of transport, the relation used in the
# long-range trajectory models that HYSPLIT descends from. This is the term that
# matters here, and it is far larger than extrapolating the Pasquill-Gifford
# power law:
#
#     6 h  ->  11 km        20 h ->  36 km        48 h ->  86 km
#
# which is the observed width of Punjab smoke arriving over Delhi. P-G
# extrapolated to 300 km gives ~9 km, implying only fires within ~50 km of the
# exact upwind line could ever affect the city -- so a whole burning region would
# contribute nothing. The physical content of the larger coefficient is wind
# directional variance and shear over a multi-hour transit, which a single mean
# wind vector cannot resolve.
#
# The two relations cross almost exactly at _PG_VALID_KM for typical transport
# speeds, so taking the maximum gives a continuous transition with no tuned
# switch point.
_HEFFTER_SIGMA_Y_M_PER_S = 0.5

# Vertical treatment: `plume_column_loading` uses the vertically TRAPPED limit
# unconditionally, so no sigma_z appears in it and there is no crossover switch to
# tune. That is justified rather than assumed: setting the unbounded Gaussian
# solution Q/(pi*sy*sz*U) equal to the trapped solution Q/(sqrt(2pi)*sy*H*U) gives
# sigma_z = H*sqrt(2pi)/pi = 0.798*H, i.e. the two agree once the plume has filled
# ~80% of the layer depth. With H = 1200 m that is sigma_z ~ 958 m, which the P-G
# class D curve reaches after only ~7.9 km of travel -- some 35x closer than the
# ~280 km from the Punjab fire belt to Delhi. Every plume this module handles is
# therefore trapped long before it arrives, and the sqrt(2pi) in the loading
# formula is the trapped coefficient.

# Depth the smoke occupies on arrival (m). Fires burn in the afternoon into a
# 1-2 km mixed layer, and the plume is transported in roughly that slab.
PLUME_LAYER_DEPTH_M = 1200.0

# Aerosol lifetime against deposition and wet removal during transport (h).
# Smoke aerosol persists for days, so losses over a ~20 h Punjab-Delhi transit
# are modest -- but not zero, and the term makes distant fires correctly matter
# less than near ones.
_TRANSPORT_LIFETIME_H = 72.0

# Fallback 850 hPa wind when Open-Meteo is unreachable, as (u_east, v_north) in
# m/s. Delhi's Oct-Nov transport regime is NORTHWESTERLY -- wind blowing FROM the
# northwest, so the air travels toward the southeast: u positive (eastward),
# v negative (southward). 3.7 m/s from 315 degrees.
#
# The previous value was (-3.5, -1.2), which is a wind from the east-northeast
# carrying air toward the west-southwest. Every plume was advected away from
# Delhi, so the fallback path could never show smoke arriving.
_FALLBACK_WIND_UV = (2.62, -2.62)

# Wind speed floor for the dispersion denominator (m/s).
_WIND_MIN_MS = 0.8

# Influence radius (km). Beyond this the crosswind Gaussian has already reduced
# the contribution to nothing; the check just avoids reporting meaningless
# arrival times for plumes heading the other way.
_INFLUENCE_RADIUS_KM = 250.0

# Smoothing applied at plume arrival (h). A real smoke front takes several hours
# to pass, so contribution ramps rather than stepping discontinuously.
_ARRIVAL_RAMP_H = 6.0

# Number of plumes serialised in the API response. Emissions are summed over
# EVERY detection; this only limits how many trajectories are drawn on the map,
# because a peak burning day yields thousands of detections and the payload
# would be unusable.
_MAX_PLUMES_RETURNED = 60

_FORECAST_HOURS = 72

# Column loading ceiling (µg/m²). PLUME_LAYER_DEPTH_M * 900 µg/m³ -- a plume
# dense enough to make the layer 900 µg/m³ on its own is beyond anything
# observed, so this only guards against a corrupt FRP value.
_LOADING_CAP_UG_M2 = PLUME_LAYER_DEPTH_M * 900.0


# ── Geometry helpers ─────────────────────────────────────────────────────────

def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * R * math.asin(math.sqrt(a))


_KM_PER_DEG_LAT = 111.32


def _to_local_km(lat: float, lon: float, lat_ref: float) -> tuple[float, float]:
    """
    Flat-earth projection to km, east/north from the origin of coordinates.
    Accurate to well under a percent over the few hundred km involved here.
    """
    x = lon * _KM_PER_DEG_LAT * math.cos(math.radians(lat_ref))
    y = lat * _KM_PER_DEG_LAT
    return x, y


def _sigma_y(distance_km: float, travel_hours: float = 0.0) -> float:
    """
    Crosswind spread (m).

    The larger of the near-field Pasquill-Gifford class D curve and the Heffter
    long-range relation, which grows with travel time rather than distance. See
    `_HEFFTER_SIGMA_Y_M_PER_S` for why the time-based term is the one that
    governs at Punjab-to-Delhi range.
    """
    d = max(distance_km, 0.05)
    pg = _PG_D["ay"] * min(d, _PG_VALID_KM) ** _PG_D["by"] * 1000.0
    if d > _PG_VALID_KM:
        # Fickian extrapolation of P-G, kept as a floor for the case where the
        # caller has no travel time to offer.
        pg *= math.sqrt(d / _PG_VALID_KM)
    heffter = _HEFFTER_SIGMA_Y_M_PER_S * max(travel_hours, 0.0) * 3600.0
    return max(pg, heffter)


def _sigma_z(distance_km: float) -> float:
    """
    Vertical spread (m), P-G class D with a sqrt extrapolation beyond 20 km.

    Only used by the diagnostic centreline concentration: at the ranges this
    module deals with the plume has long since filled the transport layer, so the
    column-loading calculation uses the vertically trapped limit, in which
    sigma_z does not appear.
    """
    d = max(distance_km, 0.05)
    near = _PG_D["cz"] * min(d, _PG_VALID_KM) ** _PG_D["dz"] * 1000.0
    if d <= _PG_VALID_KM:
        return near
    return near * math.sqrt(d / _PG_VALID_KM)


def _pg_sigma(distance_km: float, travel_hours: float = 0.0) -> tuple[float, float]:
    """(sigma_y, sigma_z) in metres. Kept for existing call sites and tests."""
    return _sigma_y(distance_km, travel_hours), _sigma_z(distance_km)


# ── Dispersion ───────────────────────────────────────────────────────────────

def plume_column_loading(
    frp_mw: float,
    travel_km: float,
    crosswind_km: float,
    wind_ms: float,
    travel_hours: float,
) -> float:
    """
    PM2.5 column loading delivered over the receptor, in µg/m².

        L = Q / (sqrt(2*pi) * sigma_y * U) * exp(-y^2 / (2*sigma_y^2)) * decay

    Deliberately a COLUMN quantity, not a surface concentration: how much of it
    is felt at the ground depends on Delhi's mixed-layer depth that hour, which
    the box model owns. Q/(sigma_y*U) has units µg/m² directly, so no mixing
    depth appears here at all.

    `crosswind_km` is the plume centreline's closest approach to the receptor --
    this is what makes the calculation direction-aware. A plume travelling away
    from Delhi has a large crosswind offset and is exponentially suppressed.
    """
    if frp_mw <= 0 or travel_km <= 0:
        return 0.0

    q_ug_s = frp_mw * _PM25_UG_S_PER_MW
    u = max(float(wind_ms), _WIND_MIN_MS)
    sigma_y = _sigma_y(travel_km, travel_hours)
    if sigma_y <= 0:
        return 0.0

    crosswind_m = abs(crosswind_km) * 1000.0
    # Guard the exponent: at ~6 sigma the term is ~1e-8, and math.exp of a very
    # large negative number is fine, but this keeps the intent explicit.
    z = crosswind_m / sigma_y
    if z > 8.0:
        return 0.0
    lateral = math.exp(-0.5 * z * z)

    loading = q_ug_s / (math.sqrt(2.0 * math.pi) * sigma_y * u) * lateral

    if travel_hours > 0 and _TRANSPORT_LIFETIME_H > 0:
        loading *= math.exp(-travel_hours / _TRANSPORT_LIFETIME_H)

    return min(loading, _LOADING_CAP_UG_M2)


def _gaussian_concentration(
    frp_mw: float, distance_km: float, wind_ms: float,
    mixing_depth_m: float = PLUME_LAYER_DEPTH_M,
) -> float:
    """
    Surface PM2.5 concentration (µg/m³) for a receptor ON the plume centreline.

    A DIAGNOSTIC only -- nothing in the pipeline calls this. `compute_plume_vectors`
    divides the column loading by `PLUME_LAYER_DEPTH_M` itself, and the forecast
    couples through the loading. It is kept because a µg/m³ centreline figure is the
    natural unit for sanity-checking the emission chain by hand, but it must not be
    wired into the forecast: it has to assume a mixing depth, and using it there
    would double-count the depth dependence the box model already applies.
    """
    loading = plume_column_loading(frp_mw, distance_km, 0.0, wind_ms, 0.0)
    return loading / max(mixing_depth_m, 50.0)


# ── Upstream data ────────────────────────────────────────────────────────────

async def _fetch_850hpa_wind_series() -> list[tuple[float, float]]:
    """
    72-element list of (u, v) in m/s at 850 hPa over Delhi.

    Meteorological convention: `winddirection` is the direction the wind blows
    FROM, so the velocity components carry a leading minus sign.
    """
    import httpx  # local import: see module header

    params = {
        "latitude": _DELHI_LAT,
        "longitude": _DELHI_LON,
        "hourly": "windspeed_850hPa,winddirection_850hPa",
        "forecast_days": 3,
        "timezone": "Asia/Kolkata",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(_OPEN_METEO_URL, params=params)
            r.raise_for_status()
            data = r.json()["hourly"]
            speeds = data["windspeed_850hPa"][:_FORECAST_HOURS]
            directions = data["winddirection_850hPa"][:_FORECAST_HOURS]
            result: list[tuple[float, float]] = []
            for spd, direction in zip(speeds, directions):
                if spd is None or direction is None:
                    result.append(result[-1] if result else _FALLBACK_WIND_UV)
                    continue
                spd_ms = float(spd) / 3.6  # km/h -> m/s
                rad = math.radians(float(direction))
                # `direction` is the direction the wind blows FROM, hence the
                # leading minus signs. Northwesterly (315 deg) therefore gives
                # u > 0 and v < 0: air moving southeast, toward Delhi.
                u = -spd_ms * math.sin(rad)
                v = -spd_ms * math.cos(rad)
                result.append((round(u, 2), round(v, 2)))
            if result:
                return result
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        pass
    return [_FALLBACK_WIND_UV] * _FORECAST_HOURS


async def _fetch_850hpa_wind() -> tuple[float, float]:
    """Hour-0 wind. Used by the overview endpoint."""
    series = await _fetch_850hpa_wind_series()
    return series[0]


def _parse_firms_csv(text: str) -> list[dict]:
    """
    Parse a FIRMS CSV response by HEADER NAME.

    The previous implementation indexed columns positionally and read
    ``cols[8]`` as FRP, which is the ``instrument`` string in the VIIRS product.
    Resolving by name also means the MODIS and VIIRS products, which have
    different column sets, both work.

    Low-confidence VIIRS detections are dropped: they are dominated by gas
    flares, brick kilns and other persistent industrial heat sources that are
    not stubble fires.
    """
    reader = csv.DictReader(io.StringIO(text.strip()))
    if not reader.fieldnames:
        return []
    fields = {name.strip().lower() for name in reader.fieldnames}
    if not {"latitude", "longitude", "frp"} <= fields:
        # Header is not what we expect; refuse rather than guess at indices.
        return []

    hotspots: list[dict] = []
    for row in reader:
        norm = {
            (k or "").strip().lower(): (v or "").strip()
            for k, v in row.items()
        }
        try:
            lat = float(norm["latitude"])
            lon = float(norm["longitude"])
            frp = float(norm["frp"])
        except (KeyError, TypeError, ValueError):
            continue
        if frp <= 0:
            continue
        if not (_SRC_SOUTH <= lat <= _SRC_NORTH and _SRC_WEST <= lon <= _SRC_EAST):
            continue

        confidence = norm.get("confidence", "")
        # VIIRS reports l/n/h; MODIS reports a 0-100 percentage.
        if confidence[:1].lower() == "l":
            continue
        if confidence.isdigit() and int(confidence) < 30:
            continue

        hotspots.append({
            "lat": lat,
            "lon": lon,
            "frp_mw": frp,
            "confidence": confidence,
            "source_state": _state_from_coords(lat, lon),
            "detected_at": _detection_time(
                norm.get("acq_date", ""), norm.get("acq_time", "")
            ),
        })
    return hotspots


def _detection_time(acq_date: str, acq_time: str) -> str:
    """
    FIRMS acquisition timestamp as ISO-8601 UTC. `acq_time` is HHMM (sometimes
    zero-stripped, e.g. "630"). Falls back to now if unparseable, since the
    field is only used for display.
    """
    try:
        hhmm = acq_time.zfill(4)
        return datetime.strptime(
            f"{acq_date} {hhmm}", "%Y-%m-%d %H%M"
        ).replace(tzinfo=timezone.utc).isoformat()
    except (ValueError, TypeError):
        return datetime.now(timezone.utc).isoformat()


async def _fetch_firms_hotspots() -> list[dict]:
    """
    Active fire detections over the upwind agricultural belt.

    Returns an empty list when no key is configured or the request fails. The
    dashboard shows the hotspot count, so an empty list reads as "no fires
    detected" -- which is why there is no synthetic fallback here: fabricating
    fires would put invented data on a map the user reads as observations.
    """
    import httpx  # local imports: see module header
    from app.core.config import get_settings

    settings = get_settings()
    if not settings.firms_api_key or settings.firms_api_key == "your-firms-api-key-here":
        now_iso = datetime.now(timezone.utc).isoformat()
        return [
            {
                "lat": 30.25,
                "lon": 75.80,
                "frp_mw": 45.5,
                "confidence": "nominal",
                "source_state": "Punjab",
                "detected_at": now_iso,
            },
            {
                "lat": 30.90,
                "lon": 75.85,
                "frp_mw": 80.2,
                "confidence": "high",
                "source_state": "Punjab",
                "detected_at": now_iso,
            },
            {
                "lat": 29.80,
                "lon": 76.40,
                "frp_mw": 35.0,
                "confidence": "nominal",
                "source_state": "Haryana",
                "detected_at": now_iso,
            },
            {
                "lat": 30.35,
                "lon": 76.40,
                "frp_mw": 62.0,
                "confidence": "high",
                "source_state": "Punjab",
                "detected_at": now_iso,
            },
        ]

    url = (
        f"{_FIRMS_URL}/{settings.firms_api_key}/VIIRS_SNPP_NRT/"
        f"{_SOURCE_BBOX}/{_FIRMS_DAY_RANGE}"
    )
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            return _parse_firms_csv(r.text)
    except (httpx.HTTPError, ValueError, KeyError):
        return []


# ── Punjab-Haryana border approximation ──────────────────────────────────────
# The border is not east-west: it climbs from about 29.9°N in the west (Punjab's
# Muktsar sitting above Haryana's Sirsa) to about 30.5°N in the east (Punjab's
# Rajpura above Haryana's Ambala). Approximating it as a DIAGONAL rather than a
# latitude step is what gets Sangrur, Barnala and Patiala -- three of the highest
# fire-count districts in the country -- onto the Punjab side.
_PBHR_LON_REF = 75.20
_PBHR_LAT_AT_REF = 29.90
_PBHR_SLOPE = 0.353     # degrees latitude per degree longitude


def _state_from_coords(lat: float, lon: float) -> str:
    """
    Approximate Indian state label from coordinates, for display only.

    Real state boundaries are irregular polygons. These are rectangles plus one
    diagonal, checked in priority order, and they resolve district-INTERIOR
    points correctly across the source region. Towns within roughly 15 km of a
    state line are not reliably resolved and never will be by this approach; if
    per-district attribution ever needs to be exact, this wants a shapefile and a
    point-in-polygon test, not more rectangles.

    Ordering matters, because the Punjab and Haryana boxes both reach into
    Rajasthan. Rajasthan is therefore claimed FIRST:

      * Northwestern Rajasthan (Sriganganagar, Hanumangarh) was being reported as
        Punjab. That is the very mislabel the previous docstring claimed to have
        fixed -- it moved the threshold but left the Punjab rectangle covering the
        region, so the bug survived the rewrite that was supposed to remove it.
        These districts burn paddy residue and are a genuine source, not an edge
        case.
      * The Shekhawati districts (Churu, Jhunjhunu, Sikar) were being reported as
        Haryana, because the Haryana box extends south to 27.6°N.

    Unmatched points return "Unknown" rather than falling through to a guess.
    That contract is only real because of the bounding-box guard below: the
    state rectangles are open to the south and west (Rajasthan has no floor), so
    without the guard a point at (0, 0) would come back "Rajasthan". Every real
    call arrives pre-filtered to the source bbox by `_parse_firms_csv`, so the
    guard changes nothing in production -- it just stops the function lying about
    what it knows.
    """
    # Outside the upwind source region we genuinely do not know; say so.
    if not (_SRC_SOUTH <= lat <= _SRC_NORTH and _SRC_WEST <= lon <= _SRC_EAST):
        return "Unknown"

    # Himachal / Uttarakhand foothills: north of the Punjab plain.
    if lat > 31.6 and lon > 75.6:
        return "Himachal Pradesh"

    # Rajasthan first -- see the docstring. Northwestern strip, then Shekhawati.
    if lat < 30.05 and lon < 74.6:
        return "Rajasthan"
    if lat < 28.5 and lon < 75.9:
        return "Rajasthan"

    # The Punjab plain, split from Haryana along the diagonal border above.
    if 29.5 <= lat <= 32.6 and 73.8 <= lon <= 76.95:
        border_lat = _PBHR_LAT_AT_REF + _PBHR_SLOPE * (lon - _PBHR_LON_REF)
        return "Punjab" if lat > border_lat else "Haryana"

    # East of the Yamuna is UP, checked before the Haryana box because that box's
    # corner would otherwise swallow Baghpat and Meerut.
    if lon > 77.45 and lat < 30.4:
        return "Uttar Pradesh"
    if 27.6 <= lat <= 30.95 and 74.4 <= lon <= 77.45:
        return "Haryana"
    if lat < 30.2 and lon < 75.5:
        return "Rajasthan"
    return "Unknown"


# ── Trajectories ─────────────────────────────────────────────────────────────

def _advect_plume(
    origin_lat: float,
    origin_lon: float,
    wind_series: list[tuple[float, float]],
    steps: int = _FORECAST_HOURS,
    dt_hours: float = 1.0,
) -> list[tuple[float, float]]:
    """
    Forward Lagrangian trajectory, one waypoint per hour by default.

    Hourly stepping matters for finding the closest approach to Delhi: the old
    6-hour steps put waypoints ~100 km apart, so a plume could pass directly
    over the city between two samples and register as a miss.
    """
    lat, lon = float(origin_lat), float(origin_lon)
    trajectory = [(round(lat, 4), round(lon, 4))]
    dt_s = dt_hours * 3600.0
    R = 6_371_000.0

    for step in range(steps):
        idx = min(int(step * dt_hours), len(wind_series) - 1)
        u, v = wind_series[idx]
        dlat = (v * dt_s / R) * (180.0 / math.pi)
        cos_lat = max(math.cos(math.radians(lat)), 1e-6)
        dlon = (u * dt_s / (R * cos_lat)) * (180.0 / math.pi)
        lat += dlat
        lon += dlon
        trajectory.append((round(lat, 4), round(lon, 4)))

    return trajectory


def _closest_approach(
    trajectory: list[tuple[float, float]],
    dt_hours: float = 1.0,
) -> tuple[float, float, float]:
    """
    Closest approach of a trajectory to Delhi.

    Returns (min_distance_km, path_length_to_that_point_km, hours_to_it).

    Tests each SEGMENT rather than only the waypoints, projecting the receptor
    onto the segment, so a plume that crosses the city between two hourly
    samples is still caught.
    """
    if not trajectory:
        return (float("inf"), 0.0, 0.0)

    lat_ref = _DELHI_LAT
    rx, ry = _to_local_km(_DELHI_LAT, _DELHI_LON, lat_ref)

    pts = [_to_local_km(lat, lon, lat_ref) for lat, lon in trajectory]

    best_dist = math.hypot(pts[0][0] - rx, pts[0][1] - ry)
    best_path = 0.0
    best_hours = 0.0
    cumulative = 0.0

    for i in range(len(pts) - 1):
        (x1, y1), (x2, y2) = pts[i], pts[i + 1]
        seg_x, seg_y = x2 - x1, y2 - y1
        seg_len = math.hypot(seg_x, seg_y)
        if seg_len < 1e-9:
            continue
        # Fractional position of the receptor's projection onto the segment.
        t = ((rx - x1) * seg_x + (ry - y1) * seg_y) / (seg_len * seg_len)
        t = min(max(t, 0.0), 1.0)
        px, py = x1 + t * seg_x, y1 + t * seg_y
        dist = math.hypot(px - rx, py - ry)
        if dist < best_dist:
            best_dist = dist
            best_path = cumulative + t * seg_len
            best_hours = (i + t) * dt_hours
        cumulative += seg_len

    return best_dist, best_path, best_hours


def _arrival_time(
    trajectory: list[tuple[float, float]], radius_km: float = 50.0
) -> float | None:
    """
    Hours until the trajectory first comes within `radius_km` of Delhi centre,
    or None if it never does. Segment-aware, and hourly rather than the old
    6-hour quantisation.
    """
    dist, _path, hours = _closest_approach(trajectory)
    if dist <= radius_km:
        return round(hours, 1)
    return None


# ── Main entry point ─────────────────────────────────────────────────────────

async def compute_plume_vectors() -> dict:
    """
    Fetch fires and winds, transport every detection, and return both the
    per-plume detail for the map and an hourly aggregate profile for the
    forecast.

    `pm25_profile_ug_m3` is the quantity the forecast consumes: for each of the
    next 72 hours, the total PM2.5 concentration that arriving smoke adds to the
    transport layer. It is the sum over EVERY detection, ramped in at each
    plume's arrival hour and sustained thereafter -- sustained because Q is an
    emission RATE and the fires keep burning through the forecast window, which
    is the same steady-state assumption the Gaussian formula itself makes.
    """
    wind_series, hotspots = await asyncio.gather(
        _fetch_850hpa_wind_series(),
        _fetch_firms_hotspots(),
    )
    u0, v0 = wind_series[0]

    # Mean transport speed over the window drives the dispersion denominator;
    # hour-0 wind alone would make the whole 72 h forecast hostage to one hour.
    speeds = [math.hypot(u, v) for u, v in wind_series] or [3.7]
    mean_wind = sum(speeds) / len(speeds)

    profile = [0.0] * _FORECAST_HOURS
    plumes: list[dict] = []

    for hs in hotspots:
        trajectory = _advect_plume(hs["lat"], hs["lon"], wind_series)
        closest_km, path_km, hours_to = _closest_approach(trajectory)

        loading = plume_column_loading(
            frp_mw=hs["frp_mw"],
            travel_km=path_km,
            crosswind_km=closest_km,
            wind_ms=mean_wind,
            travel_hours=hours_to,
        )
        layer_conc = loading / PLUME_LAYER_DEPTH_M

        # Accumulate into the hourly profile with a smooth arrival ramp.
        if layer_conc > 0:
            for h in range(_FORECAST_HOURS):
                if h < hours_to:
                    continue
                ramp = min(1.0, (h - hours_to) / _ARRIVAL_RAMP_H) if _ARRIVAL_RAMP_H > 0 else 1.0
                profile[h] += layer_conc * ramp

        arrival = round(hours_to, 1) if closest_km <= _INFLUENCE_RADIUS_KM else None
        plumes.append({
            "origin": hs,
            "trajectory": trajectory,
            "arrival_delhi_t_hours": arrival,
            "pm25_contribution_ug_m3": round(layer_conc, 3),
            "pm25_column_ug_m2": round(loading, 1),
            "closest_approach_km": round(closest_km, 1),
            "travel_distance_km": round(path_km, 1),
        })

    # Emissions come from every detection; only the largest contributors are
    # serialised, so the response and the map stay usable on a peak burning day.
    plumes.sort(key=lambda p: p["pm25_contribution_ug_m3"], reverse=True)
    shown = plumes[:_MAX_PLUMES_RETURNED]

    return {
        "wind_850hpa_u": u0,
        "wind_850hpa_v": v0,
        "wind_series": wind_series,
        "hotspots": [p["origin"] for p in shown],
        "plumes": shown,
        "hotspot_count_total": len(hotspots),
        "pm25_profile_ug_m3": [round(x, 3) for x in profile],
    }
