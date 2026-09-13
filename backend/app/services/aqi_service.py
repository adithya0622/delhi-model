"""
AQI Service — CPCB Sub-Index Calculations & 72-Hour Forecast Rollout
=====================================================================
Implements the official CPCB National AQI methodology (2014 standard) on top of
a prognostic single-column model, coupled two ways to the meteorology.

Architecture
------------
  physics/box_model.py       mass budget: emission, ventilation, deposition,
                             entrainment, stranding aloft  (the chemistry)
  physics/inversion_engine.py inversion diagnostics + the aerosol radiative
                             kernels                       (the meteorology)
  this module                closes the loop between them and maps the result
                             onto the CPCB index

Two-way coupling, solved as a fixed point
-----------------------------------------
Meteorology -> chemistry: the mixed-layer depth sets both dilution AND
accumulation. A collapsing lid strands pollution aloft and concentrates what
remains; a growing lid entrains it back down. This is handled by
`box_model.step`, which is prognostic -- hour N depends on hour N-1, so an
inversion genuinely traps rather than merely scaling a steady state.

Chemistry -> meteorology: the PM2.5 column sets an optical depth, which removes
surface shortwave, which cools the surface, which suppresses buoyancy and
shallows the mixed layer -- which raises PM2.5 again.

Because each direction depends on the other, every hour is solved by Picard
iteration in `_solve_coupled_hour()`. Three properties make the answer
trustworthy:

  * The baseline and perturbed mixing depths both come from
    `pbl_from_stability()`, which is the IDENTITY at zero aerosol cooling. Their
    ratio is therefore a real feedback signal. The previous implementation
    differenced an amplification built from the observed Open-Meteo PBL against
    one built by an unrelated empirical formula; that difference was dominated
    by the mismatch between the two parameterisations and collapsed to exactly
    zero in the shallow-PBL regime the model exists to capture.
  * Shortwave forcing is gated on the actual incoming solar flux, so the daytime
    mechanism is absent at night instead of being applied round the clock with a
    constant coefficient.
  * Nocturnal episodes are carried by a surface thermal-memory term: daytime
    aerosol dimming leaves the surface colder at sunset, strengthening the
    following night's inversion.

Honesty note
------------
This is a parameterised single-column surrogate, not a chemistry transport
model. Emission fluxes and backgrounds in `box_model.SPECIES` are hand-set to
reproduce the order of magnitude and diurnal shape of CPCB Delhi climatology.
No accuracy figure should be quoted for this model unless code in `tests/`
computes it against withheld observations.
"""


import asyncio
import math
from datetime import datetime, timezone

from app.physics import box_model
from app.physics.box_model import BoxColumn
from app.physics.inversion_engine import (
    PBL_MIN_M,
    aerosol_optical_depth,
    amplification_factor,
    compute_inversion_series,
    pbl_from_stability,
    shortwave_reduction,
    surface_cooling_from_sw,
    surface_memory_decay,
    wind_perturbation,
)
from app.physics.plume_advection import compute_plume_vectors
from app.physics import plume_advection
from app.domain.aqi_scales import (
    EPA_MODE_NAMES,
    _cat as scale_category,
    _sub_index as scale_sub_index,
    aqi_input_details,
    aqi_method,
    epa_nowcast,
    rolling_mean,
    aqi_standard,
)
from app.domain.species import AQICategory, Pollutant
from app.domain.units import CANONICAL_CONCENTRATION_LABEL
from app.services.ml_forecast_service import predict_pm25_series
from app.services.weather_providers import fetch_forecast_weather

# ── CPCB Breakpoint tables (concentration → sub-index) ───────────────────────
# Format: [(C_lo, C_hi, I_lo, I_hi), ...]
_BREAKPOINTS: dict[Pollutant, list[tuple[float, float, int, int]]] = {
    Pollutant.PM25: [
        (0.0, 30.0, 0, 50),
        (30.0, 60.0, 51, 100),
        (60.0, 90.0, 101, 200),
        (90.0, 120.0, 201, 300),
        (120.0, 250.0, 301, 400),
        (250.0, 500.0, 401, 500),
    ],
    Pollutant.PM10: [
        (0, 50, 0, 50),
        (50, 100, 51, 100),
        (100, 250, 101, 200),
        (250, 350, 201, 300),
        (350, 430, 301, 400),
        (430, 600, 401, 500),
    ],
    Pollutant.O3: [
        (0, 50, 0, 50),
        (50, 100, 51, 100),
        (100, 168, 101, 200),
        (168, 208, 201, 300),
        (208, 748, 301, 400),
        (748, 1000, 401, 500),
    ],
    Pollutant.NO2: [
        (0, 40, 0, 50),
        (40, 80, 51, 100),
        (80, 180, 101, 200),
        (180, 280, 201, 300),
        (280, 400, 301, 400),
        (400, 800, 401, 500),
    ],
    Pollutant.SO2: [
        (0, 40, 0, 50),
        (40, 80, 51, 100),
        (80, 380, 101, 200),
        (380, 800, 201, 300),
        (800, 1600, 301, 400),
        (1600, 2000, 401, 500),
    ],
    Pollutant.CO: [
        (0, 1.0, 0, 50),
        (1.0, 2.0, 51, 100),
        (2.0, 10.0, 101, 200),
        (10.0, 17.0, 201, 300),
        (17.0, 34.0, 301, 400),
        (34.0, 50.0, 401, 500),
    ],
}

_CATEGORY_BREAKS = [
    (0, 50, AQICategory.GOOD),
    (51, 100, AQICategory.SATISFACTORY),
    (101, 200, AQICategory.MODERATE),
    (201, 300, AQICategory.POOR),
    (301, 400, AQICategory.VERY_POOR),
    (401, 500, AQICategory.SEVERE),
]

# ── Fixed-point solver settings ──────────────────────────────────────────────
_MAX_PICARD_ITER = 12
_PICARD_RELAX = 0.6      # under-relaxation; the loop is monotone and can oscillate
_PBL_TOL_M = 1.0         # convergence tolerance on mixing depth

# ── Seasonal scaling of emissions and regional background ────────────────────
# Fractions of the Nov/Dec climatological peak. Shape follows CPCB Delhi
# monthly-mean PM2.5: a deep monsoon minimum (~30% of peak), a sharp October
# rise as the monsoon withdraws and stubble burning starts, a Nov-Jan plateau.
_SEASON_PM25 = {
    1: 0.95, 2: 0.70, 3: 0.50, 4: 0.45, 5: 0.42, 6: 0.38,
    7: 0.28, 8: 0.30, 9: 0.42, 10: 0.75, 11: 1.00, 12: 1.00,
}

