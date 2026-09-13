"""
Unit tests for City Aggregate (CPCB Multi-Pollutant Maximum Rule).
"""

import pytest
from app.services.aqi_service import compute_city_aggregate


@pytest.mark.asyncio
async def test_compute_city_aggregate():
    res = await compute_city_aggregate(mode="instant")
    assert res.overall_aqi > 0
    assert res.station_count > 0
    assert res.dominant_pollutant in ["PM2.5", "PM10", "O3", "NO2", "SO2", "CO"]
    assert res.aqi_category in ["Good", "Satisfactory", "Moderate", "Poor", "Very Poor", "Severe"]
    assert "PM2.5" in res.sub_indices
    assert "O3" in res.sub_indices
    
    # Check that overall_aqi is genuinely the maximum sub-index
    max_idx = max(d.index for d in res.sub_indices.values())
    assert res.overall_aqi == max_idx
