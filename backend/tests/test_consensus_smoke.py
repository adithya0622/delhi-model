import asyncio
from app.services.consensus_service import _aqi_from_pm25, _forecast

async def main():
    points = await _forecast({"pm25": 178.0, "pm10": 286.0, "aqi": 318.0, "temp": 19.0, "wind": 5.2})
    assert [p["horizon_hours"] for p in points] == [12, 24, 48, 72]
    assert all(0 <= p["aqi"] <= 500 for p in points)
    assert _aqi_from_pm25(178.0) > 300
    print("consensus smoke test passed")

if __name__ == "__main__":
    asyncio.run(main())
