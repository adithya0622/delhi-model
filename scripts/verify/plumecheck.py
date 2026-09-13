"""Verification script — run from anywhere:  python scripts/verify/plumecheck.py

Prints numbers to be argued with. It asserts *behaviour* (signs, monotonicity,
mass conservation, seasonal contrast), never accuracy against observations —
there is no withheld-data backtest in this repository yet.
"""
import sys
from pathlib import Path

# backend/ is not an installed package; put it on the path so `app.*` resolves
# regardless of the working directory the script is launched from.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

"""Numerical verification of the rewritten plume transport module.

Checks the things that were silently broken before: emission magnitude,
direction-awareness, FIRMS CSV parsing, and state labelling. Every number
printed is computed, not asserted in a docstring.
"""
import math

from app.physics import plume_advection as PA

FAIL = []


def check(label, cond, detail=""):
    tag = "PASS" if cond else "FAIL"
    if not cond:
        FAIL.append(label)
    print("  [%s] %s %s" % (tag, label, detail))


print("=" * 72)
print("1. FRP -> PM2.5 emission chain")
print("=" * 72)
print("  ug PM2.5 per second per MW FRP = %.3e" % PA._PM25_UG_S_PER_MW)
print("  ( = %.2f g/s per MW )" % (PA._PM25_UG_S_PER_MW / 1e6))
check("emission rate is ~3 g/s/MW, not 50 ug/s",
      2e6 < PA._PM25_UG_S_PER_MW < 5e6)
# Total PM2.5 for a realistic peak Punjab burning day.
peak_frp_mw = 20000.0
kg_per_day = peak_frp_mw * PA._PM25_UG_S_PER_MW * 86400 / 1e9
print("  20,000 MW aggregate FRP => %.0f tonnes PM2.5/day" % (kg_per_day / 1000))
check("peak-day emission is 1000-20000 t/day (published: few 1000s)",
      1000 < kg_per_day / 1000 < 20000)

print()
print("=" * 72)
print("2. Dispersion: sigma_y growth, near-field P-G vs long-range Heffter")
print("=" * 72)
print("   dist_km   t_hours   sigma_y_m   governing")
for d, t in [(1, 0.06), (5, 0.3), (20, 1.2), (50, 3.0), (150, 9.0), (300, 18.0),
             (450, 27.0)]:
    sy = PA._sigma_y(d, t)
    heff = PA._HEFFTER_SIGMA_Y_M_PER_S * t * 3600
    gov = "Heffter (time)" if abs(sy - heff) < 1 else "Pasquill-Gifford"
    print("  %8.0f %9.1f %11.0f   %s" % (d, t, sy, gov))
check("sigma_y at 300 km / 18 h is 20-60 km (observed regional plume width)",
      20000 < PA._sigma_y(300, 18.0) < 60000, "%.0f m" % PA._sigma_y(300, 18.0))
check("sigma_y is monotonic in travel time",
      PA._sigma_y(300, 9.0) < PA._sigma_y(300, 18.0))
check("near field still uses P-G, not Heffter",
      abs(PA._sigma_y(1, 0.06) - 220) < 20, "%.0f m" % PA._sigma_y(1, 0.06))

print()
print("=" * 72)
print("3. Direction-awareness: the headline bug")
print("=" * 72)
# Amritsar is ~375 km NW of Delhi. Build the exact bearing that carries a plume
# from there to Delhi, then compare it against the reverse and a crosswise flow.
fire_lat, fire_lon = 31.3, 74.9
_fx, _fy = PA._to_local_km(fire_lat, fire_lon, PA._DELHI_LAT)
_dx, _dy = PA._to_local_km(PA._DELHI_LAT, PA._DELHI_LON, PA._DELHI_LAT)
_mag = math.hypot(_dx - _fx, _dy - _fy)
SPEED = 7.2
_ux, _uy = SPEED * (_dx - _fx) / _mag, SPEED * (_dy - _fy) / _mag
toward = [(_ux, _uy)] * 72
away = [(-_ux, -_uy)] * 72
crosswise = [(-_uy, _ux)] * 72   # rotated 90 degrees