# PM10 carries a large crustal/dust component, so its seasonality is flatter
# with a secondary pre-monsoon (Apr–Jun) dust maximum.
_SEASON_PM10 = {
    1: 0.85, 2: 0.75, 3: 0.70, 4: 0.80, 5: 0.90, 6: 0.90,
    7: 0.45, 8: 0.40, 9: 0.55, 10: 0.80, 11: 1.00, 12: 0.95,
}

# Gaseous emissions (traffic, industry) barely vary month to month; the observed
# seasonal swing in NO2/CO is mostly dilution, which the box model already
# supplies. The residual accounts for winter space heating.
_SEASON_GAS_FLOOR = 0.70

# ── Photochemical O3 ─────────────────────────────────────────────────────────
# O3 is not carried by the box model: its lifetime is short and it is produced
# in situ rather than emitted, so a diagnostic balance is more appropriate.
# Regional background over the Indo-Gangetic Plain (µg/m³). Present day AND
# night; the previous model returned exactly 0 after sunset, which is wrong --
# surface O3 at night is titrated by fresh NO, not annihilated.
_O3_BACKGROUND_UG = 35.0
_O3_SOLAR_COEFF = 0.11        # µg/m³ of O3 per W/m² of shortwave
_O3_NOX_SUPPRESSION = 0.35    # fractional daytime loss per 100 µg/m³ NO2
_O3_NIGHT_TITRATION = 0.45    # fractional nighttime loss per 100 µg/m³ NO2
_O3_FLOOR_UG = 4.0

# ── Plume coupling ───────────────────────────────────────────────────────────
# Advected smoke is handled as an elevated regional background inside the box
# model (see `box_model.step`), not as a surface emission flux. The plume module
# returns the smoke concentration in the transport layer, so no depth or
# persistence constant is needed here -- the previous version's conversion
# applied the mixing-depth dependence twice, once in the plume Gaussian and again
# in the box model.

_DT_S = 3600.0     # forecast timestep: Open-Meteo is hourly

# ── Open-Meteo field sets ────────────────────────────────────────────────────
# CORE is everything the coupled column cannot run without. Anything outside it
# is presentational or reserved for future physics, so a provider that rejects one
# unfamiliar name must not be able to take the forecast down -- hence the retry in
# `_fetch_met_with_solar`, which falls back to CORE alone.
_HOURLY_CORE = (
    "temperature_1000hPa",
    "temperature_925hPa",
    "boundary_layer_height",
    "shortwave_radiation",
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "wind_speed_10m",
    "wind_direction_10m",
)

# Extended surface/soil/profile fields. The 80/120/180 m winds and temperatures
# give the shear and above-canopy profile the ventilation term currently has to
# infer from the 10 m wind alone; the soil block matters for dust suspension.
_HOURLY_EXTENDED = (
    "dew_point_2m",
    "apparent_temperature",
    "precipitation_probability",
    "rain",
    "showers",
    "snowfall",
    "snow_depth",
    "weather_code",
    "pressure_msl",
    "surface_pressure",
    "cloud_cover",
    "cloud_cover_low",
    "cloud_cover_mid",
    "cloud_cover_high",
    "visibility",
    "evapotranspiration",
    "et0_fao_evapotranspiration",
    "vapour_pressure_deficit",
    "wind_speed_80m",
    "wind_speed_120m",
    "wind_speed_180m",
    "wind_direction_80m",
    "wind_direction_120m",
    "wind_direction_180m",
    "wind_gusts_10m",
    "temperature_80m",
    "temperature_120m",
    "temperature_180m",
    "soil_temperature_0cm",
    "soil_temperature_6cm",
    "soil_temperature_18cm",
    "soil_temperature_54cm",
    "soil_moisture_0_to_1cm",
    "soil_moisture_1_to_3cm",
    "soil_moisture_3_to_9cm",
    "soil_moisture_9_to_27cm",
    "soil_moisture_27_to_81cm",
)

_DAILY_FIELDS = (
    "weather_code",
    "temperature_2m_max",
    "temperature_2m_min",
    "apparent_temperature_max",
    "apparent_temperature_min",
    "uv_index_max",
    "sunrise",
    "sunset",
    "daylight_duration",
    "sunshine_duration",
    "wind_speed_10m_max",
    "wind_gusts_10m_max",
    "wind_direction_10m_dominant",
    "shortwave_radiation_sum",
    "et0_fao_evapotranspiration",
    "precipitation_probability_max",
    "precipitation_hours",
    "precipitation_sum",
)

_CURRENT_FIELDS = (
    "temperature_2m",
    "relative_humidity_2m",
    "apparent_temperature",
    "is_day",
    "precipitation",
    "rain",
    "showers",
    "snowfall",
    "weather_code",
    "surface_pressure",
    "pressure_msl",
    "cloud_cover",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
)

# Wire-name -> species, shared by the observational seeding and the hour-0 nudge.
_POLLUTANT_BY_NAME: dict[str, Pollutant] = {
    "PM2.5": Pollutant.PM25,
    "PM10": Pollutant.PM10,
    "NO2": Pollutant.NO2,
    "SO2": Pollutant.SO2,
    "CO": Pollutant.CO,
    "O3": Pollutant.O3,
}


def _linear_interpolate_subindex(concentration: float, breakpoints: list[tuple]) -> int:
    """CPCB linear interpolation within a breakpoint segment."""
    if concentration is None or concentration <= 0:
        return 0
    if concentration >= breakpoints[-1][1]:
        return breakpoints[-1][3]
    for C_lo, C_hi, I_lo, I_hi in breakpoints:
        if C_lo <= concentration <= C_hi:
            if C_hi == C_lo:
                return I_hi
            return round(I_lo + (I_hi - I_lo) * (concentration - C_lo) / (C_hi - C_lo))
    # CPCB segments are contiguous, so this is unreachable. Snap up rather than
    # silently reporting 500 for a value that merely failed to match a segment.
    for C_lo, _C_hi, I_lo, _I_hi in breakpoints:
        if concentration < C_lo:
            return I_lo
    return breakpoints[-1][3]


def _aqi_category(index: int, mode: str = "instant") -> AQICategory:
    return AQICategory(scale_category(index, mode)[0])


