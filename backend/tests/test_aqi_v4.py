"""v4 direct-AQI model: target consistency, leakage contract, serving fallback.

The defining property of v4 is that the TRAINING target and the SERVING
computed block come from the same breakpoint tables — so the first test below
is a consistency proof, not a spot check. The leakage test mirrors
test_ml_contract.py but for the AQI heads: poisoning target-hour pm2_5 must
not move a predicted AQI.
"""
from __future__ import annotations

import numpy as np
import pytest

from app.api.v1.ml_forecast_endpoint import _canonicalise_chemistry, compute_hour_aqi
from app.services import ml_forecast_service as svc
from app.services.ml_features import compute_aqi_targets


# ── Target builder ───────────────────────────────────────────────────────────

CONC_SETS = [
    {"pm25": 180.0, "pm10": 300.0, "no2": 60.0, "o3": 40.0, "so2": 20.0, "co": 800.0},
    {"pm25": 60.0, "pm10": 70.0, "no2": 20.0, "o3": 150.0, "so2": 10.0, "co": 500.0},
    {"pm25": 45.0, "pm10": 90.0, "no2": 30.0, "o3": 25.0, "so2": 8.0, "co": 900.0},
    {"pm25": 300.0, "pm10": 420.0, "no2": 90.0, "o3": 60.0, "so2": 40.0, "co": 2000.0},
]


@pytest.mark.parametrize("conc", CONC_SETS)
def test_targets_match_serving_computed_block_exactly(conc):
    """Trainer target == endpoint computed AQI, for every concentration set."""
    cpcb, epa = compute_aqi_targets(conc)
    assert cpcb == compute_hour_aqi(conc, "instant")["aqi"]
    assert epa == compute_hour_aqi(conc, "epa")["aqi"]


def test_targets_missing_species_score_zero():
    assert compute_aqi_targets({k: None for k in ("pm25", "pm10", "no2", "o3", "so2", "co")}) == (0, 0)


def test_targets_partial_data_uses_available_species():
    cpcb, epa = compute_aqi_targets({"no2": 40.0})
    assert cpcb == compute_hour_aqi({"no2": 40.0}, "instant")["aqi"] > 0
    assert epa == compute_hour_aqi({"no2": 40.0}, "epa")["aqi"]


def test_targets_reject_nan_negative_and_clamp_500():
    cpcb, _ = compute_aqi_targets({"pm25": float("nan"), "pm10": -5.0, "o3": 30.0})
    assert cpcb == compute_hour_aqi({"o3": 30.0}, "instant")["aqi"]
    cpcb2, _ = compute_aqi_targets({"pm25": 10_000.0})
    assert cpcb2 == 500


# ── Serving: fallback + rejection contract ──────────────────────────────────

@pytest.fixture()
def _clear_v4_cache():
    svc._load_v4_bundle.cache_clear()
    yield
    svc._load_v4_bundle.cache_clear()


def _payload_set():
    times = [f"2026-11-10T{h:02d}:00" for h in range(6)]
    weather = {"hourly": {
        "time": times,
        "temperature_2m": [20.0] * 6,
        "relative_humidity_2m": [50.0] * 6,
        "precipitation": [0.0] * 6,
        "boundary_layer_height": [600.0] * 6,
        "shortwave_radiation": [100.0] * 6,
        "wind_speed_10m": [2.0] * 6,
        "wind_direction_10m": [270.0] * 6,
        "temperature_1000hPa": [20.0] * 6,
        "temperature_925hPa": [18.0] * 6,
    }}
    air = {"hourly": {
        "time": times,
        "pm2_5": [80.0] * 6,
        "pm10": [150.0] * 6,
        "no2": [40.0] * 6,
        "o3": [30.0] * 6,
        "so2": [10.0] * 6,
        "co": [1.0] * 6,  # Open-Meteo CAMS delivers mg/m³; canonicalised ×1000
    }}
    history = [{"timestamp": t, "value_ug_m3": 80.0} for t in times]
    return times, weather, air, history


class _StubModel:
    def predict(self, X):
        return np.full(len(X), 123.0)


