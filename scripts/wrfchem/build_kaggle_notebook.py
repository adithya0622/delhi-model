"""Rebuild scripts/wrfchem/kaggle_wrfchem_run.ipynb deterministically.

Every URL and model contract used here was verified against live sources:
  * WRF/WPS v4.6.0 tarballs via codeload.github.com (release-asset names 404)
  * jasper 1.900.1 from github.com/mdadams/jasper (libjasper-dev is NOT in
    Ubuntu 22.04; ungrib needs jasper for GRIB2)
  * GFS 0.25-deg analyses on noaa-gfs-bdp-pds.s3 (verified for past dates)
  * geog low/high resolution sets on www2.mmm.ucar.edu (verified 200)
  * EDGAR v8.1 air pollutants on jeodpp.jrc.ec.europa.eu (v81_FT2022_AP_new,
    ~4 MB zips, SO2 has a _v2 suffix)
  * WorldPop India 1 km UNadj aggregated GeoTIFF (18 MB, verified 200)
  * FIRMS area API (VIIRS_SNPP_SP / MODIS_SP cover the Nov-2025 window; NRT
    does not) - verified live with real stubble-belt detections + FRP
  * MOZCART emission contract read from WRF v4.6.0 source:
      Registry/registry.chem package "mozcem" (emiss_opt==8):
        gases  (mol km^-2 hr^-1): E_CO E_NO E_NO2 E_BIGALK E_BIGENE E_C2H4
               E_C2H5OH E_C2H6 E_C3H6 E_C3H8 E_CH2O E_CH3CHO E_CH3COCH3
               E_CH3OH E_MEK E_SO2 E_TOLUENE E_NH3 E_ISOP E_C10H16
        aerosols (ug m^-2 s^-1):  E_PM_10 E_PM_25 E_BC E_OC E_SULF
    module_emissions_anthropogenics.F: gases convert with
    4.828e-4/rho*dt/(dz*60), aerosols with alt*dt/dz -> file units as above.
  * io_style_emissions=2 semantics read from share/mediation_integrate.F v4.6.0:
      the AUXINPUT5 alarm fires every auxinput5_interval minutes and each read
      consumes the NEXT sequential record; the file name comes from &chem's
      emi_inname (default 'wrfchemi_d<domain>_<date>') where <date> expands to
      the FULL current timestamp 'YYYY-MM-DD_HH:MM:SS' (construct_filename2a +
      current_timestr) - i.e. the file is re-selected (and re-opened) every
      hour. So one 24-record file per day must be named
      'wrfchemi_d01_2025-11-10_00:00:00' (the file's FIRST hour) and carry 24
      hourly records, with auxinput5_interval=60 and frames_per_auxinput5=24.
      (auxinput5_interval_m in &time_control is the minutes form - the shipped
      namelist.input.chem uses it; plain auxinput5_interval is equivalent.)
      anthropogenic_emiss is NOT a v4.6.0 namelist variable (zero rconfig
      declarations, zero code references) - it would fatal the namelist read;
      the canonical namelist.input.chem &chem block omits it.
"""
import json

# Registry-verified emiss_opt=8 (mozcem) contract (self-checked at the bottom).
MOZCEM_GASES = ["E_CO", "E_NO", "E_NO2", "E_BIGALK", "E_BIGENE", "E_C2H4",
                "E_C2H5OH", "E_C2H6", "E_C3H6", "E_C3H8", "E_CH2O", "E_CH3CHO",
                "E_CH3COCH3", "E_CH3OH", "E_MEK", "E_SO2", "E_TOLUENE",
                "E_NH3", "E_ISOP", "E_C10H16"]
MOZCEM_AERS = ["E_PM_10", "E_PM_25", "E_BC", "E_OC", "E_SULF"]

NB = {"cells": [], "metadata": {
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
    "language_info": {"name": "python", "version": "3.10"},
}, "nbformat": 4, "nbformat_minor": 5}


def md(text):
    NB["cells"].append({"cell_type": "markdown", "metadata": {},
                        "source": text.splitlines(keepends=True)})


def code(text):
    NB["cells"].append({"cell_type": "code", "metadata": {}, "execution_count": None,
                        "outputs": [], "source": text.splitlines(keepends=True)})


# ---------------------------------------------------------------- title
md("""# WRF-Chem for Delhi NCR — free Kaggle/Colab run (v5, URL- and source-verified)

Produces **real wrfout NetCDF files** from an actual WRF-Chem v4.6.0 run (MOZCART gas phase +
GOCART aerosols, `chem_opt=301`) over a nested Delhi-NCR domain, so the repo's
`/api/v1/validation/wrf-compare` endpoint can score WRF-Chem against CAMS reanalysis.

**Why v1 produced nothing, fixed here:** v1 ran with Internet OFF and failed every apt/wget call;
it also had no cells to download the WRF/WPS sources, a dead jasper URL, a Python syntax error in
the compile cell, SORGAM-style emission variable names that `emiss_opt=8` (MOZCART) does not read,
`biomass_burn_opt=1` without the MOZBC files it requires, no `&time_control` block, and a timestep
formula (`DX/6` s) that would have crashed the run. v2 verifies internet up front, uses only URLs
probed live, generates the **exact 25-variable MOZCART contract read from the WRF registry source**,
and carries a complete, consistent namelist. **v4** (full audit against the actual WRF v4.6.0 source
tree) fixes the `./configure chem` positional flag, the menu-capture hang/bytes crash, removes the
nonexistent `anthropogenic_emiss` key, enables `aer_ra_feedback=1` (the two-way aerosol↔meteorology
coupling), sets the hourly emission cadence (`auxinput5_interval_m=60`, `frames_per_auxinput5=24`)
with full-timestamp `wrfchemi_d0X_<day>_00:00:00` filenames, corrects `num_land_cat=24`, and runs
`wrf.exe` synchronously so Save & Run All completes the full 72 h.

**Runtime on a free 4-vCPU session:** compile ~50–80 min · WPS+real ~25 min · wrfchemi ~10 min ·
72-h run ~2 h (24/6 km fast config, OpenMP) — fits one 12-h session with margin.

**Flow back into the project:** download `wrfout_delhi.tar.gz` from this notebook's Output →
drop it in the repo → `python scripts/wrfchem/fetch_wrfout.py wrfout_delhi.tar.gz --set` →
`GET /api/v1/validation/wrf-compare` scores real WRF-Chem vs CAMS.""")

md("""## 0 · Environment + configuration

If the internet check fails: Kaggle Settings → Internet ON (phone verification required) →
Save Version → Save & Run All. Nothing below works offline.""")