def compute_sub_indices(
    concentrations: dict[Pollutant, float], mode: str = "instant",
    aqi_concentrations: dict[Pollutant, float] | None = None,
    aqi_averaging: dict[Pollutant, str] | None = None,
) -> list[dict]:
    """Compute scale-specific sub-indices from canonical ug/m3 concentrations."""
    results = []
    for pollutant, conc in concentrations.items():
        if pollutant not in _BREAKPOINTS:
            continue
        # Clamp BOTH ends. The upper bound was already here; the lower one was
        # not. This is defensive rather than a fix for a reachable path -- the
        # interpolator's fall-through already returns the lowest segment floor
        # for a sub-range value -- but the schema declares sub_index as ge=0 and
        # `_aqi_category` has no band below 0, so anything negative arriving here
        # would either 500 the response or be silently labelled "Severe", which
        # is the worst possible way to render clean air. Cheap to make impossible.
        raw = max(0.0, float(conc))
        raw_aqi = max(
            0.0,
            float((aqi_concentrations or {}).get(pollutant, raw)),
        )
        if pollutant is Pollutant.CO:
            # The box carries CO mass in mg/m³ while every other species is in
            # µg/m³, but the scale boundary is canonical µg/m³ for all modes
            # (CPCB converts to mg and EPA to ppm internally). Without this a
            # real 1.2 mg/m³ reading scored sub-index 0. Convert once, here,
            # where physics meets reporting -- never inside the mass budget.
            canonical = raw * 1000.0
            aqi_concentration = raw_aqi * 1000.0
        else:
            canonical = raw
            aqi_concentration = raw_aqi
        idx = max(0, min(scale_sub_index(pollutant.value, aqi_concentration, mode), 500))
        try:
            aqi_value, aqi_unit = aqi_input_details(
                pollutant.value, aqi_concentration, mode
            )
        except ValueError:
            continue
        results.append({
            "pollutant": pollutant,
            # Never report a negative concentration either; a bad upstream
            # reading should show as 0, not as a physically impossible value.
            "concentration": round(canonical, 2),
            "concentration_unit": CANONICAL_CONCENTRATION_LABEL,
            "aqi_concentration": aqi_value,
            "aqi_unit": aqi_unit,
            "aqi_averaging_period": (aqi_averaging or {}).get(
                pollutant, "instant concentration"
            ),
            "sub_index": idx,
            "category": _aqi_category(idx, mode),
        })
    return results


def _aqi_from_conc(
    concentrations: dict[Pollutant, float], mode: str = "instant"
) -> int:
    """Selected AQI = max of pollutant sub-indices."""
    subs = compute_sub_indices(concentrations, mode)
    return max((s["sub_index"] for s in subs), default=0)


def _scale_conc(conc: dict[Pollutant, float], factor: float) -> dict[Pollutant, float]:
    """Scale the accumulated pollutant column by `factor`, leaving O3 untouched.

    O3 is not a box-model species: it is diagnosed each hour from the shortwave
    flux in `_solve_coupled_hour`, not accumulated as a mass budget. The hour-0
    observational correction constrains the accumulated load (PM2.5/PM10/NO2/
    SO2/CO), so it must not rescale the photochemical O3 diagnostic along with it.
    """
    return {
        p: (c * factor if p is not Pollutant.O3 else c)
        for p, c in conc.items()
    }


def _conc_scale_for_target_aqi(
    conc: dict[Pollutant, float], target_aqi: int, lo: float, hi: float,
    mode: str = "instant",
) -> float:
    """Column scale factor in [lo, hi] whose CPCB AQI matches `target_aqi`.

    The observational anchor from OpenAQ is an AQI, not a concentration, so we
    cannot scale the column by a ratio directly. AQI is monotone in a uniform
    concentration scale (every sub-index is monotone in concentration and the AQI
    is their max), so a bisection converges on the factor that reproduces the
    observed AQI. Working in concentration space -- rather than multiplying the
    headline AQI -- is what keeps aqi == max(sub-indices) in the response.
    """
    if target_aqi <= 0:
        return lo
    if _aqi_from_conc(_scale_conc(conc, lo), mode) >= target_aqi:
        return lo
    if _aqi_from_conc(_scale_conc(conc, hi), mode) <= target_aqi:
        return hi
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        if _aqi_from_conc(_scale_conc(conc, mid), mode) < target_aqi:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _photochemical_o3(
    solar_w_m2: float,
    no2_ug_m3: float,
    pbl_m: float,
) -> float:
    """
    Surface O3 as regional background plus in-situ photochemical production,
    minus NO titration.

    Daytime: production scales with the shortwave flux that actually reaches the
    surface, so the aerosol dimming computed by the feedback loop suppresses O3 —
    the observed behaviour on hazy Delhi days.

    Nighttime: production stops but background O3 does not vanish. Fresh NO
    titrates it, most effectively when NOx is trapped in a shallow layer, so a
    collapsing lid simultaneously raises PM2.5 and destroys O3.
    """
    no2 = max(0.0, float(no2_ug_m3))
    if solar_w_m2 <= 0:
        shallow = min(2.0, 1200.0 / max(pbl_m, PBL_MIN_M) / 2.0)
        titration = min(0.92, _O3_NIGHT_TITRATION * (no2 / 100.0) * shallow)
        return round(max(_O3_FLOOR_UG, _O3_BACKGROUND_UG * (1.0 - titration)), 2)

    production = _O3_SOLAR_COEFF * solar_w_m2
    suppression = max(0.15, 1.0 - _O3_NOX_SUPPRESSION * (no2 / 100.0))
    return round(max(_O3_FLOOR_UG, _O3_BACKGROUND_UG + production * suppression), 2)


def seasonal_factors(month: int) -> dict[str, float]:
    """Seasonal multipliers keyed by the `season` field of box_model.Species."""
    f_pm25 = _SEASON_PM25.get(month, 0.6)
    f_pm10 = _SEASON_PM10.get(month, 0.7)
    return {
        "pm25": f_pm25,
        "pm10": f_pm10,
        "gas": _SEASON_GAS_FLOOR + (1.0 - _SEASON_GAS_FLOOR) * f_pm25,
        # The monsoon washes out LOCAL emissions, but the regional background is
        # advected IGP air: its seasonal swing is much flatter (Delhi August
        # climatology ~55-65 ug/m3 vs ~150-200 in November, not 0.3x). Applying
        # the emission factor to the background made monsoon hindcasts
        # under-predict by ~50% - a calibration error the hindcast caught.
        # Floor 0.72 puts the August background near 40 ug/m3, which with local
        # emissions reproduces the ~55-65 observed; the remainder of the monsoon
        # gap is attributed to the emission factor, honestly left as error.
        "bg": 0.72 + 0.45 * f_pm25,
    }


