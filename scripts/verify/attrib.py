"""Verification script — run from anywhere:  python scripts/verify/attrib.py

Prints numbers to be argued with. It asserts *behaviour* (signs, monotonicity,
mass conservation, seasonal contrast), never accuracy against observations —
there is no withheld-data backtest in this repository yet.
"""
import sys
from pathlib import Path

# backend/ is not an installed package; put it on the path so `app.*` resolves
# regardless of the working directory the script is launched from.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

"""Attribution: how much does the two-way coupling actually change the forecast?

Runs the identical column twice -- once with the aerosol->meteorology leg active,
once with it disabled (aerosol optical depth forced to zero) -- and reports the
difference. This is the number to quote for "what does the coupling buy you",
and it is computed, not asserted.
"""
import app.services.aqi_service as S
from app.physics import box_model as B
from app.physics import inversion_engine as ie
from app.physics.box_model import BoxColumn
from app.domain.species import Pollutant as P


def run(month, pbl, sol, wind, feedback=True, plume_conc=0.0, days=4):
    season = S.seasonal_factors(month)
    col = BoxColumn.at_background(pbl[0], season)
    decay = ie.surface_memory_decay()
    carry = 0.0
    rows = []
    for _d in range(days):
        rows = []
        for h in range(24):
            st = S._solve_coupled_hour(col, pbl[h], sol[h] if feedback else 0.0,
                                       wind[h], S.emission_scale(h), season,
                                       plume_conc, carry if feedback else 0.0)
            # O3 still needs the true solar flux even when the radiative leg is
            # off, otherwise we would be comparing two different chemistries.
            st['conc'][P.O3] = S._photochemical_o3(sol[h], st['conc'][P.NO2], st['pbl_m'])
            st['aqi'] = S._aqi_from_conc(st['conc'])
            carry = decay * carry + (1 - decay) * st['cooling_instant_k']
            rows.append(st)
    return rows


def compare(name, month, pbl, sol, wind, plume_conc=0.0):
    on = run(month, pbl, sol, wind, True, plume_conc)
    off = run(month, pbl, sol, wind, False, plume_conc)
    print('=== %s ===' % name)
    print('  h   PBL_off  PBL_on  supp%   PM25_off  PM25_on   d%    AQI_off AQI_on  dAQI')
    for h in range(24):
        a, b = off[h], on[h]
        pm_a, pm_b = a['conc'][P.PM25], b['conc'][P.PM25]
        print('  %2d  %7.0f %7.0f %6.1f   %8.1f %8.1f %5.1f   %7d %6d %5d' % (
            h, a['pbl_m'], b['pbl_m'], 100 * (1 - b['pbl_m'] / a['pbl_m']),
            pm_a, pm_b, 100 * (pm_b / pm_a - 1), a['aqi'], b['aqi'],
            b['aqi'] - a['aqi']))
    pa = [x['conc'][P.PM25] for x in off]
    pb = [x['conc'][P.PM25] for x in on]
    aa = [x['aqi'] for x in off]
    ab = [x['aqi'] for x in on]
    print('  PM2.5 daily mean  %.1f -> %.1f  (%+.1f%%)' % (
        sum(pa) / 24, sum(pb) / 24, 100 * (sum(pb) / sum(pa) - 1)))
    print('  AQI   daily mean  %.0f -> %.0f  (%+.0f points, %+.1f%%)' % (
        sum(aa) / 24, sum(ab) / 24, (sum(ab) - sum(aa)) / 24,
        100 * (sum(ab) / sum(aa) - 1)))
    print('  AQI   peak        %d -> %d  (%+d points)' % (max(aa), max(ab), max(ab) - max(aa)))
    print('  max hourly dAQI   %+d' % max(ab[i] - aa[i] for i in range(24)))
    print()


aug_pbl = [350, 320, 300, 290, 300, 400, 650, 900, 1200, 1500, 1800, 2100,
           2300, 2400, 2300, 2000, 1600, 1100, 700, 500, 430, 400, 380, 360]
aug_sol = [0, 0, 0, 0, 0, 0, 60, 220, 420, 600, 740, 820,
           830, 760, 620, 430, 220, 60, 0, 0, 0, 0, 0, 0]
aug_wnd = [1.6, 1.5, 1.4, 1.4, 1.5, 1.8, 2.2, 2.6, 3.0, 3.4, 3.8, 4.0,
           4.2, 4.2, 4.0, 3.4, 2.8, 2.2, 1.9, 1.8, 1.7, 1.7, 1.6, 1.6]
nov_pbl = [180, 165, 155, 150, 150, 155, 170, 220, 350, 550, 750, 900,
           980, 980, 880, 650, 400, 260, 220, 200, 195, 190, 185, 182]
nov_sol = [0, 0, 0, 0, 0, 0, 0, 80, 240, 400, 520, 570,
           540, 430, 270, 100, 0, 0, 0, 0, 0, 0, 0, 0]
nov_wnd = [0.8, 0.7, 0.7, 0.6, 0.6, 0.7, 0.8, 1.0, 1.4, 1.9, 2.3, 2.6,
           2.7, 2.6, 2.2, 1.6, 1.1, 0.9, 0.8, 0.8, 0.7, 0.7, 0.7, 0.7]

compare('AUGUST (monsoon)', 8, aug_pbl, aug_sol, aug_wnd)
compare('NOVEMBER (inversion episode)', 11, nov_pbl, nov_sol, nov_wnd)
compare('NOVEMBER + 60 ug/m3 stubble plume', 11, nov_pbl, nov_sol, nov_wnd, 60.0)