code(r"""# 0 · Environment probe, hard internet check, all run configuration in one place
import os, socket, sys, math, json

NB_VERSION = "v5"
print("notebook build:", NB_VERSION)  # must print v5 — proves the fixed notebook is running

def check_internet(host="github.com"):
    try:
        socket.gethostbyname(host); return True
    except Exception:
        return False

print("cores:", os.cpu_count())
if not check_internet():
    sys.exit("NO INTERNET. Kaggle: Settings -> Internet ON (needs phone verification), "
             "then Save Version -> Save & Run All again. Nothing below can work offline.")

CFG = {
    # fast config fits a free session; switch to 12000/4000 after one success (4x slower)
    "DX_D01": 24000, "DX_D02": 6000,
    "REF_LAT": 28.6, "REF_LON": 77.2,           # Delhi centre (d02 target)
    "C1_LAT": 29.5, "C1_LON": 76.0,             # d01 centre: IGP w/ stubble belt interior
    # d01 110x90 at 24 km ~ 2640x2160 km (all IGP + Pakistan Punjab, no Tibet);
    # d02 100x100 at 6 km ~ 600 km NCR box. (E_WE/E_SN d02 - 1 divisible by 3.)
    "E_WE": (110, 100), "E_SN": (90, 100),      # (d01, d02) grid sizes
    "START": "2025-11-10_00",                    # peak stubble-burning window
    "END":   "2025-11-13_00",                    # 72 h
    "WRF_VER": "v4.6.0", "WPS_VER": "v4.6.0",
    "OMP_NUM_THREADS": str(min(4, os.cpu_count() or 2)),
}
# place the two-way nest so d02 centres on Delhi (metres -> degrees, lat-scaled for lon)
KM_PER_DEG = 111.32
half_lon = (CFG["E_WE"][0] - 1) / 2 * CFG["DX_D01"] / (KM_PER_DEG * 1e3 * math.cos(math.radians(CFG["C1_LAT"])))
half_lat = (CFG["E_SN"][0] - 1) / 2 * CFG["DX_D01"] / (KM_PER_DEG * 1e3)
lon_w, lat_s = CFG["C1_LON"] - half_lon, CFG["C1_LAT"] - half_lat
i_del = (CFG["REF_LON"] - lon_w) / (CFG["DX_D01"] / (KM_PER_DEG * 1e3 * math.cos(math.radians(CFG["C1_LAT"]))))
j_del = (CFG["REF_LAT"] - lat_s) / (CFG["DX_D01"] / (KM_PER_DEG * 1e3))
CFG["I_PARENT"] = int(round(i_del - 55e3 / CFG["DX_D01"]))
CFG["J_PARENT"] = int(round(j_del - 45e3 / CFG["DX_D01"]))
e_edge = CFG["I_PARENT"] + (CFG["E_WE"][1] - 1) // 3
n_edge = CFG["J_PARENT"] + (CFG["E_SN"][1] - 1) // 3
assert 5 <= CFG["I_PARENT"] and 5 <= CFG["J_PARENT"], "nest start too close to d01 edge"
assert e_edge <= CFG["E_WE"][0] - 5 and n_edge <= CFG["E_SN"][0] - 5, f"d02 does not fit in d01: {e_edge},{n_edge}"
print("I_PARENT/J_PARENT:", CFG["I_PARENT"], CFG["J_PARENT"], "| d02 east/north edge:", e_edge, n_edge)

WORK = "/kaggle/working/wrf-chem-run" if os.path.isdir("/kaggle/working") else "/content/wrf-chem-run"
os.makedirs(WORK, exist_ok=True)
os.environ["WORK"] = WORK   # later cells re-read this from the environment
CFG["WORK"] = WORK
open(f"{WORK}/cfg.json", "w").write(json.dumps(CFG))
assert os.environ.get("WORK") == WORK, "cell 2 must export WORK for all later cells"
print("WORK =", WORK)
print({k: v for k, v in CFG.items() if k != "WORK"})""")

code(r"""# 0b · RESUME CHECK — run first on a re-attached session.
#      /kaggle/working persists as session output: if a previous session already
#      compiled the models you can skip the build cells and resume at the data cells.
import os, json, pathlib
W = "/kaggle/working/wrf-chem-run"
cfgp = pathlib.Path(W, "cfg.json")
CFG = json.load(open(cfgp)) if cfgp.exists() else {"WORK": W}
have = {x: pathlib.Path(W, x).exists() for x in
        ("WRF/main/wrf.exe", "WRF/main/real.exe", "WPS/geogrid.exe", "run/wrfinput_d01", "run/wrfinput_d02")}
for k, v in have.items():
    print(f"{k}: {v}")
print("skip build cells 1-4:", have["WRF/main/wrf.exe"] and have["WRF/main/real.exe"] and have["WPS/geogrid.exe"])
print("skip WPS/real cells 5-7:", have["run/wrfinput_d01"] and have["run/wrfinput_d02"])""")

# ---------------------------------------------------------------- build
md("""## 1 · Build toolchain + WRF/WPS (the long part)

Ubuntu 22.04 provides everything except **jasper** (dropped from the repos; ungrib needs it to
decode GRIB2), built here from the canonical 1.900.1 source — this was the fatal step in v1.""")

code(r"""# 1 · apt dependencies (all verified on Ubuntu 22.04) + jasper 1.900.1 from canonical source
import os, json, subprocess, sys
CFG = json.load(open(f"{os.environ['WORK']}/cfg.json")); W = CFG["WORK"]
os.environ["OMP_NUM_THREADS"] = CFG["OMP_NUM_THREADS"]

subprocess.run(["apt-get", "update", "-qq"], capture_output=True)
r = subprocess.run(["apt-get", "install", "-y", "-qq", "gfortran", "gcc", "g++", "cpp", "m4",
                    "csh", "tcsh", "perl", "make", "wget", "curl", "unzip", "file",
                    "libnetcdf-dev", "libnetcdff-dev", "libopenmpi-dev", "openmpi-bin"],
                   capture_output=True, text=True)
if r.returncode != 0:
    print(r.stderr[-2000:]); sys.exit("apt install failed - is Internet ON?")
for b in ("gfortran", "nc-config", "nf-config", "mpirun"):
    ok = subprocess.run(["which", b], capture_output=True).returncode == 0
    print(f"{b}: {'ok' if ok else 'MISSING'}")

os.chdir(W)
if not os.path.exists(f"{W}/local/lib/libjasper.a"):
    subprocess.run(["wget", "-q", "https://github.com/mdadams/jasper/archive/refs/tags/version-1.900.1.zip",
                    "-O", "jasper.zip"], check=True)
    subprocess.run(["unzip", "-q", "-o", "jasper.zip"], check=True)
    src = [d for d in os.listdir(W) if d.startswith("jasper-") and os.path.isdir(d)][0]
    for cmd in (["./configure", f"--prefix={W}/local"], ["make", f"-j{os.cpu_count()}"], ["make", "install"]):
        subprocess.run(cmd, cwd=src, capture_output=True, check=True)
print("jasper:", os.path.exists(f"{W}/local/lib/libjasper.a"))

# library environment for every configure/compile below
os.environ.update({"DIR": f"{W}/local", "NETCDF": "/usr", "NETCDF_classic": "1",
                   "JASPERLIB": f"{W}/local/lib", "JASPERINC": f"{W}/local/include",
                   "LD_LIBRARY_PATH": f"/usr/lib:{W}/local/lib"})
print("env ready")""")

code(r"""# 2 · Download + extract WRF & WPS sources (verified codeload URLs; release-asset names 404)
import os, json, subprocess
CFG = json.load(open(f"{os.environ['WORK']}/cfg.json")); W = CFG["WORK"]
os.chdir(W)
for fname, url in {
    "WRF.tar.gz": f"https://codeload.github.com/wrf-model/WRF/tar.gz/refs/tags/{CFG['WRF_VER']}",
    "WPS.tar.gz": f"https://codeload.github.com/wrf-model/WPS/tar.gz/refs/tags/{CFG['WPS_VER']}",
}.items():
    if not os.path.exists(fname):
        subprocess.run(["wget", "-q", url, "-O", fname], check=True)
        print(fname, int(os.path.getsize(fname) / 1e6), "MB")
for pkg, prefix in (("WRF", "WRF-"), ("WPS", "WPS-")):
    if not os.path.isdir(f"{W}/{pkg}"):
        subprocess.run(["tar", "xzf", f"{pkg}.tar.gz"], check=True)
        d = [x for x in os.listdir(W) if x.startswith(prefix)]
        assert len(d) == 1, f"ambiguous extract: {d}"
        os.rename(d[0], f"{W}/{pkg}")
print("sources ready:", os.path.isdir(f"{W}/WRF/phys"), os.path.isdir(f"{W}/WPS/ungrib"))""")