def emission_scale(hour_local: int) -> dict[Pollutant, float]:
    """
    Diurnal emission multipliers by species.

    `hour_local` MUST already be Indian Standard Time. Open-Meteo is queried with
    timezone=Asia/Kolkata, so its timestamps are already IST — adding an offset
    on top (as the previous version did) slid the whole traffic cycle by five
    hours and put the morning rush at 02:00.

    Aerosol and gas profiles differ deliberately. Traffic NOx and CO collapse
    overnight, but PM does not: residential biomass and waste burning run late
    into the night through the Delhi winter, and heavy vehicles are only
    permitted after 23:00.
    """
    h = int(hour_local) % 24

    aero_morning = 1.5 if 7 <= h <= 10 else 1.0
    aero_evening = 1.8 if 17 <= h <= 22 else 1.0
    aero_night = 0.80 if 0 <= h <= 5 else 1.0
    aero = max(aero_morning, aero_evening) * aero_night

    traf_morning = 1.6 if 7 <= h <= 10 else 1.0
    traf_evening = 1.8 if 17 <= h <= 21 else 1.0
    traf_night = 0.45 if 1 <= h <= 5 else 1.0
    traf = max(traf_morning, traf_evening) * traf_night

    return {
        Pollutant.PM25: aero,
        Pollutant.PM10: aero,
        Pollutant.NO2: traf,
        Pollutant.CO: traf,
        Pollutant.SO2: 1.0,     # industrial, near-constant
    }


def _solve_coupled_hour(
    col: BoxColumn,
    pbl_observed_m: float,
    solar_w_m2: float,
    wind_ms: float,
    emis_scale: dict[Pollutant, float],
    season: dict[str, float],
    plume_pm25: float,
    cooling_carry_k: float,
    dt_s: float = _DT_S,
    pm25_target_ug_m3: float | None = None,
    wind_carry_k: float = 0.0,
) -> dict:
    """
    Advance one hour of the coupled meteorology <-> chemistry system.

    Unknowns are the mixing depth and the aerosol load; each determines the
    other. The loop trial-steps a CLONE of the column to find the self-consistent
    depth, then commits exactly one real step at that depth so the prognostic
    mass budget stays exact.

    `plume_pm25` is the smoke concentration in the transport layer arriving over
    Delhi this hour; the box model applies it as an elevated regional background.

    `cooling_carry_k` is the surface thermal memory from preceding hours
    (positive kelvin of cooling); it is what keeps the feedback alive after
    sunset, when the shortwave term is necessarily zero.

    `wind_carry_k` is the effective cooling that drove the PREVIOUS hour's
    surface-wind response. The wind reacts to aerosol with a lag: momentum
    already in the boundary layer keeps flowing for a while after the thermals
    that mixed it down weaken. Passing last hour's cooling here closes the wind
    leg of the two-way loop without making the wind a function of the hour's own
    concentration -- which would add a second fixed point inside the first.
    """
    pbl_observed_m = max(float(pbl_observed_m), PBL_MIN_M)
    solar_w_m2 = max(0.0, float(solar_w_m2 or 0.0))
    cooling_carry_k = max(0.0, float(cooling_carry_k))
    wind_carry_k = max(0.0, float(wind_carry_k))
    pm25_target = (
        max(0.0, min(1000.0, float(pm25_target_ug_m3)))
        if pm25_target_ug_m3 is not None and math.isfinite(float(pm25_target_ug_m3))
        else None
    )

    h = pbl_observed_m
    aod = d_sw = 0.0
    cooling_instant = 0.0
    cooling_eff = cooling_carry_k
    # The wind leg enters BEFORE the Picard loop: hour i's wind responds to hour
    # i-1's cooling, so it is a known input this hour, not an unknown to solve
    # for. A lagged (semi-implicit) wind is also what keeps the existing Picard
    # convergence guarantees intact -- the loop still solves for ONE unknown.
    wind_frac = wind_perturbation(wind_carry_k)
    wind_effective = max(0.0, float(wind_ms)) * (1.0 + wind_frac)
    iterations = 0
    converged = False

    for it in range(1, _MAX_PICARD_ITER + 1):
        iterations = it
        trial = col.clone()
        conc = box_model.step(
            trial, h, dt_s, emis_scale, wind_effective, season, plume_pm25
        )

        # Assimilate trained/live PM2.5 in concentration space before the
        # radiative leg. This makes ML chemistry alter AOD, cooling and solved
        # PBL rather than being pasted onto an already-finished physics output.
        if pm25_target is not None:
            trial.mixed[Pollutant.PM25] = pm25_target * trial.h_m
            conc[Pollutant.PM25] = pm25_target

        aod = aerosol_optical_depth(conc[Pollutant.PM25], h)
        d_sw = shortwave_reduction(aod, solar_w_m2)
        cooling_instant = -surface_cooling_from_sw(d_sw)      # positive kelvin

        # The lid responds to whichever is stronger: this hour's dimming, or the
        # heat deficit still stored in the surface from earlier hours.
        cooling_eff = max(cooling_instant, cooling_carry_k)

        h_target = pbl_from_stability(pbl_observed_m, cooling_eff)
        h_next = _PICARD_RELAX * h_target + (1.0 - _PICARD_RELAX) * h

        if abs(h_next - h) < _PBL_TOL_M:
            h = h_next
            converged = True
            break
        h = h_next

    # Commit the accepted step to the real column -- at the FEEDBACK wind, not
    # the raw met wind, so the ventilation the mass budget experiences is the
    # same one the trial steps used.
    conc = box_model.step(col, h, dt_s, emis_scale, wind_effective, season, plume_pm25)
    if pm25_target is not None:
        col.mixed[Pollutant.PM25] = pm25_target * col.h_m
        conc[Pollutant.PM25] = pm25_target

    # O3 sees the DIMMED shortwave flux, closing the loop on photochemistry too.
    solar_effective = max(0.0, solar_w_m2 + d_sw)
    conc[Pollutant.O3] = _photochemical_o3(
        solar_effective, conc[Pollutant.NO2], h
    )

    return {
        "conc": conc,
        "pbl_m": h,
        "pbl_observed_m": pbl_observed_m,
        "amp": amplification_factor(h),
        "aod": aod,
        "d_sw_w_m2": d_sw,
        "cooling_instant_k": cooling_instant,
        "cooling_effective_k": cooling_eff,
        "dt_surface_c": -cooling_eff,
        "solar_effective_w_m2": solar_effective,
        "wind_effective_ms": wind_effective,
        "wind_perturbation_frac": wind_frac,
        "iterations": iterations,
        "converged": converged,
        "pm25_assimilated": pm25_target is not None,
    }


def _plume_layer_conc(plume_data: dict, n_hours: int) -> list[float]:
    """
    Per-hour stubble-smoke concentration in the transport layer (µg/m³).

    Prefers the aggregate profile the plume module now publishes, which is summed
    over EVERY fire detection. Falls back to summing the per-plume values for
    plumes that have arrived, which is what the old interface supported and is
    still what a hand-built test payload will provide.
    """
    profile = plume_data.get("pm25_profile_ug_m3") or []
    if profile:
        return [
            float(profile[i]) if i < len(profile) else float(profile[-1])
            for i in range(n_hours)
        ]

    plumes = plume_data.get("plumes") or []
    out: list[float] = []
    for h in range(n_hours):
        total = 0.0
        for p in plumes:
            arrival = p.get("arrival_delhi_t_hours")
            if arrival is not None and arrival <= h:
                total += float(p.get("pm25_contribution_ug_m3", 0.0) or 0.0)
        out.append(total)
    return out


