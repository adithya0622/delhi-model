import httpx
r = httpx.get('http://localhost:8000/api/v1/realtime/stations', timeout=25)
s = r.json()
print(f"Total: {len(s)}")
for x in s[:5]:
    print(f"AQI: {x.get('aqi')} | PM25: {x.get('pollutants',{}).get('PM2.5')} | {x.get('name')}")
