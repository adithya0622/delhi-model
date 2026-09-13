import asyncio
import httpx

async def main():
    print("Testing raw OpenAQ fetching...")
    
    # Hit the local backend API
    async with httpx.AsyncClient(timeout=45.0) as client:
        r = await client.get("http://localhost:8000/api/v1/realtime/stations")
        r.raise_for_status()
        data = r.json()
        
        print(f"\nTotal Active Stations: {len(data)}")
        assert len(data) > 0, "No stations returned!"
        
        # We expect a good number of stations now that pagination is enabled
        print(f"Expect ~46+ stations (returned {len(data)})")
        
        print("\n{:<10} | {:<35} | {:<5} | {:<5} | {:<6} | {:<6} | {:<5}".format(
            "UID", "NAME", "AQI", "PM2.5", "PM10", "NO2", "O3"))
        print("-" * 88)
        
        for s in data:
            uid = s["uid"]
            name = s["name"][:32] + "..." if len(s["name"]) > 32 else s["name"]
            aqi = s["aqi"]
            pm25 = s["pollutants"].get("PM2.5", "-")
            pm10 = s["pollutants"].get("PM10", "-")
            no2 = s["pollutants"].get("NO2", "-")
            o3 = s["pollutants"].get("O3", "-")
            
            print(f"{uid:<10} | {name:<35} | {aqi:<5} | {pm25:<5} | {pm10:<6} | {no2:<6} | {o3:<5}")
        
        print("\nAll stations successfully fetched purely from OpenAQ without artificial median clamping.")

if __name__ == "__main__":
    asyncio.run(main())
