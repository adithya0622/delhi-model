"""
Single-Column Box Model (prognostic mixed layer + residual layer)
=================================================================
Why this exists
---------------
The earlier forecast scaled emissions by (reference PBL / actual PBL). That is a
STEADY-STATE assumption, and it cannot represent trapping. Trapping is not a
dilution effect -- it is accumulation: emissions keep entering a shallow layer
faster than ventilation removes them, so the concentration climbs hour after
hour. A 1/h scaling gives the same answer at hour 1 and hour 9 of an inversion,
which is exactly the phenomenon this project is supposed to forecast.

It also broke the diurnal shape. Delhi's observed morning peak and afternoon
minimum come from mixed-layer growth entraining cleaner air and stranding
pollution aloft, then re-entraining it the next morning. That needs a memory of
what is above the boundary layer.

What this implements
--------------------
The classical two-reservoir slab model:

  * Mixed layer, depth h, uniformly mixed, column mass m [µg/m²], C = m/h
  * Residual layer, occupying [h, h_res], uniform, column mass r [µg/m²]
  * A regional background concentration the column relaxes toward

Per time step:
  1. Emit into the mixed layer:      m += E · dt
  2. Relax toward background:        first-order loss with timescale tau
  3. Adjust depth:
       h grows  -> entrain from the residual layer first, then background
                   (this is the classic morning fumigation peak)
       h shrinks -> mass above the new top is STRANDED into the residual layer
                   and does not return until the layer grows again

Loss timescale combines deposition and ventilation out of the urban domain:

      1/tau = 1/tau_dep  +  U / L

with L the city length scale. So a calm night has a long residence time and a
windy afternoon a short one -- the wind field does real work here rather than
just being displayed on the dashboard.

Honesty note
------------
Emission fluxes and background concentrations below are hand-set so the column
reproduces the ORDER OF MAGNITUDE and the diurnal SHAPE of CPCB Delhi monthly
climatology. They are not an emissions inventory and they have not been fitted
to, or validated against, withheld observations. Do not quote an accuracy figure
for this model that is not produced by code in `tests/`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from app.domain.species import Pollutant

# Length scale for ventilation out of the urban domain (m). Delhi NCT is ~40 km
# across, so this is the distance a parcel must travel to leave the source area.
_CITY_SCALE_M = 40_000.0

# Ceiling on the residual layer top (m). Above this, pollution is in the free
# troposphere and is not coming back down within a 72 h forecast.
_RESIDUAL_TOP_MAX_M = 3_000.0

# Wind speed floor (m/s). Perfectly calm air would give infinite residence time;
# even on the stillest Delhi night there is drainage flow.
_WIND_MIN_MS = 0.4


@dataclass(frozen=True)
class Species:
    """Per-pollutant emission and removal parameters."""
    # Area emission flux at the winter reference, µg/m²/s.
    emission_flux: float
    # Regional background concentration at the winter reference, µg/m³
    # (mg/m³ for CO). The column relaxes toward this, not toward zero: air
    # advected into Delhi is already polluted, so ventilation cannot clean below
    # the Indo-Gangetic Plain background.
    background: float
    # Deposition / chemical loss timescale in hours, excluding ventilation.
    tau_loss_h: float
    # Which seasonal curve scales this species.
    season: str = "pm25"


# Deposition timescales: fine PM2.5 deposits slowly (~2 days); coarse PM10
# settles far faster (~12 h); NO2 is photochemically short-lived (~8 h);
# SO2 oxidises over ~1.5 days; CO is effectively inert on these timescales, so
# it is ventilation-limited.
SPECIES: dict[Pollutant, Species] = {
    Pollutant.PM25: Species(emission_flux=1.60, background=55.0, tau_loss_h=48.0, season="pm25"),
    Pollutant.PM10: Species(emission_flux=3.10, background=95.0, tau_loss_h=12.0, season="pm10"),
    Pollutant.NO2:  Species(emission_flux=1.10, background=8.0,  tau_loss_h=8.0,  season="gas"),
    Pollutant.SO2:  Species(emission_flux=0.30, background=6.0,  tau_loss_h=36.0, season="gas"),
    # CO carried in mg/m³ to match the CPCB breakpoint table, so its flux is
    # mg/m²/s. Effectively inert on a 72 h timescale, so it is
    # ventilation-limited: whatever is emitted stays until the wind removes it.
    Pollutant.CO:   Species(emission_flux=0.030, background=0.35, tau_loss_h=240.0, season="gas"),
}

# Fraction of an arriving stubble plume that is felt in the MIXED layer.
# Long-range smoke is transported above the shallow nocturnal boundary layer, so
# most of an arriving plume initially sits in the residual layer and only reaches
# the ground when the mixed layer grows into it the following morning -- the
# observed fumigation signature of a transport episode. The remaining fraction
# here is applied to the residual layer in full.
PLUME_DIRECT_FRACTION = 0.40

# Ratio of plume PM10 to plume PM2.5. Biomass smoke is dominated by fine mode,
# so this is much closer to 1 than the ~1.9 urban ratio, which carries road and
# construction dust.
PLUME_PM10_RATIO = 1.15


@dataclass
class BoxColumn:
    """
    Mutable state of one atmospheric column.

    `mixed` and `residual` hold COLUMN MASS in µg/m² (mg/m² for CO), not
    concentration, because mass is what is conserved when the layer depth moves.
    """
    h_m: float
    h_residual_top_m: float
    mixed: dict[Pollutant, float] = field(default_factory=dict)
    residual: dict[Pollutant, float] = field(default_factory=dict)

    @classmethod
    def at_background(
        cls, h_m: float, season_factors: dict[str, float]
    ) -> "BoxColumn":
        """Initialise a column sitting at the regional background."""
        h_m = max(h_m, 50.0)
        top = max(h_m * 1.5, h_m + 200.0)
        mixed, residual = {}, {}
        for p, sp in SPECIES.items():
            # EMISSIONS follow the seasonal factor; the regional background has
            # its own, much flatter one (`bg`) — monsoon washout acts on local
            # sources, not on air advecting in from the IGP.
            bg = sp.background * season_factors.get("bg", season_factors.get(sp.season, 1.0))
            mixed[p] = bg * h_m
            residual[p] = bg * (top - h_m)
        return cls(h_m=h_m, h_residual_top_m=top, mixed=mixed, residual=residual)

    def concentrations(self) -> dict[Pollutant, float]:
        return {p: self.mixed[p] / self.h_m for p in self.mixed}

    def clone(self) -> "BoxColumn":
        """
        Shallow copy with independent mass dicts. Needed because the aerosol
        feedback has to trial-step the column several times while searching for
        the mixing depth, and only the accepted step may mutate real state.
        """
        return BoxColumn(
            h_m=self.h_m,
            h_residual_top_m=self.h_residual_top_m,
            mixed=dict(self.mixed),
            residual=dict(self.residual),
        )


def _tau_seconds(tau_loss_h: float, wind_ms: float, surface: bool) -> float:
    """
    Combined removal timescale in seconds.

        1/tau = 1/tau_deposition + U/L

    `surface=False` (the residual layer) drops the deposition term: aerosol
    aloft is not in contact with the ground.
    """
    u = max(float(wind_ms), _WIND_MIN_MS)
    inv = u / _CITY_SCALE_M
    if surface and tau_loss_h > 0:
        inv += 1.0 / (tau_loss_h * 3600.0)
    return 1.0 / inv if inv > 0 else 1e9


def _plume_background(
    pollutant: Pollutant, plume_pm25_ug_m3: float
) -> float:
    """Increment to the regional background from advected smoke (µg/m³)."""
    if plume_pm25_ug_m3 <= 0:
        return 0.0
    if pollutant is Pollutant.PM25:
        return plume_pm25_ug_m3
    if pollutant is Pollutant.PM10:
        return plume_pm25_ug_m3 * PLUME_PM10_RATIO
    return 0.0


def step(
    col: BoxColumn,
    h_new_m: float,
    dt_s: float,
    emission_scale: dict[Pollutant, float],
    wind_ms: float,
    season_factors: dict[str, float],
    plume_pm25_ug_m3: float = 0.0,
) -> dict[Pollutant, float]:
    """
    Advance the column one time step and return surface concentrations.

    `emission_scale` multiplies each species' reference flux (diurnal traffic
    profile x seasonal factor).

    `plume_pm25_ug_m3` is the stubble-smoke concentration present in the
    transport layer arriving over Delhi. It raises the REGIONAL BACKGROUND the
    column relaxes toward rather than acting as a surface emission, because that
    is what advected material physically is: the air flowing into the city is
    already smoky, so ventilation can no longer clean below that level. Treating
    it as a surface flux instead would apply the mixing-depth dependence twice --
    once in the transport calculation and again here.

    Only the mixed layer's background gets PLUME_DIRECT_FRACTION of it; the
    residual layer gets all of it, so the surface only feels the full plume once
    the boundary layer grows into the smoke next morning.

    Mutates `col` in place, because the whole point is that this hour depends on
    the last one.
    """
    h_old = max(col.h_m, 50.0)
    h_new = max(float(h_new_m), 50.0)
    h_res = max(col.h_residual_top_m, h_old)

    for p, sp in SPECIES.items():
        f_season = season_factors.get(sp.season, 1.0)
        # Background relaxation uses the flat `bg` factor; see `at_background`.
        bg_clean = sp.background * season_factors.get("bg", f_season)
        smoke = _plume_background(p, plume_pm25_ug_m3)
        bg_mixed = bg_clean + smoke * PLUME_DIRECT_FRACTION
        bg_above = bg_clean + smoke

        # ── 1. Emission into the mixed layer ────────────────────────────────
        emis = sp.emission_flux * f_season * emission_scale.get(p, 1.0)
        m = col.mixed[p] + emis * dt_s
        r = col.residual.get(p, 0.0)

        # ── 2. First-order relaxation toward the regional background ────────
        tau_s = _tau_seconds(sp.tau_loss_h, wind_ms, surface=True)
        decay = math.exp(-dt_s / tau_s)
        m_bg = bg_mixed * h_old
        m = m_bg + (m - m_bg) * decay

        res_depth = max(h_res - h_old, 0.0)
        if res_depth > 0:
            tau_r = _tau_seconds(sp.tau_loss_h, wind_ms, surface=False)
            decay_r = math.exp(-dt_s / tau_r)
            r_bg = bg_above * res_depth
            r = r_bg + (r - r_bg) * decay_r
        else:
            r = 0.0

        # ── 3. Move the lid ────────────────────────────────────────────────
        if h_new > h_old:
            # Growth: entrain the residual layer first (fumigation), then air
            # from above it, which is also smoke-laden during an episode.
            d = h_new - h_old
            overlap = min(d, res_depth)
            if res_depth > 0 and overlap > 0:
                frac = overlap / res_depth
                m += r * frac
                r -= r * frac
            m += bg_above * max(0.0, d - overlap)
        elif h_new < h_old:
            # Collapse: strand everything above the new lid. It stays aloft
            # until the layer grows again -- this is what makes the model
            # path-dependent, and what lets an inversion actually trap.
            c_now = m / h_old
            stranded = c_now * (h_old - h_new)
            m -= stranded
            r += stranded

        col.mixed[p] = max(m, 0.0)
        col.residual[p] = max(r, 0.0)

    col.h_m = h_new
    col.h_residual_top_m = min(max(h_res, h_old, h_new), _RESIDUAL_TOP_MAX_M)
    return col.concentrations()


# ── SIH deterministic two-way feedback forecast ───────────────────────────────
# This path is intentionally separate from the coupled research model above so
# the dashboard has an explicit, auditable hour-by-hour implementation of the
# SIH brief: aerosol cooling feeds back into temperature, which changes PBL and
# inversion, which changes the next hour's concentration.

@dataclass(frozen=True)
class FeedbackMetHour:
    temperature_c: float
    wind_speed_kmh: float
    wind_direction_deg: float
    shortwave_w_m2: float


def _feedback_inversion(pbl_m: float) -> str:
    if pbl_m < 300:
        return "Strong"
    if pbl_m <= 800:
        return "Moderate"
    return "Weak"


def _is_daylight(hour_of_day: int) -> bool:
    return 7 <= hour_of_day <= 17


def simulate_feedback_72h(
    base_pm25: float,
    start_hour: int,
    met: list[FeedbackMetHour],
) -> tuple[list[dict[str, float | int | str]], dict[str, str | float]]:
    """Run the specified two-way PM2.5/PBL feedback loop for 72 hourly steps."""
    if not met:
        raise ValueError("Meteorology series cannot be empty")
    pm25 = max(1.0, float(base_pm25))
    output: list[dict[str, float | int | str]] = []
    for t in range(72):
        weather = met[min(t, len(met) - 1)]
        local_hour = (start_hour + t) % 24
        daylight = _is_daylight(local_hour)
        temp_penalty = -((pm25 - 150.0) * 0.015) if pm25 > 150 and daylight else 0.0
        adjusted_temp = weather.temperature_c + temp_penalty
        if daylight:
            pbl = max(400.0, 1500.0 * (adjusted_temp / 35.0))
        else:
            pbl = max(200.0, 300.0 + (weather.wind_speed_kmh * 10.0))
        inversion = _feedback_inversion(pbl)
        nw_plume = 270.0 <= weather.wind_direction_deg <= 360.0 and weather.wind_speed_kmh > 5.0
        stubble_injection = 40.0 if nw_plume else 0.0
        # Lower PBL concentrates the inherited mass; ventilation removes more
        # under strong winds. A small hourly source term preserves accumulation.
        pbl_factor = max(0.55, min(2.25, 700.0 / pbl))
        dispersion = min(0.45, weather.wind_speed_kmh / 120.0)
        daylight_dilution = 0.92 if daylight else 1.03
        next_pm25 = max(2.0, pm25 * pbl_factor * (1.0 - dispersion) * daylight_dilution + stubble_injection + 2.5)
        # Avoid explosive numerical growth while retaining strong nocturnal spikes.
        next_pm25 = min(next_pm25, 900.0)
        aqi = _pm25_to_indian_aqi(next_pm25)
        output.append({
            "hour": f"+{t + 1}h",
            "pm2_5": round(next_pm25, 1),
            "aqi": aqi,
            "pbl_height": round(pbl, 1),
            "inversion": inversion,
            "temp_penalty": round(temp_penalty, 2),
            "adjusted_temp": round(adjusted_temp, 1),
            "wind_speed": round(weather.wind_speed_kmh, 1),
            "wind_direction": round(weather.wind_direction_deg, 1),
            "shortwave": round(weather.shortwave_w_m2, 1),
            "stubble_injection": round(stubble_injection, 1),
        })
        pm25 = next_pm25
    current = output[0]
    insights: dict[str, str | float] = {
        "current_pbl": current["pbl_height"],
        "inversion_risk": str(current["inversion"]),
        "aerosol_feedback_status": (
            f"Active: PM2.5 is suppressing surface heating by {abs(float(current['temp_penalty'])):.1f}°C"
            if float(current["temp_penalty"]) < 0
            else "Inactive: PM2.5 is below the daylight aerosol-cooling threshold"
        ),
        "stubble_plume_risk": (
            "High (NW Winds detected)"
            if any(float(item["stubble_injection"]) > 0 for item in output)
            else "Low (no sustained NW plume signal)"
        ),
    }
    return output, insights


def _pm25_to_indian_aqi(pm25: float) -> int:
    """Linear interpolation over CPCB PM2.5 concentration breakpoints."""
    breakpoints = [(0, 30, 0, 50), (31, 60, 51, 100), (61, 90, 101, 200), (91, 120, 201, 300), (121, 250, 301, 400), (251, 500, 401, 500)]
    c = max(0.0, min(500.0, pm25))
    for c_low, c_high, i_low, i_high in breakpoints:
        if c <= c_high:
            return round((i_high - i_low) / (c_high - c_low) * (c - c_low) + i_low)
    return 500
