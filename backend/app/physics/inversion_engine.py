"""
Atmospheric Inversion Engine
============================
Computes thermal inversion diagnostics from pressure-level temperature data,
and provides the physical kernels used by the two-way meteorology <-> chemistry
coupling in `services/aqi_service.py`.

Meteorology -> chemistry (dilution):
  dT = T(925 hPa) - T(1000 hPa)
  dT > 0  =>  temperature increases with altitude  =>  inversion (warm lid)
  Pollutants mix through the boundary layer, so surface concentration scales
  as (reference PBL / actual PBL).

Chemistry -> meteorology (aerosol radiative effect):
  PM2.5 column -> aerosol optical depth -> reduced surface shortwave
              -> surface cooling -> weaker buoyancy -> shallower PBL
  which raises PM2.5 again. `aqi_service` closes this loop by fixed-point
  iteration; every kernel below is a pure function so the loop is testable.

Design rule that matters: `pbl_from_stability()` is the ONLY place a PBL height
is perturbed, and it is the identity map when the aerosol cooling is zero. The
baseline and the perturbed PBL therefore always come from the same function, so
their difference is a real feedback signal rather than an artefact of comparing
two different PBL parameterisations.

Data source: Open-Meteo pressure-level API (free, no key needed).
"""

import math

# httpx is imported lazily inside fetch_inversion_data() rather than here, so the
# physics in this module can be imported and unit-tested with the standard library
# alone. Everything above the fetch is pure arithmetic; only the one function that
# actually talks to Open-Meteo needs an HTTP client.

# Open-Meteo endpoint for pressure-level data
_OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# Delhi centre coordinates used for met data fetch
_DELHI_LAT = 28.6139
_DELHI_LON = 77.2090

# ── Inversion severity thresholds (dT in °C between 1000 and 925 hPa) ────────
# Ranges follow the convention used in Indian boundary-layer literature for
# surface-based inversions; they are classification bands, not fitted values.
_INVERSION_THRESHOLDS = {
    "none": 0.0,
    "weak": 1.5,      # dT > 1.5°C
    "moderate": 3.5,  # dT > 3.5°C
    "strong": 6.0,    # dT > 6.0°C
}

# Reference (well-mixed) PBL height used to normalise the dilution factor.
# Concentrations from `_base_emissions_diurnal` are defined AT this height.
_PBL_BASE_HEIGHT_M = 1200.0

# Physical floor on mixing depth. Delhi winter nocturnal PBL is routinely
# 100-200 m; anything shallower is below the surface roughness sublayer where
# a uniformly-mixed box model stops being meaningful.
PBL_MIN_M = 150.0

# Ceiling on the dilution factor. 1200/150 = 8.0 is the geometric maximum;
# capping at 6.0 leaves headroom for the fact that emissions are not perfectly
# trapped (horizontal advection ventilates the box even under a strong lid).
_AMP_MAX = 6.0
_AMP_MIN = 0.25   # deep, well-ventilated afternoon PBL (~4800 m)

# ── Aerosol radiative feedback constants ─────────────────────────────────────
# Mass extinction efficiency of aged urban aerosol (m^2 per gram). Dry fine-mode
# MEE is ~4 m^2/g; hygroscopic growth at Delhi winter RH (70-90%) roughly
# doubles it. Range in the literature is 5-12 m^2/g.
_MEE_M2_PER_G = 8.0

# Aerosol is not confined to the mixed layer -- a residual layer and elevated
# transported smoke sit above it and still attenuate sunlight. This scales the
# mixed-layer column up to a whole-atmosphere column.
_COLUMN_ENHANCEMENT = 1.5

# Optical depth is physically unbounded but >3 means near-total extinction;
# clamp so the exponential below cannot be driven by a runaway concentration.
_AOD_MAX = 3.0

# Surface shortwave dimming per unit aerosol optical depth, as a fraction of the
# incoming flux. Observed clear-sky aerosol forcing efficiency at the surface
# over the Indo-Gangetic Plain is roughly -90 to -110 W/m^2 per unit AOD near
# local noon; at ~830 W/m^2 peak insolation that is a fraction of ~0.13.
# The response is close to LINEAR in AOD up to ~2 because Delhi aerosol contains
# enough black carbon to absorb rather than merely scatter forward.
_ATTEN_PER_AOD = 0.13

# Saturation ceiling: the maximum fraction of surface shortwave aerosol can
# remove. Not 1.0 -- scattering redistributes photons into the diffuse field,
# much of which still reaches the ground, so surface dimming saturates well
# below total extinction.
_ATTEN_MAX = 0.45

# Surface temperature response per W/m^2 of shortwave forcing (K / (W/m^2)).
# Gives ~2 K cooling for ~-100 W/m^2, consistent with reported aerosol-induced
# daytime surface cooling over the Indo-Gangetic Plain.
_DT_PER_SW = 0.02

# Sensitivity of mixing depth to surface cooling (1/K). exp(-0.15 * 1.5 K) = 0.80,
# i.e. ~20% PBL suppression for 1.5 K of aerosol cooling -- within the 10-30%
# range reported for high-aerosol Delhi winter days.
_PBL_LAMBDA_PER_K = 0.15

