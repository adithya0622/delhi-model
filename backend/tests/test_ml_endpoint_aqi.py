"""Pure-function tests for the /forecast/72hr-ml AQI arithmetic.

The HTTP endpoint needs live weather providers, so the max-of-sub-indices
computation was extracted into `compute_hour_aqi` and is tested directly —
the same pattern the box-model and AQI-scale tests use.
"""
from __future__ import annotations

import math

import pytest

from app.api.v1.ml_forecast_endpoint import (
    _FALLBACK_UG_M3,
    _canonicalise_chemistry,
    compute_hour_aqi,
)


# ── Max rule ─────────────────────────────────────────────────────────────────

def test_pm25_dominant_in_typical_winter():
    concentrations = {"pm25": 180.0, "pm10": 300.0, "no2": 60.0, "o3": 40.0, "so2": 20.0, "co": 800.0}
    block = compute_hour_aqi(concentrations, "instant")
    # CPCB PM2.5 180 → between 120-250 → sub-index 301-400 band ≈ 344; PM10 300 → 229.
    assert block["dominant_pollutant"] == "PM2.5"
    assert block["aqi"] == block["sub_indices"][0]["sub_index"]
    assert max(s["sub_index"] for s in block["sub_indices"]) == block["aqi"]


def test_ozone_can_override_pm25():
    # PM2.5 = 60 → CPCB sub-index 102; O3 = 150 → CPCB sub-index ≈ 197. O3 wins.
    concentrations = {"pm25": 60.0, "pm10": 70.0, "no2": 20.0, "o3": 150.0, "so2": 10.0, "co": 500.0}
    block = compute_hour_aqi(concentrations, "instant")
    assert block["dominant_pollutant"] == "O3"
    assert block["aqi"] > 100


def test_pm10_dust_spike_can_override_pm25():
    # PM2.5 = 60 → 102; PM10 = 420 → sub-index ≈ 395. PM10 wins.
    concentrations = {"pm25": 60.0, "pm10": 420.0, "no2": 20.0, "o3": 30.0, "so2": 10.0, "co": 500.0}
    block = compute_hour_aqi(concentrations, "instant")
    assert block["dominant_pollutant"] == "PM10"


def test_epa_and_cpcb_can_disagree_on_dominant():
    # EPA PM2.5 at 180 µg/m³ → sub-index 233; CPCB → 344. Same species, both
    # standards must still apply the max rule independently.
    concentrations = {"pm25": 180.0, "pm10": 300.0, "no2": 60.0, "o3": 40.0, "so2": 20.0, "co": 800.0}
    cpcb = compute_hour_aqi(concentrations, "instant")
    epa = compute_hour_aqi(concentrations, "epa")
    assert cpcb["aqi"] >= 300
    assert 200 <= epa["aqi"] < 300
    assert epa["category"] != cpcb["category"]  # different band names by design


# ── Missing data must not win or masquerade ──────────────────────────────────

def test_missing_species_score_zero_and_cannot_be_dominant():
    concentrations = {"pm25": None, "pm10": None, "no2": None, "o3": None, "so2": None, "co": None}
    block = compute_hour_aqi(concentrations, "instant")
    assert block["aqi"] == 0
    assert block["dominant_pollutant"] == "unknown"
    assert all(s["sub_index"] == 0 for s in block["sub_indices"])


def test_nan_and_negative_rejected():
    concentrations = {"pm25": float("nan"), "pm10": -5.0, "no2": 40.0, "o3": None, "so2": None, "co": None}
    block = compute_hour_aqi(concentrations, "instant")
    by_name = {s["pollutant"]: s for s in block["sub_indices"]}
    assert by_name["PM2.5"]["sub_index"] == 0
    assert by_name["PM10"]["sub_index"] == 0
    assert by_name["NO2"]["sub_index"] > 0
    assert block["dominant_pollutant"] == "NO2"


# ── CPCB breakpoint interpolation (spot checks against the 2014 table) ──────

def test_cpcb_pm25_breakpoint_interpolation():
    # 45 µg/m³ sits in the 30-60 → 51-100 segment: 51 + 49*(15/30) = 75.5 → 76.
    block = compute_hour_aqi({"pm25": 45.0}, "instant")
    assert block["sub_indices"][0]["sub_index"] == 76


def test_cpcb_co_converts_mg_per_m3():
    # Canonical 2100 µg/m³ = 2.1 mg/m³ sits inside the CPCB 2-10 → 101-200
    # segment: 101 + 99*(0.1/8) ≈ 102. (Exactly 2.0 mg/m³ is the segment edge
    # and belongs to the 1-2 segment below — the interpolator returns 100 there,
    # which is the standard's own boundary convention.)
    block = compute_hour_aqi({"co": 2100.0}, "instant")
    assert block["sub_indices"][5]["sub_index"] == 102


def test_epa_pm25_uses_2024_breakpoints():
    # 9.0 µg/m³ → EPA 2024 first breakpoint edge → sub-index 50.
    block = compute_hour_aqi({"pm25": 9.0}, "epa")
    assert block["sub_indices"][0]["sub_index"] == 50
    assert block["aqi"] == 50


# ── CO unit canonicalisation ─────────────────────────────────────────────────

def test_canonicalise_chemistry_scales_open_meteo_co_to_ug():
    chem = {"co": [0.45, 0.5, None]}
    out = _canonicalise_chemistry(chem, "open-meteo-aq-reconstructed")
    assert out["co"] == [450.0, 500.0, None]


def test_canonicalise_chemistry_leaves_weatherapi_co_untouched():
    chem = {"co": [450.0, 500.0]}
    out = _canonicalise_chemistry(chem, "weatherapi")
    assert out["co"] == [450.0, 500.0]


def test_canonicalise_chemistry_copies_other_species():
    chem = {"pm2_5": [10.0, 20.0], "no2": [30.0]}
    out = _canonicalise_chemistry(chem, "open-meteo")
    assert out["pm2_5"] == [10.0, 20.0]
    assert out["no2"] == [30.0]


# ── Fallback table sanity ────────────────────────────────────────────────────

def test_fallbacks_are_positive_and_canonical():
    for key, value in _FALLBACK_UG_M3.items():
        assert math.isfinite(value) and value > 0
    # CO fallback is canonical µg/m³ (0.45 mg/m³), matching the old default.
    assert _FALLBACK_UG_M3["co"] == pytest.approx(450.0)
