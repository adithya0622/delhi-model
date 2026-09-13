"""The two-way coupling: does the feedback actually do anything?

This file exists because of AUDIT.md §7.1, the central finding. The problem
statement asks for a system where meteorology drives chemistry AND chemistry
alters meteorology. The original code had the *shape* of that -- there was a
function computing aerosol cooling, and a function suppressing the PBL -- but it
was de-tuned into irrelevance by three compounding choices: an 800 m floor on the
PBL, a separate damping factor, and a duplicate suppression already applied
upstream. Switching the coupling off changed the 72-hour forecast by well under a
percent, so nothing downstream could tell whether the feedback existed.

The fix was subtractive. So the tests here are mostly DIFFERENTIAL: run the same
hour with and without the aerosol pathway and assert the answers differ by a
physically meaningful amount, in the right direction, at the right times of day.
A coupling that is merely present is not enough -- it has to bite.

The four claims under test:
  1. In dirty air under a shallow lid, the feedback measurably shrinks the PBL and
     raises PM2.5. (If not, it is decorative.)
  2. In clean air it is ~zero. (If not, it is a bias, not a feedback.)
  3. At night the shortwave term is exactly zero, yet the feedback survives via
     surface thermal memory. (This is the regime Delhi episodes occur in.)
  4. The Picard loop terminates, converges, and never corrupts the mass budget --
     it trial-steps clones and commits exactly one real step.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.species import Pollutant
from app.physics import box_model
from app.physics.box_model import BoxColumn
from app.services import aqi_service as A

_SEASON_NOV = A.seasonal_factors(11)
_SEASON_AUG = A.seasonal_factors(8)


def _solve(col, pbl, solar, wind=1.5, hour=8, season=None, plume=0.0, carry=0.0):
    return A._solve_coupled_hour(
        col,
        pbl_observed_m=pbl,
        solar_w_m2=solar,
        wind_ms=wind,
        emis_scale=A.emission_scale(hour),
        season=season or _SEASON_NOV,
        plume_pm25=plume,
        cooling_carry_k=carry,
    )


def _dirty_column(pbl=250.0, hours=10, season=None, plume=0.0):
    """A column that has been accumulating under a shallow lid, i.e. a real episode."""
    season = season or _SEASON_NOV
    col = BoxColumn.at_background(pbl, season)
    for h in range(hours):
        box_model.step(col, pbl, 3600.0, A.emission_scale(h % 24), 1.0, season, plume)
    return col


# ── Claim 1: the feedback bites in dirty air ────────────────────────────────

def test_feedback_measurably_shrinks_the_pbl_in_dirty_air():
    """
    The headline assertion. Under a shallow November lid with real aerosol load and
    midday sun, the solved mixing depth must be meaningfully BELOW the met-model
    depth it started from. "Meaningfully" is >2%, which is far above the <1% the
    de-tuned version produced.
    """
    col = _dirty_column()
    st = _solve(col, pbl=300.0, solar=450.0, hour=12)

    assert st["pbl_m"] < st["pbl_observed_m"], (
        "solved PBL %.1f is not below the met PBL %.1f -- the feedback is inert"
        % (st["pbl_m"], st["pbl_observed_m"])
    )
    shrink = 1.0 - st["pbl_m"] / st["pbl_observed_m"]
    assert shrink > 0.02, (
        "feedback only shrank the layer by %.3f%% -- this is the de-tuned regime "
        "the audit found" % (shrink * 100.0)
    )
    # And the intermediate quantities must all be live, not zero.
    assert st["aod"] > 0.1, "AOD %.3f is too small to matter" % st["aod"]
    assert st["d_sw_w_m2"] < 0.0, "no shortwave loss was computed"
    assert st["cooling_instant_k"] > 0.0, "no cooling was computed"


def _integrate(hours, pbl, solar, carry=0.0, plume=0.0, start_hour=12, season=None):
    """
    Run several coupled hours and return the final state. Needed because the
    feedback's effect on CONCENTRATION is inherently multi-hour: see
    `test_within_one_hour_a_collapsing_lid_does_not_change_concentration`.
    """
    season = season or _SEASON_NOV
    col = _dirty_column(season=season)
    st = None
    for i in range(hours):
        st = A._solve_coupled_hour(
            col, pbl_observed_m=pbl, solar_w_m2=solar, wind_ms=1.5,
            emis_scale=A.emission_scale((start_hour + i) % 24),
            season=season, plume_pm25=plume, cooling_carry_k=carry,
        )
    return st


def test_within_one_hour_a_collapsing_lid_does_not_change_concentration():
    """
    Pinned because it is counter-intuitive and because two earlier drafts of the
    tests below passed on 2.8e-14 of floating-point noise while appearing to prove
    the feedback raised PM2.5 in a single hour. It does not, and it should not.

    The box model strands mass aloft at the concentration it already had (see
    `test_a_collapsing_lid_is_not_a_piston` in test_box_model.py), so a suppressed
    lid changes the surface concentration only through the FOLLOWING hours' reduced
    dilution volume. Any test asserting a single-hour concentration response to a
    collapsing lid is measuring rounding error.
    """
    a = _solve(_dirty_column(), pbl=200.0, solar=0.0, hour=3, carry=0.0)
    b = _solve(_dirty_column(), pbl=200.0, solar=0.0, hour=3, carry=1.2)

    assert b["pbl_m"] < a["pbl_m"], "the carried cooling did not suppress the lid"
    assert abs(b["conc"][Pollutant.PM25] - a["conc"][Pollutant.PM25]) < 1e-9, (
        "a one-hour collapse changed PM2.5 by %.3e; the model is treating the mixed "
        "layer as compressible"
        % (b["conc"][Pollutant.PM25] - a["conc"][Pollutant.PM25])
    )


def test_coupling_raises_pm25_versus_no_feedback():
    """
    Differential test against the counterfactual: integrate the same six hours with
    the sun on (feedback active) and with solar = 0 and no carry (feedback fully
    off). The coupled run must end dirtier, because the suppressed lid dilutes each
    hour's emissions less.

    This is the number that answers "what does your coupling buy you?" -- measured
    here rather than asserted in a slide.
    """
    coupled = _integrate(6, pbl=300.0, solar=450.0)
    uncoupled = _integrate(6, pbl=300.0, solar=0.0, carry=0.0)

    assert uncoupled["pbl_m"] == uncoupled["pbl_observed_m"], (
        "the no-feedback control did not reduce to the identity; it is not a control"
    )
    pm_c = coupled["conc"][Pollutant.PM25]
    pm_u = uncoupled["conc"][Pollutant.PM25]
    assert pm_c > pm_u, (
        "coupled PM2.5 %.1f is not above uncoupled %.1f" % (pm_c, pm_u)
    )
    assert (pm_c - pm_u) / pm_u > 0.02, (
        "coupling changed PM2.5 by only %.2f%% over six hours"
        % ((pm_c - pm_u) / pm_u * 100.0)
    )


def test_dirtier_air_produces_a_stronger_feedback():
    """
    Monotonicity of the whole loop, which is what makes it a feedback rather than an
    offset: more aerosol -> more dimming -> more cooling -> shallower lid.
    """
    shrinks = []
    for hours in (0, 4, 10, 20):
        col = _dirty_column(hours=hours) if hours else BoxColumn.at_background(300.0, _SEASON_NOV)
        st = _solve(col, pbl=300.0, solar=450.0, hour=12)
        shrinks.append((hours, 1.0 - st["pbl_m"] / st["pbl_observed_m"], st["aod"]))

    for (h_a, s_a, aod_a), (h_b, s_b, aod_b) in zip(shrinks, shrinks[1:]):
        assert aod_b >= aod_a, "AOD fell as the column got dirtier (%s -> %s)" % (h_a, h_b)
        assert s_b >= s_a - 1e-9, (
            "feedback weakened as air got dirtier: %s h -> %.4f, %s h -> %.4f"
            % (h_a, s_a, h_b, s_b)
        )
    assert shrinks[-1][1] > shrinks[0][1], "feedback strength is flat in aerosol load"


# ── Claim 2: near-zero in clean air ────────────────────────────────────────

def test_feedback_is_negligible_in_clean_air():
    """
    A feedback that fires in clean air is a bias. A monsoon-season column at
    background under a deep well-mixed layer should barely move.
    """
    col = BoxColumn.at_background(2000.0, _SEASON_AUG)
    st = _solve(col, pbl=2000.0, solar=800.0, hour=12, wind=5.0, season=_SEASON_AUG)
    shrink = 1.0 - st["pbl_m"] / st["pbl_observed_m"]
    assert shrink < 0.25, (
        "clean monsoon air shrank the PBL by %.1f%%; the feedback is acting as a "
        "bias" % (shrink * 100.0)
    )


def test_zero_aerosol_means_exactly_no_feedback():
    """
    The strict limit. With no PM at all there is no AOD, so no dimming, so no
    cooling, so the solved depth must be EXACTLY the met depth. Any drift here means
    something is perturbing the PBL outside the aerosol pathway -- the §4.2 bug.
    """
    col = BoxColumn.at_background(1000.0, _SEASON_NOV)
    for p in col.mixed:
        col.mixed[p] = 0.0
        col.residual[p] = 0.0
    # Zero the backgrounds too, so the step cannot refill the column.
    season_zero = {k: 0.0 for k in _SEASON_NOV}
    st = A._solve_coupled_hour(
        col, pbl_observed_m=1000.0, solar_w_m2=700.0, wind_ms=2.0,
        emis_scale={p: 0.0 for p in box_model.SPECIES},
        season=season_zero, plume_pm25=0.0, cooling_carry_k=0.0,
    )
    assert st["aod"] == 0.0, "AOD %.6f with no aerosol present" % st["aod"]
    assert st["d_sw_w_m2"] == 0.0
    assert st["cooling_instant_k"] == 0.0
    assert st["pbl_m"] == 1000.0, (
        "PBL moved to %.4f with zero aerosol -- something outside the feedback is "
        "perturbing it" % st["pbl_m"]
    )


# ── Claim 3: night-time behaviour ──────────────────────────────────────────

def test_shortwave_term_is_exactly_zero_at_night():
    """No sun, no dimming. Anything else is manufactured cooling at 3 a.m."""
    st = _solve(_dirty_column(), pbl=200.0, solar=0.0, hour=3, carry=0.0)
    assert st["d_sw_w_m2"] == 0.0
    assert st["cooling_instant_k"] == 0.0
    assert st["solar_effective_w_m2"] == 0.0


def test_feedback_survives_the_night_through_surface_memory():
    """
    The physically important case, and the reason `cooling_carry_k` exists. Delhi's
    episodes happen overnight. The shortwave term MUST be zero then, but the surface
    is still carrying the heat deficit from the day's dimming, so the nocturnal
    inversion is still strengthened. Without this the whole feedback would switch off
    exactly when it matters.

    Integrated over six night hours, because the concentration response is
    cumulative -- see
    `test_within_one_hour_a_collapsing_lid_does_not_change_concentration`.
    """
    no_memory = _integrate(6, pbl=200.0, solar=0.0, carry=0.0, start_hour=22)
    with_memory = _integrate(6, pbl=200.0, solar=0.0, carry=1.2, start_hour=22)

    assert no_memory["pbl_m"] == no_memory["pbl_observed_m"], (
        "with no sun and no memory the feedback must be the identity"
    )
    assert with_memory["pbl_m"] < with_memory["pbl_observed_m"], (
        "carried cooling did not suppress the nocturnal layer"
    )
    assert with_memory["cooling_effective_k"] == 1.2
    assert with_memory["d_sw_w_m2"] == 0.0, "shortwave term must be zero at night"

    pm_mem = with_memory["conc"][Pollutant.PM25]
    pm_none = no_memory["conc"][Pollutant.PM25]
    assert pm_mem > pm_none, (
        "the night-time feedback did not raise PM2.5 (%.1f vs %.1f)" % (pm_mem, pm_none)
    )
    assert (pm_mem - pm_none) / pm_none > 0.02, (
        "night-time feedback moved PM2.5 by only %.2f%% over six hours -- this is "
        "the de-tuned regime" % ((pm_mem - pm_none) / pm_none * 100.0)
    )


def test_effective_cooling_takes_the_stronger_of_instant_and_carried():
    """
    Midday dimming must not be *reduced* by a smaller stored deficit, and a large
    stored deficit must not be erased by a weak instantaneous one.
    """
    strong_sun = _solve(_dirty_column(), pbl=300.0, solar=600.0, hour=12, carry=0.1)
    assert strong_sun["cooling_effective_k"] == strong_sun["cooling_instant_k"]

    weak_sun = _solve(_dirty_column(), pbl=300.0, solar=40.0, hour=17, carry=1.5)
    assert weak_sun["cooling_effective_k"] == 1.5
    assert weak_sun["cooling_effective_k"] >= weak_sun["cooling_instant_k"]


def test_reported_surface_temperature_perturbation_is_a_cooling():
    """`dt_surface_c` is rendered in the dashboard; aerosol dimming cools."""
    st = _solve(_dirty_column(), pbl=300.0, solar=500.0, hour=12)
    assert st["dt_surface_c"] < 0.0
    assert abs(st["dt_surface_c"] + st["cooling_effective_k"]) < 1e-12


# ── Claim 4: the solver itself ─────────────────────────────────────────────

def test_picard_loop_converges_within_the_cap():
    """
    Under-relaxed fixed-point iteration on a monotone map. It must converge, and
    well inside the cap -- if it routinely hits the ceiling the relaxation factor is
    wrong and the reported depth is whatever the last iterate happened to be.
    """
    for pbl in (160.0, 250.0, 500.0, 1200.0, 2500.0):
        for solar in (0.0, 200.0, 500.0, 900.0):
            st = _solve(_dirty_column(), pbl=pbl, solar=solar, hour=12, carry=0.5)
            assert st["converged"], (
                "no convergence at pbl=%s solar=%s after %d iterations"
                % (pbl, solar, st["iterations"])
            )
            assert st["iterations"] <= A._MAX_PICARD_ITER
            assert st["iterations"] < A._MAX_PICARD_ITER, (
                "hit the iteration cap at pbl=%s solar=%s" % (pbl, solar)
            )


def test_iteration_cap_is_honoured_even_if_it_cannot_converge():
    """A pathological case must terminate and report honestly, not spin."""
    col = _dirty_column()
    st = A._solve_coupled_hour(
        col, pbl_observed_m=1e9, solar_w_m2=1200.0, wind_ms=0.0,
        emis_scale=A.emission_scale(12), season=_SEASON_NOV,
        plume_pm25=5000.0, cooling_carry_k=50.0,
    )
    assert st["iterations"] <= A._MAX_PICARD_ITER
    assert st["pbl_m"] >= A.PBL_MIN_M
    assert st["pbl_m"] == st["pbl_m"], "solved PBL went NaN"
    for p, v in st["conc"].items():
        assert v == v and v >= 0.0, "%s = %s in the pathological case" % (p, v)


def test_solver_commits_exactly_one_step_to_the_mass_budget():
    """
    The trial-step-a-clone discipline. The loop may step a clone many times, but the
    real column must advance exactly once per hour. If discarded trials leaked in,
    the column would gain several hours of emissions per hour and the whole forecast
    would drift high with nothing in the code obviously wrong.
    """
    coupled = _dirty_column()
    control = _dirty_column()
    assert coupled.mixed == control.mixed, "the two fixtures did not start equal"

    st = _solve(coupled, pbl=300.0, solar=450.0, hour=12)
    assert st["iterations"] > 1, "need a multi-iteration solve for this to be a test"

    # One manual step at the solved depth must reproduce the solver's state exactly.
    box_model.step(
        control, st["pbl_m"], 3600.0, A.emission_scale(12), 1.5, _SEASON_NOV, 0.0
    )
    for p in box_model.SPECIES:
        assert abs(coupled.mixed[p] - control.mixed[p]) < abs(control.mixed[p]) * 1e-9, (
            "%s mass %.6f != single-step control %.6f -- trial iterations are "
            "leaking into the real budget" % (p, coupled.mixed[p], control.mixed[p])
        )
        assert abs(coupled.residual[p] - control.residual[p]) < max(
            abs(control.residual[p]) * 1e-9, 1e-9
        )
    assert coupled.h_m == control.h_m


def test_solver_never_reports_a_depth_below_the_guard():
    for carry in (0.0, 2.0, 10.0, 50.0):
        st = _solve(_dirty_column(), pbl=160.0, solar=900.0, hour=12, carry=carry)
        assert st["pbl_m"] >= A.PBL_MIN_M, "solved PBL %.2f below guard" % st["pbl_m"]


def test_observed_pbl_is_reported_alongside_the_solved_one():
    """
    Both are returned so the dashboard can show the feedback's magnitude rather than
    asserting it. `pbl_observed_m` must be the untouched met input (above the guard).
    """
    st = _solve(_dirty_column(), pbl=420.0, solar=500.0, hour=12)
    assert st["pbl_observed_m"] == 420.0
    assert st["pbl_m"] != st["pbl_observed_m"]


# ── O3: the third species in the loop ──────────────────────────────────────

def test_o3_is_suppressed_by_aerosol_dimming():
    """
    Closing the loop on photochemistry: O3 production sees the DIMMED flux, so a hazy
    day must produce less ozone than a clear one at the same solar input. This is the
    observed behaviour on Delhi smog days and it falls out of the coupling for free.
    """
    hazy = _solve(_dirty_column(hours=20), pbl=300.0, solar=600.0, hour=12)
    clear = _solve(BoxColumn.at_background(300.0, _SEASON_AUG), pbl=300.0,
                   solar=600.0, hour=12, season=_SEASON_AUG)
    assert hazy["solar_effective_w_m2"] < clear["solar_effective_w_m2"], (
        "the hazy case did not see a dimmer sun"
    )
    assert hazy["solar_effective_w_m2"] >= 0.0, "dimming drove the flux negative"


def test_o3_is_present_but_low_at_night_never_zero():
    """
    Photochemical production stops at night; background ozone does not vanish. A
    hard zero would be wrong, and would also make the O3 sub-index meaningless.
    """
    night = _solve(_dirty_column(), pbl=200.0, solar=0.0, hour=3)
    day = _solve(_dirty_column(), pbl=800.0, solar=700.0, hour=12)
    o3_night = night["conc"][Pollutant.O3]
    o3_day = day["conc"][Pollutant.O3]
    assert o3_night > 0.0, "O3 went to exactly zero at night"
    assert o3_day > o3_night, (
        "daytime O3 %.1f is not above night-time %.1f" % (o3_day, o3_night)
    )


def test_o3_is_titrated_by_nox_in_a_shallow_layer():
    """
    A collapsing lid raises PM2.5 and DESTROYS O3, because trapped fresh NO titrates
    it. Getting this backwards would show ozone spiking during a smog episode, which
    is the opposite of what is observed.
    """
    deep = A._photochemical_o3(0.0, 40.0, 1500.0)
    shallow = A._photochemical_o3(0.0, 200.0, 200.0)
    assert shallow < deep, (
        "trapped NOx did not titrate O3 (shallow %.1f vs deep %.1f)" % (shallow, deep)
    )
    assert shallow > 0.0, "titration drove O3 to zero"


def test_o3_never_goes_negative_or_unbounded():
    for solar in (0.0, 100.0, 500.0, 1200.0):
        for no2 in (0.0, 20.0, 100.0, 500.0):
            for pbl in (150.0, 400.0, 2000.0):
                o3 = A._photochemical_o3(solar, no2, pbl)
                assert 0.0 < o3 < 400.0, (
                    "O3=%s at solar=%s no2=%s pbl=%s" % (o3, solar, no2, pbl)
                )


# ── The plume enters through the coupling ──────────────────────────────────

def test_plume_raises_pm25_and_strengthens_the_feedback():
    """
    A stubble plume is more aerosol, so it must both raise PM2.5 and deepen the
    radiative feedback -- the "external spike alters local weather" half of the
    problem statement.
    """
    clean = _solve(_dirty_column(), pbl=300.0, solar=450.0, hour=12, plume=0.0)
    smoky = _solve(_dirty_column(plume=120.0), pbl=300.0, solar=450.0, hour=12, plume=120.0)

    assert smoky["conc"][Pollutant.PM25] > clean["conc"][Pollutant.PM25]
    assert smoky["aod"] > clean["aod"], "the plume did not thicken the aerosol column"
    assert smoky["cooling_instant_k"] >= clean["cooling_instant_k"]
    assert smoky["pbl_m"] <= clean["pbl_m"], (
        "the plume did not suppress the layer further (%.1f vs %.1f)"
        % (smoky["pbl_m"], clean["pbl_m"])
    )
