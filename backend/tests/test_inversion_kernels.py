"""Inversion diagnostics and aerosol-feedback kernels.

Two audit findings live here.

AUDIT.md §4.2 -- the de-tuning trap. `pbl_from_stability` used to be applied on
top of a met-model PBL that had already been floored at 800 m and separately
damped, so the aerosol feedback was cancelled by construction: turn the coupling
on or off and the answer barely moved. The fixes were subtractive -- the floor,
the damping, and the duplicate suppression were removed, not retuned -- which
means the property to test is an IDENTITY: at zero forcing every kernel must be a
no-op, so the only thing that can ever change a PBL is real physics.

AUDIT.md §4.3 -- the amplification factor was the mechanism. Concentrations were
produced by multiplying a baseline AQI by `amplification_factor(pbl)`. It is now a
reported diagnostic only; the box model produces concentrations. It still has to
be bounded, because it is rendered in the dashboard.

Sign conventions, which are load-bearing and easy to get backwards:
  * ΔT = T(925 hPa) - T(1000 hPa). POSITIVE means an inversion.
  * `shortwave_reduction` returns a NEGATIVE flux perturbation (W/m², a loss).
  * `surface_cooling_from_sw` returns a NEGATIVE temperature perturbation (K).
  * `pbl_from_stability` wants a POSITIVE cooling MAGNITUDE, so the caller must
    negate. See `test_pbl_from_stability_silently_noops_on_a_negative_cooling`
    for why that asymmetry is dangerous and is pinned here.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.physics import inversion_engine as I


# ── The identity property: zero forcing must be a no-op ──────────────────────

def test_pbl_from_stability_is_the_identity_at_zero_forcing():
    """
    The single most important assertion in this file. `pbl_from_stability` is the
    only place a PBL is ever perturbed. If it returns anything other than its input
    when the aerosol cooling is zero, then some hidden damping or floor is being
    applied to the met-model PBL again, and the feedback becomes untestable --
    which is exactly the state the audit found.
    """
    for baseline in (150.0, 300.0, 800.0, 1200.0, 2500.0, 4000.0):
        out = I.pbl_from_stability(baseline, 0.0)
        assert out == baseline, (
            "zero cooling changed PBL %s -> %s; something is damping the met PBL "
            "behind the feedback's back" % (baseline, out)
        )


def test_no_800m_floor_survives():
    """
    A shallow winter-night PBL is the whole phenomenon being modelled. The old code
    floored it at 800 m, which erased the inversion it was supposed to detect. Only
    PBL_MIN_M (a numerical guard, far below any real Delhi night) may clip.
    """
    assert I.PBL_MIN_M <= 200.0, (
        "PBL_MIN_M=%s is high enough to erase a real inversion" % I.PBL_MIN_M
    )
    for shallow in (160.0, 200.0, 350.0, 500.0, 799.0):
        assert I.pbl_from_stability(shallow, 0.0) == shallow
        # And with real cooling it must go DOWN from there, not snap up to a floor.
        assert I.pbl_from_stability(shallow, 1.5) < shallow


def test_pbl_never_goes_below_the_numerical_guard():
    """Division by the mixing depth happens downstream; it must stay positive."""
    for cooling in (0.0, 1.0, 5.0, 20.0, 100.0):
        out = I.pbl_from_stability(160.0, cooling)
        assert out >= I.PBL_MIN_M, "PBL fell to %s, below the guard" % out
        assert out > 0.0


def test_cooling_monotonically_suppresses_the_pbl():
    """More aerosol cooling must mean a shallower layer, with no sign flips."""
    prev = I.pbl_from_stability(1200.0, 0.0)
    for cooling in (0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0):
        out = I.pbl_from_stability(1200.0, cooling)
        assert out < prev, (
            "cooling %s gave PBL %s, not below the previous %s" % (cooling, out, prev)
        )
        prev = out


def test_pbl_suppression_magnitude_is_in_the_published_range():
    """
    1.5 K of aerosol cooling should suppress the layer by roughly 10-30%, the range
    reported for high-aerosol IGP winter days. Pinned so a lambda edit that made the
    feedback cosmetic (or explosive) fails here rather than being argued about.
    """
    ratio = I.pbl_from_stability(1200.0, 1.5) / 1200.0
    assert 0.70 <= ratio <= 0.90, (
        "1.5 K of cooling changed the PBL by %.1f%%, outside the 10-30%% range"
        % ((1.0 - ratio) * 100.0)
    )


def test_pbl_from_stability_silently_noops_on_a_negative_cooling():
    """
    A deliberate trap, pinned rather than fixed. `surface_cooling_from_sw` returns a
    NEGATIVE kelvin perturbation, but `pbl_from_stability` wants a POSITIVE
    magnitude and treats anything <= 0 as "no forcing". So a caller that forgets to
    negate gets the identity map -- the entire aerosol feedback disappears with no
    error, no warning, and a plausible-looking dashboard.

    That is precisely how the original de-tuning went unnoticed. This test states
    the contract, and `test_coupling.py` verifies the real call site in
    `_solve_coupled_hour` negates correctly.
    """
    d_sw = I.shortwave_reduction(1.0, 700.0)
    raw_cooling = I.surface_cooling_from_sw(d_sw)
    assert raw_cooling < 0.0, "cooling should be reported as a negative perturbation"

    # Wrong: passing it straight through kills the feedback.
    assert I.pbl_from_stability(1200.0, raw_cooling) == 1200.0
    # Right: negate to a magnitude first.
    assert I.pbl_from_stability(1200.0, -raw_cooling) < 1200.0


# ── Shortwave gating: the feedback must switch off at night ──────────────────

def test_shortwave_reduction_is_exactly_zero_at_night():
    """
    Aerosols cannot block sunlight that is not arriving. If this returns anything
    non-zero at solar=0, the model manufactures radiative cooling at 3 a.m. -- which
    the pre-fix version, using a constant W/m² per AOD, did.
    """
    for aod in (0.0, 0.5, 1.0, 3.0, 10.0):
        assert I.shortwave_reduction(aod, 0.0) == 0.0
        # Negative irradiance is not physical, but must not produce heating either.
        assert I.shortwave_reduction(aod, -50.0) == 0.0


def test_no_aerosol_means_no_shortwave_loss():
    for solar in (0.0, 200.0, 500.0, 900.0):
        assert I.shortwave_reduction(0.0, solar) == 0.0


def test_shortwave_reduction_is_negative_and_cannot_exceed_the_incoming_flux():
    """
    It is a loss, so the sign is negative, and its magnitude can never exceed the
    incoming irradiance -- otherwise a thick plume would drive net-negative surface
    radiation. The _ATTEN_MAX cap is what enforces that.
    """
    for solar in (100.0, 500.0, 900.0):
        for aod in (0.1, 0.5, 1.0, 2.0, 5.0, 20.0):
            d_sw = I.shortwave_reduction(aod, solar)
            assert d_sw <= 0.0, "aod=%s solar=%s gave POSITIVE %s" % (aod, solar, d_sw)
            assert abs(d_sw) <= solar, (
                "aod=%s solar=%s lost %s W/m², more than arrived" % (aod, solar, d_sw)
            )
            assert abs(d_sw) <= solar * I._ATTEN_MAX + 1e-9


def test_shortwave_loss_grows_with_aod_then_saturates():
    solar = 700.0
    prev = 0.0
    for aod in (0.2, 0.5, 1.0, 1.5, 2.0):
        loss = abs(I.shortwave_reduction(aod, solar))
        assert loss > prev, "aod=%s did not increase the loss" % aod
        prev = loss
    # Above the cap it must flatten, not keep growing.
    capped = abs(I.shortwave_reduction(50.0, solar))
    assert abs(capped - solar * I._ATTEN_MAX) < 1e-9


# ── AOD magnitude has to be physically sane ─────────────────────────────────

def test_aod_is_in_a_realistic_range_for_delhi():
    """
    Sanity-check against published AERONET/MODIS values rather than trusting the
    arithmetic: Delhi runs ~0.3-0.8 on a clean day and ~0.9-1.5 in a November smog
    episode. If the kernel returned 0.02 the feedback would be invisible; if it
    returned 15 the surface would go dark and the model would produce nonsense.
    """
    clean = I.aerosol_optical_depth(30.0, 1000.0)
    assert 0.2 < clean < 0.6, "clean-air AOD %.3f is implausible" % clean

    episode = I.aerosol_optical_depth(250.0, 300.0)
    assert 0.6 < episode < 2.0, "smog-episode AOD %.3f is implausible" % episode
    assert episode > clean


def test_aod_is_zero_in_clean_air_and_rises_with_pm():
    assert I.aerosol_optical_depth(0.0, 1000.0) == 0.0
    assert I.aerosol_optical_depth(-5.0, 1000.0) == 0.0
    assert I.aerosol_optical_depth(100.0, 0.0) == 0.0
    prev = 0.0
    for pm in (10.0, 50.0, 100.0, 200.0, 400.0):
        aod = I.aerosol_optical_depth(pm, 800.0)
        assert aod > prev
        prev = aod


def test_aod_accounts_for_column_depth_not_just_concentration():
    """
    The same concentration spread through a deep layer is more total aerosol than in
    a shallow one, so column AOD must depend on the mixing depth. If it did not, the
    model would have confused concentration with column loading.
    """
    shallow = I.aerosol_optical_depth(150.0, 300.0)
    deep = I.aerosol_optical_depth(150.0, 1500.0)
    assert deep > shallow, (
        "AOD ignores mixing depth (shallow=%.3f deep=%.3f)" % (shallow, deep)
    )


def test_aod_is_capped():
    """An extreme column must saturate rather than run away into the attenuation."""
    assert I.aerosol_optical_depth(5000.0, 3000.0) == I._AOD_MAX


# ── Cooling and thermal memory ──────────────────────────────────────────────

def test_cooling_is_zero_without_shortwave_loss_and_negative_with_it():
    assert I.surface_cooling_from_sw(0.0) == 0.0
    for d_sw in (-10.0, -50.0, -150.0, -300.0):
        cooling = I.surface_cooling_from_sw(d_sw)
        assert cooling < 0.0, "a shortwave loss must cool, got %s" % cooling
        # Plausible magnitude: hundreds of W/m² is a few kelvin, not fifty.
        assert abs(cooling) < 15.0, "%s W/m² gave %.2f K" % (d_sw, cooling)


def test_full_radiative_chain_magnitude_on_a_severe_winter_day():
    """
    End-to-end through the three kernels with realistic November inputs: 250 µg/m³
    PM2.5 in a 300 m layer under 450 W/m² of winter midday sun. The result should be
    on the order of 1 K of cooling -- big enough to matter, small enough to be
    physical. This is the number that makes or breaks the whole feedback claim, so
    it is pinned rather than left to inspection.
    """
    aod = I.aerosol_optical_depth(250.0, 300.0)
    d_sw = I.shortwave_reduction(aod, 450.0)
    cooling = -I.surface_cooling_from_sw(d_sw)       # to a positive magnitude
    pbl = I.pbl_from_stability(300.0, cooling)

    assert 0.3 < cooling < 3.0, "chain gave %.3f K, implausible" % cooling
    assert pbl < 300.0, "cooling did not suppress the layer"
    assert pbl > I.PBL_MIN_M, "layer collapsed to the guard"
    suppression = (300.0 - pbl) / 300.0
    assert 0.02 < suppression < 0.40, (
        "feedback suppressed the layer by %.1f%%, outside a defensible range"
        % (suppression * 100.0)
    )


def test_surface_memory_decay_is_a_partial_carry_over():
    """
    The one-pole thermal-memory filter is what keeps the feedback alive after
    sunset. Its per-step factor must be a strict fraction: 1.0 would mean cooling
    never decays, 0.0 would mean it vanishes the instant the sun sets and the
    night-time inversion would lose its aerosol contribution entirely -- which is
    the regime Delhi's episodes actually occur in.
    """
    decay = I.surface_memory_decay()
    assert 0.0 < decay < 1.0, "memory decay factor %.4f is not a partial carry" % decay
    # With tau = 8 h and hourly steps, ~0.88.
    assert 0.7 < decay < 0.99, "decay %.4f implies an implausible timescale" % decay
    assert decay ** 6 > 0.2, "cooling decays too fast to survive the night"


# ── amplification_factor: diagnostic only, but still rendered ────────────────

def test_amplification_factor_is_bounded_at_both_ends():
    """
    No longer the mechanism (§4.3), but still shown in the dashboard, so a
    pathological PBL must not produce an absurd number on screen.
    """
    for pbl in (0.0, 1.0, 50.0, 150.0, 500.0, 1200.0, 5000.0, 100000.0):
        amp = I.amplification_factor(pbl)
        assert I._AMP_MIN <= amp <= I._AMP_MAX, "pbl=%s gave amp=%s" % (pbl, amp)


def test_amplification_factor_is_one_at_the_reference_height():
    """It is defined as reference/actual, so it must be exactly 1 at reference."""
    assert abs(I.amplification_factor(I._PBL_BASE_HEIGHT_M) - 1.0) < 1e-9


def test_amplification_factor_rises_as_the_layer_shallows():
    prev = I.amplification_factor(3000.0)
    for pbl in (2000.0, 1200.0, 800.0, 400.0, 200.0):
        amp = I.amplification_factor(pbl)
        assert amp >= prev, "pbl=%s gave amp=%s, below the deeper layer's %s" % (
            pbl, amp, prev
        )
        prev = amp


def test_amplification_factor_survives_a_zero_pbl():
    """Guard against ZeroDivisionError on a bad upstream value."""
    assert I.amplification_factor(0.0) == I._AMP_MAX


def test_legacy_amplification_wrapper_ignores_delta_t():
    """
    `_aqi_amplification(delta_t, pbl)` is a back-compat shim; dilution depends on
    mixing depth alone. If delta_t ever starts mattering again, the double-counting
    of §4.2 has come back.
    """
    for delta_t in (-5.0, 0.0, 3.0, 12.0):
        assert I._aqi_amplification(delta_t, 400.0) == I.amplification_factor(400.0)


# ── Lapse rate, sign convention, severity bands ─────────────────────────────

def test_positive_delta_t_means_inversion_and_suppresses_mixing():
    """
    ΔT = T(925 hPa) - T(1000 hPa). POSITIVE means warmer air aloft, i.e. an
    inversion, i.e. suppressed mixing. A sign error here inverts the entire
    product: it would forecast clean air on exactly the nights Delhi chokes.
    """
    strong = I._suppressed_pbl(6.0)
    weak = I._suppressed_pbl(1.0)
    none = I._suppressed_pbl(-2.0)
    assert strong < weak < none, (
        "inversion strength is not suppressing mixing monotonically "
        "(strong=%s weak=%s none=%s)" % (strong, weak, none)
    )
    assert strong >= I.PBL_MIN_M
    assert none == I._PBL_BASE_HEIGHT_M


def test_classify_inversion_bands_match_the_documented_thresholds():
    """None <1.5 <= Weak <3.5 <= Moderate <6.0 <= Strong."""
    cases = [
        (-5.0, "None"), (0.0, "None"), (1.49, "None"),
        (1.5, "Weak"), (2.0, "Weak"), (3.49, "Weak"),
        (3.5, "Moderate"), (5.0, "Moderate"), (5.99, "Moderate"),
        (6.0, "Strong"), (10.0, "Strong"), (25.0, "Strong"),
    ]
    for delta_t, expected in cases:
        got = I._classify_inversion(delta_t)
        assert got == expected, (
            "delta_t=%s classified as %r, expected %r" % (delta_t, got, expected)
        )


def test_classify_inversion_thresholds_come_from_the_constant_table():
    """The bands must be driven by _INVERSION_THRESHOLDS, not inlined numbers."""
    t = I._INVERSION_THRESHOLDS
    assert t["weak"] == 1.5 and t["moderate"] == 3.5 and t["strong"] == 6.0
    for key, label in (("weak", "Weak"), ("moderate", "Moderate"), ("strong", "Strong")):
        assert I._classify_inversion(t[key]) == label
        assert I._classify_inversion(t[key] - 1e-9) != label


def test_classify_inversion_is_monotone_across_the_whole_range():
    """No band may be skipped or recur out of order as ΔT increases."""
    order, seen = [], None
    dt = -10.0
    while dt <= 30.0:
        label = I._classify_inversion(dt)
        if label != seen:
            order.append(label)
            seen = label
        dt += 0.05
    assert order == ["None", "Weak", "Moderate", "Strong"], (
        "bands did not appear once each in order: %s" % order
    )


def test_lapse_rate_sign_is_consistent_with_delta_t():
    """
    Γ = -ΔT / 0.75 km. An inversion (ΔT > 0) is a NEGATIVE lapse rate; a normal
    atmosphere (ΔT < 0) gives the familiar positive ~6.5 K/km.
    """
    for entry in I.compute_inversion_series(_met(delta_t=5.0, hours=3)):
        assert entry["lapse_rate_k_per_km"] < 0, (
            "ΔT=+5 K must give a negative lapse rate, got %s"
            % entry["lapse_rate_k_per_km"]
        )
        assert entry["delta_t_celsius"] == 5.0

    for entry in I.compute_inversion_series(_met(delta_t=-4.875, hours=3)):
        rate = entry["lapse_rate_k_per_km"]
        assert rate > 0, "ΔT=-4.875 K must give a positive lapse rate, got %s" % rate
        assert 5.0 < rate < 8.0, (
            "a normal atmosphere should be ~6.5 K/km, got %.2f" % rate
        )


def test_inversion_present_flag_agrees_with_the_severity_label():
    """A row must not say severity="Weak" while inversion_present=False."""
    for delta_t in (-3.0, 0.0, 1.4, 1.5, 2.0, 4.0, 8.0):
        entry = I.compute_inversion_series(_met(delta_t=delta_t, hours=1))[0]
        expected = entry["severity"] != "None"
        assert entry["inversion_present"] == expected, (
            "ΔT=%s: severity=%r but inversion_present=%s"
            % (delta_t, entry["severity"], entry["inversion_present"])
        )


# ── compute_inversion_series must trust the met model ────────────────────────

def test_series_reports_the_met_pbl_unmodified():
    """
    §4.2's core regression. `compute_inversion_series` is a DIAGNOSTIC pass: it
    classifies the inversion and reports the met-model mixing depth. It must not
    floor, damp, or aerosol-adjust that depth -- the coupled solver owns all of
    that, and doing it twice is what cancelled the feedback.
    """
    depths = [180.0, 240.0, 600.0, 1500.0, 2400.0]
    series = I.compute_inversion_series(_met(delta_t=4.0, pbl=depths))
    assert len(series) == len(depths)
    for entry, expected in zip(series, depths):
        assert abs(entry["pbl_height_m"] - expected) < 0.05, (
            "met PBL %s came back as %s -- the diagnostic pass is modifying it"
            % (expected, entry["pbl_height_m"])
        )


def test_a_strong_inversion_does_not_override_a_deep_measured_pbl():
    """
    The sharpest form of the same check. Even with ΔT = 8 K -- an unambiguous strong
    inversion -- a measured 2000 m mixing depth must be reported as 2000 m. The old
    code would have applied its own suppression on top and reported a few hundred.
    """
    entry = I.compute_inversion_series(_met(delta_t=8.0, pbl=[2000.0]))[0]
    assert entry["severity"] == "Strong"
    assert abs(entry["pbl_height_m"] - 2000.0) < 0.05


def test_missing_pbl_falls_back_to_the_empirical_fit():
    """
    The fallback is the one legitimate use of `_suppressed_pbl`: the field is
    genuinely absent. It must engage on None and on non-physical values, and its
    output must match the fit rather than some third number.
    """
    for absent in (None, 0.0, -50.0):
        entry = I.compute_inversion_series(_met(delta_t=4.0, pbl=[absent]))[0]
        assert abs(entry["pbl_height_m"] - round(I._suppressed_pbl(4.0), 1)) < 0.05, (
            "fallback for pbl=%r gave %s, not the empirical fit %s"
            % (absent, entry["pbl_height_m"], I._suppressed_pbl(4.0))
        )


def test_series_is_capped_at_72_hours_and_survives_a_short_payload():
    for n in (1, 6, 24, 72):
        assert len(I.compute_inversion_series(_met(delta_t=2.0, hours=n))) == n
    # The endpoint promises 72 hours; a longer payload must be truncated, not
    # returned whole, or the response would fail schema validation.
    assert len(I.compute_inversion_series(_met(delta_t=2.0, hours=120))) == 72


def test_series_handles_a_missing_boundary_layer_field_entirely():
    """Open-Meteo occasionally omits the variable rather than nulling the values."""
    payload = _met(delta_t=3.0, hours=4)
    del payload["hourly"]["boundary_layer_height"]
    series = I.compute_inversion_series(payload)
    assert len(series) == 4
    for entry in series:
        assert entry["pbl_height_m"] >= I.PBL_MIN_M


# ── helpers ─────────────────────────────────────────────────────────────────

def _met(delta_t: float = 0.0, hours: int = 1, pbl=None) -> dict:
    """
    A minimal Open-Meteo hourly payload, the shape `compute_inversion_series`
    actually consumes. `delta_t` is applied as T(925) - T(1000); `pbl` may be a
    list (which sets the length) and may contain None to simulate a gap.
    """
    if pbl is not None:
        depths = list(pbl)
        hours = len(depths)
    else:
        depths = [1200.0] * hours
    t_surface = 20.0
    return {
        "hourly": {
            "time": ["2026-11-%02dT%02d:00" % (1 + i // 24, i % 24) for i in range(hours)],
            "temperature_1000hPa": [t_surface] * hours,
            "temperature_925hPa": [t_surface + delta_t] * hours,
            "boundary_layer_height": depths,
        }
    }
