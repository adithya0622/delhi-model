"""WRF-Chem adapter: unconfigured state must be honest, never fake data."""
from __future__ import annotations

import os

import pytest

from app.services import wrf_service
from app.services.wrf_service import _hour_key, _metric_block, compare_surrogate_to_wrf


def test_wrf_status_unconfigured_when_env_missing(monkeypatch=None):
    # No WRF_OUTPUT_DIR -> available False with setup steps, no exception.
    saved = os.environ.pop("WRF_OUTPUT_DIR", None)
    try:
        status = wrf_service.wrf_status()
        assert status["available"] is False
        assert status["setup"]
    finally:
        if saved is not None:
            os.environ["WRF_OUTPUT_DIR"] = saved


def test_wrf_compare_raises_when_unavailable():
    saved = os.environ.pop("WRF_OUTPUT_DIR", None)
    try:
        try:
            wrf_service.compare_against_wrf("wrfout_d03_fake")
        except RuntimeError as exc:
            assert "unavailable" in str(exc).lower()
        else:
            raise AssertionError("expected RuntimeError")
    finally:
        if saved is not None:
            os.environ["WRF_OUTPUT_DIR"] = saved


def test_compare_surrogate_to_wrf_raises_when_unconfigured():
    saved = os.environ.pop("WRF_OUTPUT_DIR", None)
    try:
        try:
            compare_surrogate_to_wrf("wrfout_d02_2025-11-10")
        except RuntimeError as exc:
            assert "unavailable" in str(exc).lower()
        else:
            raise AssertionError("expected RuntimeError when WRF_OUTPUT_DIR unset")
    finally:
        if saved is not None:
            os.environ["WRF_OUTPUT_DIR"] = saved


# ── Hour-key normalisation: the wrfout/CAMS/surrogate pairing contract ──────

def test_hour_key_unifies_time_formats():
    # wrfout ('...T00:00:00+00:00'), CAMS archive ('...T00:00') and a saved
    # surrogate row must all pair on the same key or the comparison silently
    # finds zero overlapping hours.
    assert _hour_key("2025-11-10T00:00:00+00:00") == "2025-11-10T00"
    assert _hour_key("2025-11-10T00:00") == "2025-11-10T00"
    assert _hour_key("2025-11-10T00:00:00") == "2025-11-10T00"
    assert _hour_key("2025-11-10T07:30:00+00:00") == "2025-11-10T07"


def test_metric_block_perfect_series():
    a = [10.0, 20.0, 30.0]
    block = _metric_block(a, a, "x", "y")
    assert block["n"] == 3
    assert block["mae_ug_m3"] == 0.0
    assert block["rmse_ug_m3"] == 0.0
    assert block["pearson_r"] == 1.0
    assert block["nash_sutcliffe"] == 1.0


def test_metric_block_known_values():
    a = [10.0, 20.0, 30.0]
    b = [15.0, 15.0, 30.0]
    block = _metric_block(a, b, "a", "b")
    # Service rounds metrics to 3 decimals: 3.3333... -> 3.333.
    assert block["mae_ug_m3"] == pytest.approx((5.0 + 5.0 + 0.0) / 3.0, abs=1e-3)
    assert block["pearson_r"] is not None
    assert block["n"] == 3


def test_metric_block_constant_right_side_handles_degenerate_variance():
    block = _metric_block([1.0, 2.0, 3.0], [5.0, 5.0, 5.0], "a", "b")
    assert block["pearson_r"] is None
    assert block["nash_sutcliffe"] is None
    assert block["mae_ug_m3"] == 3.0


def test_metric_block_empty():
    assert _metric_block([], [], "a", "b") == {"n": 0}


# ── Extraction units: real wrfout PM2.5 is a near-surface native ug/m-3 diag ──

