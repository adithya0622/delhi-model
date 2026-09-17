"""Endpoint tests for /forecast/72hr-stations (offline).

The city forecast handler is mocked (the chronos/T5 machinery has its own
coverage in test_chronos_service.py); these tests pin the station-layer
contract: calibration over both city response shapes, honest error surfacing
when the city path is unusable, and auth on the refresh route.
"""
import asyncio
from datetime import datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.api.v1 import chronos_endpoint as ep
from app.services.station_forecast_service import load_offsets

CITY_HOURS = [
    {
        "hour_index": 1,
        "timestamp": "2026-09-17T10:00:00+05:30",
        "aqi_cpcb": 92,
        "pollutants": {
            "pm2_5": {"p50": 40.0, "p10": 30.0, "p90": 50.0},
            "pm10": {"p50": 80.0},
            "no2": {"p50": 30.0},
            "so2": {"p50": 10.0},
            "co": {"p50": 1000.0},
            "o3": {"p50": 45.0},
        },
    }
] * 72

ML_HOURS = [
    {
        "hour_index": 1,
        "timestamp": "2026-09-17T10:00:00+05:30",
        "aqi": 88,
        "sub_indices": [
            {"pollutant": "PM2.5", "concentration": 40.0, "sub_index": 67},
            {"pollutant": "PM10", "concentration": 80.0, "sub_index": 79},
            {"pollutant": "NO2", "concentration": 30.0, "sub_index": 38},
            {"pollutant": "SO2", "concentration": 10.0, "sub_index": 13},
            {"pollutant": "CO", "concentration": 1000.0, "sub_index": 50},
            {"pollutant": "O3", "concentration": 45.0, "sub_index": 45},
        ],
    }
] * 72


def _make_request(path: str = "/api/v1/forecast/72hr-stations") -> Request:
    scope = {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1", "method": "GET", "scheme": "http",
        "path": path, "raw_path": path.encode(), "query_string": b"",
        "root_path": "", "server": ("127.0.0.1", 8000), "client": ("127.0.0.1", 55590),
        "headers": [],
    }
    return Request(scope)


@pytest.fixture()
def _restore_state():
    """Snapshot module state the tests patch; restore after each test.

    Also blanks the offsets cache so endpoint tests are hermetic regardless
    of whether a real refresh has run on this machine (a saved artifact with
    measured/IQAir stations would otherwise leak into the assertions), and
    forces the per-zone layer OFF by default (offline tests) — individual
    tests re-enable it with a mock to exercise the zone path.
    """
    saved = {
        "city": ep.forecast_72hr_chronos,
        "serving_model": ep.serving_model,
        "status": ep.chronos_model_status,
        "weather": ep.fetch_forecast_weather,
        "zone_layer": ep.build_zone_station_layer,
    }
    import app.services.station_forecast_service as sfs
    saved_cache = sfs._OFFSETS_CACHE
    sfs._OFFSETS_CACHE = {"computed_at": None, "stations": {}}

    async def _no_network(*args, **kwargs):
        raise RuntimeError("offline test: weather fetch blocked")

    ep.fetch_forecast_weather = _no_network
    yield ep
    ep.forecast_72hr_chronos = saved["city"]
    ep.serving_model = saved["serving_model"]
    ep.chronos_model_status = saved["status"]
    ep.fetch_forecast_weather = saved["weather"]
    ep.build_zone_station_layer = saved["zone_layer"]
    sfs._OFFSETS_CACHE = saved_cache


def _mock_city(shape: str = "chronos"):
    if shape == "chronos":
        async def city(request, *, lat, lon, station_name, num_samples=20):
            return {"fallback_used": False, "hourly": CITY_HOURS, "model_name": "chronos"}
    else:
        async def city(request, *, lat, lon, station_name, num_samples=20):
            return {"fallback_used": True, "forecast_hours": ML_HOURS, "model": "ml"}
    return city


def test_zone_layer_served_when_available(_restore_state) -> None:
    """v2 path: when the per-zone layer computes, it IS the response core."""
    fake_layer = {
        "method": "per-zone Chronos",
        "zone_count": 7,
        "station_count": 50,
        "distinct_zone_curves": 7,
        "zones": [],
        "zone_failures": [],
        "stations": [],
        "most_polluted": [],
        "cleanest": [],
    }

    from datetime import datetime, timedelta
    t0 = datetime(2026, 9, 17, 13, 0)
    stamps = [(t0 + timedelta(hours=i)).isoformat() for i in range(72)]

    async def fake_weather(lat, lon):
        return {"hourly": {"time": stamps}}

    async def fake_zone_layer(forecast_times, origin, num_samples):
        assert len(forecast_times) == 72
        return fake_layer

    ep.fetch_forecast_weather = fake_weather
    ep.build_zone_station_layer = fake_zone_layer
    result = asyncio.run(ep.forecast_72hr_stations(
        _make_request(), lat=28.6139, lon=77.2090, station_name="X", num_samples=20
    ))
    assert result["model_name"] == "per-zone chronos (station layer v2)"
    assert result["station_layer"]["zone_count"] == 7
    assert result["station_layer"]["distinct_zone_curves"] == 7
    # The city path must NOT have been invoked (no fallback fields present).
    assert "fallback_used" not in result


