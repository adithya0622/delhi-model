"""Verification script — run from anywhere:  python scripts/verify/calib.py

Prints numbers to be argued with. It asserts *behaviour* (signs, monotonicity,
mass conservation, seasonal contrast), never accuracy against observations —
there is no withheld-data backtest in this repository yet.
"""
import sys
from pathlib import Path

# backend/ is not an installed package; put it on the path so `app.*` resolves
# regardless of the working directory the script is launched from.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import app.services.aqi_service as S
from app.physics import inversion_engine as ie
from app.physics.box_model import BoxColumn
from app.domain.species import Pollutant as P


def sim(name, month, pbl, sol, wind, plume_conc=0.0, days=4, show=True):
    season = S.seasonal_factors(month)
    col = BoxColumn.at_background(pbl[0], season)
    decay = ie.surface_memory_decay()
    carry = 0.0
    rows = []
    for _d in range(days):          # repeat the day to reach a periodic state
        rows = []
        for h in range(24):
            st = S._solve_coupled_hour(col, pbl[h], sol[h], wind[h],
                                       S.emission_scale(h), season,
                                       plume_conc, carry)
            st['aqi'] = S._aqi_from_conc(st['conc'])
            carry = decay * carry + (1 - decay) * st['cooling_instant_k']
            rows.append((h, st))
    if show:
        print('=== %s ===' % name)
        print('  h  PBLmet PBLfb supp%   AOD    dT   PM2.5   PM10    NO2    O3    CO   AQI  it')
        for h, st in rows:
            c = st['conc']
            supp = 100 * (1 - st['pbl_m'] / st['pbl_observed_m'])
            print('  %2d %6.0f%6.0f%6.1f%7.3f%6.2f%8.1f%7.1f%7.1f%6.1f%6.2f%6d%4d' % (
                h, st['pbl_observed_m'], st['pbl_m'], supp, st['aod'],
                st['dt_surface_c'], c[P.PM25], c[P.PM10], c[P.NO2],
                c[P.O3], c[P.CO], st['aqi'], st['iterations']))
    pm = [st['conc'][P.PM25] for _, st in rows]
    a = [st['aqi'] for _, st in rows]
    print('  --> PM2.5 min %.0f mean %.0f max %.0f | AQI min %d mean %.0f max %d' % (
        min(pm), sum(pm) / 24, max(pm), min(a), sum(a) / 24, max(a)))
    print()
    return rows


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

print('TARGETS (CPCB Delhi climatology):')
print('  Aug: PM2.5 diurnal ~20-55, mean ~35   | AQI mean ~85-100')
print('  Nov: PM2.5 diurnal ~110-330, mean ~190 | AQI mean ~350-400')
print()
sim('AUGUST (monsoon)', 8, aug_pbl, aug_sol, aug_wnd)
sim('NOVEMBER (inversion episode)', 11, nov_pbl, nov_sol, nov_wnd)
sim('NOVEMBER + 60ug/m3 stubble plume', 11, nov_pbl, nov_sol, nov_wnd,
    plume_conc=60.0, show=False)