# Thermal memory of the surface, in hours. Aerosol dimming during the day leaves
# the surface colder at sunset, which strengthens the following nocturnal
# inversion. Without this the shortwave-driven feedback would be exactly zero at
# night -- precisely the regime Delhi's pollution episodes occur in.
_SURFACE_MEMORY_TAU_H = 8.0

# ── Chemistry -> meteorology: the wind leg ───────────────────────────────────
# Aerosol dimming stabilises the boundary layer: a cooler surface weakens the
# buoyant thermals that mix momentum down from the level of the wind maximum,
# so the surface flow weakens under a persistent haze. Weaker surface wind
# lengthens the ventilation timescale U/L in the box model, which raises PM2.5
# -- closing the loop. Reported 10 m wind declines of 10-30% on heavy-aerosol
# days are the observational basis; the cap below encodes the top of that band.
_WIND_REDUCTION_PER_K = 0.06   # fractional surface-wind reduction per K of cooling
_WIND_REDUCTION_MAX = 0.30     # saturating cap: momentum is not destroyed, only mixed more slowly


def _classify_inversion(delta_t: float) -> str:
    if delta_t < _INVERSION_THRESHOLDS["weak"]:
        return "None"
    elif delta_t < _INVERSION_THRESHOLDS["moderate"]:
        return "Weak"
    elif delta_t < _INVERSION_THRESHOLDS["strong"]:
        return "Moderate"
    return "Strong"


def _suppressed_pbl(delta_t: float) -> float:
    """
    Fallback PBL estimate from inversion strength, used ONLY when Open-Meteo
    does not return `boundary_layer_height` for an hour.

    Empirical exponential fit, not a model output:
      dT = 0    -> 1200 m (free convection)
      dT = 6°C  -> ~150 m (severe capping)

    Do NOT use this to perturb an observed PBL -- use `pbl_from_stability()`,
    which is the identity when there is no aerosol forcing. Mixing the two is
    the bug this docstring exists to prevent.
    """
    if delta_t <= 0:
        return _PBL_BASE_HEIGHT_M
    suppression = math.exp(-0.35 * delta_t)
    return max(PBL_MIN_M, _PBL_BASE_HEIGHT_M * suppression)


def amplification_factor(pbl_height_m: float) -> float:
    """
    Concentration amplification from boundary-layer compression.

    Assumes pollutants are uniformly mixed through depth `pbl_height_m`, so
    surface concentration scales inversely with mixing depth relative to the
    reference depth at which baseline emissions are defined.

        factor = reference_PBL / actual_PBL

    Bounded by [_AMP_MIN, _AMP_MAX]; see the constants for why.
    """
    pbl = max(float(pbl_height_m), PBL_MIN_M)
    factor = _PBL_BASE_HEIGHT_M / pbl
    return min(max(factor, _AMP_MIN), _AMP_MAX)


def _aqi_amplification(delta_t: float, pbl_height: float) -> float:
    """
    Back-compatible wrapper. `delta_t` is unused: the dilution factor depends on
    mixing depth alone, and dT already determined that depth upstream. Kept so
    existing call sites and tests keep working.
    """
    return amplification_factor(pbl_height)


# ── Chemistry -> meteorology kernels ─────────────────────────────────────────

def aerosol_optical_depth(pm25_ug_m3: float, pbl_height_m: float) -> float:
    """
    Column aerosol optical depth from a mixed-layer PM2.5 concentration.

        AOD = MEE [m^2/g] * concentration [g/m^3] * path length [m]

    The 1e-6 converts µg/m^3 to g/m^3, so the result is dimensionless.

    Sanity check: 200 µg/m^3 through a 300 m mixed layer gives AOD ~= 0.72,
    which is the right order for a severe Delhi winter day (MODIS retrievals
    reach 0.8-1.5).
    """
    if pm25_ug_m3 <= 0 or pbl_height_m <= 0:
        return 0.0
    aod = (
        _MEE_M2_PER_G
        * _COLUMN_ENHANCEMENT
        * (pm25_ug_m3 * 1e-6)
        * pbl_height_m
    )
    return min(aod, _AOD_MAX)


def shortwave_reduction(aod: float, solar_w_m2: float) -> float:
    """
    Reduction in surface shortwave flux caused by aerosol (W/m^2, <= 0).

        dSW = -solar_actual * min(ATTEN_MAX, ATTEN_PER_AOD * AOD)

    Linear in AOD with a saturation cap, which matches observed IGP forcing
    efficiency better than an exponential: `1 - exp(-AOD)` saturates by AOD ~1
    and would under-predict the severe winter cases that matter most.

    Gating on the ACTUAL incoming flux is what makes this physical -- at night
    `solar_w_m2` is 0, so aerosol cannot produce shortwave cooling. The previous
    implementation used a constant W/m^2 per AOD and therefore "cooled" the
    surface at 02:00.
    """
    if aod <= 0 or solar_w_m2 <= 0:
        return 0.0
    attenuation = min(_ATTEN_MAX, _ATTEN_PER_AOD * aod)
    return -solar_w_m2 * attenuation