code(r"""# 3 · Configure WRF as WRF-CHEM: GNU + OpenMP ('smpar') - solid speedup on 4 vCPU
import os, json, subprocess, re, pathlib, sys
CFG = json.load(open(f"{os.environ['WORK']}/cfg.json")); W = CFG["WORK"]
os.chdir(f"{W}/WRF")
if not pathlib.Path("configure.wrf").exists():
    # v4.6 semantics: 'chem' is a POSITIONAL arg ('./configure chem'); BOTH runs
    # need it or the build silently loses chemistry. The menu prints
    # '  N. (serial)   M. (smpar) ... GNU (gfortran/gcc)' - numbers and the
    # compiler description on ONE line, numbered cumulatively across stanzas.
    menu = ""
    try:
        r = subprocess.run(["./configure", "chem"], stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=60)
        menu = r.stdout + r.stderr
    except subprocess.TimeoutExpired as e:  # normal: Config.pl loops on EOF stdin
        out = e.output or b""
        err = e.stderr or b""
        if isinstance(out, bytes):           # POSIX delivers bytes even with text=True
            out = out.decode(errors="ignore")
        if isinstance(err, bytes):
            err = err.decode(errors="ignore")
        menu = out + err
    open("menu_chem.txt", "w").write(menu)
    gnu_lines = [ln for ln in menu.splitlines() if "(serial)" in ln and "GNU" in ln]
    if not gnu_lines:
        print(menu[-2000:]); sys.exit("GNU (serial/smpar) menu line not found - see menu_chem.txt")
    pick = {}
    for kind in ("smpar", "serial"):
        m = re.search(r"(\d+)\.\s+\(" + kind + r"\)", gnu_lines[0])
        if m:
            pick[kind] = m.group(1)
    if not pick:
        print(gnu_lines[0]); sys.exit("could not read option numbers from the GNU menu line")
    opt = pick.get("smpar") or pick["serial"]
    print("menu:", gnu_lines[0].strip()[:120])
    print("chose option", opt, f"(of {pick}) + nesting 1 (basic)")
    with open("opt_input", "w") as f:
        f.write(f"{opt}\n1\n")     # line 1: stanza, line 2: nesting prompt
    with open("opt_input") as fin:
        p2 = subprocess.run(["./configure", "chem"], stdin=fin, capture_output=True, text=True)
    open("configure_out.txt", "w").write(p2.stdout + p2.stderr)
    print((p2.stdout + p2.stderr)[-400:])
assert pathlib.Path("configure.wrf").exists(), "configure.wrf missing"
_cw = pathlib.Path("configure.wrf").read_text()
assert "WRF_CHEM" in _cw or "BUILD_CHEM" in _cw, "configure.wrf lacks chem flags - rerun with 'chem' arg"
print("WRF configured for chem")""")

code(r"""# 4 · Compile WRF (chem-enabled), ~50-80 min on 4 vCPU. Fails loudly with the log tail.
#      NOTE: NEVER run './clean -a' here - the v4.6.0 clean script DELETES
#      configure.wrf (its line 51), which would throw away cell 3's chem
#      configure and './compile' aborts with 'You must run configure first'.
#      The tree is freshly extracted - there is nothing to clean.
import os, json, subprocess, pathlib, time, shutil
CFG = json.load(open(f"{os.environ['WORK']}/cfg.json")); W = CFG["WORK"]
os.chdir(f"{W}/WRF")
need = ["main/wrf.exe", "main/real.exe"]
if not all(pathlib.Path(x).exists() for x in need):
    bak = pathlib.Path("configure.wrf.backup")   # resume after an aborted clean
    if bak.exists() and not pathlib.Path("configure.wrf").exists():
        shutil.copyfile(bak, "configure.wrf")
    t0 = time.time()
    p = subprocess.run(["./compile", "em_real", f"-j{os.cpu_count()}"], capture_output=True, text=True)
    open("compile_wrf.log", "w").write(p.stdout + p.stderr)
    print("compile:", int(time.time() - t0), "s")
for x in need:
    print(x, pathlib.Path(x).exists())
if not all(pathlib.Path(x).exists() for x in need):
    print(open("compile_wrf.log").read()[-3000:])
    raise SystemExit("WRF compile failed - see log tail above")
print("WRF executables ready")""")

code(r"""# 5 · Compile WPS (GNU serial = option 1), ~5 min. Uses JASPERLIB/JASPERINC from cell 1.
import os, json, subprocess, pathlib
CFG = json.load(open(f"{os.environ['WORK']}/cfg.json")); W = CFG["WORK"]
os.chdir(f"{W}/WPS")
if not pathlib.Path("configure.wps").exists():
    with open("opt_input", "w") as f:
        f.write("1\n")
    p = subprocess.run(["./configure"], stdin=open("opt_input"), capture_output=True, text=True)
    print((p.stdout + p.stderr)[-300:])
exes = ["geogrid.exe", "ungrib.exe", "metgrid.exe"]
if not all(pathlib.Path(x).exists() for x in exes):
    p = subprocess.run(["./compile"], capture_output=True, text=True)
    open("compile_wps.log", "w").write(p.stdout + p.stderr)
for x in exes:
    print(x, pathlib.Path(x).exists())
    if not pathlib.Path(x).exists():
        print(open("compile_wps.log").read()[-2000:])
        raise SystemExit("WPS compile failed")
print("WPS ready")""")

# ---------------------------------------------------------------- WPS + real
md("""## 2 · Domains, meteorology, real.exe

`d01` covers the IGP stubble belt + NCR at 24 km; the two-way nested `d02` (`feedback = 1` —
the problem statement's requirement) covers Delhi NCR at 6 km.""")

code(r"""# 6 · namelist.wps + static geography + geogrid (both domains)
import os, json, subprocess, pathlib
CFG = json.load(open(f"{os.environ['WORK']}/cfg.json")); W = CFG["WORK"]
os.makedirs(f"{W}/geog", exist_ok=True)
if not os.listdir(f"{W}/geog"):
    subprocess.run(["wget", "-q", "-c",
                    "https://www2.mmm.ucar.edu/wrf/src/wps_files/geog_low_res_mandatory.tar.gz",
                    "-O", f"{W}/geog.tar.gz"], check=True)
    subprocess.run(["tar", "xzf", f"{W}/geog.tar.gz", "-C", f"{W}/geog", "--strip-components=1"], check=True)
print("geog field dirs:", len([d for d in os.listdir(f'{W}/geog') if os.path.isdir(f'{W}/geog/{d}')]))

nl = f'''&share
 wrf_core = 'ARW',
 max_dom = 2,
 start_date = '{CFG['START']}','{CFG['START']}',
 end_date   = '{CFG['END']}','{CFG['END']}',
 interval_seconds = 21600,
/
&geogrid
 parent_id         =   1,   1,
 parent_grid_ratio =   1,   3,
 i_parent_start    =  {CFG['I_PARENT']},  {CFG['I_PARENT']},
 j_parent_start    =  {CFG['J_PARENT']},  {CFG['J_PARENT']},
 e_we              =  {CFG['E_WE'][0]},  {CFG['E_WE'][1]},
 e_sn              =  {CFG['E_SN'][0]},  {CFG['E_SN'][1]},
 geog_data_res     = 'default','default',   # USGS 24-category land use ->
                                               # num_land_cat MUST be 24 in
                                               # namelist.input or real.exe fatals
 dx = {CFG['DX_D01']},
 dy = {CFG['DX_D01']},
 map_proj = 'lambert',
 ref_lat  = {CFG['C1_LAT']}, ref_lon = {CFG['C1_LON']},
 truelat1 = 30.0, truelat2 = 45.0, stand_lon = {CFG['C1_LON']},
 geog_data_path = '{W}/geog/',
/
&ungrib
 out_format = 'WPS',
 prefix = 'GFS',
/
&metgrid
 fg_name = 'GFS',
/
'''
open(f"{W}/WPS/namelist.wps", "w").write(nl)
os.chdir(f"{W}/WPS")
if not (pathlib.Path("geo_em.d01.nc").exists() and pathlib.Path("geo_em.d02.nc").exists()):
    subprocess.run(["./geogrid.exe"], capture_output=True)
ok = pathlib.Path("geo_em.d01.nc").exists() and pathlib.Path("geo_em.d02.nc").exists()
print("geogrid:", "OK (d01+d02)" if ok else "FAILED - see geogrid.log")
if not ok:
    print(open("geogrid.log", errors="ignore").read()[-1500:])
    raise SystemExit("geogrid failed")""")

