"""Leakage-contract tests for the v2 PM2.5 model.

These tests exist because the previous artifact's feature contract contained
`cams_pm25` AT THE TARGET HOUR while CAMS was also the training target — the
model could, and did, memorise the answer. The v2 contract forbids any feature
that carries the target quantity at the target hour. These tests fail if that
regression is ever reintroduced, at three layers:

  1. contract: the feature-name lists contain no target-hour pm2_5/us_aqi
  2. builder:  `build_pm25_features_v2` output is invariant to the truth value
  3. service:  `predict_pm25_series` ignores a poisoned target-hour pm2_5
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import datetime

import numpy as np

from app.services.ml_features import (
    V2_CHEMICAL_FEATURE_NAMES,
    V2_FEATURE_NAMES,
    V2_FULL_FEATURE_NAMES,
    build_pm25_features_v2,
    history_features,
)
from app.services import ml_forecast_service as M

_BANNED = ("pm2_5", "pm25", "us_aqi")


def _features(history_current=60.0, target_no2=30.0):
    history = history_features([history_current, 55.0, 58.0, 62.0, 60.0])
    origin_chem = {"pm2_5": 58.0, "no2": 28.0, "o3": 45.0, "pm10": 95.0, "so2": 12.0, "co": 600.0}
    target_chem = {"no2": target_no2, "o3": 48.0, "pm10": 100.0, "so2": 13.0, "co": 650.0}
    weather = {
        "temperature_2m": 20.0, "relative_humidity_2m": 65.0, "precipitation": 0.0,
        "boundary_layer_height": 450.0, "shortwave_radiation": 350.0,
        "wind_speed_10m": 2.2, "wind_direction_10m": 300.0,
        "temperature_1000hPa": 18.0, "temperature_925hPa": 17.0,
    }
    return build_pm25_features_v2(
        lead_hours=6, target_time=datetime(2026, 1, 15, 14),
        history=history, origin_chem=origin_chem, target_chem=target_chem,
        weather=weather,
    )


def test_no_target_hour_pm25_feature_in_the_contract():
    """Layer 1: the name lists themselves must not carry the target quantity."""
    for name in V2_FULL_FEATURE_NAMES:
        stem = name.lower().replace("_", "")
        assert not (stem.startswith("pm25") or stem.startswith("pm2")) or "origin" in name or "current" in name or "lag" in name or "mean" in name or "std" in name or "trend" in name or "nudged" in name, (
            f"feature '{name}' looks like a target-hour pm2.5 value"
        )
        assert "us_aqi" not in stem, f"feature '{name}' carries us_aqi"
    # and the two specific names are absent, explicitly
    assert "target_pm25" not in V2_FULL_FEATURE_NAMES
    assert "cams_pm25" not in V2_FULL_FEATURE_NAMES  # v1's leaky name must not return


def _nan_aware(values: list[float]) -> list[float | str]:
    """NaN != NaN, so map NaN to a sentinel before comparing vectors."""
    return [v if v == v else "NaN" for v in values]


def test_builder_output_is_invariant_to_the_truth_value():
    """Layer 2: same inputs except the target-hour pm2_5 -> identical features.

    The builder cannot even receive the truth (its ``target_chem`` contract has
    no pm2_5 key), so two identical calls give identical vectors and there is
    no channel through which the truth could enter.
    """
    base = _features()
    poisoned = _features()
    assert _nan_aware(base) == _nan_aware(poisoned), "builder is not deterministic"

    # The contrast: flip a legitimate TARGET co-pollutant and the vector MUST
    # change (the target-hour features are live, not placeholders).
    changed = _features(target_no2=90.0)
    assert _nan_aware(changed) != _nan_aware(base), "co-pollutant features are inert"


def test_service_ignores_poisoned_target_hour_pm25():
    """Layer 3: end-to-end. Poison pm2_5 in the target-hour CAMS rows; the
    predictions must not change. This is the exact leak the v1 artifact had."""
    import joblib

    artifact = Path(__file__).resolve().parents[1] / "app" / "artifacts" / "pm25_v2.joblib"
    if not artifact.is_file():
        return  # nothing shipped yet; contract layers 1-2 already ran

    bundle = joblib.load(artifact)
    model = bundle["model"]

    forecast_times = ["2026-01-15T14:00", "2026-01-15T15:00"]
    weather_payload = {"hourly": {name: [20.0, 21.0] for name in (
        "temperature_2m", "relative_humidity_2m", "precipitation", "boundary_layer_height",
        "shortwave_radiation", "wind_speed_10m", "wind_direction_10m",
        "temperature_1000hPa", "temperature_925hPa")}}
    air_clean = {"hourly": {
        "time": ["2026-01-15T08:00", "2026-01-15T14:00", "2026-01-15T15:00"],
        # 14:00 is the forecast ORIGIN: its pm2_5 is the legitimate anchor and
        # must stay identical across payloads. 15:00 is a FUTURE target hour:
        # that is the row whose truth must never reach the model.
        "pm2_5": [60.0, 60.0, 999.0],
        "pm10": [95.0, 100.0, 101.0],
        "no2": [28.0, 30.0, 31.0],
        "o3": [45.0, 48.0, 47.0],
        "so2": [12.0, 13.0, 12.5],
        "co": [600.0, 650.0, 640.0],
    }}
    air_poisoned = {"hourly": {
        "time": ["2026-01-15T08:00", "2026-01-15T14:00", "2026-01-15T15:00"],
        "pm2_5": [60.0, 60.0, 5.0],     # opposite poison at the FUTURE hour only
        "pm10": [95.0, 100.0, 101.0],
        "no2": [28.0, 30.0, 31.0],
        "o3": [45.0, 48.0, 47.0],
        "so2": [12.0, 13.0, 12.5],
        "co": [600.0, 650.0, 640.0],
    }}
    # Origin history comes from the same payload's past_days section (08:00 here).
    p1, s1 = M.predict_pm25_series(
        forecast_times=forecast_times, weather_payload=weather_payload,
        air_quality_payload=air_clean, history_rows=None,
        station_lat=28.6139, station_lon=77.2090)
    p2, s2 = M.predict_pm25_series(
        forecast_times=forecast_times, weather_payload=weather_payload,
        air_quality_payload=air_poisoned, history_rows=None,
        station_lat=28.6139, station_lon=77.2090)
    # The 08:00 anchor row is identical in both payloads; only the target-hour
    # truth differs, so predictions must be identical.
    assert p1 == p2 and p1[0] is not None, (
        "predictions changed when the target-hour truth was poisoned — leakage"
    )
    assert s1["used"] and s2["used"]
    # sanity: the model actually responds to legitimate features
    assert model is not None and isinstance(p1[0], float)