def _write_synthetic_wrfout(path, pm25_native=True):
    """Minimal wrfout-shaped NetCDF: 2 times, 3x4 grid, 2 layers.

    PM2_5_DRY follows the v4.6.0 registry: units 'ug m^-3' (native
    concentration). If pm25_native is False the file carries only PM25_TOT.
    """
    import numpy as np
    from netCDF4 import Dataset

    ds = Dataset(path, "w")
    ds.createDimension("Time", 2)
    ds.createDimension("bottom_top", 2)
    ds.createDimension("south_north", 3)
    ds.createDimension("west_east", 4)
    ds.createDimension("DateStrLen", 19)
    lat = ds.createVariable("XLAT", "f4", ("Time", "south_north", "west_east"))
    lon = ds.createVariable("XLONG", "f4", ("Time", "south_north", "west_east"))
    lat[:] = 28.5 + np.arange(3)[:, None] * 0.1 + np.zeros((1, 4))
    lon[:] = 77.1 + np.arange(4)[None, :] * 0.1 + np.zeros((3, 1))
    tv = ds.createVariable("Times", "S1", ("Time", "DateStrLen"))
    for t, stamp in enumerate(("2025-11-10_00:00:00", "2025-11-10_01:00:00")):
        tv[t, :] = list(stamp)
    if pm25_native:
        v = ds.createVariable("PM2_5_DRY", "f4", ("Time", "bottom_top", "south_north", "west_east"))
        v.units = "ug m^-3"
        v[0, 0] = 180.0   # surface, t0
        v[0, 1] = 999.0   # upper layer must be ignored (native-conc extraction)
        v[1, 0] = 220.0
        v[1, 1] = 999.0
    else:
        v = ds.createVariable("PM25_TOT", "f4", ("Time", "bottom_top", "south_north", "west_east"))
        v[0, 0] = 100.0; v[0, 1] = 50.0
        v[1, 0] = 120.0; v[1, 1] = 60.0
    ds.close()


def test_extract_pm25_dry_native_units(tmp_path, monkeypatch):
    # PM2_5_DRY is native ug/m-3 per the registry: the surface layer is read
    # as-is. A rho conversion here inflated values ~1000x.
    from app.services.wrf_service import extract_delhi_pm25_series

    f = tmp_path / "wrfout_d02_2025-11-10"
    _write_synthetic_wrfout(f, pm25_native=True)
    monkeypatch.setenv("WRF_OUTPUT_DIR", str(tmp_path))
    rows, method = extract_delhi_pm25_series(f)
    assert rows[0]["pm25_ug_m3"] == 180.0 and rows[1]["pm25_ug_m3"] == 220.0
    assert "native" in method


def test_extract_prefers_pm25_tot(tmp_path, monkeypatch):
    from app.services.wrf_service import extract_delhi_pm25_series

    f = tmp_path / "wrfout_d02_2025-11-11"
    _write_synthetic_wrfout(f, pm25_native=False)
    monkeypatch.setenv("WRF_OUTPUT_DIR", str(tmp_path))
    rows, method = extract_delhi_pm25_series(f)
    assert rows[0]["pm25_ug_m3"] == 150.0 and rows[1]["pm25_ug_m3"] == 180.0
    assert "PM25_TOT" in method


def test_extract_missing_chem_vars_is_honest(tmp_path):
    import numpy as np
    from netCDF4 import Dataset
    from app.services.wrf_service import extract_delhi_pm25_series

    f = tmp_path / "wrfout_d01_plain"
    ds = Dataset(f, "w")
    ds.createDimension("Time", 1); ds.createDimension("south_north", 2)
    ds.createDimension("west_east", 2); ds.createDimension("DateStrLen", 19)
    lat = ds.createVariable("XLAT", "f4", ("Time", "south_north", "west_east")); lat[:] = 28.6
    lon = ds.createVariable("XLONG", "f4", ("Time", "south_north", "west_east")); lon[:] = 77.2
    tv = ds.createVariable("Times", "S1", ("Time", "DateStrLen")); tv[0, :] = list("2025-11-10_00:00:00")
    ds.close()
    try:
        extract_delhi_pm25_series(f)
    except RuntimeError as exc:
        assert "PM25_TOT or PM2_5_DRY" in str(exc)
    else:
        raise AssertionError("expected RuntimeError for a non-chem wrfout")