def test_zone_failure_degrades_to_city_offsets(_restore_state) -> None:
    """When the zone layer returns None, the city-offset layer still serves."""
    from datetime import datetime, timedelta
    t0 = datetime(2026, 9, 17, 13, 0)
    stamps = [(t0 + timedelta(hours=i)).isoformat() for i in range(72)]

    async def fake_weather(lat, lon):
        return {"hourly": {"time": stamps}}

    async def none_layer(forecast_times, origin, num_samples):
        return None

    ep.fetch_forecast_weather = fake_weather
    ep.build_zone_station_layer = none_layer
    ep.forecast_72hr_chronos = _mock_city("chronos")
    result = asyncio.run(ep.forecast_72hr_stations(
        _make_request(), lat=28.6139, lon=77.2090, station_name="X", num_samples=20
    ))
    layer = result["station_layer"]
    assert layer is not None
    assert layer["station_count"] >= 40
    assert "city-scale series" in layer["method"]


def test_station_layer_over_chronos_shape(_restore_state) -> None:
    ep.forecast_72hr_chronos = _mock_city("chronos")
    result = asyncio.run(ep.forecast_72hr_stations(
        _make_request(), lat=28.6139, lon=77.2090, station_name="X", num_samples=20
    ))
    layer = result["station_layer"]
    assert layer is not None
    assert layer["station_count"] >= 40
    assert layer["stations_measured"] >= 0
    assert (
        layer["stations_measured"]
        + layer["stations_iqair_live"]
        + layer["stations_catalog_prior"]
        == layer["station_count"]
    )
    by_uid = {s["uid"]: s for s in layer["stations"]}
    av = by_uid["delhi-anand-vihar"]
    # Catalog prior (1.18) applied to the untouched city value (40.0).
    assert av["hourly"][0]["concentrations"]["pm25"] == round(40.0 * 1.18, 2)
    assert av["hourly"][0]["aqi_cpcb"] > 0
    assert av["hourly"][0]["aqi_category"]
    # The embedded city block is unmodified.
    assert result["hourly"][0]["pollutants"]["pm2_5"]["p50"] == 40.0


def test_station_layer_over_ml_fallback_shape(_restore_state) -> None:
    ep.forecast_72hr_chronos = _mock_city("ml")
    result = asyncio.run(ep.forecast_72hr_stations(
        _make_request(), lat=28.6139, lon=77.2090, station_name="X", num_samples=20
    ))
    layer = result["station_layer"]
    assert layer is not None
    station = layer["stations"][0]
    assert station["hourly"][0]["concentrations"]["pm25"] > 0
    assert station["hourly"][0]["aqi_cpcb"] > 0


def test_station_layer_error_is_honest_when_city_empty(_restore_state) -> None:
    async def broken_city(request, *, lat, lon, station_name, num_samples=20):
        return {"fallback_used": True, "forecast_hours": [], "model": "ml"}

    ep.forecast_72hr_chronos = broken_city
    result = asyncio.run(ep.forecast_72hr_stations(
        _make_request(), lat=28.6139, lon=77.2090, station_name="X", num_samples=20
    ))
    assert result["station_layer"] is None
    assert "station_layer_error" in result


def test_refresh_requires_api_key(_restore_state) -> None:
    from app.main import app

    client = TestClient(app)
    response = client.post("/api/v1/forecast/station-offsets/refresh")
    # Protected either way: 403 for a bad/missing key when APP_API_KEY is
    # configured, 503 when it is still the placeholder (mutation disabled).
    assert response.status_code in (401, 403, 503)


def test_measured_offset_flows_through_endpoint(_restore_state) -> None:
    import app.services.station_forecast_service as sfs

    sfs._OFFSETS_CACHE = {
        "computed_at": "2026-09-17T00:00:00+00:00",
        "stations": {"delhi-anand-vihar": {"pm25": {"ratio": 1.5, "n_hours": 900}}},
    }
    ep.forecast_72hr_chronos = _mock_city("chronos")
    result = asyncio.run(ep.forecast_72hr_stations(
        _make_request(), lat=28.6139, lon=77.2090, station_name="X", num_samples=20
    ))
    layer = result["station_layer"]
    assert layer["stations_measured"] == 1
    by_uid = {s["uid"]: s for s in layer["stations"]}
    av = by_uid["delhi-anand-vihar"]
    assert av["offset_basis"] == "measured"
    # Measured 1.5 beats the catalog 1.18.
    assert av["hourly"][0]["concentrations"]["pm25"] == 60.0
    assert av["hourly"][0]["adjustments"]["pm25"]["basis"] == "measured_openaq_vs_cams_cell"
    # Artifact timestamp is surfaced for transparency.
    assert layer["artifact_generated_at"] == "2026-09-17T00:00:00+00:00"