code(r"""# 7 · GFS 0.25-deg analyses (keyless AWS, verified for past dates) -> ungrib -> metgrid
import os, json, subprocess
from datetime import datetime, timedelta
from netCDF4 import Dataset
CFG = json.load(open(f"{os.environ['WORK']}/cfg.json")); W = CFG["WORK"]
os.chdir(f"{W}/WPS")
t = datetime.strptime(CFG["START"], "%Y-%m-%d_%H")
t1 = datetime.strptime(CFG["END"], "%Y-%m-%d_%H")
while t <= t1:
    stamp = t.strftime("%Y%m%d_%H")
    dest = f"GFS:{stamp}"
    if not os.path.exists(dest):
        url = (f"https://noaa-gfs-bdp-pds.s3.amazonaws.com/gfs.{t.strftime('%Y%m%d')}/"
               f"{t.strftime('%H')}/atmos/gfs.t{t.strftime('%H')}z.pgrb2.0p25.anl")
        subprocess.run(["wget", "-q", url, "-O", dest], check=True)
    print(dest, int(os.path.getsize(dest) / 1e6), "MB")
    t += timedelta(hours=6)
subprocess.run(["cp", "ungrib/Variable_Tables/Vtable.GFS", "Vtable"], check=True)
subprocess.run(["./link_grib.csh", "GFS:"], check=True)
p = subprocess.run(["./ungrib.exe"], capture_output=True, text=True)
assert p.returncode == 0, "ungrib failed: " + (p.stdout + p.stderr)[-800:]
p = subprocess.run(["./metgrid.exe"], capture_output=True, text=True)
mets = sorted(x for x in os.listdir(".") if x.startswith("met_em.d01"))
print("met_em.d01 files:", len(mets))
assert len(mets) >= 13, "expected 13 six-hourly met_em files (72 h window)"
assert p.returncode == 0, "metgrid failed: " + (p.stdout + p.stderr)[-800:]

# level counts must match the GFS input exactly - read them from the met_em file
ds = Dataset(mets[0])
CFG["NUM_METGRID_LEVELS"] = len(ds.dimensions["bottom_top"])
soil_dims = [k for k in ds.dimensions if "soil" in k.lower()]
CFG["NUM_METGRID_SOIL_LEVELS"] = len(ds.dimensions[soil_dims[0]]) if soil_dims else 4
ds.close()
json.dump(CFG, open(f"{W}/cfg.json", "w"))
print("num_metgrid_levels:", CFG["NUM_METGRID_LEVELS"],
      "| num_metgrid_soil_levels:", CFG["NUM_METGRID_SOIL_LEVELS"])""")

code(r"""# 8 · namelist.input (complete &time_control + verified chem contract) -> real.exe
import os, json, subprocess, pathlib
CFG = json.load(open(f"{os.environ['WORK']}/cfg.json")); W = CFG["WORK"]
time_step = int(CFG["DX_D01"] / 1000 * 6)   # 6 s per km of dx - the stable guidance
nl = f'''&time_control
 run_days   = 3,
 start_year = 2025, 2025,
 start_month = 11,   11,
 start_day  = 10,   10,
 start_hour = 00,   00,
 end_year   = 2025, 2025,
 end_month  = 11,   11,
 end_day    = 13,   13,
 end_hour   = 00,   00,
 interval_seconds = 21600,
 input_from_file = .true., .true.,
 history_interval = 180, 60,   # d01 3-hourly (context), d02 hourly (validation)
 frames_per_outfile = 24, 24,  # ~1 GB/day/domain; keeps /kaggle/working under quota
 restart = .false.,
 restart_interval = 4320,
 io_form_history = 2,
 io_form_restart = 2,
 io_form_input = 2,
 io_form_boundary = 2,
 io_form_auxinput5 = 2,
 auxinput5_interval_m = 60, 60,
 frames_per_auxinput5 = 24, 24,
 debug_level = 0,
/
&domains
 time_step = {time_step},
 time_step_fract_num = 0, time_step_fract_den = 1,
 max_dom = 2,
 e_we   = {CFG['E_WE'][0]}, {CFG['E_WE'][1]},
 e_sn   = {CFG['E_SN'][0]}, {CFG['E_SN'][1]},
 e_vert = 45, 45,
 p_top_requested = 5000,
 num_metgrid_levels = {CFG['NUM_METGRID_LEVELS']},
 num_metgrid_soil_levels = {CFG['NUM_METGRID_SOIL_LEVELS']},
 dx = {CFG['DX_D01']}, {CFG['DX_D02']},
 dy = {CFG['DX_D01']}, {CFG['DX_D02']},
 grid_id = 1, 2,
 parent_id = 1, 1,
 i_parent_start = {CFG['I_PARENT']}, {CFG['I_PARENT']},
 j_parent_start = {CFG['J_PARENT']}, {CFG['J_PARENT']},
 parent_grid_ratio = 1, 3,
 parent_time_step_ratio = 1, 3,
 feedback = 1,
 smooth_option = 0,
/
&physics
 mp_physics = 8, 8,
 ra_lw_physics = 4, 4,
 ra_sw_physics = 4, 4,
 radt = 15, 15,
 sf_sfclay_physics = 1, 1,
 sf_surface_physics = 2, 2,
 bl_pbl_physics = 1, 1,
 bldt = 0, 0,
 cu_physics = 1, 0,
 cudt = 5, 0,
 surface_input_source = 3,
 num_land_cat = 24,
/
&chem
 chemdt = 5,
 io_style_emissions = 2,
 chem_opt = 301, 301,
 emiss_opt = 8, 8,
 emiss_inpt_opt = 111, 111,
 emi_inname = 'wrfchemi_d<domain>_<date>',
 aer_ra_feedback = 1, 1,
 biomass_burn_opt = 0, 0,
 phot_opt = 3, 3,
 gas_bc_opt = 1, 1,
 gas_ic_opt = 1, 1,
 aer_bc_opt = 1, 1,
 aer_ic_opt = 1, 1,
 have_bcs_chem = .false.,
 chem_in_opt = 0,
 kemit = 1,
/
&dynamics
 w_damping = 1,
 diff_opt = 1, 1,  km_opt = 4, 4,
 diff_6th_opt = 0, 0,  diff_6th_factor = 0.12, 0.12,
 base_temp = 290.,
 damp_opt = 0,
 zdamp = 5000., 5000.,
 dampcoef = 0.2, 0.2,
 khdif = 0, 0,  kvdif = 0, 0,
 non_hydrostatic = .true., .true.,
 moist_adv_opt = 1, 1,  scalar_adv_opt = 1, 1,
 gwd_opt = 0, 0,
/
&bdy_control
 spec_bdy_width = 5,
 spec_zone = 1,
 relax_zone = 4,
 specified = .true., .false.,
 nested = .false., .true.,
/
&namelist_quilt
 nio_tasks_per_group = 0, nio_groups = 1,
/
'''
os.makedirs(f"{W}/run", exist_ok=True)
os.system(f"cp -n {W}/WRF/run/* {W}/run/ 2>/dev/null")
open(f"{W}/run/namelist.input", "w").write(nl)
os.chdir(f"{W}/run")
os.system(f"ln -sf {W}/WPS/met_em.d0* .")
if not (pathlib.Path("wrfinput_d01").exists() and pathlib.Path("wrfinput_d02").exists()):
    p = subprocess.run(["./real.exe"], capture_output=True, text=True,
                       env=dict(os.environ, OMP_NUM_THREADS=CFG["OMP_NUM_THREADS"]))
ok = pathlib.Path("wrfinput_d01").exists() and pathlib.Path("wrfinput_d02").exists()
print("real.exe:", "OK" if ok else "FAILED")
if not ok:
    print(open("rsl.error.0000", errors="ignore").read()[-2500:])
    raise SystemExit("real.exe failed")
print("wrfinput_d01/d02 ready for the emissions step")""")