def test_predict_aqi_series_absent_artifact_returns_none(_clear_v4_cache, monkeypatch):
    monkeypatch.setattr(svc, "_load_v4_bundle", lambda: None)
    times, weather, air, history = _payload_set()
    cpcb, epa, status = svc.predict_aqi_series(
        forecast_times=times, weather_payload=weather,
        air_quality_payload=air, history_rows=history,
    )
    assert cpcb == [None] * 6 and epa == [None] * 6
    assert status["available"] is False and status["used"] is False


def test_loader_rejects_unaccepted_or_mismatched_artifact(tmp_path, monkeypatch, _clear_v4_cache):
    """A bundle whose gates failed, or whose contract drifted, never serves."""
    import joblib

    p = tmp_path / "aqi_v4.joblib"
    fake = {
        "feature_names": svc.V3_FEATURE_NAMES,
        "metadata": {"accepted": False},
        "model_full": _StubModel(),
    }
    joblib.dump(fake, p)
    monkeypatch.setattr(svc, "_V4_PATH", p)
    svc._load_v4_bundle.cache_clear()
    try:
        assert svc._load_v4_bundle() is None  # gates failed -> rejected
        fake["metadata"]["accepted"] = True
        joblib.dump(fake, p)
        svc._load_v4_bundle.cache_clear()
        assert svc._load_v4_bundle() is not None  # gates passed -> served
        fake["feature_names"] = ["wrong", "contract"]
        joblib.dump(fake, p)
        svc._load_v4_bundle.cache_clear()
        assert svc._load_v4_bundle() is None  # schema drift -> rejected
    finally:
        svc._load_v4_bundle.cache_clear()


def test_predict_aqi_series_stub_model_predicts_directly(_clear_v4_cache, monkeypatch):
    fake = {
        "feature_names": svc.V3_FEATURE_NAMES,
        "model_winter": _StubModel(),
        "model_non_winter": _StubModel(),
        "model_full": _StubModel(),
        "model_epa": _StubModel(),
        "metadata": {"accepted": True, "model_version": "v4-test"},
    }
    monkeypatch.setattr(svc, "_load_v4_bundle", lambda: fake)
    times, weather, air, history = _payload_set()
    cpcb, epa, status = svc.predict_aqi_series(
        forecast_times=times, weather_payload=weather,
        air_quality_payload=air, history_rows=history,
    )
    assert cpcb == [123] * 6
    assert epa == [123] * 6
    assert status["used"] is True and status["hours_used"] == 6


def test_predict_aqi_series_poisoned_target_pm25_changes_nothing(_clear_v4_cache, monkeypatch):
    """The v4 leakage contract: target-hour pm2_5 must not reach the features."""
    fake = {
        "feature_names": svc.V3_FEATURE_NAMES,
        "model_winter": _StubModel(),
        "model_non_winter": _StubModel(),
        "model_full": _StubModel(),
        "model_epa": _StubModel(),
        "metadata": {"accepted": True},
    }
    monkeypatch.setattr(svc, "_load_v4_bundle", lambda: fake)
    times, weather, air, history = _payload_set()

    poisoned_air = {**air, "hourly": {**air["hourly"], "pm2_5": [5000.0] * 6}}
    cpcb_clean, _, _ = svc.predict_aqi_series(
        forecast_times=times, weather_payload=weather,
        air_quality_payload=air, history_rows=history,
    )
    cpcb_poison, _, _ = svc.predict_aqi_series(
        forecast_times=times, weather_payload=weather,
        air_quality_payload=poisoned_air, history_rows=history,
    )
    assert cpcb_clean == cpcb_poison