def surface_cooling_from_sw(d_sw_w_m2: float) -> float:
    """
    Surface temperature perturbation (K) from a shortwave forcing.
    Negative forcing -> negative (cooling) response.
    """
    return d_sw_w_m2 * _DT_PER_SW


def pbl_from_stability(pbl_baseline_m: float, cooling_k: float) -> float:
    """
    Perturb a baseline mixing depth by aerosol-induced surface cooling.

        PBL = PBL_baseline * exp(-lambda * cooling)

    `cooling_k` is a POSITIVE magnitude in K. Critically this is the identity
    map at cooling_k = 0, so the baseline and perturbed depths are produced by
    the same function and their ratio isolates the feedback.
    """
    if cooling_k <= 0:
        return max(float(pbl_baseline_m), PBL_MIN_M)
    perturbed = float(pbl_baseline_m) * math.exp(-_PBL_LAMBDA_PER_K * cooling_k)
    return max(perturbed, PBL_MIN_M)


def surface_memory_decay() -> float:
    """
    Per-hour retention factor for the surface thermal memory, exp(-1/tau).
    Exposed as a function so `aqi_service` and the tests share one constant.
    """
    return math.exp(-1.0 / _SURFACE_MEMORY_TAU_H)


def wind_perturbation(cooling_k: float) -> float:
    """
    Fractional change in the surface wind (<= 0) from aerosol-induced cooling.

        dU/U = -min(WIND_REDUCTION_MAX, WIND_REDUCTION_PER_K * cooling)

    Physical picture: dimming cools the surface, the boundary layer stabilises,
    downward momentum mixing weakens, and the 10 m wind drops. This is the
    observed 'aerosol stagnation' response.

    Like `pbl_from_stability`, this is the IDENTITY (returns 0.0) at cooling = 0,
    so a clean column has exactly no wind feedback and any baseline/perturbed
    wind difference is a real signal rather than parameterisation mismatch.
    The result is a fraction in (-WIND_REDUCTION_MAX, 0]; multiply the wind by
    (1 + dU/U) to get the effective value.
    """
    if cooling_k <= 0:
        return 0.0
    return -min(_WIND_REDUCTION_MAX, _WIND_REDUCTION_PER_K * float(cooling_k))


async def fetch_inversion_data() -> dict:
    """
    Fetches T1000, T925 and boundary layer height for Delhi.
    Uses WeatherAPI meteorological telemetry and atmospheric profiling.
    """
    from app.services.weather_providers import fetch_forecast_weather
    return await fetch_forecast_weather(_DELHI_LAT, _DELHI_LON)


def compute_inversion_series(met_data: dict) -> list[dict]:
    """
    Takes raw Open-Meteo JSON, returns per-hour inversion diagnostics.
    Each dict maps cleanly to the InversionStatus schema.
    """
    hourly = met_data["hourly"]
    n = min(72, len(hourly["time"]))
    pbl_series = hourly.get("boundary_layer_height") or [None] * n
    results = []
    for i in range(n):
        t1000 = hourly["temperature_1000hPa"][i]
        t925 = hourly["temperature_925hPa"][i]
        pbl = pbl_series[i] if i < len(pbl_series) else None

        delta_t = t925 - t1000

        # Trust the model's boundary layer height. Only fall back to the
        # empirical fit when the field is genuinely missing. The old code
        # clamped every hour to >= 800 m "for summer", which erased the shallow
        # nocturnal layers that drive winter episodes.
        if pbl is not None and pbl > 0:
            pbl_h = max(float(pbl), PBL_MIN_M)
        else:
            pbl_h = _suppressed_pbl(delta_t)

        # Environmental lapse rate (K/km) between 1000 and 925 hPa.
        # Thickness of that layer is ~750 m in a standard atmosphere.
        # Gamma = -dT/dz, so a POSITIVE dT (inversion) gives a NEGATIVE gamma.
        altitude_diff_km = 0.75
        lapse_rate = -delta_t / altitude_diff_km  # negative = inverted, positive = normal

        severity = _classify_inversion(delta_t)

        results.append({
            "delta_t_celsius": round(delta_t, 2),
            "pbl_height_m": round(pbl_h, 1),
            "lapse_rate_k_per_km": round(lapse_rate, 2),
            # Derived from `severity`, NOT recomputed as `delta_t > threshold`.
            # It used to be the latter, and the two disagreed at exactly the
            # threshold: `_classify_inversion` treats the boundary as inclusive
            # (`delta_t < weak` -> "None"), while `>` treats it as exclusive, so
            # dT = 1.5 was reported as severity "Weak" with inversion_present
            # False. The dashboard would render a Weak badge while any consumer
            # gating on the flag saw no inversion. Deriving one from the other
            # makes the whole class of disagreement impossible.
            "inversion_present": severity != "None",
            "severity": severity,
            "aqi_amplification_factor": round(amplification_factor(pbl_h), 3),
        })
    return results