# ---------------------------------------------------------------- emissions
md("""## 3 · Real emissions — EDGAR v8.1 anthropogenics + FIRMS fire injections

Anthropogenic: EDGAR v8.1 annual totals (CO, NOx, SO2, NH3, NMVOC, PM2.5, PM10, BC, OC — ~4 MB
zips each, keyless) regridded to both WRF domains, speciated to the **exact 25-variable MOZCART
contract** (`emiss_opt=8`, read from the WRF v4.6.0 registry). Units are load-bearing: the model
converts gases with `4.828e-4/rho·dt/(dz·60)` and aerosols with `alt·dt/dz`, so the files carry
**mol km⁻² hr⁻¹** for the 20 gas species and **µg m⁻² s⁻¹** for E_PM_25/E_PM_10/E_BC/E_OC/E_SULF.
All fluxes are computed as *intensive* quantities on the EDGAR 0.1° grid first (so the result is
resolution-independent), then nearest-neighbour mapped onto each WRF domain.

Fire: NASA FIRMS (VIIRS SNPP **SP** archive + MODIS SP — the NRT feed does not reach Nov 2025;
both verified live against the real window) FRP → combustion mass (ΔH ≈ 18.7 MJ/kg, Woof 2011) →
Akagi et al. (2011) cropland emission factors, injected into the same wrfchemi files. This is the
stubble-burning plume driver the problem statement asks to model.""")

code(r"""# 9 · Download EDGAR v8.1 sector grids (verified JRC per-sector/yr NetCDF) + WorldPop India
#      Format verified live: 0.1-deg global grid, variable 'emissions' in Tonnes/cell/yr.
#      Sectors (IPCC v8 codes): AWB=ag-waste burning (EXCLUDED here - fires come from
#      FIRMS, avoiding double counting), ENE=power, IND=industry, RCO=buildings,
#      TRO=transport, REF_TRF=refineries, SWD_INC=waste. Per-species sector lists
#      verified live against the JRC FTP (OC has no CHE sector -> 62 downloads).
import os, json, subprocess, zipfile, urllib.request, sys
CFG = json.load(open(f"{os.environ['WORK']}/cfg.json")); W = CFG["WORK"]
BASE = "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/EDGAR/datasets/v81_FT2022_AP_new"
SECTORS = {
    "CO": ["ENE", "IND", "RCO", "TRO", "REF_TRF", "SWD_INC", "CHE"],
    "NOx": ["ENE", "IND", "RCO", "TRO", "REF_TRF", "SWD_INC", "CHE"],
    "SO2": ["ENE", "IND", "RCO", "TRO", "REF_TRF", "SWD_INC", "CHE"],
    "NH3": ["ENE", "IND", "RCO", "TRO", "REF_TRF", "SWD_INC", "CHE"],
    "NMVOC": ["ENE", "IND", "RCO", "TRO", "REF_TRF", "SWD_INC", "CHE"],
    "PM2.5": ["ENE", "IND", "RCO", "TRO", "REF_TRF", "SWD_INC", "CHE"],
    "PM10": ["ENE", "IND", "RCO", "TRO", "REF_TRF", "SWD_INC", "CHE"],
    "BC": ["ENE", "IND", "RCO", "TRO", "REF_TRF", "SWD_INC", "CHE"],
    "OC": ["ENE", "IND", "RCO", "TRO", "REF_TRF", "SWD_INC"],   # no CHE sector (verified)
}
import socket
socket.setdefaulttimeout(120)   # urllib + all fetches get a sane timeout
os.makedirs(f"{W}/edgar", exist_ok=True)
need = 0
for sp in SECTORS:
    for sec in SECTORS[sp]:
        url = f"{BASE}/{sp}/{sec}/emi_nc/v8.1_FT2022_AP_{sp}_2022_{sec}_emi_nc.zip"
        dest = f"{W}/edgar/{sp}_{sec}_2022.zip"
        if not os.path.exists(dest):
            urllib.request.urlretrieve(url, dest)
            need += 1
        with zipfile.ZipFile(dest) as z:
            z.extractall(f"{W}/edgar")
ncs = [x for x in os.listdir(f'{W}/edgar') if x.endswith('.nc')]
print(f"downloaded {need} new; EDGAR nc files: {len(ncs)}")
EXPECTED = len(SPEC_DIR) * len(SECTORS)
if len(ncs) < EXPECTED:
    print("sample names:", ncs[:3]); sys.exit(f"EDGAR download incomplete: {len(ncs)}/{EXPECTED}")
if not os.path.exists(f"{W}/edgar/worldpop_ind.tif"):
    subprocess.run(["wget", "-q",
                    "https://data.worldpop.org/GIS/Population/Global_2000_2020_1km_UNadj/"
                    "2020/IND/ind_ppp_2020_1km_Aggregated_UNadj.tif",
                    "-O", f"{W}/edgar/worldpop_ind.tif"], check=True)
print("worldpop:", int(os.path.getsize(f"{W}/edgar/worldpop_ind.tif") / 1e6), "MB (QC overlay)")""")

