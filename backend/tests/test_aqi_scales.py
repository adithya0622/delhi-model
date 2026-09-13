"""AQI sub-index and category regressions.

The headline bug here (AUDIT.md §4.1) was that EPA breakpoint segments were
transcribed as integer-bounded ranges, leaving numeric gaps between them --
pm10 54 -> 55, pm25 12.0 -> 12.1, no2 53 -> 54. `_sub_index` fell through every
segment and hit a bare `return 500`, so a PM10 reading of 54.5 µg/m³, which is
clean air, was reported as maximum severity. Because AQI is the max over
sub-indices and the citywide number averages stations, one station in a gap
dragged the whole city dark red. It was live in the sidebar's "EPA NowCast" mode.

The fix has two parts and both are tested: truncate to EPA reporting precision
before lookup (which is what the EPA method actually requires, and what closes
the gaps by construction), and clamp out-of-range values instead of defaulting
to 500.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.species import AQICategory, Pollutant
from app.services import aqi_service as A

# The scale math is imported from `domain`, not from `services.realtime_service`,
# specifically so this file can run without httpx/cachetools installed. That
# extraction was itself part of the fix: while the arithmetic lived inside the
# HTTP service module, the single most demo-critical function in the project could
# not be unit-tested at all. `realtime_service` re-exports these names, and
# `test_realtime_reexports_the_same_functions` checks the re-export still works
# whenever the web stack happens to be available.
from app.domain import aqi_scales as R


# ── The §4.1 regression, case by case ────────────────────────────────────────

def test_epa_gap_values_are_not_severe():
    """Every concentration the audit found returning a false 500."""
    cases = [
        ("pm10", 54.5),     # between segment 1 (0-54) and segment 2 (55-154)
        ("pm10", 154.5),
        ("pm10", 254.5),
        ("pm25", 9.05),     # between 0-9.0 and 9.1-35.4 (EPA 2024 table)
        ("pm25", 35.45),
        ("pm25", 55.45),
        ("no2", 53.5),      # between 0-53 and 54-100
        ("so2", 35.5),
        ("o3", 107.5),
    ]
    for param, conc in cases:
        idx = R._sub_index(param, conc, mode="nowcast")
        assert idx < 500, (
            "%s=%s returned %d in nowcast mode; a gap value must not report 500"
            % (param, conc, idx)
        )
        # And it must be plausible, not merely "not 500".
        assert 0 <= idx <= 200, "%s=%s gave implausible %d" % (param, conc, idx)


def test_epa_gap_values_land_in_the_lower_segment():
    """
    Truncation is what closes the gaps: PM10 is reported to 0 decimals, so 54.5
    truncates to 54 and lands in segment 1 (AQI <= 50), not segment 2.
    """
    assert R._sub_index("pm10", 54.5, mode="nowcast") == 50
    assert R._sub_index("pm10", 54.9, mode="nowcast") == 50
    assert R._sub_index("pm10", 55.0, mode="nowcast") == 51
    # PM2.5 uses the breakpoints effective May 6 2024: the segment gap sits
    # between 9.0 and 9.1 ug/m3, so 9.05 truncates to 9.0 -- top of segment 1.
    assert R._sub_index("pm25", 9.05, mode="nowcast") == 50
    # 12.05 truncates to 12.0, which sits inside segment 2 (9.1-35.4).
    assert R._sub_index("pm25", 12.05, mode="nowcast") == 56
    # Segment 2 interpolates: 51 + 49 * (12.1-9.1)/(35.4-9.1) = 57.
    assert R._sub_index("pm25", 12.1, mode="nowcast") == 57


def test_500_is_reachable_only_at_the_top_of_the_scale():
    """500 must mean "off the scale", never "failed to match a segment"."""
    assert R._sub_index("pm25", 600.0, mode="nowcast") == 500
    assert R._sub_index("pm25", 99999.0, mode="nowcast") == 500
    # ... and nothing in the ordinary range reaches it.
    for conc in (0.0, 5.0, 12.0, 35.0, 55.0, 150.0, 250.0):
        assert R._sub_index("pm25", conc, mode="nowcast") < 500


def test_sub_index_rejects_junk_without_raising():
    for bad in (None, "", "abc", float("nan"), float("inf"), -5.0):
        assert R._sub_index("pm25", bad, mode="nowcast") == 0
        assert R._sub_index("pm25", bad, mode="instant") == 0


def test_unknown_pollutant_is_skipped_not_guessed():
    assert R._sub_index("benzene", 42.0) == 0


# ── CPCB and EPA are different scales and must be labelled differently ───────

def test_cpcb_and_epa_labels_disagree_where_the_scales_disagree():
    """
    An AQI of 150 is "Unhealthy for Sensitive Groups" on the EPA scale and
    "Moderate" on CPCB, because EPA breaks at 150 and CPCB at 200. Applying CPCB
    names to an EPA number mislabels the entire 101-200 range.
    """
    cpcb_label, _ = R._cat(150, mode="instant")
    epa_label, _ = R._cat(150, mode="nowcast")
    assert cpcb_label == "Moderate"
    assert epa_label == "Unhealthy for Sensitive Groups"
    assert cpcb_label != epa_label


def test_category_tables_are_contiguous_and_cover_0_to_500():
    for name, table in (("CPCB", R.AQI_CATEGORIES), ("EPA", R.AQI_CATEGORIES_EPA)):
        assert table[0][0] == 0, "%s table must start at 0" % name
        assert table[-1][1] == 500, "%s table must end at 500" % name
        for (lo_a, hi_a, _, _), (lo_b, _, _, _) in zip(table, table[1:]):
            assert lo_b == hi_a + 1, (
                "%s table has a gap or overlap at %d/%d" % (name, hi_a, lo_b)
            )
        # Every integer 0-500 must resolve to a label.
        for aqi in range(0, 501):
            mode = "nowcast" if name == "EPA" else "instant"
            label, colour = R._cat(aqi, mode=mode)
            assert label and colour.startswith("#")


def test_cat_defaults_to_cpcb():
    """Existing instant-mode call sites pass no mode; they must stay CPCB."""
    assert R._cat(150) == R._cat(150, mode="instant")


# ── CPCB forecast path ───────────────────────────────────────────────────────

def test_cpcb_breakpoints_are_contiguous():
    """
    The reason the CPCB path never had the EPA gap bug: its segments touch. This
    asserts the property rather than trusting it.
    """
    for pollutant, bps in A._BREAKPOINTS.items():
        for (lo_a, hi_a, _, _), (lo_b, _, _, _) in zip(bps, bps[1:]):
            assert lo_b <= hi_a, (
                "%s has a gap between %s and %s" % (pollutant, hi_a, lo_b)
            )


def test_cpcb_interpolation_matches_the_published_formula():
    """
    I = I_lo + (I_hi - I_lo) * (C - C_lo) / (C_hi - C_lo), checked by hand against
    the table the code actually carries.

    Note on a deliberate deviation from CPCB's printed table: CPCB prints
    integer-bounded segments (0-30, 31-60, 61-90, ...), which leaves real-valued
    gaps at 30.5, 60.5 and so on. This code uses contiguous bounds instead
    (0-30, 30-60, 60-90) so that every concentration matches exactly one segment.
    That is the same class of choice the EPA path gets wrong -- see the module
    docstring -- and here it is made correctly by construction.

    The cost is up to 4 AQI points of difference from the printed table just above
    a boundary (worst case: PM2.5 at 61.1 µg/m³ scores 105 here, 101 by the printed
    bounds). That is well inside measurement uncertainty for a ±10% reference
    monitor, and it buys a function with no unreachable branches. This test pins
    the convention so it cannot drift silently.
    """
    bps = A._BREAKPOINTS[Pollutant.PM25]
    assert bps[1][:2] == (30.0, 60.0), (
        "PM2.5 segment 2 bounds changed to %s; the contiguous-bounds convention "
        "documented here no longer holds" % (bps[1][:2],)
    )
    # 51 + (100-51) * (45-30)/(60-30) = 51 + 49*0.5 = 75.5 -> 76
    assert A._linear_interpolate_subindex(45.0, bps) == 76
    # Segment boundaries must land exactly on the published index values.
    assert A._linear_interpolate_subindex(30.0, bps) == 50
    assert A._linear_interpolate_subindex(60.0, bps) == 100
    assert A._linear_interpolate_subindex(90.0, bps) == 200
    assert A._linear_interpolate_subindex(120.0, bps) == 300
    assert A._linear_interpolate_subindex(250.0, bps) == 400


def test_interpolator_has_no_unreachable_500_and_no_zero_division():
    """
    Two failure modes the EPA path had. Sweep every pollutant's full range at fine
    resolution: no segment may divide by zero (CO's first segment is only 1 unit
    wide, so a table edit collapsing it would crash rather than misreport), and 500
    must never be returned for a concentration below the top segment.

    The bound is "below the top segment", not "below the top of the scale": inside
    the final segment, interpolation legitimately rounds to 500 near its ceiling
    (PM2.5 at 498.75 µg/m³ scores exactly 500 and should). What must never happen
    is the original bug -- 500 returned for a value nowhere near the top, as a
    fall-through for failing to match any segment.
    """
    for pollutant, bps in A._BREAKPOINTS.items():
        top = bps[-1][1]
        top_segment_floor = bps[-1][0]
        c = 0.0
        while c < top:
            idx = A._linear_interpolate_subindex(c, bps)
            assert 0 <= idx <= 500, "%s at %s gave %s" % (pollutant, c, idx)
            if c < top_segment_floor:
                assert idx < 500, (
                    "%s at %s returned 500 while below the top segment (starts at "
                    "%s) -- this is the fall-through bug"
                    % (pollutant, c, top_segment_floor)
                )
            c += top / 400.0
        assert A._linear_interpolate_subindex(top, bps) == 500
        assert A._linear_interpolate_subindex(top * 10, bps) == 500


def test_sub_indices_clamp_both_ends():
    """
    Regression for the missing lower bound. The schema declares sub_index as
    ge=0 and `_aqi_category` has no band below zero, so a negative arriving here
    would either fail response validation or be silently labelled "Severe" --
    the worst possible way to render clean air.
    """
    subs = A.compute_sub_indices({Pollutant.PM25: -5.0, Pollutant.PM10: 60.0})
    by_p = {s["pollutant"]: s for s in subs}
    assert by_p[Pollutant.PM25]["sub_index"] == 0
    assert by_p[Pollutant.PM25]["category"] == AQICategory.GOOD
    assert by_p[Pollutant.PM25]["concentration"] == 0.0, \
        "a negative concentration must not be reported verbatim"
    for s in subs:
        assert 0 <= s["sub_index"] <= 500


def test_aqi_is_the_max_of_sub_indices():
    conc = {
        Pollutant.PM25: 45.0,    # ~75
        Pollutant.PM10: 60.0,    # ~61
        Pollutant.NO2: 20.0,     # low
    }
    subs = A.compute_sub_indices(conc)
    assert A._aqi_from_conc(conc) == max(s["sub_index"] for s in subs)


def test_co_is_carried_in_mg_not_ug():
    """
    CPCB's CO breakpoints are in mg/m³. Feeding µg/m³ into them reports clean air
    as Severe: 2000 µg/m³ (= 2 mg/m³, satisfactory) would score off the scale.
    """
    top_of_scale = A._BREAKPOINTS[Pollutant.CO][-1][1]
    assert top_of_scale < 100, (
        "CO breakpoints look like µg/m³ (top=%s); they must be mg/m³" % top_of_scale
    )
    assert A._linear_interpolate_subindex(2.0, A._BREAKPOINTS[Pollutant.CO]) <= 100


def test_co_mg_converted_once_at_reporting_boundary():
    """
    The box carries CO in mg/m³; the scale boundary is canonical µg/m³. A real
    Delhi reading of 1.22 mg/m³ must score EPA ~11 and CPCB ~62 -- never 0.
    A 0 here meant 1.22 was read as 1.22 µg/m³, i.e. clean air by three
    orders of magnitude.
    """
    subs_epa = A.compute_sub_indices({Pollutant.CO: 1.22}, mode="epa")
    by_epa = {s["pollutant"]: s for s in subs_epa}
    assert by_epa[Pollutant.CO]["concentration"] == 1220.0
    assert by_epa[Pollutant.CO]["sub_index"] == 11

    subs_cpcb = A.compute_sub_indices({Pollutant.CO: 1.22}, mode="instant")
    by_cpcb = {s["pollutant"]: s for s in subs_cpcb}
    assert by_cpcb[Pollutant.CO]["sub_index"] == 62


def test_no_saturation_at_500_for_a_severe_but_real_delhi_day():
    """
    A bad-but-real November morning must not peg the index. If it does, the
    dashboard shows a flat line through the worst hours and the forecast becomes
    useless exactly when it matters.
    """
    conc = {
        Pollutant.PM25: 340.0, Pollutant.PM10: 520.0, Pollutant.NO2: 110.0,
        Pollutant.SO2: 25.0, Pollutant.CO: 3.2, Pollutant.O3: 30.0,
    }
    aqi = A._aqi_from_conc(conc)
    assert 400 <= aqi < 500, "expected Severe but unsaturated, got %d" % aqi


# ── The domain/service split ─────────────────────────────────────────────────

def test_realtime_reexports_the_same_functions():
    """
    `realtime_service` must keep exporting these names, since the endpoints and
    the NowCast path import them from there. Skipped rather than failed when the
    web stack is absent -- the point of the extraction is that the scale tests
    above do not depend on it.
    """
    try:
        from app.services import realtime_service as RS
    except ImportError:
        return          # httpx/cachetools unavailable; nothing to check
    for name in ("_sub_index", "_cat", "_conc_to_aqi", "_truncate",
                 "_normalise_param", "_BP", "_BP_EPA", "_PRECISION",
                 "AQI_CATEGORIES", "AQI_CATEGORIES_EPA"):
        assert hasattr(RS, name), "realtime_service stopped exporting %s" % name
        assert getattr(RS, name) is getattr(R, name), (
            "realtime_service.%s is a divergent copy, not the domain object" % name
        )
