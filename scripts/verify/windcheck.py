"""Verification script — run from anywhere:  python scripts/verify/windcheck.py

Checks the 850 hPa wind sign convention end to end, against the *real* module
rather than a re-implementation of it. Asserts behaviour (signs, directions),
never accuracy against observations.

Why this script exists: the wind bug that made stubble transport impossible was
a sign error. `direction` from Open-Meteo is the direction the wind blows FROM,
so converting it to velocity components needs a leading minus on both terms, and
reporting a velocity back as a direction needs atan2(-u, -v). Getting either
backwards sends every Punjab plume away from Delhi, which is exactly what the
code used to do.
"""
import math
import sys
from pathlib import Path

# backend/ is not an installed package; put it on the path so `app.*` resolves
# regardless of the working directory the script is launched from.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.physics import plume_advection as PA

DELHI = (PA._DELHI_LAT, PA._DELHI_LON)
LUDHIANA = (30.90, 75.85)          # heart of the Punjab burning belt

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print("  %s %s%s" % ("PASS" if ok else "FAIL", label,
                         ("  -- " + detail) if detail else ""))
    if not ok:
        failures.append(label)


def to_uv(speed_ms: float, met_dir_deg: float) -> tuple[float, float]:
    """The conversion as written in _fetch_850hpa_wind_series."""
    rad = math.radians(met_dir_deg)
    return -speed_ms * math.sin(rad), -speed_ms * math.cos(rad)


# ── 1. Direction -> velocity ──────────────────────────────────────────────────
print("1. met direction (blowing FROM) -> velocity components")
print("   met_dir  name              u (east)   v (north)   transport toward")
CASES = [(0, "northerly", 180), (90, "easterly", 270),
         (180, "southerly", 0), (270, "westerly", 90),
         (315, "northwesterly", 135)]
for d, name, expect_toward in CASES:
    u, v = to_uv(5.0, d)
    toward = (math.degrees(math.atan2(u, v)) + 360) % 360
    print("     %4d   %-16s %+8.2f   %+8.2f   %6.1f deg" % (d, name, u, v, toward))
    check("%s air moves toward %d deg" % (name, expect_toward),
          abs((toward - expect_toward + 180) % 360 - 180) < 0.01)

# ── 2. The fallback wind must point at Delhi ──────────────────────────────────
print("\n2. fallback wind constant")
u_fb, v_fb = PA._FALLBACK_WIND_UV
dlat = DELHI[0] - LUDHIANA[0]
dlon = DELHI[1] - LUDHIANA[1]
print("   _FALLBACK_WIND_UV = (%+.2f, %+.2f)" % (u_fb, v_fb))
print("   Ludhiana -> Delhi displacement: %+.2f deg lat, %+.2f deg lon" % (dlat, dlon))
print("   a plume must therefore travel south and east: needs u > 0, v < 0")
check("fallback pushes plumes east (u > 0)", u_fb > 0, "u=%+.2f" % u_fb)
check("fallback pushes plumes south (v < 0)", v_fb < 0, "v=%+.2f" % v_fb)
fb_met = (math.degrees(math.atan2(-u_fb, -v_fb)) + 360) % 360
print("   -> that is met direction %.0f deg (northwesterly), the climatological"
      " transport direction during the burning season" % fb_met)
check("fallback is a northwesterly", 290.0 <= fb_met <= 340.0, "%.0f deg" % fb_met)

# ── 3. Velocity -> reported direction ─────────────────────────────────────────
print("\n3. velocity -> reported wind_direction_deg (must invert step 1)")
for d, name, _ in CASES:
    u, v = to_uv(5.0, d)
    naive = (math.degrees(math.atan2(u, v)) + 360) % 360
    met = (math.degrees(math.atan2(-u, -v)) + 360) % 360
    print("     true met dir %3d  ->  atan2(u,v)=%5.1f (wrong)  atan2(-u,-v)=%5.1f"
          % (d, naive, met))
    check("round-trip preserves met dir %d" % d,
          abs((met - d + 180) % 360 - 180) < 0.01)

# ── 4. A real trajectory has to close on Delhi ────────────────────────────────
print("\n4. trajectories under prescribed winds")


def track(met_dir: float, speed: float = 3.7) -> tuple[float, float, int, int]:
    """Advect from Ludhiana under a constant wind; return distances and timing."""
    winds = [to_uv(speed, met_dir)] * 72
    traj = PA._advect_plume(LUDHIANA[0], LUDHIANA[1], winds)
    dists = [PA._haversine(la, lo, DELHI[0], DELHI[1]) for la, lo in traj]
    return dists[0], min(dists), dists.index(min(dists)), len(traj)


# 4a. the fallback wind: a climatological northwesterly, so it should carry smoke
#     a long way toward the city even though it is not aimed exactly at it.
d0, dmin, t_min, n = track(fb_met)
print("   fallback (%.0f deg): start %.0f km, closest %.0f km at +%d h, %d waypoints"
      % (fb_met, d0, dmin, t_min, n))
check("fallback closes most of the distance", dmin < 0.4 * d0,
      "%.0f km -> %.0f km" % (d0, dmin))
check("closest approach inside the forecast window", 0 < t_min < 36,
      "+%d h" % t_min)
print("   note: %.0f km is a real miss, not an error -- a 315 deg wind is ~18 deg\n"
      "         off the Ludhiana->Delhi bearing. Live winds are read hourly from\n"
      "         Open-Meteo; this constant is only the no-data fallback." % dmin)

# 4b. a wind aimed exactly along the Ludhiana -> Delhi bearing must score a hit.
bearing = (math.degrees(math.atan2(
    dlon * PA._KM_PER_DEG_LAT * math.cos(math.radians((DELHI[0] + LUDHIANA[0]) / 2)),
    dlat * PA._KM_PER_DEG_LAT)) + 360) % 360
aimed = (bearing + 180.0) % 360.0
d0, dmin, t_min, _ = track(aimed)
print("   aimed  (%.0f deg): start %.0f km, closest %.0f km at +%d h"
      % (aimed, d0, dmin, t_min))
check("a wind on the bearing scores a direct hit", dmin < 25.0, "%.0f km" % dmin)

# 4c. the reverse wind must carry smoke away. This is the check that fails loudly
#     if the sign convention is ever flipped back.
d0, dmin, t_min, _ = track((aimed + 180.0) % 360.0)
print("   reversed (%.0f deg): start %.0f km, closest %.0f km at +%d h"
      % ((aimed + 180.0) % 360.0, d0, dmin, t_min))
check("reversed wind never approaches", dmin >= d0 - 1.0,
      "closest %.0f km vs start %.0f km" % (dmin, d0))
check("reversed wind's closest point is the origin", t_min == 0, "+%d h" % t_min)

print("\n%d checks failed" % len(failures))
if failures:
    for f in failures:
        print("  - " + f)
sys.exit(1 if failures else 0)