async def build_72h_forecast(
    lat: float,
    lon: float,
    station_name: str,
    live_pm25: float | None = None,
    live_pm10: float | None = None,
    base_aqi: int | None = None,
    live_pollutants: dict[str, float] | None = None,
    aqi_mode: str = "epa",
    live_pm25_history: list[dict] | None = None,
    met_data_override: dict | None = None,
    plume_override: dict | None = None,
    use_ml: bool = True,
) -> dict:
    """
    Assembles the full 72-hour forecast.

    base_aqi: live station/city AQI used to bias-correct hour 0. This is
    observational nudging, not physics — the ratio of observed to modelled AQI at
    hour 0 is applied to the whole series with an exponential decay, so the curve
    starts on the real value and relaxes to pure model output. The ratio is
    clamped so a single stuck sensor cannot distort 72 hours of forecast.
    """
    if aqi_mode not in {"instant", *EPA_MODE_NAMES}:
        raise ValueError("aqi_mode must be 'epa' or 'instant'")

    async def _fetch_met_with_solar():
        # Backtest hook: a hindcast supplies ANALYSIS meteorology for a past
        # window instead of a live forecast. Used only by the validation path.
        if met_data_override is not None:
            return met_data_override
        # Provider failover lives in weather_providers: Open-Meteo first (the only
        # source with a measured boundary layer and temperatures aloft), then
        # WeatherAPI. A single exhausted quota no longer takes the forecast down.
        return await fetch_forecast_weather(lat, lon)

    async def _fetch_air_quality_forecast():
        import httpx as _httpx
        # Full co-pollutant set: pm2_5 is the truth the ML model is scored
        # against and its history anchor; the co-pollutants (pm10, gases) are
        # leak-free v2 model features at the target hour. `past_days=2` supplies
        # the origin history so the trained model can run live without any key.
        params = {
            "latitude": lat,
            "longitude": lon,
            "hourly": "pm2_5,pm10,nitrogen_dioxide,ozone,sulphur_dioxide,carbon_monoxide,aerosol_optical_depth,dust",
            "past_days": 2,
            "forecast_hours": 72,
            "timezone": "Asia/Kolkata",
        }
        try:
            async with _httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get("https://air-quality-api.open-meteo.com/v1/air-quality", params=params)
                r.raise_for_status()
                return r.json()
        except _httpx.HTTPError:
            # CAMS drives optional ML correction. Core coupled forecast remains
            # available when this independent provider fails.
            return {}

    met_data, plume_data_live, air_quality_data = await asyncio.gather(
        _fetch_met_with_solar(),
        compute_plume_vectors(),
        _fetch_air_quality_forecast(),
    )
    # FIRMS reports only the current overpass snapshot, so a hindcast runs
    # smoke-free: the plume contribution is excluded from validation rather than
    # simulated with made-up historical fires.
    if plume_override is not None:
        # An empty payload yields an all-zero profile via `_plume_layer_conc`:
        # the hindcast runs smoke-free because FIRMS has no historical archive
        # at this tier, and the code does not invent fires to fill the gap.
        plume_data = dict(plume_override)
        plume_data.setdefault("pm25_profile_ug_m3", [0.0] * 72)
        plume_data.setdefault("wind_series", [plume_advection._FALLBACK_WIND_UV])
    else:
        plume_data = plume_data_live

    # CAMS is the preferred chemistry predictor, but when it is unavailable the
    # WeatherAPI fallback carries its own per-hour PM2.5, so the trained model
    # still has a chemistry covariate instead of dropping to physics-only.
    if not (air_quality_data.get("hourly") or {}).get("pm2_5"):
        fallback_chem = met_data.get("chemistry") or {}
        if fallback_chem.get("pm2_5"):
            air_quality_data = {
                "hourly": {
                    "time": list(met_data["hourly"].get("time") or []),
                    **fallback_chem,
                },
                "source": met_data.get("weather_source", "weatherapi"),
            }

    inversion_series = compute_inversion_series(met_data)
    required_fields = (
        "time",
        "temperature_1000hPa",
        "temperature_925hPa",
        "boundary_layer_height",
        "shortwave_radiation",
        "temperature_2m",
        "relative_humidity_2m",
        "precipitation",
        "wind_speed_10m",
        "wind_direction_10m",
    )
    lengths = {
        name: len(met_data["hourly"].get(name) or []) for name in required_fields
    }
    if min(lengths.values()) < 72:
        raise RuntimeError(f"Open-Meteo returned fewer than 72 values: {lengths}")
    n_hours = 72

    hourly = met_data["hourly"]
    hourly_times = hourly["time"][:n_hours]

    def _series(name: str, default: float = 0.0) -> list:
        values = hourly.get(name) or []
        return [values[i] if i < len(values) and values[i] is not None else default for i in range(n_hours)]

    solar_raw = _series("shortwave_radiation")
    wind10_raw = _series("wind_speed_10m")
    wind_dir10_raw = _series("wind_direction_10m")
    temperature2_raw = _series("temperature_2m")
    humidity_raw = _series("relative_humidity_2m")
    precipitation_raw = _series("precipitation")
    dewpoint_raw = _series("dew_point_2m")
    apparent_raw = _series("apparent_temperature")
    precip_probability_raw = _series("precipitation_probability")
    rain_raw = _series("rain")
    showers_raw = _series("showers")
    visibility_raw = _series("visibility")
    cloud_cover_raw = _series("cloud_cover")
    surface_pressure_raw = _series("surface_pressure")
    pressure_msl_raw = _series("pressure_msl")
    weather_code_raw = _series("weather_code")
    wind_gust_raw = _series("wind_gusts_10m")
    wind_series = plume_data.get("wind_series") or [plume_advection._FALLBACK_WIND_UV]

    def _solar_at(i: int) -> float:
        if i < len(solar_raw) and solar_raw[i] is not None:
            return max(0.0, float(solar_raw[i]))
        return 0.0

    def _wind_at(i: int) -> float:
        """Surface wind in m/s, used for the ventilation term."""
        if i < len(wind10_raw) and wind10_raw[i] is not None:
            return max(0.0, float(wind10_raw[i]))
        u, v = wind_series[min(i, len(wind_series) - 1)]
        return math.sqrt(u * u + v * v) * 0.45   # scale 850 hPa down to 10 m

    # Per-hour smoke concentration in the transport layer, summed over all fires.
    plume_conc_by_hour = _plume_layer_conc(plume_data, n_hours)

    # Backtest mode skips the trained model: it was fitted on CAMS, and a
    # hindcast scored against CAMS would report training fit, not skill.
    if not use_ml:
        ml_pm25 = [None] * n_hours
        ml_status = {
            "available": False,
            "used": False,
            "reason": "disabled for hindcast validation (trained on the verification dataset)",
        }
    else:
        ml_pm25, ml_status = predict_pm25_series(
            forecast_times=hourly_times,
            weather_payload=met_data,
            air_quality_payload=air_quality_data,
            history_rows=live_pm25_history,
            station_lat=lat,
            station_lon=lon,
        )

    first_dt = datetime.fromisoformat(hourly_times[0])
    season0 = seasonal_factors(first_dt.month)
    decay = surface_memory_decay()

    def _seed_column() -> BoxColumn:
        """Initial condition built only from data available at issue time.

        This replaces a 24-hour spin-up that replayed the first 24 FORECAST
        hours before starting the forecast. That made hour 0 a function of
        tomorrow's meteorology and of plume arrivals that have not happened
        yet: nobody standing at the issue time with the same inputs could
        reproduce it, and editing hour 40's weather moved hour 0. Observed
        pollutant concentrations are the legitimate initial condition, and they
        anchor the column far better than any replay did.
        """
        col = BoxColumn.at_background(inversion_series[0]["pbl_height_m"], season0)
        observed: dict[Pollutant, float] = {}
        for name, value in (live_pollutants or {}).items():
            pollutant = _POLLUTANT_BY_NAME.get(name)
            if pollutant is None or value is None:
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number) and number >= 0:
                observed[pollutant] = number
        if live_pm25 is not None and math.isfinite(float(live_pm25)) and float(live_pm25) >= 0:
            observed[Pollutant.PM25] = float(live_pm25)

        for pollutant, value in observed.items():
            # O3 is diagnosed from the shortwave flux each hour, never accumulated
            # as a mass budget, so seeding it would be discarded anyway.
            if pollutant is Pollutant.O3 or pollutant not in col.mixed:
                continue
            col.mixed[pollutant] = value * col.h_m
        return col

    def _run_column(
        plume_profile: list[float],
        pm25_targets: list[float | None] | None = None,
    ) -> list[dict]:
        """
        Integrate the column over the forecast window.

        Called twice: once with the real smoke profile and once with it zeroed.
        Differencing the two is the only defensible way to state how much of the
        AQI is stubble burning, because the plume enters as a background
        elevation whose surface effect depends on the boundary layer, the
        residual-layer entrainment history and the ventilation rate. The previous
        code just subtracted the plume concentration from the modelled surface
        value, which ignores all three.
        """
        col = _seed_column()
        carry = 0.0
        # Wind memory: the effective cooling that drove the previous hour's
        # surface-wind response. It decays with the same surface timescale but
        # never drops below the current hour's cooling, so the wind response
        # trails dimming smoothly through the evening transition instead of
        # switching off the instant the sun sets.
        wind_carry = 0.0

        # Forward pass. Sequential in time (the box model and the surface thermal
        # memory both couple one hour to the next), iterative within each hour.
        out: list[dict] = []
        for i, time_str in enumerate(hourly_times):
            dt_h = datetime.fromisoformat(time_str)   # already IST
            state = _solve_coupled_hour(
                col=col,
                pbl_observed_m=inversion_series[i]["pbl_height_m"],
                solar_w_m2=_solar_at(i),
                wind_ms=_wind_at(i),
                emis_scale=emission_scale(dt_h.hour),
                season=seasonal_factors(dt_h.month),
                plume_pm25=plume_profile[i],
                cooling_carry_k=carry,
                pm25_target_ug_m3=(pm25_targets[i] if pm25_targets else None),
                wind_carry_k=wind_carry,
            )
            state["dt"] = dt_h
            state["inv"] = inversion_series[i]
            state["raw_aqi"] = _aqi_from_conc(state["conc"], aqi_mode)
            out.append(state)
            carry = decay * carry + (1.0 - decay) * state["cooling_instant_k"]
            wind_carry = max(state["cooling_instant_k"], decay * wind_carry)
        return out

    hybrid_pm25_targets: list[float | None] = [
        max(0.0, float(live_pm25)) if i == 0 and live_pm25 is not None else ml_pm25[i]
        for i in range(n_hours)
    ]
    has_fires = any(c > 0 for c in plume_conc_by_hour)

    # ── Smoke attribution, measured on the physics alone ─────────────────────
    # The smoke/no-smoke pair must differ ONLY in the plume. Previously `solved`
    # was pinned to the trained PM2.5 while `clean` ran free physics, so their
    # difference was "model minus physics" and got reported as the stubble-burning
    # share. The plume increment is therefore taken from two unpinned physics runs,
    # and that increment is then carried into the assimilated pair as an offset --
    # so the model still sets the absolute level, but inversion and smoke still
    # move it, and the attribution stays a genuine counterfactual.
    physics_smoke = _run_column(plume_conc_by_hour)
    physics_clean = _run_column([0.0] * n_hours) if has_fires else physics_smoke
    plume_increment = [
        max(
            0.0,
            float(physics_smoke[i]["conc"].get(Pollutant.PM25, 0.0))
            - float(physics_clean[i]["conc"].get(Pollutant.PM25, 0.0)),
        )
        for i in range(n_hours)
    ]

    assimilated = any(target is not None for target in hybrid_pm25_targets)
    if not assimilated:
        # Physics-only: the runs above are already the answer, no need to repeat them.
        solved, clean = physics_smoke, physics_clean
    else:
        solved = _run_column(plume_conc_by_hour, hybrid_pm25_targets)
        if has_fires:
            clean_targets: list[float | None] = [
                None if hybrid_pm25_targets[i] is None
                else max(0.0, float(hybrid_pm25_targets[i]) - plume_increment[i])
                for i in range(n_hours)
            ]
            clean = _run_column([0.0] * n_hours, clean_targets)
        else:
            clean = solved

    # ── Observational nudging of hour 0 ──────────────────────────────────────
    _NUDGE_LO, _NUDGE_HI = 0.4, 2.5
    conc_h0 = solved[0]["conc"]
    _TAU_H = 12.0

    # Species-specific scaling dictionary
    species_scales_by_hour: dict[Pollutant, list[float]] = {}
    pollutant_map = _POLLUTANT_BY_NAME

    if live_pollutants:
        for name, enum_val in pollutant_map.items():
            if name in live_pollutants and live_pollutants[name] is not None:
                obs_val = float(live_pollutants[name])
                raw_val = conc_h0.get(enum_val, 0.0)
                scale_0 = obs_val / raw_val if raw_val > 0 else 1.0
                scale_0 = min(max(scale_0, 0.05), 20.0)
                species_scales_by_hour[enum_val] = [
                    1.0 + (scale_0 - 1.0) * math.exp(-i / _TAU_H) for i in range(n_hours)
                ]

    if base_aqi is not None:
        scale_h0 = _conc_scale_for_target_aqi(
            conc_h0, base_aqi, _NUDGE_LO, _NUDGE_HI, aqi_mode
        )
    elif live_pm25 is not None:
        raw_pm25_h0 = conc_h0.get(Pollutant.PM25, 0.0)
        scale_h0 = live_pm25 / raw_pm25_h0 if raw_pm25_h0 > 0 else 1.0
    else:
        scale_h0 = 1.0
    scale_h0 = min(max(scale_h0, _NUDGE_LO), _NUDGE_HI)
    uniform_scale_by_hour = [
        1.0 + (scale_h0 - 1.0) * math.exp(-i / _TAU_H) for i in range(n_hours)
    ]

    forecast_hours = []
    concentration_history: dict[Pollutant, list[float]] = {
        pollutant: [] for pollutant in Pollutant
    }
    live_pm25_values = [
        float(row.get("value_ug_m3"))
        for row in (live_pm25_history or [])
        if row.get("value_ug_m3") is not None
    ]
    for i, state in enumerate(solved):
        wind_speed_i = _wind_at(i)
        wind_dir_i = float(wind_dir10_raw[i])
        wind_eff_i = float(state.get("wind_effective_ms", wind_speed_i))

        conc = {}
        for pol, val in state["conc"].items():
            if pol in species_scales_by_hour:
                conc[pol] = val * species_scales_by_hour[pol][i]
            elif pol is Pollutant.O3:
                conc[pol] = val
            else:
                conc[pol] = val * uniform_scale_by_hour[i]

        for pollutant, value in conc.items():
            concentration_history[pollutant].append(max(0.0, float(value)))

        aqi_concentrations = dict(conc)
        aqi_averaging: dict[Pollutant, str] = {}
        if aqi_mode in EPA_MODE_NAMES:
            # concentration_history already holds hours 0..i, so live observations
            # only pad the leading hours; newest-first is what epa_nowcast wants.
            # Appending the current hour LAST made it the oldest sample (weight
            # w**11) and pinned the reported NowCast to stale history.
            pm25_series = live_pm25_values + concentration_history[Pollutant.PM25]
            aqi_concentrations[Pollutant.PM25] = epa_nowcast(
                reversed(pm25_series[-12:])
            ) or conc.get(Pollutant.PM25, 0.0)
            aqi_averaging[Pollutant.PM25] = "EPA NowCast (up to 12 hourly values)"
            for pollutant in (Pollutant.PM10,):
                aqi_concentrations[pollutant] = epa_nowcast(
                    reversed(concentration_history[pollutant][-12:])
                ) or conc.get(pollutant, 0.0)
                aqi_averaging[pollutant] = "EPA NowCast (up to 12 hourly values)"
            for pollutant in (Pollutant.CO, Pollutant.O3):
                aqi_concentrations[pollutant] = rolling_mean(
                    reversed(concentration_history[pollutant][-8:]), 8
                ) or conc.get(pollutant, 0.0)
                aqi_averaging[pollutant] = "EPA 8-hour rolling mean"
            for pollutant in (Pollutant.NO2, Pollutant.SO2):
                aqi_averaging[pollutant] = "EPA 1-hour concentration"

        sub_indices = compute_sub_indices(
            conc, aqi_mode, aqi_concentrations=aqi_concentrations,
            aqi_averaging=aqi_averaging,
        )
        aqi = max((s["sub_index"] for s in sub_indices), default=0)
        dominant = max(sub_indices, key=lambda s: s["sub_index"])

        # Remove the physics-estimated smoke increment and recompute the AQI under
        # the IDENTICAL averaging contract. `aqi_no_plume` used to be computed from
        # raw hourly concentrations while `aqi` came from EPA NowCast/rolling
        # windows, so the two differed even with zero smoke and the difference was
        # reported as a stubble-burning share on fire-free days.
        no_plume_conc = dict(conc)
        no_plume_aqi_conc = dict(aqi_concentrations)
        for pollutant in (Pollutant.PM25, Pollutant.PM10):
            smoke_increment = max(
                0.0,
                float(state["conc"].get(pollutant, 0.0))
                - float(clean[i]["conc"].get(pollutant, 0.0)),
            )
            no_plume_conc[pollutant] = max(0.0, no_plume_conc.get(pollutant, 0.0) - smoke_increment)
            no_plume_aqi_conc[pollutant] = max(
                0.0, float(no_plume_aqi_conc.get(pollutant, 0.0)) - smoke_increment
            )
        aqi_no_plume = max(
            (
                s["sub_index"]
                for s in compute_sub_indices(
                    no_plume_conc, aqi_mode,
                    aqi_concentrations=no_plume_aqi_conc,
                    aqi_averaging=aqi_averaging,
                )
            ),
            default=0,
        )
        if aqi > 0 and aqi_no_plume < aqi:
            plume_fraction = max(0.0, min(1.0, (aqi - aqi_no_plume) / aqi))
        else:
            plume_fraction = 0.0

        pm25_source = (
            "live OpenAQ observation"
            if i == 0 and live_pm25 is not None
            else "trained PM2.5 model"
            if ml_pm25[i] is not None
            else "coupled physics model"
        )

        forecast_hours.append({
            "timestamp": state["dt"].isoformat(),
            "aqi": aqi,
            "aqi_standard": aqi_standard(aqi_mode),
            "aqi_method": aqi_method(aqi_mode),
            "pm25_source": pm25_source,
            "category": _aqi_category(aqi, aqi_mode),
            "dominant_pollutant": dominant["pollutant"],
            "sub_indices": sub_indices,
            # Mixing depth AFTER the aerosol feedback — the quantity the
            # chemistry actually modified.
            "pbl_height_m": round(state["pbl_m"], 1),
            "pbl_height_met_m": round(state["pbl_observed_m"], 1),
            "pbl_suppression_pct": round(
                100.0 * (1.0 - state["pbl_m"] / state["pbl_observed_m"]), 1
            ),
            "inversion_delta_t": state["inv"]["delta_t_celsius"],
            "aerosol_optical_depth": round(state["aod"], 3),
            "aerosol_sw_forcing_w_m2": round(state["d_sw_w_m2"], 1),
            "aerosol_dt_surface_c": round(state["dt_surface_c"], 2),
            "feedback_iterations": state["iterations"],
            "wind_speed_ms": round(wind_speed_i, 2),
            "wind_direction_deg": round(wind_dir_i, 1),
            # The wind leg of the return coupling: hour i's surface wind after
            # hour i-1's aerosol cooling weakened momentum mixing.
            "wind_effective_ms": round(wind_eff_i, 2),
            "wind_perturbation_frac": round(float(state.get("wind_perturbation_frac", 0.0)), 3),
            "temperature_2m_c": round(float(temperature2_raw[i]), 1),
            "relative_humidity_pct": round(float(humidity_raw[i]), 1),
            "precipitation_mm": round(float(precipitation_raw[i]), 2),
            "shortwave_radiation_w_m2": round(float(solar_raw[i]), 1),
            "dew_point_2m_c": round(float(dewpoint_raw[i]), 1),
            "apparent_temperature_c": round(float(apparent_raw[i]), 1),
            "precipitation_probability_pct": round(float(precip_probability_raw[i]), 1),
            "rain_mm": round(float(rain_raw[i]), 2),
            "showers_mm": round(float(showers_raw[i]), 2),
            "visibility_m": round(float(visibility_raw[i]), 1),
            "cloud_cover_pct": round(float(cloud_cover_raw[i]), 1),
            "surface_pressure_hpa": round(float(surface_pressure_raw[i]), 1),
            "pressure_msl_hpa": round(float(pressure_msl_raw[i]), 1),
            "weather_code": int(weather_code_raw[i]),
            "wind_gusts_ms": round(float(wind_gust_raw[i]), 2),
            "plume_contribution": round(plume_fraction, 3),
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "location": {"lat": lat, "lon": lon},
        "station_name": station_name,
        "aqi_standard": aqi_standard(aqi_mode),
        "aqi_method": aqi_method(aqi_mode),
        "concentration_unit": CANONICAL_CONCENTRATION_LABEL,
        "forecast_hours": forecast_hours,
        "current_weather": met_data.get("current") or {},
        "weather_units": met_data.get("hourly_units") or {},
        # Full provider arrays, passed through once instead of promoted into ~40
        # per-hour schema fields nothing renders yet. `weather_units` labels them,
        # so the soil, cloud-layer and 80/120/180 m profile data is available to
        # callers without committing the response schema to every field name.
        "hourly_weather": met_data.get("hourly") or {},
        "daily_weather": met_data.get("daily") or {},
        "daily_units": met_data.get("daily_units") or {},
        "weather_field_set": met_data.get("weather_field_set", "expanded"),
        # Which provider answered, and whether the boundary layer / temperatures
        # aloft were measured or parameterised from surface fields.
        "weather_source": met_data.get("weather_source", "open-meteo"),
        "profile_source": met_data.get("profile_source", "measured"),
        "provider_failures": met_data.get("provider_failures") or [],
        "model": "hybrid trained PM2.5 + coupled two-reservoir physics surrogate",
        "ml_model": ml_status,
        "spatial_resolution": "point forecast; no horizontal chemistry grid",
        "validation_status": (
            f"trained PM2.5 held-out RMSE {ml_status.get('held_out_rmse_pm25_ug_m3')} µg/m³"
            if ml_status.get("available")
            else "physics-only; trained PM2.5 artifact unavailable"
        ),
        "limitations": [
            "not WRF-Chem or a 3-D chemistry transport model",
            "hand-set scalar emissions rather than a gridded inventory",
            "diagnostic ozone chemistry",
            "held-out PM2.5 metrics are diagnostic; operational AQI accuracy is not established",
        ],
    }


# ── City-Wide Aggregate Service ───────────────────────────────────────────────

async def compute_city_aggregate(mode: str = "epa"):
    """
    Harmonized City Aggregate across all live monitoring stations in Delhi NCR.
    Applies the selected multi-pollutant maximum rule across the network.
    """
    from app.domain.aqi_scales import _cat, _sub_index, aqi_input_details, aqi_method, aqi_standard
    from app.schemas.forecast import CityAggregateResponse, PollutantDetail
    from app.services.realtime_service import fetch_all_stations

    stations = await fetch_all_stations(mode=mode)

    species_keys = [
        ("PM2.5", "pm25", "µg/m³"),
        ("PM10", "pm10", "µg/m³"),
        ("O3", "o3", "µg/m³"),
        ("NO2", "no2", "µg/m³"),
        ("SO2", "so2", "µg/m³"),
        ("CO", "co", CANONICAL_CONCENTRATION_LABEL),
    ]

    sub_indices: dict[str, PollutantDetail] = {}
    for disp_name, norm_key, unit in species_keys:
        vals = []
        for s in stations:
            p_map = s.get("pollutants", {})
            val = p_map.get(disp_name)
            if val is not None and not math.isnan(val):
                vals.append(float(val))

        if vals:
            # Harmonized Network Mean concentration across Delhi NCR
            conc = round(sum(vals) / len(vals), 1)
            sub_idx = _sub_index(norm_key, conc, mode=mode)
        else:
            conc = 0.0
            sub_idx = 0

        aqi_conc, aqi_unit = aqi_input_details(norm_key, conc, mode)
        sub_indices[disp_name] = PollutantDetail(
            index=sub_idx,
            conc=conc,
            unit=unit,
            aqi_conc=aqi_conc,
            aqi_unit=aqi_unit,
        )

    # The headline is ALWAYS max(sub-indices) over the network mean — the same
    # rule the station grid and the forecast hero use. Anchoring it to IQAir
    # instead mixed two different measurement bases: IQAir's city model value
    # (a different number from a different method) would sit beside sub-indices
    # computed from the CPCB network mean, and the dashboard's max-of-sub-indices
    # invariant would visibly disagree with the headline. IQAir is kept as a
    # labelled cross-check field, not as the headline.
    from app.services.realtime_service import fetch_iqair_realtime
    iq_live = None
    try:
        iq_live = await fetch_iqair_realtime(mode=mode)
    except (ValueError, RuntimeError, httpx.HTTPError):
        iq_live = None

    overall_aqi = 0
    dominant_pollutant = "PM2.5"
    for name, detail in sub_indices.items():
        if detail.index > overall_aqi:
            overall_aqi = detail.index
            dominant_pollutant = name

    iqair_aqi = int(iq_live["aqi"]) if iq_live and iq_live.get("aqi") is not None else None

    cat_label, hex_color = _cat(overall_aqi, mode=mode)

    return CityAggregateResponse(
        location_label=f"DELHI NCR / CITY AGGREGATE ({len(stations)} STATIONS)",
        station_count=len(stations),
        overall_aqi=overall_aqi,
        aqi_standard=aqi_standard(mode),
        aqi_method=aqi_method(mode),
        aqi_category=cat_label,
        dominant_pollutant=dominant_pollutant,
        color=hex_color,
        sub_indices=sub_indices,
        iqair_aqi=iqair_aqi,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
