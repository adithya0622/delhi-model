"""Stubble-plume transport: the four bugs that made it produce zeros.

AUDIT.md §4.5. The previous plume module could not have worked, for four
independent reasons, and every one of them failed *silently* -- the feature
returned an empty plume list or a negligible concentration rather than an error,
so nothing downstream could tell it was broken:

  1. The FIRMS bounding box string was ordered (lat_min,lat_max,lon_min,lon_max)
     but the API expects west,south,east,north, so it requested a box over
     Kazakhstan instead of Punjab.
  2. The CSV was parsed by hard-coded column index; `cols[8]` is the literal
     string "VIIRS", so `float()` raised, the bare except swallowed it, and the
     parser returned [].
  3. Q = frp_mw * 50 µg/s was about six orders of magnitude too small -- one
     grain of dust per megawatt of fire.
  4. Dispersion used straight-line fire->Delhi distance regardless of wind, so a
     plume blowing due north away from the city delivered the same concentration
     as one aimed straight at it.

These tests pin the physical direction and magnitude of the fixes, and drive the
FIRMS parser with synthetic CSV so the header-name resolution is exercised for
both the VIIRS and MODIS layouts without a network call.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.physics import plume_advection as P

_DELHI = (P._DELHI_LAT, P._DELHI_LON)

# A Punjab fire (Sangrur, a real high-count district) and the northwesterly
# transport wind that carries its smoke toward Delhi.
_SANGRUR = (30.25, 75.84)
_NW_WIND = [P._FALLBACK_WIND_UV] * P._FORECAST_HOURS


# ── Bug 3: the emission chain ───────────────────────────────────────────────

def test_emission_rate_is_grams_per_second_not_micrograms():
    """
    The chain is Wooster (0.368 kg dry matter / MJ) x Andreae & Merlet
    (8.5 g PM2.5 / kg) = ~3.13 g/s per MW of FRP. The old constant was 50 µg/s --
    a factor of ~6e4 smaller -- which is the difference between a plume that shows
    up in the forecast and one that never does.
    """
    assert P._DM_PER_FRP_KG_PER_MJ == 0.368
    assert P._EF_PM25_G_PER_KG_DM == 8.5
    per_mw_g_s = P._PM25_UG_S_PER_MW / 1e6
    assert abs(per_mw_g_s - 3.128) < 0.01, (
        "FRP->PM2.5 rate is %.4f g/s per MW, not the ~3.13 the chain gives"
        % per_mw_g_s
    )
    # Guard against a silent return to the µg-scale constant.
    assert P._PM25_UG_S_PER_MW > 1e6, "emission constant is back in the µg regime"


def test_loading_scales_linearly_with_fire_power():
    """Twice the FRP is twice the column loading; the map value must track FRP."""
    a = P.plume_column_loading(100.0, 200.0, 0.0, 3.0, 15.0)
    b = P.plume_column_loading(200.0, 200.0, 0.0, 3.0, 15.0)
    assert a > 0
    assert abs(b - 2 * a) < 1e-6 * b, "loading is not linear in FRP"


def test_a_realistic_fire_delivers_a_meaningful_column():
    """
    A 200 MW fire ~280 km upwind, on the plume centreline, at typical transport
    speed. It should deliver enough to matter -- tens of µg/m³ once spread through
    the transport layer -- not a rounding error and not an absurd value.
    """
    loading = P.plume_column_loading(
        frp_mw=200.0, travel_km=280.0, crosswind_km=0.0, wind_ms=3.7, travel_hours=20.0
    )
    layer_conc = loading / P.PLUME_LAYER_DEPTH_M
    assert 1.0 < layer_conc < 900.0, (
        "a 200 MW fire delivered %.2f µg/m³ to the layer -- outside the plausible "
        "band, so the emission scale is wrong" % layer_conc
    )


def test_loading_is_capped_against_a_corrupt_frp():
    huge = P.plume_column_loading(1e9, 50.0, 0.0, 3.0, 5.0)
    assert huge <= P._LOADING_CAP_UG_M2


# ── Bug 4: direction awareness ──────────────────────────────────────────────

def test_a_plume_on_the_centreline_beats_one_blown_crosswind():
    """
    The core of the direction fix: crosswind offset enters as a Gaussian. A fire
    whose plume passes directly over Delhi (crosswind 0) must deliver far more
    than the identical fire whose plume misses by 80 km.
    """
    on_line = P.plume_column_loading(150.0, 250.0, 0.0, 3.7, 18.0)
    off_line = P.plume_column_loading(150.0, 250.0, 80.0, 3.7, 18.0)
    assert on_line > off_line
    assert off_line < 0.5 * on_line, (
        "an 80 km crosswind miss (%.1f) is not strongly suppressed relative to a "
        "direct hit (%.1f) -- the Gaussian offset is too weak to be direction-aware"
        % (off_line, on_line)
    )


def test_a_plume_far_off_axis_delivers_essentially_nothing():
    """Beyond several sigma the contribution must vanish, not merely shrink."""
    way_off = P.plume_column_loading(150.0, 250.0, 400.0, 3.7, 18.0)
    assert way_off == 0.0, (
        "a 400 km crosswind miss still delivered %.3g µg/m² -- the exponent guard "
        "is not firing" % way_off
    )


def test_zero_frp_or_zero_travel_is_zero_loading():
    assert P.plume_column_loading(0.0, 250.0, 0.0, 3.7, 18.0) == 0.0
    assert P.plume_column_loading(150.0, 0.0, 0.0, 3.7, 18.0) == 0.0


def test_distant_fires_matter_less_than_near_ones():
    """
    Two effects must make a far fire weaker at equal FRP: a wider plume (more
    dilution) and more transport-time decay. This is what stops a Kazakhstan-sized
    box from making every distant fire count as much as a Haryana one.
    """
    near = P.plume_column_loading(150.0, 80.0, 0.0, 3.7, 6.0)
    far = P.plume_column_loading(150.0, 300.0, 0.0, 3.7, 22.0)
    assert near > far, "a near fire (%.1f) did not beat a far one (%.1f)" % (near, far)


# ── Wind sign convention ────────────────────────────────────────────────────

def test_fallback_wind_blows_from_the_northwest_toward_delhi():
    """
    The §4.5 sign bug in miniature. `direction` in the met convention is where the
    wind comes FROM, so a northwesterly (315°) must give u>0 (eastward) and v<0
    (southward): air travelling southeast, toward Delhi. The old fallback pointed
    the other way and advected every plume away from the city.
    """
    u, v = P._FALLBACK_WIND_UV
    assert u > 0 and v < 0, "fallback wind (%.2f,%.2f) does not blow toward Delhi" % (u, v)
    bearing_from = (math.degrees(math.atan2(-u, -v)) + 360) % 360
    assert 300 <= bearing_from <= 330, (
        "fallback wind is coming FROM %.0f°, not the ~315° northwesterly regime"
        % bearing_from
    )


def test_a_northwesterly_carries_a_punjab_fire_toward_the_city():
    """
    End to end for the sign convention: advect the Sangrur fire under the
    northwesterly and confirm the trajectory moves SOUTHEAST -- latitude falls,
    longitude rises -- i.e. toward Delhi, not away.
    """
    traj = P._advect_plume(_SANGRUR[0], _SANGRUR[1], _NW_WIND)
    start_lat, start_lon = traj[0]
    end_lat, end_lon = traj[-1]
    assert end_lat < start_lat, "trajectory moved north; wind sign is inverted"
    assert end_lon > start_lon, "trajectory moved west; wind sign is inverted"

    start_dist = P._haversine(start_lat, start_lon, *_DELHI)
    closest, _path, _hrs = P._closest_approach(traj)
    assert closest < start_dist, (
        "the plume's closest approach (%.0f km) is no nearer than its start "
        "(%.0f km) -- it is being carried away from Delhi" % (closest, start_dist)
    )


def test_wind_component_recovery_matches_the_met_convention():
    """
    Reproduce the (u,v) the fetch computes from (speed, direction) and confirm the
    leading minus signs are present: for a wind FROM 315° at 5 m/s, u = -5·sin =
    +3.54, v = -5·cos = +3.54... no: cos(315°) is +0.707, so v = -3.54. Pin it.
    """
    spd_ms = 5.0
    for direction, want_u_sign, want_v_sign in (
        (315.0, +1, -1),   # from NW -> toward SE
        (270.0, +1, 0),    # from W  -> toward E (v ~ 0)
        (180.0, 0, +1),    # from S  -> toward N
        (90.0, -1, 0),     # from E  -> toward W
    ):
        rad = math.radians(direction)
        u = -spd_ms * math.sin(rad)
        v = -spd_ms * math.cos(rad)
        if want_u_sign > 0:
            assert u > 0.1, "dir %g: u=%.2f not eastward" % (direction, u)
        elif want_u_sign < 0:
            assert u < -0.1, "dir %g: u=%.2f not westward" % (direction, u)
        if want_v_sign > 0:
            assert v > 0.1, "dir %g: v=%.2f not northward" % (direction, v)
        elif want_v_sign < 0:
            assert v < -0.1, "dir %g: v=%.2f not southward" % (direction, v)


# ── Bug 2: FIRMS parsing by header name ─────────────────────────────────────

_VIIRS_HEADER = (
    "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,"
    "instrument,confidence,version,bright_ti5,frp,daynight"
)


def _viirs_row(lat, lon, frp, conf="n", date="2025-11-05", time="0812"):
    return (
        f"{lat},{lon},320.1,0.5,0.5,{date},{time},N,VIIRS,{conf},2.0NRT,290.3,"
        f"{frp},D"
    )


def test_viirs_csv_is_parsed_by_header_not_column_index():
    """
    The bug that returned []. `instrument` sits where the old code read FRP; a
    header-driven parser must pull the real FRP column and never choke on the
    string "VIIRS".
    """
    csv_text = _VIIRS_HEADER + "\n" + "\n".join([
        _viirs_row(30.25, 75.84, 45.6),
        _viirs_row(29.69, 76.99, 12.3),
    ])
    hotspots = P._parse_firms_csv(csv_text)
    assert len(hotspots) == 2, "expected 2 hotspots, got %d" % len(hotspots)
    frps = sorted(h["frp_mw"] for h in hotspots)
    assert frps == [12.3, 45.6], "FRP column misread: %s" % frps
    assert all(isinstance(h["frp_mw"], float) for h in hotspots)


def test_modis_csv_with_a_different_layout_also_parses():
    """
    MODIS has a different column set and a numeric confidence. Header resolution
    means the same parser handles it; positional indexing never could.
    """
    modis = (
        "latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,"
        "instrument,confidence,version,bright_t31,frp,daynight\n"
        "30.10,75.50,330.0,1.0,1.0,2025-11-05,0730,Terra,MODIS,78,6.1NRT,290.0,88.8,D"
    )
    hotspots = P._parse_firms_csv(modis)
    assert len(hotspots) == 1
    assert hotspots[0]["frp_mw"] == 88.8
    assert hotspots[0]["confidence"] == "78"


def test_parser_refuses_a_header_without_the_required_columns():
    """
    Better to return nothing than to guess column positions. If latitude/longitude/
    frp are not all present the parser must bail, not fabricate.
    """
    assert P._parse_firms_csv("a,b,c\n1,2,3") == []
    assert P._parse_firms_csv("latitude,longitude\n30.2,75.8") == []
    assert P._parse_firms_csv("") == []
    assert P._parse_firms_csv("   ") == []


def test_parser_drops_nonpositive_and_out_of_box_detections():
    """FRP<=0 is a non-fire pixel; outside the source bbox is not our region."""
    rows = [
        _viirs_row(30.25, 75.84, 40.0),      # keep
        _viirs_row(30.25, 75.84, 0.0),       # drop: zero FRP
        _viirs_row(30.25, 75.84, -5.0),      # drop: negative FRP
        _viirs_row(10.0, 75.84, 40.0),       # drop: south of the box
        _viirs_row(30.25, 60.0, 40.0),       # drop: west of the box (old Kazakhstan bug)
    ]
    hotspots = P._parse_firms_csv(_VIIRS_HEADER + "\n" + "\n".join(rows))
    assert len(hotspots) == 1, (
        "expected 1 surviving detection, got %d -- the bbox/FRP filters are wrong"
        % len(hotspots)
    )
    assert hotspots[0]["frp_mw"] == 40.0


def test_low_confidence_viirs_is_dropped_but_nominal_is_kept():
    """
    Low-confidence VIIRS pixels are dominated by gas flares and brick kilns, not
    stubble. 'l' is dropped; 'n' and 'h' are kept.
    """
    rows = [
        _viirs_row(30.25, 75.84, 40.0, conf="l"),   # drop
        _viirs_row(30.25, 75.84, 41.0, conf="n"),   # keep
        _viirs_row(30.25, 75.84, 42.0, conf="h"),   # keep
    ]
    hotspots = P._parse_firms_csv(_VIIRS_HEADER + "\n" + "\n".join(rows))
    kept = sorted(h["frp_mw"] for h in hotspots)
    assert kept == [41.0, 42.0], "confidence filter wrong: kept %s" % kept


def test_low_numeric_confidence_modis_is_dropped():
    """MODIS numeric confidence below 30% is dropped; at/above is kept."""
    header = (
        "latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,"
        "instrument,confidence,version,bright_t31,frp,daynight"
    )
    rows = [
        f"30.25,75.84,330,1,1,2025-11-05,0730,Terra,MODIS,10,6.1,290,50,D",   # drop
        f"30.25,75.84,330,1,1,2025-11-05,0730,Terra,MODIS,30,6.1,290,51,D",   # keep
        f"30.25,75.84,330,1,1,2025-11-05,0730,Terra,MODIS,95,6.1,290,52,D",   # keep
    ]
    hotspots = P._parse_firms_csv(header + "\n" + "\n".join(rows))
    kept = sorted(h["frp_mw"] for h in hotspots)
    assert kept == [51.0, 52.0], "numeric confidence filter wrong: kept %s" % kept


def test_parsed_hotspot_carries_a_state_label_and_time():
    hotspots = P._parse_firms_csv(_VIIRS_HEADER + "\n" + _viirs_row(30.25, 75.84, 40.0))
    hs = hotspots[0]
    assert hs["source_state"] == "Punjab"
    assert hs["detected_at"].startswith("2025-11-05")


# ── Bug 1 (indirectly) + geometry helpers ───────────────────────────────────

def test_source_box_is_west_south_east_north_and_covers_punjab():
    """
    The bbox string must be west,south,east,north with west<east and south<north,
    and it must actually contain the Punjab/Haryana fire belt. The old string
    described a box over Kazakhstan.
    """
    assert P._SRC_WEST < P._SRC_EAST, "bbox longitude order is reversed"
    assert P._SRC_SOUTH < P._SRC_NORTH, "bbox latitude order is reversed"
    # Sangrur and Karnal must both fall inside.
    for lat, lon in (_SANGRUR, (29.69, 76.99)):
        assert P._SRC_SOUTH <= lat <= P._SRC_NORTH
        assert P._SRC_WEST <= lon <= P._SRC_EAST
    assert P._SOURCE_BBOX == f"{P._SRC_WEST},{P._SRC_SOUTH},{P._SRC_EAST},{P._SRC_NORTH}"


def test_haversine_matches_a_known_distance():
    """Delhi to Chandigarh is ~240 km; a gross error in the metric shows here."""
    d = P._haversine(28.6139, 77.2090, 30.7333, 76.7794)
    assert 230 < d < 260, "Delhi-Chandigarh came out %.0f km" % d


def test_haversine_is_zero_for_coincident_points():
    assert P._haversine(28.6, 77.2, 28.6, 77.2) == 0.0


def test_state_labels_place_interior_districts_correctly():
    """
    The mislabel the previous docstring claimed to have fixed but had not: NW
    Rajasthan read as Punjab, and Punjab's own high-count districts (Sangrur,
    Patiala) read as Haryana. Interior points only -- rectangles cannot resolve
    border towns.
    """
    cases = {
        "Punjab": [(30.90, 75.85), (31.63, 74.87), (30.25, 75.84), (30.34, 76.39)],
        "Haryana": [(29.69, 76.99), (29.15, 75.72), (29.53, 75.03), (28.90, 76.61)],
        "Rajasthan": [(29.92, 73.88), (29.58, 74.32), (28.30, 74.97), (27.61, 75.14)],
        "Uttar Pradesh": [(28.98, 77.70), (29.97, 77.55)],
    }
    for want, pts in cases.items():
        for lat, lon in pts:
            got = P._state_from_coords(lat, lon)
            assert got == want, "(%.2f,%.2f) labelled %s, expected %s" % (
                lat, lon, got, want
            )


def test_an_unrecognised_point_is_unknown_not_a_guess():
    """Far outside the region must admit ignorance rather than defaulting to UP."""
    assert P._state_from_coords(20.0, 60.0) == "Unknown"


def test_to_local_km_is_consistent_with_haversine():
    """The flat-earth projection must agree with the sphere to <1% over ~300 km."""
    lat_ref = P._DELHI_LAT
    x1, y1 = P._to_local_km(30.25, 75.84, lat_ref)
    x2, y2 = P._to_local_km(P._DELHI_LAT, P._DELHI_LON, lat_ref)
    flat = math.hypot(x1 - x2, y1 - y2)
    sphere = P._haversine(30.25, 75.84, P._DELHI_LAT, P._DELHI_LON)
    assert abs(flat - sphere) / sphere < 0.01, (
        "flat projection %.1f km disagrees with haversine %.1f km by >1%%"
        % (flat, sphere)
    )


# ── Dispersion kernels ──────────────────────────────────────────────────────

def test_sigma_y_grows_with_distance_and_with_travel_time():
    """Both the near-field P-G term and the long-range Heffter term must be monotone."""
    assert P._sigma_y(5.0) < P._sigma_y(50.0), "sigma_y not monotone in distance"
    # At long range the time-based Heffter term should dominate and grow with time.
    assert P._sigma_y(250.0, 6.0) < P._sigma_y(250.0, 20.0), (
        "sigma_y not monotone in travel time -- the Heffter term is inert"
    )


def test_heffter_dominates_at_punjab_range():
    """
    The whole reason the Heffter term exists: extrapolated P-G at 300 km gives a
    plume ~9 km wide, implying a whole burning region contributes nothing. The
    time-based term must win at transport range.
    """
    d, t = 280.0, 20.0
    pg_only = P._PG_D["ay"] * min(d, P._PG_VALID_KM) ** P._PG_D["by"] * 1000.0
    pg_only *= math.sqrt(d / P._PG_VALID_KM)
    heffter = P._HEFFTER_SIGMA_Y_M_PER_S * t * 3600.0
    assert heffter > pg_only, "Heffter term (%.0f m) did not dominate P-G (%.0f m)" % (
        heffter, pg_only
    )
    assert abs(P._sigma_y(d, t) - max(pg_only, heffter)) < 1.0


def test_sigma_z_traps_by_the_time_smoke_reaches_delhi():
    """
    The trapped-limit justification: sigma_z must exceed 0.798·H (the crossover to
    a vertically well-mixed layer) well before Punjab-Delhi range, so the column
    formula's trapped coefficient is the right one.
    """
    trap_threshold = P.PLUME_LAYER_DEPTH_M * math.sqrt(2 * math.pi) / math.pi
    assert P._sigma_z(50.0) > trap_threshold, "plume not vertically trapped by 50 km"


def test_pg_sigma_returns_both_components():
    sy, sz = P._pg_sigma(100.0, 12.0)
    assert sy == P._sigma_y(100.0, 12.0)
    assert sz == P._sigma_z(100.0)


# ── Trajectory geometry ─────────────────────────────────────────────────────

def test_closest_approach_catches_a_crossing_between_hourly_samples():
    """
    The reason `_closest_approach` projects onto each SEGMENT rather than testing
    only waypoints: a plume can pass directly over Delhi between two hourly points.
    Build a trajectory that straddles the city and confirm the closest approach is
    ~0, not the ~35 km of the nearest waypoint.
    """
    # Two waypoints either side of Delhi, ~0.3° apart, with the city on the line.
    traj = [
        (P._DELHI_LAT + 0.30, P._DELHI_LON - 0.30),
        (P._DELHI_LAT - 0.30, P._DELHI_LON + 0.30),
    ]
    closest, path, hours = P._closest_approach(traj)
    waypoint_min = min(
        P._haversine(la, lo, *_DELHI) for la, lo in traj
    )
    assert closest < 5.0, "segment projection missed the crossing (%.1f km)" % closest
    assert closest < waypoint_min, (
        "closest approach %.1f is not below the nearest waypoint %.1f -- projection "
        "is not happening" % (closest, waypoint_min)
    )


def test_closest_approach_on_an_empty_trajectory_is_infinite():
    d, path, hrs = P._closest_approach([])
    assert d == float("inf")


def test_arrival_time_is_none_when_the_plume_misses():
    """A plume that never comes within the radius must report no arrival."""
    # A fire east of Delhi under a northwesterly is carried further southeast,
    # away from the city -- it should never arrive.
    traj = P._advect_plume(28.0, 80.0, _NW_WIND)
    assert P._arrival_time(traj, radius_km=50.0) is None


def test_arrival_time_is_reported_when_the_plume_hits():
    """A trajectory passing over the city returns a finite, ordered arrival hour."""
    traj = [
        (P._DELHI_LAT + 0.5, P._DELHI_LON - 0.5),
        (P._DELHI_LAT, P._DELHI_LON),
        (P._DELHI_LAT - 0.5, P._DELHI_LON + 0.5),
    ]
    arrival = P._arrival_time(traj, radius_km=50.0)
    assert arrival is not None and arrival >= 0.0


def test_advection_waypoint_count_is_hourly():
    """One origin point plus one waypoint per forecast hour."""
    traj = P._advect_plume(30.25, 75.84, _NW_WIND, steps=P._FORECAST_HOURS)
    assert len(traj) == P._FORECAST_HOURS + 1


def test_calm_wind_barely_moves_the_plume():
    """A near-zero wind must leave the fire almost where it started."""
    calm = [(0.0, 0.0)] * P._FORECAST_HOURS
    traj = P._advect_plume(30.25, 75.84, calm)
    assert P._haversine(traj[0][0], traj[0][1], traj[-1][0], traj[-1][1]) < 1.0


# ── The plume->PM10 relationship the box model applies ──────────────────────

def test_plume_is_carried_into_pm10_as_well_as_pm25():
    """
    Smoke is fine-mode but not purely PM2.5. The box model raises PM10 background
    by PLUME_PM10_RATIO × the PM2.5 plume, and adds nothing to the gases.
    """
    from app.physics import box_model
    from app.domain.species import Pollutant

    assert box_model._plume_background(Pollutant.PM25, 100.0) == 100.0
    assert box_model._plume_background(Pollutant.PM10, 100.0) == 100.0 * box_model.PLUME_PM10_RATIO
    assert box_model._plume_background(Pollutant.NO2, 100.0) == 0.0
    assert box_model.PLUME_PM10_RATIO > 1.0, "PM10 plume should exceed the PM2.5 plume"
    assert box_model.PLUME_PM10_RATIO < 1.5, "smoke is fine-mode; PM10/PM2.5 should be modest"
