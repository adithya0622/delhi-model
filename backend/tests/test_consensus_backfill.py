"""Consensus Open-Meteo backfill: temp/wind must come from live weather hourly."""
from __future__ import annotations

from app.services.consensus_service import ProviderResult, _backfill_open_meteo_weather


def test_backfill_fills_missing_temp_wind():
    aq = ProviderResult(source="Open-Meteo", pm25=65.7, temp=None, wind=None)
    out = _backfill_open_meteo_weather(aq, {"temperature_2m": [29.1], "wind_speed_10m": [6.8]})
    assert out["temp"] == 29.1
    assert out["wind"] == 6.8


def test_backfill_never_overwrites_observed():
    aq = ProviderResult(source="Open-Meteo", pm25=65.7, temp=30.0, wind=7.0)
    out = _backfill_open_meteo_weather(aq, {"temperature_2m": [29.1], "wind_speed_10m": [6.8]})
    assert out["temp"] == 30.0
    assert out["wind"] == 7.0


def test_backfill_tolerates_empty_hourly():
    aq = ProviderResult(source="Open-Meteo", pm25=65.7, temp=None, wind=None)
    out = _backfill_open_meteo_weather(aq, {})
    assert out["temp"] is None
    assert out["wind"] is None