def test_predict_pm25_series_still_works_after_refactor(_clear_v4_cache, monkeypatch):
    """The v3/v2 path must be unchanged by the shared-row refactor."""
    class _StubV3:
        def predict(self, X):
            return np.full(len(X), 55.5)

    fake_v3 = {
        "feature_names": svc.V3_FEATURE_NAMES,
        "model_winter": _StubV3(),
        "model_non_winter": _StubV3(),
        "model_full": _StubV3(),
        "metadata": {"accepted": True, "model_version": "v3-test"},
    }
    monkeypatch.setattr(svc, "_load_v3_bundle", lambda: fake_v3)
    monkeypatch.setattr(svc, "model_status", lambda: {"available": True, "mode": "v3_seasonal_sub_models"})
    times, weather, air, history = _payload_set()
    preds, status = svc.predict_pm25_series(
        forecast_times=times, weather_payload=weather,
        air_quality_payload=air, history_rows=history,
        station_lat=28.6, station_lon=77.2,
    )
    assert preds == [55.5] * 6
    assert status["used"] is True


# ── Endpoint: served-AQI selection logic (offline via monkeypatched providers) ──

@pytest.fixture()
def _offline_endpoint(monkeypatch):
    times, weather, air, history = _payload_set()
    from starlette.requests import Request

    def make_request():
        scope = {
            "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1", "method": "GET", "scheme": "http",
            "path": "/api/v1/forecast/72hr-ml", "raw_path": b"/api/v1/forecast/72hr-ml",
            "query_string": b"", "root_path": "", "server": ("127.0.0.1", 8000),
            "client": ("127.0.0.1", 55590), "headers": [],
        }
        return Request(scope)

    async def fake_met(lat, lon):
        return {**weather, "weather_source": "open-meteo", "chemistry": air["hourly"], "provider_failures": []}

    async def fake_iqair():
        return {"pm25": 80.0, "aqi": 150}

    ep_mod = pytest.importorskip("app.api.v1.ml_forecast_endpoint")
    monkeypatch.setattr(ep_mod, "fetch_forecast_weather", fake_met)
    monkeypatch.setattr(ep_mod, "fetch_iqair_realtime", fake_iqair)
    monkeypatch.setattr(ep_mod, "model_status", lambda: {"available": True, "mode": "v3"})
    return ep_mod, make_request, times


def test_endpoint_serves_predicted_aqi_primary(_offline_endpoint, monkeypatch, _clear_v4_cache):
    ep_mod, make_request, times = _offline_endpoint
    def fake_pm25(**kwargs):
        return [80.0] * len(times), {"available": True, "used": True}
    def fake_aqi(**kwargs):
        return [200] * len(times), [180] * len(times), {"available": True, "used": True}
    monkeypatch.setattr(ep_mod, "predict_pm25_series", fake_pm25)
    monkeypatch.setattr(ep_mod, "predict_aqi_series", fake_aqi)

    import asyncio
    result = asyncio.run(ep_mod.forecast_72hr_ml(make_request(), lat=28.6139, lon=77.2090, station_name="X"))
    h0 = result["forecast_hours"][0]
    assert h0["aqi"] == 200
    assert h0["aqi_source"] == "direct ML v4"
    assert h0["aqi_computed"] == compute_hour_aqi(
        {"pm25": 80.0, "pm10": 150.0, "no2": 40.0, "o3": 30.0, "so2": 10.0, "co": 1000.0}, "instant"
    )["aqi"]
    assert h0["epa"]["aqi"] == 180
    assert result["aqi_model"]["used"] is True


def test_endpoint_falls_back_to_computed_when_v4_missing(_offline_endpoint, monkeypatch, _clear_v4_cache):
    ep_mod, make_request, times = _offline_endpoint
    def fake_pm25(**kwargs):
        return [80.0] * len(times), {"available": True, "used": True}
    def fake_aqi(**kwargs):
        return [None] * len(times), [None] * len(times), {"available": False, "used": False}
    monkeypatch.setattr(ep_mod, "predict_pm25_series", fake_pm25)
    monkeypatch.setattr(ep_mod, "predict_aqi_series", fake_aqi)

    import asyncio
    result = asyncio.run(ep_mod.forecast_72hr_ml(make_request(), lat=28.6139, lon=77.2090, station_name="X"))
    h0 = result["forecast_hours"][0]
    assert h0["aqi_source"] == "computed from concentrations"
    assert h0["aqi"] == h0["aqi_computed"]
