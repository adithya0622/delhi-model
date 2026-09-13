"""Two-reservoir box model: mass budget, path dependence, ventilation.

This module is the answer to the audit's central finding (AUDIT.md §4.3): before
the rewrite, concentrations were a baseline AQI multiplied by an amplification
factor derived from the PBL, which is not a model of anything -- it has no memory,
so a lid that had been closed for six hours produced the same answer as one that
just shut, and pollution "released" by a lifting lid simply ceased to exist.

The replacement carries COLUMN MASS in µg/m² across two reservoirs (mixed layer
and residual layer). That makes the state path-dependent, which is the property
that lets an inversion actually trap. Everything worth testing here is a
conservation or monotonicity statement about that budget:

  * a collapsing lid must MOVE mass aloft, not destroy it
  * a persistent lid must ACCUMULATE, hour over hour
  * a growing lid must ENTRAIN the stranded mass back down (morning fumigation)
  * ventilation must scale with wind speed
  * the column must relax toward the regional BACKGROUND, never toward zero

Each is checked as an invariant rather than against a golden number, so the tests
survive parameter retuning but fail on a structural regression.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.species import Pollutant
from app.physics import box_model as B

_SEASON = {"pm25": 1.0, "pm10": 1.0, "gas": 1.0}
_NO_EMIS = {p: 0.0 for p in B.SPECIES}
_UNIT_EMIS = {p: 1.0 for p in B.SPECIES}
_HOUR = 3600.0


def _total_mass(col: B.BoxColumn, p: Pollutant) -> float:
    """Column mass in both reservoirs -- the quantity that must be conserved."""
    return col.mixed[p] + col.residual.get(p, 0.0)


# ── Mass conservation across a moving lid ────────────────────────────────────

def test_collapsing_lid_moves_mass_aloft_instead_of_destroying_it():
    """
    The defining test for the rewrite. When the lid drops, mass above the new lid
    must be STRANDED in the residual layer, not deleted. With emissions and
    removal switched off, the total column mass has to be exactly conserved.
    """
    col = B.BoxColumn.at_background(1200.0, _SEASON)
    before = {p: _total_mass(col, p) for p in B.SPECIES}
    mixed_before = dict(col.mixed)

    # Collapse 1200 m -> 250 m with no emissions and effectively no removal.
    B.step(col, 250.0, 1.0, _NO_EMIS, 0.0, _SEASON)

    for p in B.SPECIES:
        after = _total_mass(col, p)
        assert abs(after - before[p]) < before[p] * 1e-6, (
            "%s lost mass on lid collapse: %.4f -> %.4f" % (p, before[p], after)
        )
        # The mixed layer must have shed mass, and the residual gained it.
        assert col.mixed[p] < mixed_before[p], "%s did not shed mass" % p
        assert col.residual[p] > 0.0


def test_collapse_then_regrowth_returns_the_mass_to_the_surface():
    """
    Morning fumigation. Mass stranded overnight must come back down when the layer
    grows into it -- that is the observed signature of a trapped episode, and the
    old multiplicative model could not produce it because nothing was stored.
    """
    col = B.BoxColumn.at_background(1200.0, _SEASON)
    B.step(col, 200.0, 1.0, _NO_EMIS, 0.0, _SEASON)      # collapse
    stranded = dict(col.residual)
    assert all(v > 0 for v in stranded.values())

    B.step(col, 1200.0, 1.0, _NO_EMIS, 0.0, _SEASON)     # regrow
    for p in B.SPECIES:
        assert col.residual[p] < stranded[p], (
            "%s was not entrained back down on growth (%.3f -> %.3f)"
            % (p, stranded[p], col.residual[p])
        )


def test_a_uniform_column_is_invariant_to_lid_movement():
    """
    Stated first because it is the boundary condition the next two tests need, and
    because getting it wrong would be a real bug. A column sitting exactly at the
    regional background is UNIFORM -- the air above the lid is as dirty as the air
    below it -- so moving the lid through it cannot change the concentration. There
    is no excess to concentrate.

    An inversion traps LOCALLY EMITTED pollution; it does not concentrate background
    air. A model that reported a jump here would be double-counting the background,
    which is exactly the error the old amplification-factor approach made: it scaled
    a baseline that already included the background by a compression ratio.
    """
    col = B.BoxColumn.at_background(1500.0, _SEASON)
    before = col.concentrations()[Pollutant.PM25]
    after = B.step(col, 300.0, 1.0, _NO_EMIS, 0.0, _SEASON)[Pollutant.PM25]
    assert abs(after - before) < 1e-9, (
        "a uniform column changed concentration on lid collapse: %.4f -> %.4f"
        % (before, after)
    )
    assert abs(before - B.SPECIES[Pollutant.PM25].background) < 1e-9


def test_a_collapsing_lid_is_not_a_piston():
    """
    A subtle and important property, easy to assume backwards. Dropping the lid does
    NOT instantaneously raise the surface concentration, even with a large local
    excess present. The mixed layer is well mixed, so when the lid descends the air
    below it keeps its concentration and the air between the old and new lid is
    stranded aloft AT THAT SAME CONCENTRATION. Mass halves, depth halves, ratio
    unchanged.

    Physically: an inversion is not a piston compressing the air column. It is a
    reduction in the volume available to DILUTE what comes next. That distinction is
    exactly what the old amplification-factor model got wrong -- it multiplied
    concentration by 1200/h the instant the layer shallowed, manufacturing a spike
    with no mass behind it.

    The real trapping is tested in the next function.
    """
    col = B.BoxColumn.at_background(1500.0, _SEASON)
    for _ in range(4):
        B.step(col, 1500.0, _HOUR, _UNIT_EMIS, 2.0, _SEASON)
    before = col.concentrations()[Pollutant.PM25]
    assert before > B.SPECIES[Pollutant.PM25].background, "no local excess was built"

    mass_before = _total_mass(col, Pollutant.PM25)
    after = B.step(col, 300.0, 1.0, _NO_EMIS, 0.0, _SEASON)[Pollutant.PM25]

    # Not exactly equal: the step also applies one second of relaxation toward
    # background before moving the lid, which is a ~1e-6 relative change. The
    # threshold is far below the 5x a piston-like compression would produce.
    assert abs(after - before) < before * 1e-4, (
        "collapse changed the surface concentration %.4f -> %.4f; the mixed layer is "
        "being treated as compressible" % (before, after)
    )
    # Mass conserved to within the same one-second relaxation, and the mixed layer
    # shed it in proportion to the depth change. (The exact-conservation check lives
    # in test_collapsing_lid_moves_mass_aloft_instead_of_destroying_it, which starts
    # at background where relaxation is a genuine no-op.)
    assert abs(_total_mass(col, Pollutant.PM25) - mass_before) < mass_before * 1e-4
    assert col.residual[Pollutant.PM25] > 0.0


def test_trapping_emerges_from_emitting_into_a_shallow_layer():
    """
    THE test for the mechanism. The same emission flux for the same duration must
    raise the surface far more under a shallow lid than a deep one, because the
    diluting volume is smaller. This is the trapping the problem statement asks for,
    and it is emergent from the mass budget rather than applied as a multiplier.
    """
    rises = {}
    for depth in (1500.0, 800.0, 400.0, 200.0):
        col = B.BoxColumn.at_background(depth, _SEASON)
        start = col.concentrations()[Pollutant.PM25]
        for _ in range(3):
            B.step(col, depth, _HOUR, _UNIT_EMIS, 1.0, _SEASON)
        rises[depth] = col.concentrations()[Pollutant.PM25] - start

    depths = sorted(rises, reverse=True)
    for deep, shallow in zip(depths, depths[1:]):
        assert rises[shallow] > rises[deep], (
            "3 h of emissions raised PM2.5 by %.1f at %s m but only %.1f at %s m -- "
            "a shallower layer must trap more"
            % (rises[shallow], shallow, rises[deep], deep)
        )
    assert rises[200.0] > rises[1500.0] * 3.0, (
        "trapping is too weak: %.1f µg/m³ at 200 m vs %.1f at 1500 m"
        % (rises[200.0], rises[1500.0])
    )


def test_a_lifting_lid_dilutes_local_excess():
    """
    Growth is NOT symmetric with collapse, and that asymmetry is physical: the lid
    rises into cleaner air (or into the residual layer), so the excess is spread
    through a deeper column and the surface concentration falls.
    """
    col = B.BoxColumn.at_background(300.0, _SEASON)
    for _ in range(4):
        B.step(col, 300.0, _HOUR, _UNIT_EMIS, 2.0, _SEASON)
    before = col.concentrations()[Pollutant.PM25]
    after = B.step(col, 2000.0, 1.0, _NO_EMIS, 0.0, _SEASON)[Pollutant.PM25]
    assert after < before, (
        "lifting the lid did not dilute (%.1f -> %.1f)" % (before, after)
    )
    # But not below the background it is mixing into.
    assert after > B.SPECIES[Pollutant.PM25].background * 0.95


# ── Path dependence: the property the old model could not have ──────────────

def test_a_persistent_lid_accumulates_hour_over_hour():
    """
    Six hours under the same shallow lid with the same emissions must give a rising
    concentration. A memoryless model returns the same number every hour; this is
    the single clearest discriminator between the two.
    """
    col = B.BoxColumn.at_background(250.0, _SEASON)
    series = [
        B.step(col, 250.0, _HOUR, _UNIT_EMIS, 1.0, _SEASON)[Pollutant.PM25]
        for _ in range(6)
    ]
    for a, b in zip(series, series[1:]):
        assert b > a, "PM2.5 did not accumulate under a persistent lid: %s" % (
            ["%.1f" % v for v in series],
        )
    assert series[-1] > series[0] * 1.15, (
        "six hours of trapping only raised PM2.5 from %.1f to %.1f"
        % (series[0], series[-1])
    )


def test_history_matters_two_columns_same_lid_different_past():
    """
    Path dependence stated directly: two columns at the SAME final mixing depth,
    one that has been capped for hours and one that just closed, must not agree.
    """
    trapped = B.BoxColumn.at_background(250.0, _SEASON)
    for _ in range(8):
        B.step(trapped, 250.0, _HOUR, _UNIT_EMIS, 1.0, _SEASON)

    fresh = B.BoxColumn.at_background(1500.0, _SEASON)
    B.step(fresh, 250.0, _HOUR, _UNIT_EMIS, 1.0, _SEASON)

    a = trapped.concentrations()[Pollutant.PM25]
    b = fresh.concentrations()[Pollutant.PM25]
    assert a > b, (
        "a column trapped for 8 h (%.1f) is not dirtier than one just capped (%.1f)"
        % (a, b)
    )


# ── Ventilation ──────────────────────────────────────────────────────────────

def test_stronger_wind_ventilates_faster():
    """1/tau includes U/L, so a windier hour must end cleaner."""
    results = {}
    for wind in (0.5, 2.0, 5.0, 10.0):
        col = B.BoxColumn.at_background(600.0, _SEASON)
        # Start well above background so there is something to ventilate.
        for p in B.SPECIES:
            col.mixed[p] *= 4.0
        results[wind] = B.step(col, 600.0, _HOUR, _NO_EMIS, wind, _SEASON)[Pollutant.PM25]
    winds = sorted(results)
    for a, b in zip(winds, winds[1:]):
        assert results[b] < results[a], (
            "wind %s left more pollution (%.1f) than wind %s (%.1f)"
            % (b, results[b], a, results[a])
        )


def test_calm_air_is_floored_so_residence_time_stays_finite():
    """Perfectly calm air would give infinite residence time; the floor prevents it."""
    assert B._WIND_MIN_MS > 0.0
    assert B._tau_seconds(48.0, 0.0, surface=True) == B._tau_seconds(
        48.0, B._WIND_MIN_MS, surface=True
    )
    for wind in (0.0, -3.0):
        tau = B._tau_seconds(48.0, wind, surface=True)
        assert 0.0 < tau < 1e8, "tau=%s for wind=%s is not finite-and-positive" % (tau, wind)


def test_residual_layer_does_not_deposit_to_the_ground():
    """
    Aerosol aloft is not in contact with the surface, so its removal timescale must
    be LONGER than the surface one -- the deposition term is dropped.
    """
    for wind in (0.5, 2.0, 8.0):
        surf = B._tau_seconds(48.0, wind, surface=True)
        aloft = B._tau_seconds(48.0, wind, surface=False)
        assert aloft > surf, (
            "residual-layer tau (%.0f s) is not longer than surface (%.0f s) at %s m/s"
            % (aloft, surf, wind)
        )


def test_ventilation_dominates_for_an_inert_species():
    """
    CO has tau_loss = 240 h, so at any realistic wind its removal must be almost
    entirely ventilation. If deposition were dominating, the parameter is wrong.
    """
    with_dep = B._tau_seconds(240.0, 2.0, surface=True)
    vent_only = B._tau_seconds(0.0, 2.0, surface=True)
    assert abs(with_dep - vent_only) / vent_only < 0.15, (
        "CO removal is not ventilation-dominated (%.0f vs %.0f s)" % (with_dep, vent_only)
    )


# ── Relaxation target: background, never zero ───────────────────────────────

def test_column_relaxes_toward_background_not_toward_zero():
    """
    Air advected into Delhi is already polluted, so ventilation cannot clean below
    the Indo-Gangetic Plain background. Running 200 hours of strong wind with no
    local emissions must converge ON the background, not to zero.
    """
    col = B.BoxColumn.at_background(1000.0, _SEASON)
    for p in B.SPECIES:
        col.mixed[p] *= 5.0
    conc = None
    for _ in range(200):
        conc = B.step(col, 1000.0, _HOUR, _NO_EMIS, 8.0, _SEASON)
    for p, sp in B.SPECIES.items():
        assert abs(conc[p] - sp.background) < sp.background * 0.05, (
            "%s settled at %.3f, not its background %.3f" % (p, conc[p], sp.background)
        )
        assert conc[p] > 0.0


def test_a_clean_column_does_not_fall_below_background():
    """The relaxation must be symmetric: it fills up toward background too."""
    col = B.BoxColumn.at_background(1000.0, _SEASON)
    for p in B.SPECIES:
        col.mixed[p] *= 0.1
    conc = None
    for _ in range(100):
        conc = B.step(col, 1000.0, _HOUR, _NO_EMIS, 6.0, _SEASON)
    for p, sp in B.SPECIES.items():
        assert conc[p] > sp.background * 0.9, (
            "%s stalled at %.3f below its background %.3f" % (p, conc[p], sp.background)
        )


def test_seasonal_factors_scale_both_emissions_and_background():
    """
    A November factor must raise the whole column, not just the emission term --
    the regional background is seasonal too (upwind burning, lower ventilation).
    """
    winter = {"pm25": 1.6, "pm10": 1.5, "gas": 1.2}
    col_w = B.BoxColumn.at_background(400.0, winter)
    col_s = B.BoxColumn.at_background(400.0, _SEASON)
    c_w = B.step(col_w, 400.0, _HOUR, _UNIT_EMIS, 2.0, winter)
    c_s = B.step(col_s, 400.0, _HOUR, _UNIT_EMIS, 2.0, _SEASON)
    assert c_w[Pollutant.PM25] > c_s[Pollutant.PM25] * 1.3
    assert c_w[Pollutant.PM10] > c_s[Pollutant.PM10] * 1.2


# ── Plume coupling ──────────────────────────────────────────────────────────

def test_plume_raises_the_background_not_the_surface_flux():
    """
    Advected smoke enters as a background increment. Only PLUME_DIRECT_FRACTION of
    it reaches the mixed layer immediately, so the instantaneous surface rise must
    be a FRACTION of the plume concentration -- not the whole thing.
    """
    plume = 100.0
    col = B.BoxColumn.at_background(300.0, _SEASON)
    clean = B.BoxColumn.at_background(300.0, _SEASON)
    with_smoke = B.step(col, 300.0, _HOUR, _NO_EMIS, 2.0, _SEASON, plume_pm25_ug_m3=plume)
    without = B.step(clean, 300.0, _HOUR, _NO_EMIS, 2.0, _SEASON)

    rise = with_smoke[Pollutant.PM25] - without[Pollutant.PM25]
    assert rise > 0.0, "a 100 µg/m³ plume produced no surface rise"
    assert rise < plume, (
        "the full plume (%s) appeared at the surface in one hour (rise %.1f); it "
        "should be damped by PLUME_DIRECT_FRACTION and the relaxation timescale"
        % (plume, rise)
    )


def test_plume_reaches_the_surface_by_fumigation_the_next_morning():
    """
    The signature of a transport episode: smoke arrives above a shallow nocturnal
    layer, and the surface only feels the full plume once the layer grows into it.
    So a night of smoke followed by morning growth must beat the same smoke with no
    growth.
    """
    trapped = B.BoxColumn.at_background(200.0, _SEASON)
    for _ in range(8):
        B.step(trapped, 200.0, _HOUR, _NO_EMIS, 1.5, _SEASON, plume_pm25_ug_m3=150.0)
    before_growth = trapped.concentrations()[Pollutant.PM25]
    after_growth = B.step(
        trapped, 1000.0, _HOUR, _NO_EMIS, 1.5, _SEASON, plume_pm25_ug_m3=150.0
    )[Pollutant.PM25]

    # Growth dilutes, but the entrained smoke must keep it well above the clean case.
    clean = B.BoxColumn.at_background(200.0, _SEASON)
    for _ in range(8):
        B.step(clean, 200.0, _HOUR, _NO_EMIS, 1.5, _SEASON)
    clean_after = B.step(clean, 1000.0, _HOUR, _NO_EMIS, 1.5, _SEASON)[Pollutant.PM25]

    assert after_growth > clean_after * 1.2, (
        "fumigation of an overnight plume gave %.1f vs %.1f clean -- the residual "
        "layer is not holding the smoke" % (after_growth, clean_after)
    )
    assert before_growth > 0.0


def test_plume_is_fine_mode_dominated():
    """
    Biomass smoke is mostly fine mode, so its PM10:PM2.5 ratio must be near 1, not
    the ~1.9 urban ratio that carries road and construction dust.
    """
    assert 1.0 <= B.PLUME_PM10_RATIO <= 1.4
    assert B._plume_background(Pollutant.PM25, 100.0) == 100.0
    assert B._plume_background(Pollutant.PM10, 100.0) == 100.0 * B.PLUME_PM10_RATIO
    # Smoke is particulate; it must not fabricate gases.
    for p in (Pollutant.NO2, Pollutant.SO2, Pollutant.CO):
        assert B._plume_background(p, 100.0) == 0.0


def test_no_plume_is_exactly_a_no_op():
    """The counterfactual run must be bit-identical, or plume attribution is noise."""
    for p in B.SPECIES:
        assert B._plume_background(p, 0.0) == 0.0
        assert B._plume_background(p, -10.0) == 0.0

    a = B.BoxColumn.at_background(400.0, _SEASON)
    b = B.BoxColumn.at_background(400.0, _SEASON)
    ca = B.step(a, 350.0, _HOUR, _UNIT_EMIS, 2.0, _SEASON, plume_pm25_ug_m3=0.0)
    cb = B.step(b, 350.0, _HOUR, _UNIT_EMIS, 2.0, _SEASON)
    for p in B.SPECIES:
        assert ca[p] == cb[p], "%s differs with an explicit zero plume" % p


# ── State hygiene ───────────────────────────────────────────────────────────

def test_clone_is_independent_so_trial_steps_cannot_corrupt_the_budget():
    """
    The Picard loop trial-steps a clone several times per hour and commits exactly
    one real step. If `clone()` shared its mass dicts, every discarded trial would
    leak into the real budget and mass conservation would be silently wrong.
    """
    col = B.BoxColumn.at_background(800.0, _SEASON)
    snapshot = dict(col.mixed)
    twin = col.clone()

    for _ in range(5):
        B.step(twin, 200.0, _HOUR, _UNIT_EMIS, 1.0, _SEASON)

    assert col.mixed == snapshot, "trial-stepping a clone mutated the original"
    assert col.h_m == 800.0, "clone shares h_m with the original"
    assert twin.mixed is not col.mixed
    assert twin.residual is not col.residual


def test_mass_and_depth_stay_physical_through_a_violent_72_hour_cycle():
    """
    Fuzz the lid hard -- deep to shallow and back, 72 times -- and assert nothing
    goes negative, NaN, or unbounded. The residual top must also respect its ceiling,
    or pollution would be stored in the free troposphere and returned days later.
    """
    col = B.BoxColumn.at_background(1200.0, _SEASON)
    depths = [150.0, 3000.0, 180.0, 2500.0, 50.0, 1800.0, 220.0, 900.0]
    for i in range(72):
        conc = B.step(
            col, depths[i % len(depths)], _HOUR, _UNIT_EMIS,
            0.4 + (i % 5), _SEASON, plume_pm25_ug_m3=(80.0 if i % 3 else 0.0),
        )
        for p, v in conc.items():
            assert v == v, "%s went NaN at hour %d" % (p, i)
            assert v >= 0.0, "%s went negative (%s) at hour %d" % (p, v, i)
            assert v < 1e6, "%s ran away to %s at hour %d" % (p, v, i)
        for p in B.SPECIES:
            assert col.mixed[p] >= 0.0
            assert col.residual[p] >= 0.0
        assert col.h_m >= 50.0
        assert col.h_residual_top_m <= B._RESIDUAL_TOP_MAX_M + 1e-9
        assert col.h_residual_top_m >= col.h_m


def test_at_background_starts_exactly_at_background():
    """A forecast that begins mid-episode by accident would be untraceable."""
    col = B.BoxColumn.at_background(700.0, _SEASON)
    conc = col.concentrations()
    for p, sp in B.SPECIES.items():
        assert abs(conc[p] - sp.background) < 1e-9, (
            "%s initialised at %.4f, not background %.4f" % (p, conc[p], sp.background)
        )
    assert col.h_residual_top_m > col.h_m, "no residual layer was created"


def test_degenerate_depths_do_not_divide_by_zero():
    """A zero or negative mixing depth from a bad upstream value must not crash."""
    for bad in (0.0, -100.0):
        col = B.BoxColumn.at_background(bad, _SEASON)
        assert col.h_m >= 50.0
        conc = B.step(col, bad, _HOUR, _UNIT_EMIS, 2.0, _SEASON)
        for p, v in conc.items():
            assert v == v and v >= 0.0, "%s = %s at degenerate depth" % (p, v)


def test_co_is_carried_in_mg_so_its_background_is_sub_unity():
    """
    CO uses the CPCB table's mg/m³. If its background were ever set in µg/m³ the
    sub-index would peg at 500 permanently -- a whole-dashboard failure from one
    unit slip.
    """
    assert B.SPECIES[Pollutant.CO].background < 5.0, (
        "CO background %.2f looks like µg/m³; it must be mg/m³"
        % B.SPECIES[Pollutant.CO].background
    )
    col = B.BoxColumn.at_background(600.0, _SEASON)
    assert col.concentrations()[Pollutant.CO] < 5.0
