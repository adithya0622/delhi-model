"""Diurnal and seasonal emission profiles.

Two audit findings (AUDIT.md §4.4).

The IST double-offset. Open-Meteo is queried with `timezone=Asia/Kolkata`, so its
timestamps are ALREADY Indian Standard Time. The old code added a further +5:30 on
top, sliding the entire traffic cycle five and a half hours: the morning rush
landed at roughly 02:00 and the overnight minimum at midday. Every diurnal claim
in the dashboard was inverted, and because the shape still *looked* like a diurnal
cycle it was easy to miss.

Species-blind diurnal scaling. A single traffic curve was applied to every
pollutant, which made PM2.5 collapse overnight along with NO2. Real Delhi PM2.5
does not: biomass and refuse burning peak in the evening and persist through the
night, which is why the 04:00 concentration is often near the daily maximum. The
fix splits the profile -- an aerosol curve for PM, a traffic curve for NO2/CO, and
a flat industrial curve for SO2.

The tests below check the SHAPE of the curves against observed Delhi behaviour, so
a reintroduced offset or a collapsed profile fails here rather than in a demo.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.species import Pollutant
from app.physics import box_model
from app.physics.box_model import BoxColumn
from app.services import aqi_service as A


def _curve(pollutant):
    """The 24-hour emission multiplier profile for one species."""
    return [A.emission_scale(h)[pollutant] for h in range(24)]


# ── The IST double-offset ────────────────────────────────────────────────────

def test_rush_hours_are_at_morning_and_evening_not_the_middle_of_the_night():
    """
    The §4.4 regression, stated as directly as possible. If a +5:30 offset is ever
    reapplied, the traffic peak moves into the small hours and this fails.
    """
    traffic = _curve(Pollutant.NO2)
    peak_hour = max(range(24), key=lambda h: traffic[h])

    assert peak_hour in range(7, 22), (
        "traffic peaks at %02d:00 -- that is not a rush hour, which means an IST "
        "offset has been applied on top of already-IST timestamps" % peak_hour
    )
    # Both rush windows must be elevated above the daily mean.
    mean = sum(traffic) / 24.0
    for window, label in (((7, 8, 9, 10), "morning"), ((17, 18, 19, 20, 21), "evening")):
        for h in window:
            assert traffic[h] > mean, (
                "%s rush hour %02d:00 is at or below the daily mean (%.2f vs %.2f)"
                % (label, h, traffic[h], mean)
            )


def test_small_hours_are_the_traffic_minimum():
    """01:00-05:00 must be the quietest part of the day for traffic-linked species."""
    traffic = _curve(Pollutant.NO2)
    trough_hour = min(range(24), key=lambda h: traffic[h])
    assert trough_hour in range(0, 7), (
        "traffic bottoms out at %02d:00, which is not the small hours" % trough_hour
    )
    for h in (1, 2, 3, 4, 5):
        assert traffic[h] < 1.0, "hour %02d is not below the reference level" % h


def test_the_two_rush_peaks_are_separated_by_a_midday_dip():
    """
    Delhi's traffic curve is bimodal. A shifted or smeared curve loses the dip, so
    checking for it catches offsets that happen to preserve one peak.
    """
    traffic = _curve(Pollutant.NO2)
    morning = max(traffic[7:11])
    midday = max(traffic[12:16])
    evening = max(traffic[17:22])
    assert midday < morning and midday < evening, (
        "no midday dip between the rush peaks (morning %.2f, midday %.2f, evening "
        "%.2f)" % (morning, midday, evening)
    )


def test_emission_scale_is_hour_of_day_periodic():
    """Hour 24 is hour 0; negative and out-of-range hours must wrap, not crash."""
    for h in range(24):
        assert A.emission_scale(h) == A.emission_scale(h + 24)
        assert A.emission_scale(h) == A.emission_scale(h + 240)
    assert A.emission_scale(-1) == A.emission_scale(23)
    assert A.emission_scale(25) == A.emission_scale(1)


# ── Species-specific profiles ───────────────────────────────────────────────

def test_pm_does_not_collapse_overnight_like_traffic():
    """
    The second §4.4 bug. Applying the traffic curve to PM2.5 made it fall to 45% of
    reference at 03:00, which contradicts every Delhi observation -- night-time PM2.5
    is typically near the daily peak because biomass burning continues and the
    boundary layer is shallow.
    """
    aerosol = _curve(Pollutant.PM25)
    traffic = _curve(Pollutant.NO2)
    for h in (1, 2, 3, 4, 5):
        assert aerosol[h] > traffic[h], (
            "at %02d:00 PM2.5 emission (%.2f) is not above traffic (%.2f) -- PM is "
            "being scaled by the traffic curve" % (h, aerosol[h], traffic[h])
        )
    # PM must stay within a modest fraction of its reference overnight.
    assert min(aerosol[0:6]) >= 0.7, (
        "PM2.5 emissions fall to %.2f overnight; that is a traffic profile"
        % min(aerosol[0:6])
    )


def test_pm_peaks_in_the_evening_not_the_morning():
    """
    Delhi's PM2.5 emission maximum is the evening (cooking, refuse and biomass
    burning), unlike NO2 which is more symmetric between the two rush periods.
    """
    aerosol = _curve(Pollutant.PM25)
    assert max(aerosol[17:23]) > max(aerosol[7:11]), (
        "PM2.5 evening peak (%.2f) is not above the morning peak (%.2f)"
        % (max(aerosol[17:23]), max(aerosol[7:11]))
    )
    peak_hour = max(range(24), key=lambda h: aerosol[h])
    assert 17 <= peak_hour <= 22, "PM2.5 peaks at %02d:00" % peak_hour


def test_pm25_and_pm10_share_the_aerosol_profile():
    assert _curve(Pollutant.PM25) == _curve(Pollutant.PM10)


def test_no2_and_co_share_the_traffic_profile():
    assert _curve(Pollutant.NO2) == _curve(Pollutant.CO)


def test_pm_and_traffic_profiles_are_actually_different():
    """
    The whole point of the fix. If these ever collapse back to one curve, the
    species-blind bug has returned.
    """
    assert _curve(Pollutant.PM25) != _curve(Pollutant.NO2), (
        "PM and traffic share a single diurnal curve again"
    )


def test_so2_is_flat_because_it_is_industrial():
    """Industry runs on shift patterns, not rush hours."""
    so2 = _curve(Pollutant.SO2)
    assert len(set(so2)) == 1, "SO2 has a diurnal cycle: %s" % sorted(set(so2))
    assert so2[0] == 1.0


def test_every_species_has_a_positive_bounded_multiplier():
    """A zero would switch a species off for that hour; a large value is a typo."""
    for h in range(24):
        scale = A.emission_scale(h)
        for p in box_model.SPECIES:
            assert p in scale, "hour %02d has no multiplier for %s" % (h, p)
            assert 0.1 < scale[p] < 5.0, (
                "%s at %02d:00 has multiplier %s" % (p, h, scale[p])
            )


def test_daily_mean_multiplier_is_near_unity():
    """
    The reference fluxes in `box_model.SPECIES` are daily averages, so a profile
    whose mean is far from 1 silently rescales total emissions -- which would look
    like a calibration problem rather than a profile problem.
    """
    for p in (Pollutant.PM25, Pollutant.NO2, Pollutant.SO2):
        mean = sum(_curve(p)) / 24.0
        assert 0.8 < mean < 1.5, (
            "%s daily-mean multiplier is %.3f, so the profile is rescaling total "
            "emissions" % (p, mean)
        )


# ── Seasonal factors ────────────────────────────────────────────────────────

def test_november_is_the_peak_and_monsoon_is_the_minimum():
    """
    The seasonal shape is the difference between a model that knows Delhi and one
    that does not. November/December is the plateau; July/August is the monsoon
    washout minimum.
    """
    monthly = {m: A.seasonal_factors(m)["pm25"] for m in range(1, 13)}
    peak = max(monthly, key=monthly.get)
    trough = min(monthly, key=monthly.get)
    assert peak in (11, 12), "PM2.5 season peaks in month %d" % peak
    assert trough in (7, 8), "PM2.5 season bottoms in month %d" % trough
    assert monthly[11] > monthly[7] * 2.5, (
        "November (%.2f) is only %.1fx July (%.2f); the seasonal swing is too weak "
        "to be Delhi" % (monthly[11], monthly[11] / monthly[7], monthly[7])
    )


def test_october_rises_sharply_as_the_monsoon_withdraws():
    """The stubble season onset is a step, not a gentle ramp."""
    sep = A.seasonal_factors(9)["pm25"]
    oct_ = A.seasonal_factors(10)["pm25"]
    nov = A.seasonal_factors(11)["pm25"]
    assert oct_ > sep * 1.4, "Sep %.2f -> Oct %.2f is not a sharp rise" % (sep, oct_)
    assert nov >= oct_


def test_pm10_has_a_pre_monsoon_dust_maximum_that_pm25_lacks():
    """
    PM10 carries a large crustal component, so April-June dust gives it a secondary
    maximum. PM2.5 has no such feature. If both curves were identical, the model
    would be missing Delhi's dust season entirely.
    """
    pm10 = {m: A.seasonal_factors(m)["pm10"] for m in range(1, 13)}
    pm25 = {m: A.seasonal_factors(m)["pm25"] for m in range(1, 13)}
    assert pm10[5] > pm10[3], "no pre-monsoon dust rise in PM10 (Mar %.2f, May %.2f)" % (
        pm10[3], pm10[5]
    )
    assert pm25[5] < pm25[3], "PM2.5 should keep falling into May"
    assert pm10 != pm25, "PM10 and PM2.5 share one seasonal curve"


def test_pm10_is_seasonally_flatter_than_pm25():
    pm10 = [A.seasonal_factors(m)["pm10"] for m in range(1, 13)]
    pm25 = [A.seasonal_factors(m)["pm25"] for m in range(1, 13)]
    assert (max(pm10) / min(pm10)) < (max(pm25) / min(pm25)), (
        "PM10 seasonal range (%.2f) is not flatter than PM2.5 (%.2f)"
        % (max(pm10) / min(pm10), max(pm25) / min(pm25))
    )


def test_gas_seasonality_is_damped_and_floored():
    """
    Traffic and industry barely vary month to month; the observed NO2/CO swing is
    mostly dilution, which the box model already supplies. So the gas factor must be
    much flatter than PM and must never fall to the monsoon PM minimum -- that would
    double-count the dilution.
    """
    gas = [A.seasonal_factors(m)["gas"] for m in range(1, 13)]
    pm25 = [A.seasonal_factors(m)["pm25"] for m in range(1, 13)]
    assert min(gas) >= A._SEASON_GAS_FLOOR - 1e-9, (
        "gas factor fell to %.3f, below the floor %.3f" % (min(gas), A._SEASON_GAS_FLOOR)
    )
    assert (max(gas) / min(gas)) < (max(pm25) / min(pm25)), (
        "gas seasonality (%.2fx) is not damped relative to PM2.5 (%.2fx)"
        % (max(gas) / min(gas), max(pm25) / min(pm25))
    )
    assert max(gas) <= 1.0 + 1e-9


def test_seasonal_factors_are_bounded_and_defined_for_every_month():
    for m in range(1, 13):
        f = A.seasonal_factors(m)
        for key in ("pm25", "pm10", "gas"):
            assert key in f, "month %d missing %s" % (m, key)
            assert 0.2 <= f[key] <= 1.0, "month %d %s = %s" % (m, key, f[key])


def test_an_invalid_month_falls_back_instead_of_raising():
    """A bad month from a malformed timestamp must degrade, not 500 the endpoint."""
    for bad in (0, 13, 99, -1):
        f = A.seasonal_factors(bad)
        for key in ("pm25", "pm10", "gas"):
            assert 0.2 <= f[key] <= 1.0, "month %s %s = %s" % (bad, key, f[key])


# ── The two profiles composed: the seasonal claim end to end ────────────────

def test_november_runs_dirtier_than_august_at_identical_meteorology():
    """
    The headline seasonal claim, isolated. Hold the mixing depth, wind and hour
    fixed and change only the month: November must come out substantially dirtier.
    Because meteorology is pinned, the entire difference is the seasonal emission and
    background scaling, which is what makes this a test of the profile rather than of
    the weather.
    """
    results = {}
    for month in (8, 11):
        season = A.seasonal_factors(month)
        col = BoxColumn.at_background(400.0, season)
        for h in range(24):
            conc = box_model.step(
                col, 400.0, 3600.0, A.emission_scale(h), 1.5, season, 0.0
            )
        results[month] = conc[Pollutant.PM25]

    assert results[11] > results[8] * 1.8, (
        "November PM2.5 %.1f is only %.2fx August's %.1f at identical meteorology"
        % (results[11], results[11] / results[8], results[8])
    )


def test_the_overnight_pm_plateau_is_reproduced():
    """
    The observable the species-blind profile got wrong. Run a full day under a
    realistic diurnal PBL cycle and check that PM2.5 in the small hours stays high
    rather than collapsing -- the flat-topped overnight plateau that Delhi actually
    shows.
    """
    season = A.seasonal_factors(11)
    # A crude but realistic November PBL cycle: shallow at night, ~1200 m at midday.
    pbl_by_hour = [
        200, 190, 180, 175, 175, 190, 250, 400, 600, 850, 1050, 1180,
        1250, 1250, 1180, 1000, 750, 500, 350, 280, 250, 230, 215, 205,
    ]
    col = BoxColumn.at_background(200.0, season)
    for _ in range(2):        # two-day spin-up so hour 0 is not a cold start
        series = []
        for h in range(24):
            conc = box_model.step(
                col, float(pbl_by_hour[h]), 3600.0,
                A.emission_scale(h), 1.2, season, 0.0
            )
            series.append(conc[Pollutant.PM25])

    night = series[0:6]
    afternoon = series[12:16]
    assert min(night) > max(afternoon), (
        "night-time PM2.5 (min %.1f) is not above the afternoon minimum (max %.1f) "
        "-- the overnight plateau is missing" % (min(night), max(afternoon))
    )
    # And the plateau must be flat-ish, not a spike.
    assert max(night) / min(night) < 2.0, (
        "the overnight PM2.5 'plateau' varies %.2fx" % (max(night) / min(night))
    )
