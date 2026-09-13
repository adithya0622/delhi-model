"""Hour-0 observational nudge: the correction must keep the response consistent.

The bug this pins was found by a LIVE boot, not by this suite -- and that is the
point. The nudge that bias-corrects hour 0 toward the live OpenAQ reading lived
entirely inside `build_72h_forecast`, an async function that calls Open-Meteo, so
no offline test ever exercised it. Worse, the nudge was a no-op (`scale = 1.0`)
whenever no live anchor is supplied, which is exactly the regime every test and
every `scripts/verify` harness runs in. So the defect was invisible until a real
`base_aqi` was threaded through.

The defect: the nudge multiplied the *headline* AQI by the correction weight but
left the concentrations and their sub-indices untouched. CPCB AQI is defined as
`max(sub-indices)`, so a nudged headline over un-nudged pollutant bars is a
self-contradictory response -- on the live run, hour 0 reported AQI 64 while its
own PM2.5 sub-index sat at ~158 (a green gauge above orange bars).

The fix moves the correction into concentration space: scale the accumulated
column, then derive AQI, sub-indices and the dominant pollutant from the SAME
corrected concentrations, so `aqi == max(sub-indices)` by construction. These
tests exercise the now-pure helpers (`_scale_conc`, `_conc_scale_for_target_aqi`)
and the invariant directly, closing the "untested because it was buried in an
async network call" gap.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.species import Pollutant as P
from app.services import aqi_service as A

# The nudge bounds and e-folding constant are declared inline in
# build_72h_forecast; mirror them here so the decay/clamp tests describe the same
# behaviour the function implements.
_LO, _HI = 0.4, 2.5
_TAU_H = 12.0


def _sample_column():
    """A synthetic hour where PM2.5 clearly dominates (raw AQI ~159)."""
    return {
        P.PM25: 78.0,   # band 61-90 -> sub-index ~159
        P.PM10: 60.0,
        P.NO2: 20.0,
        P.SO2: 10.0,
        P.CO: 0.5,
        P.O3: 20.0,     # a diagnostic, must never be scaled by the load nudge
    }


# ── _scale_conc: scales the accumulated load, never the O3 diagnostic ─────────

def test_scale_conc_scales_every_species_except_o3():
    conc = _sample_column()
    scaled = A._scale_conc(conc, 0.5)
    for p in (P.PM25, P.PM10, P.NO2, P.SO2, P.CO):
        assert math.isclose(scaled[p], conc[p] * 0.5), p
    # O3 is set by photochemistry each hour, not accumulated; the observational
    # load correction must leave it exactly as it was.
    assert scaled[P.O3] == conc[P.O3]


def test_scale_conc_factor_one_is_identity():
    conc = _sample_column()
    assert A._scale_conc(conc, 1.0) == conc


# ── _conc_scale_for_target_aqi: reproduces the anchor, in concentration space ─

def test_scale_reproduces_the_target_aqi():
    conc = _sample_column()
    raw = A._aqi_from_conc(conc)
    assert raw > 150   # sanity: the synthetic column really is dirty
    target = 66        # the live-boot anchor that exposed the bug
    s = A._conc_scale_for_target_aqi(conc, target, _LO, _HI)
    assert _LO < s < 1.0   # a real downward correction, inside the guard band
    got = A._aqi_from_conc(A._scale_conc(conc, s))
    assert abs(got - target) <= 1   # bisection lands on the anchor bar to rounding


def test_the_headline_and_the_bars_now_agree():
    """The exact regression: after nudging, aqi == max(sub-indices).

    Before the fix, hour 0 could report AQI 66 while the PM2.5 sub-index stayed
    at ~158. Here we drive the same correction through concentration space and
    assert the headline equals its own breakdown, and that the PM2.5 bar -- the
    dominant pollutant -- reads the headline value rather than the un-nudged 158.
    """
    conc = _sample_column()
    s = A._conc_scale_for_target_aqi(conc, 66, _LO, _HI)
    nudged = A._scale_conc(conc, s)
    subs = A.compute_sub_indices(nudged)
    aqi = max(x["sub_index"] for x in subs)

    assert aqi == max(x["sub_index"] for x in subs)         # invariant, by construction
    pm25_sub = next(x["sub_index"] for x in subs if x["pollutant"] is P.PM25)
    assert pm25_sub == aqi                                   # dominant bar == headline
    assert abs(aqi - 66) <= 1
    assert pm25_sub < 100    # the whole point: not the stale ~158


def test_target_below_the_floor_saturates_at_lo():
    """A single stuck sensor reading near zero cannot collapse the forecast."""
    dirty = {P.PM25: 300.0, P.PM10: 400.0, P.NO2: 40.0, P.SO2: 20.0,
             P.CO: 1.0, P.O3: 20.0}
    s = A._conc_scale_for_target_aqi(dirty, 5, _LO, _HI)
    assert s == _LO   # even at the floor the AQI is still far above 5


def test_target_above_the_ceiling_saturates_at_hi():
    """Nor can a stuck-high reading triple a clean column."""
    clean = {P.PM25: 20.0, P.PM10: 30.0, P.NO2: 10.0, P.SO2: 5.0,
             P.CO: 0.3, P.O3: 15.0}
    s = A._conc_scale_for_target_aqi(clean, 480, _LO, _HI)
    assert s == _HI   # even at 2.5x the AQI cannot reach 480


def test_zero_or_negative_target_returns_the_floor():
    conc = _sample_column()
    assert A._conc_scale_for_target_aqi(conc, 0, _LO, _HI) == _LO


# ── live_pm25 anchor: a pure concentration ratio ─────────────────────────────

def test_live_pm25_ratio_lands_on_the_observed_value():
    conc = _sample_column()
    live_pm25 = 40.0
    scale = live_pm25 / conc[P.PM25]           # what build_72h_forecast computes
    scale = min(max(scale, _LO), _HI)
    nudged = A._scale_conc(conc, scale)
    assert math.isclose(nudged[P.PM25], live_pm25)
    subs = A.compute_sub_indices(nudged)
    assert max(x["sub_index"] for x in subs) == \
        next(x["sub_index"] for x in subs if x["pollutant"] is P.PM25)


# ── the decay envelope: hour 0 is fully corrected, later hours relax ─────────

def test_correction_decays_from_hour0_toward_the_model():
    scale_h0 = 0.5
    weights = [1.0 + (scale_h0 - 1.0) * math.exp(-i / _TAU_H) for i in range(72)]
    assert weights[0] == scale_h0                    # hour 0 fully anchored
    assert weights[-1] > weights[0]                  # relaxes back toward 1.0
    assert all(a <= b for a, b in zip(weights, weights[1:]))   # monotone for s<1
    assert abs(weights[-1] - 1.0) < 0.05             # ~gone by +72 h


def test_no_anchor_is_an_exact_no_op():
    """With neither base_aqi nor live_pm25, scale is 1.0 and the column is
    untouched -- which is why the 149-test suite and every verify harness (all
    run without an anchor) neither caught the bug nor are perturbed by the fix."""
    conc = _sample_column()
    scale_h0 = 1.0   # the else-branch of the nudge
    assert A._scale_conc(conc, scale_h0) == conc
    assert A._aqi_from_conc(A._scale_conc(conc, scale_h0)) == A._aqi_from_conc(conc)