print("  fire at (%.1f, %.1f), %.0f km from Delhi; wind speed %.1f m/s"
      % (fire_lat, fire_lon, _mag, SPEED))
loads = {}
for name, wind in [("toward Delhi", toward), ("away from Delhi", away),
                   ("perpendicular", crosswise)]:
    traj = PA._advect_plume(fire_lat, fire_lon, wind)
    closest, path, hrs = PA._closest_approach(traj)
    load = PA.plume_column_loading(60.0, path, closest, SPEED, hrs)
    loads[name] = load
    print("  %-16s closest %7.1f km  path %7.1f km  t %5.1f h  loading %10.1f ug/m2"
          % (name, closest, path, hrs, load))

check("plume aimed at Delhi delivers a real loading", loads["toward Delhi"] > 10.0)
check("plume blowing AWAY delivers essentially nothing",
      loads["away from Delhi"] < 0.01 * loads["toward Delhi"])
check("perpendicular flow also suppressed",
      loads["perpendicular"] < 0.01 * loads["toward Delhi"])
print("  (old code used straight-line distance only: all three would have been"
      " identical)")

print()
print("=" * 72)
print("4. Closest approach is segment-aware, not waypoint-only")
print("=" * 72)
# A fast plume that passes over Delhi BETWEEN two hourly samples.
fast = [(0.0, -20.0)] * 72   # 20 m/s due south = 72 km/h, straight down 77.209E
traj = PA._advect_plume(28.6139 + 6.0, 77.2090, fast)
dist, path, hrs = PA._closest_approach(traj)
waypoint_min = min(PA._haversine(la, lo, PA._DELHI_LAT, PA._DELHI_LON)
                   for la, lo in traj)
print("  segment-aware closest : %.2f km at t=%.2f h" % (dist, hrs))
print("  waypoint-only closest : %.2f km" % waypoint_min)
check("segment search finds a closer approach than waypoints alone",
      dist <= waypoint_min + 1e-6)
check("a plume passing overhead registers as a hit", dist < 40.0)
old_6h = PA._advect_plume(28.6139 + 6.0, 77.2090, fast, steps=12, dt_hours=6.0)
old_min = min(PA._haversine(la, lo, PA._DELHI_LAT, PA._DELHI_LON)
              for la, lo in old_6h)
print("  (old 6-hourly waypoints would have seen %.0f km -> a miss)" % old_min)

print()
print("=" * 72)
print("5. FIRMS CSV parsing by header name")
print("=" * 72)
# Real VIIRS_SNPP_NRT header. Note column index 8 is 'instrument' -- the old
# code read that as FRP, so float('VIIRS') raised on every single row.
viirs = (
    "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,"
    "instrument,confidence,version,bright_ti5,frp,daynight\n"
    "30.5123,75.4321,332.1,0.42,0.38,2026-08-22,0630,N,VIIRS,n,2.0NRT,289.4,12.7,D\n"
    "29.8000,76.9000,350.0,0.40,0.36,2026-08-22,0632,N,VIIRS,h,2.0NRT,295.0,44.2,D\n"
    "30.1000,75.0000,310.0,0.40,0.36,2026-08-22,0634,N,VIIRS,l,2.0NRT,280.0,3.1,D\n"
    "12.0000,60.0000,310.0,0.40,0.36,2026-08-22,0636,N,VIIRS,h,2.0NRT,280.0,9.9,D\n"
)
parsed = PA._parse_firms_csv(viirs)
for p in parsed:
    print("  %-16s lat %.4f lon %.4f frp %6.2f MW conf %s"
          % (p["source_state"], p["lat"], p["lon"], p["frp_mw"], p["confidence"]))
check("parses VIIRS rows at all (old code parsed zero)", len(parsed) > 0)
check("FRP read from the 'frp' column, not 'instrument'",
      any(abs(p["frp_mw"] - 12.7) < 1e-6 for p in parsed))
check("low-confidence detection dropped",
      all(p["confidence"][:1].lower() != "l" for p in parsed))
check("out-of-region detection dropped",
      all(p["lat"] > 20 for p in parsed))
