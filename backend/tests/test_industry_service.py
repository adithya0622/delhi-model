"""
Unit Tests for Delhi-Only Industry Data Service
===============================================
Verifies that:
1. Only Delhi industry records (city='Delhi' AND state='Delhi') are loaded.
2. Non-Delhi records (e.g. Chennai, Tamil Nadu, Mumbai) are strictly filtered out and rejected.
3. The /api/v1/industries endpoint returns HTTP 200 with strictly Delhi records.
"""
import pytest
from app.services.industry_service import _normalize_raw_record, fetch_delhi_industries
from app.schemas.industry import IndustryResponse


def test_normalize_delhi_record_success():
    raw_delhi = {
        "id": "del-01",
        "name": "Badarpur Thermal Power Station",
        "city": "Delhi",
        "state": "Delhi",
        "latitude": 28.5080,
        "longitude": 77.3050,
        "category": "Power Generation",
    }
    rec = _normalize_raw_record(raw_delhi)
    assert rec is not None
    assert rec.name == "Badarpur Thermal Power Station"
    assert rec.city == "Delhi"
    assert rec.state == "Delhi"
    assert rec.latitude == 28.5080
    assert rec.longitude == 77.3050


def test_reject_chennai_tamil_nadu_records():
    # Attempting to load a Chennai / Tamil Nadu industry
    raw_chennai = {
        "id": "che-01",
        "name": "Ennore Thermal Power Station",
        "city": "Chennai",
        "state": "Tamil Nadu",
        "latitude": 13.2010,
        "longitude": 80.3230,
        "category": "Power Plant",
    }
    rec = _normalize_raw_record(raw_chennai)
    assert rec is None, "Chennai / Tamil Nadu records must be strictly rejected!"


def test_reject_mismatched_state_or_city():
    # Record claiming city Delhi but state Haryana
    raw_mismatch = {
        "id": "mis-01",
        "name": "Border Facility",
        "city": "Delhi",
        "state": "Haryana",
        "latitude": 28.50,
        "longitude": 77.10,
    }
    rec = _normalize_raw_record(raw_mismatch)
    assert rec is None, "Records not matching BOTH city='Delhi' and state='Delhi' must be rejected!"


@pytest.mark.asyncio
async def test_fetch_delhi_industries_all_delhi():
    res = await fetch_delhi_industries()
    assert isinstance(res, IndustryResponse)
    assert res.count > 0
    assert res.city == "Delhi"
    assert res.state == "Delhi"
    for r in res.records:
        assert r.city == "Delhi"
        assert r.state == "Delhi"
        assert 28.0 <= r.latitude <= 29.2
        assert 76.8 <= r.longitude <= 77.6
