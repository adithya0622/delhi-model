import asyncio
import os
from dotenv import load_dotenv
import httpx
import sys

# Add backend to path so we can import app modules for AQI calculation
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'backend')))
from app.services.realtime_service import _openaq_locations, _openaq_latest, _conc_to_aqi, _cat

load_dotenv()

async def verify_openaq():
    api_key = os.getenv("OPENAQ_API_KEY")
    if not api_key:
        print("FAIL: OPENAQ_API_KEY not found in .env")
        sys.exit(1)
        
    print("OPENAQ_API_KEY loaded successfully.")
    print("Fetching OpenAQ locations for Delhi NCR...")
    
    try:
        locations = await _openaq_locations()
    except Exception as e:
        print(f"FAIL: Fetching locations failed: {e}")
        sys.exit(1)
        
    assert len(locations) > 0, "FAIL: OpenAQ returned empty results for Delhi NCR bbox."
    print(f"SUCCESS: Found {len(locations)} monitoring locations.\n")
    
    print(f"{'Station Name':<45} | {'Coordinates':<20} | {'PM2.5':<8} | {'PM10':<8} | {'AQI (CPCB)':<10}")
    print("-" * 105)
    
    loc_sample = locations[:10]  # sample 10 to keep it fast
    readings_list = await asyncio.gather(
        *[_openaq_latest(loc["id"]) for loc in loc_sample],
        return_exceptions=True
    )
    
    for loc, readings in zip(loc_sample, readings_list):
        if isinstance(readings, Exception):
            print(f"Error fetching {loc['id']}: {readings}")
            continue
            
        name = loc.get("name", "Unknown")[:44]
        coords = f"{loc['coordinates']['latitude']:.4f}, {loc['coordinates']['longitude']:.4f}"
        pm25 = readings.get("pm25", "N/A")
        pm10 = readings.get("pm10", "N/A")
        
        aqi, dom = _conc_to_aqi(readings)
        aqi_str = str(aqi) if aqi > 0 else "N/A"
        
        pm25_str = f"{pm25:.1f}" if isinstance(pm25, float) else pm25
        pm10_str = f"{pm10:.1f}" if isinstance(pm10, float) else pm10
        
        print(f"{name:<45} | {coords:<20} | {pm25_str:<8} | {pm10_str:<8} | {aqi_str:<10}")

if __name__ == "__main__":
    asyncio.run(verify_openaq())