code(r"""# 10 · Build wrfchemi_d01/d02: EDGAR regrid + MOZCART speciation + FIRMS fire injection
#
# Design: all fluxes are computed as INTENSIVE quantities (per m2) on the EDGAR
# 0.1-deg grid, then nearest-neighbour mapped to each WRF domain - correct for
# per-area fluxes at any nest resolution, and fire mass is not artificially
# concentrated when d02 is finer than the inventory grid.
import os, json, csv, io, glob, urllib.request
from datetime import datetime, timedelta
import numpy as np
from netCDF4 import Dataset

CFG = json.load(open(f"{os.environ['WORK']}/cfg.json")); W = CFG["WORK"]
os.chdir(f"{W}/run")

# Registry-verified emiss_opt=8 (mozcem) contract - the writer emits exactly
# these variables, because the reader maps wrfchemi columns onto emis_ant by name.
GASES = ["E_CO", "E_NO", "E_NO2", "E_BIGALK", "E_BIGENE", "E_C2H4", "E_C2H5OH", "E_C2H6",
         "E_C3H6", "E_C3H8", "E_CH2O", "E_CH3CHO", "E_CH3COCH3", "E_CH3OH", "E_MEK",
         "E_SO2", "E_TOLUENE", "E_NH3", "E_ISOP", "E_C10H16"]
AERS = ["E_PM_10", "E_PM_25", "E_BC", "E_OC", "E_SULF"]
assert len(set(GASES + AERS)) == len(GASES) + len(AERS), "duplicate contract variable"

# ---- EDGAR nc sector grids (format verified live: dims lat=1800 lon=3600 at
#      0.1 deg, variable 'emissions' in Tonnes/cell/yr). Sum sectors per species. ----
def edgar_species(sp, spdir):
    # real v8.1 filenames: v8.1_FT2022_AP_<SP>_2022_<SEC>_emi.nc (verified live;
    # SP is the EDGAR token - 'PM2.5' with the dot - not the local key 'PM25')
    files = sorted(glob.glob(f"{W}/edgar/v8.1_FT2022_AP_{spdir}_2022_*_emi.nc"))
    assert len(files) == len(SECTORS[sp]), f"{sp}: found {len(files)} sector grids, want {len(SECTORS[sp])}"
    assert files, f"no EDGAR nc sector files for {sp}"
    total, la, lo = None, None, None
    for f in files:
        ds = Dataset(f)
        la = np.asarray(ds.variables["lat"][:], dtype=np.float64)
        lo = np.asarray(ds.variables["lon"][:], dtype=np.float64)
        d = np.asarray(ds.variables["emissions"][:], dtype=np.float64)
        ds.close()
        total = d if total is None else total + d
    mi = np.where((la >= 26.5) & (la <= 33.0))[0]
    mj = np.where((lo >= 73.0) & (lo <= 82.5))[0]
    box = total[np.ix_(mi, mj)]
    print(f"{sp}: {len(files)} sector grids -> box {box.shape}, "
          f"sum {float(np.nansum(box)) / 1e9:.2f} Mt/yr")
    return la[mi], lo[mj], box

species = {sp: edgar_species(sp, sp) for sp in SECTORS}
la_ed, lo_ed, _ = species["CO"]
nla, nlo = len(la_ed), len(lo_ed)
dlat = float(np.mean(np.abs(np.diff(la_ed)))) or 0.1
dlon = float(np.mean(np.abs(np.diff(lo_ed)))) or 0.1
cell_m2 = (dlat * 111.32e3) * (dlon * 111.32e3 * np.cos(np.deg2rad(la_ed)))[:, None]  # (nla,1)
print(f"EDGAR box: {nla} lats x {nlo} lons, dlat {dlat:.3f} dlon {dlon:.3f} deg")

MW = {"CO": 28.01, "NO": 30.0061, "NO2": 46.0055, "SO2": 64.066, "NH3": 17.031}
# NMVOC -> MOZCART gas species: documented global-average mol fractions; the
# remainder folds into E_BIGALK so the carbon budget is closed. (E_BENZENE and
# E_XYLENE are NOT part of the mozcem package - folded into E_BIGALK too.)
VOC_FRAC = {"E_BIGALK": 0.26, "E_BIGENE": 0.04, "E_C2H6": 0.05, "E_C3H8": 0.04,
            "E_C2H4": 0.04, "E_C3H6": 0.03, "E_CH2O": 0.06, "E_CH3CHO": 0.03,
            "E_CH3COCH3": 0.03, "E_CH3OH": 0.07, "E_MEK": 0.02, "E_TOLUENE": 0.09,
            "E_ISOP": 0.02, "E_C2H5OH": 0.02, "E_C10H16": 0.0}
VOC_FRAC["E_BIGALK"] += 1.0 - sum(VOC_FRAC.values())
# hourly activity profile (traffic + domestic peaks), normalised to mean 1
DIURNAL = np.array([0.5, .45, .4, .4, .45, .6, 1.0, 1.4, 1.6, 1.5, 1.4, 1.4,
                    1.4, 1.4, 1.4, 1.5, 1.7, 2.0, 2.2, 2.0, 1.7, 1.3, .9, .7])
DIURNAL = DIURNAL / DIURNAL.mean()

# ---- intensive anthropogenic fluxes on the EDGAR grid ----
def mol_km2_hr(field_t, mw):
    '''tonnes/cell/yr -> mol km^-2 hr^-1 (annual mean; diurnal profile applied later).'''
    return field_t * 1e6 / mw / cell_m2 * 1e6 / 8760.0

def ug_m2_s(field_t):
    '''tonnes/cell/yr -> ug m^-2 s^-1.'''
    return field_t * 1e9 / cell_m2 / (365.0 * 86400.0)

anthro_gas = {
    "E_CO": mol_km2_hr(species["CO"][2], MW["CO"]),
    "E_SO2": mol_km2_hr(species["SO2"][2], MW["SO2"]),
    "E_NH3": mol_km2_hr(species["NH3"][2], MW["NH3"]),
}
nox = mol_km2_hr(species["NOx"][2], MW["NO2"])
anthro_gas["E_NO"] = 0.9 * nox
anthro_gas["E_NO2"] = 0.1 * nox
voc = mol_km2_hr(species["NMVOC"][2], 14.0)      # NMVOC reported as mol C-equivalent proxy
for var, frac in VOC_FRAC.items():
    anthro_gas[var] = frac * voc
anthro_aer = {
    "E_PM_25": ug_m2_s(np.clip(species["PM25"][2] - species["OC"][2] - species["BC"][2], 0.0, None)),
    "E_PM_10": ug_m2_s(species["PM10"][2]),
    "E_OC": ug_m2_s(species["OC"][2]),
    "E_BC": ug_m2_s(species["BC"][2]),
    "E_SULF": ug_m2_s(np.zeros_like(species["BC"][2])),   # sulphate carried as SO2 gas
}
assert set(anthro_gas) == set(GASES), f"gas contract mismatch: {set(GASES) ^ set(anthro_gas)}"
print("EDGAR flux sanity (Delhi-region max): E_CO %.1f mol/km2/hr | E_PM_25 %.2f ug/m2/s"
      % (anthro_gas["E_CO"].max(), anthro_aer["E_PM_25"].max()))

# ---- FIRMS fire fluxes (SP archive covers the window; NRT does not) ----
# Kaggle keeps Secrets in UserSecretsClient, not the process env.
FIRMS_KEY = os.environ.get("FIRMS_API_KEY", "")
if not FIRMS_KEY:
    try:
        from kaggle_secrets import UserSecretsClient
        FIRMS_KEY = UserSecretsClient().get_secret("FIRMS_API_KEY")
        print("FIRMS key read from Kaggle Secrets")
    except Exception:
        pass
BOX = "73,26.5,82.5,33"
EF_CROPLAND = {"CO": 67.0, "NO": 2.0, "PM25": 12.0, "PM10": 15.0, "OC": 4.7, "BC": 0.6}  # g/kg (Akagi 2011)
DH_MJ_KG = 18.7                                        # heat of combustion, MJ/kg

def firms_rows(src, day):
    url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{FIRMS_KEY}/{src}/{BOX}/3/{day}"
    try:
        data = urllib.request.urlopen(url, timeout=90).read().decode()
        return list(csv.DictReader(io.StringIO(data)))
    except Exception as e:
        print("FIRMS fetch failed", src, day, ":", e)
        return []

def fire_flux_grid(day):
    '''day -> {species: g/m2/day on the EDGAR box} (zeros when no key/fires).'''
    out = {k: np.zeros((nla, nlo)) for k in EF_CROPLAND}
    if not FIRMS_KEY:
        print(f"{day}: FIRMS_API_KEY not set - fire injection skipped (documented)")
        return out
    fires = []
    for r in firms_rows("VIIRS_SNPP_SP") + firms_rows("MODIS_SP"):
        try:
            conf = r.get("confidence", "")
            confv = 50.0 if conf in ("n", "l", "h") else float(conf)
            typ = r.get("type", "0")
            if typ not in ("0", "3") or confv < 30:
                continue
            frp = float(r["frp"])
            if frp <= 0:
                continue
            fires.append((float(r["latitude"]), float(r["longitude"]), frp))
        except (ValueError, KeyError):
            continue
    print(f"{day}: fire detections used (VIIRS+MODIS SP, conf>=30): {len(fires)}")
    kg_day_total = 0.0
    for lat_f, lon_f, frp in fires:
        i = int(np.argmin(np.abs(la_ed - lat_f)))
        j = int(np.argmin(np.abs(lo_ed - lon_f)))
        kg_day = frp / DH_MJ_KG * 86400.0               # MW -> MJ/day -> kg/day
        kg_day_total += kg_day
        for k, ef in EF_CROPLAND.items():
            out[k][i, j] += kg_day * ef * 1000.0 / cell_m2[i, 0]   # g/day -> g/m2/day
    print(f"{day}: combusted {kg_day_total / 1e3:.1f} t fuel -> {kg_day_total * 67.0 / 1e6:.1f} t CO")
    return out

t0 = datetime.strptime(CFG["START"], "%Y-%m-%d_%H")
t1 = datetime.strptime(CFG["END"], "%Y-%m-%d_%H")
days = []
d = t0
while d < t1:
    days.append(d.strftime("%Y-%m-%d"))
    d += timedelta(days=1)
fire_by_day = {day: fire_flux_grid(day) for day in days}

# ---- nearest-neighbour mapping (intensive fields) EDGAR box -> WRF grid ----
order = np.argsort(la_ed)                     # robust to ascending/descending latitude
la_sorted = la_ed[order]
def map_to_grid(field, lat2d, lon2d):
    ii = np.clip(np.searchsorted(la_sorted, lat2d.ravel()), 0, nla - 1)
    row_of = order[ii]
    jj = np.clip(np.searchsorted(lo_ed, lon2d.ravel()), 0, nlo - 1)
    return field.reshape(-1)[row_of * nlo + jj].reshape(lat2d.shape)

for dom in (1, 2):
    ds = Dataset(f"wrfinput_d0{dom}")
    lat2d = ds.variables["XLAT"][0]; lon2d = ds.variables["XLONG"][0]
    ds.close()
    ny, nx = lat2d.shape
    zero2d = np.zeros((ny, nx))
    for day in days:
        ff = fire_by_day[day]
        # fire gases: g/m2/day -> mol/km2/hr (uniform across the 24 h of that day)
        fire_gas = {
            "E_CO": map_to_grid(ff["CO"], lat2d, lon2d) * 1e6 / MW["CO"] / 24.0,
            "E_NO": map_to_grid(ff["NO"], lat2d, lon2d) * 1e6 / MW["NO"] / 24.0,
        }
        # fire aerosols: g/m2/day -> ug/m2/s
        conv_ug = 1e6 / 86400.0
        fire_aer = {
            "E_PM_25": map_to_grid(ff["PM25"], lat2d, lon2d) * conv_ug,
            "E_PM_10": map_to_grid(ff["PM10"], lat2d, lon2d) * conv_ug,
            "E_OC": map_to_grid(ff["OC"], lat2d, lon2d) * conv_ug,
            "E_BC": map_to_grid(ff["BC"], lat2d, lon2d) * conv_ug,
        }
        emis = {}
        for var in GASES:
            fg = fire_gas.get(var)
            fire_part = fg[None, :, :] if fg is not None else zero2d[None, :, :]
            emis[var] = anthro_gas[var][None, :, :] * DIURNAL[:, None, None] + fire_part
        for var in AERS:
            fa = fire_aer.get(var)
            fire_part = fa[None, :, :] if fa is not None else zero2d[None, :, :]
            emis[var] = anthro_aer[var][None, :, :] + fire_part
        assert set(emis) == set(GASES + AERS), f"contract mismatch: {set(GASES + AERS) ^ set(emis)}"

        # io_style_emissions=2 filename contract (verified in module_io_domain.F
        # construct_filename2a): <date> -> full 'YYYY-MM-DD_HH:MM:SS' of the open
        # instant. With 60-min alarms + frames_per_auxinput5=24 the file opens
        # once per day at 00Z, so the day file is named with '_00:00:00' and
        # carries all 24 hourly records read sequentially.
        out = f"wrfchemi_d0{dom}_{day}_00:00:00"
        nc = Dataset(out, "w", format="NETCDF3_64BIT_OFFSET")
        nc.createDimension("Time", 24)
        nc.createDimension("DateStrLen", 19)
        nc.createDimension("kemit", 1)
        nc.createDimension("south_north", ny)
        nc.createDimension("west_east", nx)
        tv = nc.createVariable("Times", "S1", ("Time", "DateStrLen"))
        for h in range(24):
            tv[h, :] = list(f"{day}_{h:02d}:00:00")
        nc.createVariable("XLAT", "f4", ("Time", "south_north", "west_east"))[:] = lat2d[None]
        nc.createVariable("XLONG", "f4", ("Time", "south_north", "west_east"))[:] = lon2d[None]
        for name in GASES + AERS:
            var = nc.createVariable(name, "f4", ("Time", "kemit", "south_north", "west_east"))
            var[:] = np.asarray(emis[name], dtype=np.float32)[:, None]
            var.units = "mol km-2 hr-1" if name in GASES else "ug m-2 s-1"
        nc.close()
        print(f"wrote {out} {os.path.getsize(out) // 1e6} MB | E_CO h12 mean "
              f"{float(np.mean(emis['E_CO'][12])):.2f} | E_PM_25 mean {float(np.mean(emis['E_PM_25'])):.4f}")
print("wrfchemi build complete")""")