check("timestamp parsed from acq_date/acq_time",
      any(p["detected_at"].startswith("2026-08-22T06:30") for p in parsed))
# MODIS has a different layout; header-name parsing should still work.
modis = (
    "latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,"
    "instrument,confidence,version,bright_t31,frp,daynight\n"
    "30.2000,75.8000,330.0,1.0,1.0,2026-08-22,0700,Terra,MODIS,85,6.1NRT,290.0,22.5,D\n"
)
check("MODIS layout also parses", len(PA._parse_firms_csv(modis)) == 1)
check("malformed header refuses rather than guessing indices",
      PA._parse_firms_csv("a,b,c\n1,2,3\n") == [])

print()
print("=" * 72)
print("6. State labelling")
print("=" * 72)
cases = [
    (30.9, 75.8, "Punjab"),      # Ludhiana
    (31.6, 74.9, "Punjab"),      # Amritsar
    (29.4, 76.9, "Haryana"),     # Karnal-ish
    (28.9, 76.6, "Haryana"),     # Rohtak
    (28.0, 74.0, "Rajasthan"),   # Sikar — old code called this Punjab
    (29.0, 73.9, "Rajasthan"),   # Sri Ganganagar — old code called this Punjab
    (28.9, 77.6, "Uttar Pradesh"),
]
for lat, lon, expect in cases:
    got = PA._state_from_coords(lat, lon)
    check("(%.1f,%.1f) -> %s" % (lat, lon, expect), got == expect, "got %s" % got)
print("  old logic on Sri Ganganagar (29.0,73.9): lon<75.5 -> 'Punjab'  [wrong]")

print()
print("=" * 72)
print("7. Aggregate magnitude on synthetic burning days")
print("=" * 72)
import random

# VIIRS detects roughly 3,000-7,000 fires/day across Punjab+Haryana at the peak
# of the paddy-residue window, and a few hundred on a quiet day. Mean per-pixel
# FRP for crop residue is ~15-25 MW.
# Northwesterly flow: wind FROM the northwest, so air travels southeast toward
# Delhi -- u positive (east), v negative (south).
wind = [PA._FALLBACK_WIND_UV] * 72
speed = math.hypot(*wind[0])
print("  transport wind (u,v) = (%+.2f, %+.2f) m/s, |V| = %.1f m/s, toward %.0f deg"
      % (wind[0][0], wind[0][1], speed,
         (math.degrees(math.atan2(wind[0][0], wind[0][1])) + 360) % 360))


def scenario(label, n_fires, mean_frp):
    random.seed(7)
    total_layer = 0.0
    arriving = 0
    for _ in range(n_fires):
        la = random.uniform(29.6, 31.6)
        lo = random.uniform(74.2, 76.6)
        frp = random.gauss(mean_frp, mean_frp * 0.5)
        if frp <= 1:
            continue
        traj = PA._advect_plume(la, lo, wind)
        c, p, h = PA._closest_approach(traj)
        load = PA.plume_column_loading(frp, p, c, speed, h)
        if load > 0.1:
            arriving += 1
        total_layer += load / PA.PLUME_LAYER_DEPTH_M
    print("  %-28s %5d fires, %4.0f MW mean -> %3d contributing, %6.1f ug/m3"
          % (label, n_fires, mean_frp, arriving, total_layer))
    return total_layer


quiet = scenario("quiet day", 300, 15.0)
moderate = scenario("moderate day", 1500, 18.0)
peak = scenario("peak burning day", 4000, 20.0)

check("peak day gives 60-300 ug/m3 (apportionment: 20-40% of a 300-500 AQI day)",
      60 < peak < 300, "%.1f ug/m3" % peak)
check("quiet day contributes a modest amount", 1 < quiet < 40,
      "%.1f ug/m3" % quiet)
check("contribution scales with fire count", quiet < moderate < peak)

print()
print("=" * 72)
if FAIL:
    print("FAILURES (%d): %s" % (len(FAIL), "; ".join(FAIL)))
else:
    print("All checks passed.")
print("=" * 72)
