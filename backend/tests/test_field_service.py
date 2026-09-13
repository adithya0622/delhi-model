"""N-station field math: IDW, spread sampling, summaries, CPCB pooling."""
from __future__ import annotations

from app.services.field_service import (
    build_idw_grid,
    haversine_km,
    idw_value,
    pool_cpcb_windows,
    spread_select,
    summarize_station_forecast,
)


def test_haversine_delhi_ludhiana_sane():
    # Delhi->Ludhiana ~300km; guards unit/radian mixups.
    d = haversine_km(28.6139, 77.2090, 30.9010, 75.8573)
    assert 250.0 < d < 350.0


def test_idw_exact_hit_returns_value():
    pts = [(28.6, 77.2, 100.0), (28.7, 77.3, 200.0)]
    assert idw_value(28.6, 77.2, pts) == 100.0


def test_idw_midpoint_averages_equal_weights():
    pts = [(0.0, 0.0, 100.0), (0.0, 2.0, 200.0)]
    assert abs(idw_value(0.0, 1.0, pts) - 150.0) < 1.0


def test_idw_requires_points():
    try:
        idw_value(0.0, 0.0, [])
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")


def test_grid_shape_and_keys():
    stations = [
        {"lat": 28.6, "lon": 77.2, "aqi": 100.0},
        {"lat": 28.7, "lon": 77.3, "aqi": 200.0},
    ]
    grid = build_idw_grid(stations, n_lat=4, n_lon=5)
    assert len(grid["lats"]) == 4
    assert len(grid["lons"]) == 5
    assert len(grid["values"]) == 4
    assert all(len(row) == 5 for row in grid["values"])


def test_spread_select_exact_length_and_spread():
    stations = [{"uid": str(i)} for i in range(10)]
    picked = spread_select(stations, 4)
    assert len(picked) == 4
    assert len({s["uid"] for s in picked}) == 4


def test_summarize_station_forecast_stats():
    station = {"uid": "x", "name": "Test", "lat": 28.6, "lon": 77.2}
    forecast = {
        "station_name": "Test",
        "forecast_hours": [
            {"aqi": 100, "sub_indices": [{"pollutant": "PM2.5", "concentration": 40.0}]},
            {"aqi": 200, "sub_indices": [{"pollutant": "PM2.5", "concentration": 120.0}]},
        ],
    }
    out = summarize_station_forecast(station, forecast)
    assert out["hourly_aqi"] == [100, 200]
    assert out["hourly_pm25"] == [40.0, 120.0]
    assert out["max_aqi_72h"] == 200
    assert out["mean_aqi_72h"] == 150.0


def test_pool_cpcb_windows_skill_sign():
    windows = [
        {"metrics": {"model_mae_horizon_ug_m3": 10.0, "persistence_mae_pm25_ug_m3": 20.0, "mae_pm25_ug_m3": 11.0}},
        {"metrics": {"model_mae_horizon_ug_m3": 30.0, "persistence_mae_pm25_ug_m3": 20.0, "mae_pm25_ug_m3": 29.0}},
    ]
    pooled = pool_cpcb_windows(windows)
    assert pooled["windows"] == 2
    assert pooled["pooled_model_mae_horizon_ug_m3"] == 20.0
    # (20 model vs 20 persistence) -> zero skill, sign trap guard.
    assert pooled["mae_skill_score"] == 0.0