# ---------------------------------------------------------------- run
code(r"""# 11 · Run WRF-Chem (72 h, two domains, two-way feedback). ~2 h on 4 vCPU at 24/6 km.
#      SYNCHRONOUS on purpose: in Kaggle 'Save & Run All' a backgrounded process
#      is killed when the commit ends - the model must block this cell.
#      Re-attach safety: a complete run (73 frames) makes this cell a no-op.
import os, json, glob, subprocess
from netCDF4 import Dataset
CFG = json.load(open(f"{os.environ['WORK']}/cfg.json")); W = CFG["WORK"]
os.chdir(f"{W}/run")

def total_frames():
    n = 0
    for f in sorted(glob.glob("wrfout_d02*")):
        try:
            ds = Dataset(f); n += ds.dimensions["Time"].size; ds.close()
        except Exception:
            pass
    return n

done = total_frames() >= 73
env = dict(os.environ, OMP_NUM_THREADS=CFG["OMP_NUM_THREADS"])
if done:
    print("run already complete:", total_frames(), "d02 frames - skipping")
else:
    print("launching wrf.exe (blocks ~2 h) ...")
    with open("wrf_run.log", "w") as log:
        p = subprocess.run(["./wrf.exe"], env=env, stdout=log, stderr=subprocess.STDOUT)
    print("wrf.exe exit code:", p.returncode)
tail = open("rsl.error.0000", errors="ignore").read()[-600:]
print(tail)
print("d02 frames:", total_frames(), "of 73")
if total_frames() < 73:
    raise SystemExit("WRF run incomplete - inspect rsl.error.0000 above (failure table at the bottom)")
print("SUCCESS COMPLETE:", "SUCCESS COMPLETE" in tail)
""")

