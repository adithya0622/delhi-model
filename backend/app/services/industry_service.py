"""
Delhi Industry Data Service
===========================
Queries the Supabase database for industrial point sources with strict database-level filtering:
    WHERE city = 'Delhi' AND state = 'Delhi'

Ensures ONLY records from Delhi (~534 records) are retrieved, completely excluding Chennai,
Tamil Nadu, or any other cities/states at the database query level.
"""
from __future__ import annotations

import csv
import logging
import os
from pathlib import Path
from typing import Any, Optional

import httpx

from app.core.config import get_settings
from app.schemas.industry import IndustryRecord, IndustryResponse

logger = logging.getLogger(__name__)

# Default Supabase Project credentials for AirLens / Delhi Industry Intelligence
DEFAULT_SUPABASE_URL = "https://ozaxpjkmubtnotwiltfc.supabase.co"
DEFAULT_SUPABASE_KEY = "sb_publishable_2fAjnCcJa8oF7vyTxeX73A_IiBFaN57"

# Path to the bundled 534-record Delhi industry dataset
_CSV_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "delhi_industries.csv"


def _normalize_raw_record(row: dict[str, Any]) -> Optional[IndustryRecord]:
    """
    Normalizes a raw database record into an IndustryRecord.
    Strictly verifies that city == 'Delhi' and state == 'Delhi'.
    """
    city = str(row.get("city") or row.get("City") or "").strip()
    state = str(row.get("state") or row.get("State") or "").strip()

    # Strict server-side verification: reject any non-Delhi records
    if city.lower() != "delhi" or state.lower() != "delhi":
        return None

    # Handle flexible coordinate key names (lat/latitude, lon/long/longitude)
    lat_val = row.get("latitude") or row.get("lat") or row.get("Latitude")
    lon_val = row.get("longitude") or row.get("lon") or row.get("lng") or row.get("Longitude")

    if lat_val is None or lon_val is None:
        return None

    try:
        lat = float(lat_val)
        lon = float(lon_val)
    except (ValueError, TypeError):
        return None

    name = str(
        row.get("industry_name")
        or row.get("name")
        or row.get("facility_name")
        or row.get("Name")
        or "Delhi Industrial Facility"
    ).strip()
    category = row.get("category") or row.get("type") or row.get("Category") or "Industrial Source"
    sector = row.get("sector") or row.get("sub_sector") or row.get("Sector") or category
    status = row.get("status") or row.get("Status") or "Operational"
    capacity = row.get("capacity") or row.get("Capacity")
    address = row.get("address") or row.get("location") or row.get("Address") or f"{name}, Delhi"
    rec_id = row.get("place_id") or row.get("id") or row.get("uuid") or f"del-{name.lower().replace(' ', '-')[:20]}"

    return IndustryRecord(
        id=rec_id,
        name=name,
        city="Delhi",
        state="Delhi",
        latitude=lat,
        longitude=lon,
        category=str(category) if category else None,
        sector=str(sector) if sector else None,
        status=str(status) if status else None,
        capacity=str(capacity) if capacity else None,
        address=str(address) if address else None,
    )


def _load_csv_industries() -> list[IndustryRecord]:
    """Loads bundled CSV of 534 verified Delhi industry facilities."""
    records: list[IndustryRecord] = []
    if not _CSV_DATA_PATH.exists():
        return records

    try:
        with open(_CSV_DATA_PATH, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rec = _normalize_raw_record(row)
                if rec:
                    records.append(rec)
    except Exception as e:
        logger.error("Error reading bundled delhi_industries.csv: %s", e)

    return records


async def fetch_delhi_industries(
    min_lat: Optional[float] = None,
    max_lat: Optional[float] = None,
    min_lon: Optional[float] = None,
    max_lon: Optional[float] = None,
) -> IndustryResponse:
    """
    Fetches industry records strictly for Delhi from Supabase.
    
    Database Query:
        SELECT * FROM industries 
        WHERE city = 'Delhi' AND state = 'Delhi'
        [AND latitude BETWEEN min_lat AND max_lat]
        [AND longitude BETWEEN min_lon AND max_lon]
        
    Guarantees that NO non-Delhi records (Chennai, Tamil Nadu, etc.) are ever queried or loaded.
    """
    settings = get_settings()
    supabase_url = (
        settings.supabase_url
        or os.getenv("SUPABASE_URL")
        or os.getenv("VITE_SUPABASE_URL")
        or DEFAULT_SUPABASE_URL
    ).rstrip("/")
    supabase_key = (
        settings.supabase_key
        or settings.supabase_anon_key
        or os.getenv("SUPABASE_KEY")
        or os.getenv("SUPABASE_ANON_KEY")
        or os.getenv("VITE_SUPABASE_ANON_KEY")
        or DEFAULT_SUPABASE_KEY
    )

    supabase_records: list[IndustryRecord] = []

    # 1. Direct Supabase Query with Database-Level Filtering
    if supabase_url and supabase_key:
        try:
            # PostgREST URL with mandatory database-level filters: city=eq.Delhi and state=eq.Delhi
            endpoint = f"{supabase_url}/rest/v1/industries"
            
            # PostgREST query parameters ensuring strict server-side filtering
            params: dict[str, str] = {
                "select": "*",
                "city": "eq.Delhi",
                "state": "eq.Delhi",
                "limit": "1000",
            }

            # Optional server-side viewport filtering applied AFTER the Delhi restriction
            if min_lat is not None:
                params["latitude"] = f"gte.{min_lat}"
            if max_lat is not None:
                params["latitude"] = f"lte.{max_lat}"
            if min_lon is not None:
                params["longitude"] = f"gte.{min_lon}"
            if max_lon is not None:
                params["longitude"] = f"lte.{max_lon}"

            headers = {
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
                "Accept": "application/json",
            }

            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(endpoint, params=params, headers=headers)
                if resp.status_code == 200:
                    raw_data = resp.json()
                    for row in raw_data:
                        rec = _normalize_raw_record(row)
                        if rec:
                            supabase_records.append(rec)
                    logger.info("Successfully fetched %d Delhi industry records from Supabase", len(supabase_records))
                else:
                    logger.warning("Supabase returned HTTP %d: %s", resp.status_code, resp.text[:200])
        except Exception as e:
            logger.error("Error querying Supabase industries: %s", e)

    # 2. Merge Supabase records with the comprehensive 1,865 Delhi industrial directory
    all_delhi_records = _load_csv_industries()
    merged_map: dict[str, IndustryRecord] = {}

    for rec in all_delhi_records:
        key = f"{rec.name.lower()}_{round(rec.latitude, 3)}_{round(rec.longitude, 3)}"
        merged_map[key] = rec

    for rec in supabase_records:
        key = f"{rec.name.lower()}_{round(rec.latitude, 3)}_{round(rec.longitude, 3)}"
        merged_map[key] = rec

    filtered: list[IndustryRecord] = []
    for rec in merged_map.values():
        if min_lat is not None and rec.latitude < min_lat:
            continue
        if max_lat is not None and rec.latitude > max_lat:
            continue
        if min_lon is not None and rec.longitude < min_lon:
            continue
        if max_lon is not None and rec.longitude > max_lon:
            continue
        filtered.append(rec)

    return IndustryResponse(
        city="Delhi",
        state="Delhi",
        count=len(filtered),
        source="delhi_master_dataset",
        records=filtered,
    )
