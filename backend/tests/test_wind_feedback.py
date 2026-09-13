"""The wind leg of the two-way coupling.

The problem statement requires the coupled system to alter "temperatures, wind
patterns, and planetary boundary layer (PBL) heights". The temperature and PBL
legs have differential tests in test_coupling.py; this file pins the third.

The mechanism: aerosol dimming cools the surface, the boundary layer
stabilises, downward momentum mixing weakens, and the 10 m wind drops. Weaker
wind lengthens the box model's ventilation timescale U/L, which raises PM2.5 --
closing the loop. The wind responds to the PREVIOUS hour's cooling (momentum
adjustment lags dimming), so hour i's wind is a known input to hour i's solve,
not a second unknown inside the Picard loop.

The same discipline as test_coupling.py: every claim is DIFFERENTIAL, run with
and without the aerosol pathway, because a coupling that is merely present in
the code is not enough -- it has to bite, in the right direction, and vanish
when the aerosol is gone.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.species import Pollutant
from app.physics import box_model
from app.physics import inversion_engine as I
from app.physics.box_model import BoxColumn
from app.services import aqi_service as A

_SEASON_NOV = A.seasonal_factors(11)
_SEASON_AUG = A.seasonal_factors(8)


def _solve(col, pbl, solar, wind=1.5, hour=8, season=None, plume=0.0, carry=0.0, wind_carry=0.0):
    return A._solve_coupled_hour(
        col,
        pbl_observed_m=pbl,
        solar_w_m2=solar,
        wind_ms=wind,
        emis_scale=A.emission_scale(hour),
        season=season or _SEASON_NOV,
        plume_pm25=plume,
        cooling_carry_k=carry,
        wind_carry_k=wind_carry,
    )


def _dirty_column(pbl=250.0, hours=10, season=None, plume=0.0):
    """A column that has been accumulating under a shallow lid, i.e. a real episode."""
    season = season or _SEASON_NOV
    col = BoxColumn.at_background(pbl, season)
    for h in range(hours):
        box_model.step(col, pbl, 3600.0, A.emission_scale(h % 24), 1.0, season, plume)
    return col


# ── The kernel itself ───────────────────────────────────────────────────────

def test_wind_perturbation_is_the_identity_at_zero_cooling():
    """No aerosol cooling, no wind response. Same contract as pbl_from_stability."""
    assert I.wind_perturbation(0.0) == 0.0
    assert I.wind_perturbation(-1.0) == 0.0  # heating is not a wind perturbation here


def test_wind_perturbation_is_negative_and_monotone_in_cooling():
    prev = 0.0
    for cooling in (0.5, 1.0, 2.0, 4.0):
        frac = I.wind_perturbation(cooling)
        assert frac < 0.0, "cooling=%s produced a non-negative wind change" % cooling
        assert frac < prev, "wind response weakened as cooling grew (%s -> %s)" % (prev, frac)
        prev = frac


def test_wind_perturbation_saturates_at_the_cap():
    """Momentum is not destroyed, only mixed down more slowly -- so the response caps."""
    deep = I.wind_perturbation(50.0)
    deeper = I.wind_perturbation(500.0)
    assert abs(deeper - deep) < 1e-12, "response kept growing past the cap"
    assert abs(deep) == I._WIND_REDUCTION_MAX


def test_wind_perturbation_is_within_the_observed_band():
    """1.5 K of aerosol cooling (a hazy Delhi day) should cost ~10% of the wind,
    inside the 10-30% observed decline band; the hard cap encodes the top of it."""
    frac = I.wind_perturbation(1.5)
    assert -0.20 < frac <= -0.05, "1.5 K moved the wind by %.1f%%" % (frac * 100)


# ── The solver threads the wind through the mass budget ─────────────────────

def test_clean_air_reports_no_wind_feedback():
    """With no cooling anywhere, the effective wind is exactly the met wind."""
    col = BoxColumn.at_background(1000.0, _SEASON_NOV)
    st = _solve(col, pbl=1000.0, solar=0.0, wind=3.0, hour=12, carry=0.0, wind_carry=0.0)
    assert st["wind_perturbation_frac"] == 0.0
    assert st["wind_effective_ms"] == 3.0


def test_prev_hour_cooling_slows_this_hour_wind():
    """The lagged coupling: hour i-1's dimming must show up in hour i's wind."""
    col = BoxColumn.at_background(300.0, _SEASON_NOV)
    calm = _solve(_dirty_column(), pbl=300.0, solar=450.0, wind=3.0, hour=12, wind_carry=0.0)
    slowed = _solve(_dirty_column(), pbl=300.0, solar=450.0, wind=3.0, hour=12, wind_carry=1.5)
    assert slowed["wind_effective_ms"] < calm["wind_effective_ms"], (
        "carried cooling did not slow the wind (%.3f vs %.3f)"
        % (slowed["wind_effective_ms"], calm["wind_effective_ms"])
    )
    assert slowed["wind_perturbation_frac"] < 0.0


def test_weaker_wind_raises_pm25_through_ventilation():
    """
    The closing of the loop, measured directly: identical columns, identical
    everything except the effective wind. The calmer run must end dirtier
    because U/L removes less. This is the assertion that makes the wind leg a
    feedback rather than a display field.
    """
    windy = _dirty_column()
    calm = _dirty_column()
    st_windy = _solve(windy, pbl=300.0, solar=450.0, wind=6.0, hour=20)
    st_calm = _solve(calm, pbl=300.0, solar=450.0, wind=3.0, hour=20)
    assert st_calm["conc"][Pollutant.PM25] > st_windy["conc"][Pollutant.PM25], (
        "calm air did not accumulate more PM2.5 than windy air -- ventilation is not doing work"
    )


def test_wind_feedback_raises_pm25_versus_the_no_feedback_counterfactual():
    """
    The full differential: two identical dirty columns under afternoon sun.
    One gets the wind feedback (wind_carry = last hour's cooling); the other
    has the leg switched off (wind_carry = 0). The feedback run must end
    dirtier, because dimming slowed its ventilation.
    """
    # Build the carry the production integrator would pass: last hour's cooling.
    col_fb = _dirty_column()
    probe = _solve(col_fb.clone(), pbl=300.0, solar=450.0, hour=11)
    carry_fb = probe["cooling_instant_k"]
    assert carry_fb > 0.0, "fixture produced no cooling to carry"

    with_feedback = _solve(_dirty_column(), pbl=300.0, solar=450.0, hour=12, wind_carry=carry_fb)
    without_feedback = _solve(_dirty_column(), pbl=300.0, solar=450.0, hour=12, wind_carry=0.0)

    assert with_feedback["wind_effective_ms"] < without_feedback["wind_effective_ms"]
    assert with_feedback["conc"][Pollutant.PM25] > without_feedback["conc"][Pollutant.PM25], (
        "the wind feedback did not raise PM2.5 (%.2f vs %.2f)"
        % (with_feedback["conc"][Pollutant.PM25], without_feedback["conc"][Pollutant.PM25])
    )


def test_wind_never_goes_negative_or_below_the_box_floor():
    """A thick plume under gale-forced met wind must not invert the flow."""
    for met_wind in (0.5, 2.0, 10.0):
        st = _solve(_dirty_column(), pbl=300.0, solar=900.0, wind=met_wind, hour=12, wind_carry=50.0)
        assert st["wind_effective_ms"] >= 0.0
        assert st["wind_effective_ms"] == st["wind_effective_ms"], "effective wind went NaN"
        assert st["wind_effective_ms"] <= met_wind, (
            "feedback wind %.2f exceeded the met wind %.2f -- the sign is wrong"
            % (st["wind_effective_ms"], met_wind)
        )


# ── Multi-hour behaviour of the lagged memory ───────────────────────────────

def test_wind_memory_survives_the_night():
    """
    Daytime dimming must still be slowing the evening wind: the wind memory
    decays but never drops below the current hour's cooling, so the response
    trails smoothly through sunset instead of switching off with the sun.
    """
    season = _SEASON_NOV
    col = BoxColumn.at_background(250.0, season)
    wind_carry = 0.0
    carry = 0.0
    states = []
    for i, hour in enumerate((14, 15, 16, 17, 18, 19, 20, 21)):
        solar = 700.0 if hour <= 17 else 0.0
        st = A._solve_coupled_hour(
            col, pbl_observed_m=250.0, solar_w_m2=solar, wind_ms=2.5,
            emis_scale=A.emission_scale(hour), season=season, plume_pm25=0.0,
            cooling_carry_k=carry, wind_carry_k=wind_carry,
        )
        states.append(st)
        carry = I.surface_memory_decay() * carry + (1.0 - I.surface_memory_decay()) * st["cooling_instant_k"]
        wind_carry = max(st["cooling_instant_k"], I.surface_memory_decay() * wind_carry)

    # At 14:00 the feedback is only just starting (wind_carry was 0 at entry).
    # By 21:00, two hours after sunset, the wind must still be perturbed.
    assert states[-1]["wind_perturbation_frac"] < 0.0, (
        "the wind response died at night with the sun -- the memory is wrong"
    )
    # Monotone deepening through the haze build-up, then persistence after sunset.
    assert states[-1]["wind_perturbation_frac"] <= states[0]["wind_perturbation_frac"]


def test_wind_feedback_is_negligible_in_clean_monsoon_air():
    """A feedback that fires in clean air is a bias, not a feedback."""
    col = BoxColumn.at_background(2000.0, _SEASON_AUG)
    st = _solve(col, pbl=2000.0, solar=800.0, hour=12, wind=5.0, season=_SEASON_AUG, wind_carry=0.0)
    assert st["wind_perturbation_frac"] == 0.0, (
        "clean monsoon air produced a wind perturbation of %s"
        % st["wind_perturbation_frac"]
    )


# ── Contract guards ─────────────────────────────────────────────────────────

def test_solver_commits_the_feedback_wind_to_the_mass_budget():
    """
    The committed step must run at the FEEDBACK wind, not the raw met wind.
    Reproduce the solver's state manually using its reported effective wind;
    if the commit used the raw wind instead, the masses would diverge.
    """
    coupled = _dirty_column()
    control = _dirty_column()
    st = _solve(coupled, pbl=300.0, solar=450.0, wind=3.0, hour=12, wind_carry=1.5)
    assert st["wind_effective_ms"] < 3.0, "fixture needs an active wind feedback"

    box_model.step(
        control, st["pbl_m"], 3600.0, A.emission_scale(12),
        st["wind_effective_ms"], _SEASON_NOV, 0.0,
    )
    for p in box_model.SPECIES:
        assert abs(coupled.mixed[p] - control.mixed[p]) < abs(control.mixed[p]) * 1e-9, (
            "%s diverged -- the committed step did not use the reported wind" % p
        )


def test_picard_convergence_unchanged_by_the_wind_leg():
    """The wind enters before the loop, so convergence behaviour must be intact."""
    for pbl in (160.0, 300.0, 1200.0):
        for solar in (0.0, 500.0, 900.0):
            st = _solve(_dirty_column(), pbl=pbl, solar=solar, hour=12, carry=0.5, wind_carry=1.0)
            assert st["converged"], "no convergence at pbl=%s solar=%s" % (pbl, solar)
            assert st["iterations"] < A._MAX_PICARD_ITER


def test_zero_aerosol_means_exactly_the_met_wind():
    """
    The strict limit from test_coupling.py, extended to the wind leg: with no PM
    anywhere the effective wind must be EXACTLY the met wind. Any drift means
    something outside the aerosol pathway is perturbing it.
    """
    col = BoxColumn.at_background(1000.0, _SEASON_NOV)
    for p in col.mixed:
        col.mixed[p] = 0.0
        col.residual[p] = 0.0
    season_zero = {k: 0.0 for k in _SEASON_NOV}
    st = A._solve_coupled_hour(
        col, pbl_observed_m=1000.0, solar_w_m2=700.0, wind_ms=2.0,
        emis_scale={p: 0.0 for p in box_model.SPECIES},
        season=season_zero, plume_pm25=0.0, cooling_carry_k=0.0, wind_carry_k=0.0,
    )
    assert st["wind_effective_ms"] == 2.0, (
        "effective wind %s != met wind 2.0 with zero aerosol" % st["wind_effective_ms"]
    )