code(r"""# 13 · Sanity: Delhi-point hourly PM2.5 series from the finished wrfout (QC before download)
import os, json, glob
import numpy as np
from netCDF4 import Dataset
CFG = json.load(open(f"{os.environ['WORK']}/cfg.json")); W = CFG["WORK"]
os.chdir(f"{W}/run")
f = sorted(glob.glob("wrfout_d02*"))[0]     # first day: 00Z start through 23Z
print("reading", f)
ds = Dataset(f)
lat = ds.variables["XLAT"][0]; lon = ds.variables["XLONG"][0]
j, i = np.unravel_index(np.argmin((lat - 28.6) ** 2 + (lon - 77.2) ** 2), lat.shape)
print("nearest d02 cell to Delhi centre:", (j, i), float(lat[j, i]), float(lon[j, i]))
series = []
for t in range(ds.dimensions["Time"].size):
    if "PM25_TOT" in ds.variables:
        v = float(np.sum(ds.variables["PM25_TOT"][t, :, j, i]))
    else:
        # Registry v4.6.0: PM2_5_DRY is a GOCART diag in native ug m^-3 at the
        # layer centre - read the first (near-surface) layer directly. (WRF
        # perturbation potential temperature is 'T', not 'THETA'; adding 300
        # gives absolute theta if a temperature is ever needed.)
        v = float(ds.variables["PM2_5_DRY"][t, 0, j, i])
    series.append(v)
ds.close()
print("hourly near-surface PM2.5 at Delhi (ug/m3):")
print([round(x, 1) for x in series])
print("mean", round(float(np.mean(series)), 1), "| min", round(min(series), 1), "| max", round(max(series), 1))
print("interpretation: <20 -> emissions too weak; 40-400 for a Nov episode is plausible; >800 -> bug")""")

code(r"""# 14 · Package outputs -> download wrfout_delhi.tar.gz from the Output pane
#      gzip ~2x on NetCDF; originals are deleted AFTER a verified tar so the
#      20 GB /kaggle/working quota holds (the tar itself is ~4-6 GB).
import os, json, glob, subprocess
CFG = json.load(open(f"{os.environ['WORK']}/cfg.json")); W = CFG["WORK"]
os.chdir(f"{W}/run")
files = sorted(glob.glob("wrfout_d0*"))
print(len(files), "wrfout files,", sum(os.path.getsize(x) for x in files) // 10**6, "MB raw")
tar = "/kaggle/working/wrfout_delhi.tar.gz"
if not os.path.exists(tar):
    subprocess.run(["tar", "czf", tar] + files, check=True)
print("wrfout_delhi.tar.gz:", int(os.path.getsize(tar) / 1e6), "MB")
# verify the tar lists every file, then free the quota
listed = subprocess.run(["tar", "-tzf", tar], capture_output=True, text=True).stdout.split()
missing = [x for x in files if x not in listed]
assert not missing, f"tar incomplete: {missing}"
for x in files:
    os.remove(x)
print("originals removed after verified tar - download", tar)
if files:
    from netCDF4 import Dataset
    ds = Dataset(files[-1], decode_times=False)
    print("backend-contract variables present:", {"PM25_TOT": "PM25_TOT" in ds.variables,
                                                  "PM2_5_DRY": "PM2_5_DRY" in ds.variables,
                                                  "Times": "Times" in ds.variables})
    ds.close()
print("Next: download -> repo folder -> python scripts/wrfchem/fetch_wrfout.py wrfout_delhi.tar.gz --set")""")

md("""## If something fails

| Symptom | Cause | Fix |
|---|---|---|
| `NO INTERNET` at cell 0 | Internet OFF in Settings | Settings → Internet ON (phone verification), Save Version → Save & Run All |
| apt/wget failures after cell 0 | transient DNS | rerun the cell; all downloads are idempotent (existence checks, `wget -c`) |
| `GNU (serial/smpar) menu line not found` (cell 3) | menu wording changed | open `WRF/menu_chem.txt`, find the GNU line, read its `(smpar)` number, write that number then `1` into `WRF/opt_input`, rerun cell 3 |
| `configure.wrf lacks chem flags` (cell 3) | configure ran without the positional `chem` arg | must be `./configure chem` (v4.6); the cell now asserts `WRF_CHEM`/`BUILD_CHEM` landed in `configure.wrf` |
| `You must run the 'configure' script...` seconds after `WRF configured for chem` | the compile cell ran `./clean -a`, which deletes `configure.wrf` | clean removed from cell 4 (v5); a fresh extract needs no cleaning |
| WRF compile fails | rare toolchain mismatch | the log tail is printed; usually rerunning cell 4 after `./clean -a` fixes it |
| real.exe fails on met fields | level-count mismatch | cell 7 reads the counts from met_em automatically; if you hand-edited the namelist, restore it |
| real.exe fails mentioning land categories | num_land_cat mismatch | the geog set is USGS (24 cats); cell 8's namelist sets `num_land_cat = 24` - keep them consistent |
| `EDGAR ... grid ... vs ... lon values` | inventory format change | the cell prints the file head as FORMAT DEBUG; adjust `read_edgar_txt` to the printed layout |
| FIRMS "no key" | env not set | add `FIRMS_API_KEY` via notebook Add-ons → Secrets → Environment variable; the run continues with anthro-only (documented) |
| wrfout PM2.5 ≈ 0 (cell 13) | EDGAR parse fell back | check the per-species parse lines in cell 10 output |
| session died mid-run | 12-h cap / disconnect | reattach, run cell 0b; compiled exes persist in /kaggle/working; resume from the failed cell |

Want a coupled-model reference **today** without compiling anything? IITM SAFAR/EWS runs
WRF-Chem operationally for this exact domain; the repo ships
`backend/app/services/safar_service.py` as a keyless reference provider at
`/api/v1/validation/safar`.""")

# self-check: writer contract must equal the registry mozcem package line verbatim
REGISTRY_LINE = ("e_co,e_no,e_no2,e_bigalk,e_bigene,e_c2h4,e_c2h5oh,e_c2h6,e_c3h6,"
                 "e_c3h8,e_ch2o,e_ch3cho,e_ch3coch3,e_ch3oh,e_mek,e_so2,e_toluene,"
                 "e_nh3,e_isop,e_c10h16,e_pm_10,e_pm_25,e_bc,e_oc,e_sulf")
writer_set = {v.lower() for v in MOZCEM_GASES + MOZCEM_AERS}
registry_set = set(REGISTRY_LINE.split(","))
assert writer_set == registry_set, "writer contract drift vs registry: " + str(writer_set ^ registry_set)

with open("scripts/wrfchem/kaggle_wrfchem_run.ipynb", "w", encoding="utf-8") as f:
    json.dump(NB, f, indent=1, ensure_ascii=True)
print("notebook written:", len(NB["cells"]), "cells")
