"""SAFAR/EWS reference provider: extraction must be shape-tolerant and honest.

Live fetches are network-dependent, so the HTTP fetch is exercised only for its
failure contract here; payload-shape handling is tested as pure logic.
"""
from __future__ import annotations

import pytest

from app.services.safar_service import _extract_series, _parse_forecast_page, safar_references


# ── Public bulletin-page parser (the globally reachable SAFAR fallback) ──────

_PAGE_BLOCK = (
    '{"title":\'Alipur\',\n'
    '       "lat":\'28.815329\',\n'
    '       "lng":\'77.15301\',\n'
    '       "description":\'<table><tr><td>Date</td><td>Category</td><td>AQI</td></tr>'
    '<tr><td align="left">2026-09-12</td><td>Good</td><td>NA</td></tr>'
    '<tr><td align="left">2026-09-14</td><td>Moderate</td><td>152</td></tr>'
    '</table>\' } , '
    '{"title":\'Anand Vihar\',\n'
    '       "lat":\'28.646835\',\n'
    '       "lng":\'77.316032\',\n'
    '       "description":\'<table><tr><td>Date</td><td>Category</td><td>AQI</td></tr>'
    '<tr><td align="left">2026-09-12</td><td>Poor</td><td>301</td></tr></table>\' }'
)


def test_parse_forecast_page_stations_and_days():
    stations = _parse_forecast_page(_PAGE_BLOCK)
    assert [s["name"] for s in stations] == ["Alipur", "Anand Vihar"]
    alipur = stations[0]
    assert alipur["lat"] == pytest.approx(28.815329)
    assert alipur["lon"] == pytest.approx(77.15301)
    assert alipur["forecasts"][0] == {"date": "2026-09-12", "category": "Good", "aqi": None}
    assert alipur["forecasts"][1] == {"date": "2026-09-14", "category": "Moderate", "aqi": 152}
    assert stations[1]["forecasts"][0]["aqi"] == 301


def test_parse_forecast_page_skips_blocks_without_coords_or_rows():
    html = _PAGE_BLOCK + ' {"title":\'NoCoords\', "description":\'<table></table>\' }'
    assert [s["name"] for s in _parse_forecast_page(html)] == ["Alipur", "Anand Vihar"]
    assert _parse_forecast_page("<html>nothing here</html>") == []


def test_extract_series_flat_list_with_mixed_case_keys():
    payload = [
        {"DateTime": "2025-11-10 00:00", "PM2.5": "145", "PM10": 300, "O3": "23"},
        {"DateTime": "2025-11-10 01:00", "pm25": "150.5", "PM10": None, "o3": None},
    ]
    series = _extract_series(payload)
    assert len(series) == 2
    assert series[0]["pm25"] == 145.0
    assert series[0]["pm10"] == 300.0
    assert series[0]["o3"] == 23.0
    # Missing species stay None — never zero, never dropped.
    assert series[1]["pm10"] is None
    assert series[1]["time"] == "2025-11-10 01:00"


def test_extract_series_wrapped_dict_shapes():
    wrapped = {"data": {"rows": [{"date": "2025-11-10T00", "pm25": 100.0}]}}
    assert _extract_series(wrapped)[0]["pm25"] == 100.0
    records = {"records": [{"time": "t1", "no2": 40.0}]}
    assert _extract_series(records)[0]["no2"] == 40.0
    flat = {"pollution_data": [{"DateTime": "2025-11-10 02:00", "PM2.5": 90.0}]}
    assert _extract_series(flat)[0]["pm25"] == 90.0


def test_extract_series_rejects_rows_without_time_or_values():
    payload = [
        {"no_time": 1},                       # no timestamp key
        {"DateTime": "2025-11-10 03:00"},     # timestamp but no pollutant values
        "not-a-dict",
    ]
    assert _extract_series(payload) == []


def test_extract_series_unparseable_values_become_none_not_crash():
    payload = [{"DateTime": "2025-11-10 04:00", "PM2.5": "n/a", "PM10": "—"}]
    series = _extract_series(payload)
    assert series == []  # no numeric values at all -> row dropped honestly


def test_extract_series_empty_inputs():
    assert _extract_series([]) == []
    assert _extract_series({}) == []
    assert _extract_series(None) == []


def test_safar_references_are_keyless_and_pointed():
    refs = safar_references()
    assert refs["api_key_required"] is False
    assert "WRF-Chem" in refs["model_class"]
    for page in ("safar_delhi", "ews_delhi"):
        assert refs["bulletin_pages"][page].startswith("https://")
