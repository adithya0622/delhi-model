import httpx
r = httpx.get('http://localhost:8000/api/v1/realtime/stations', timeout=30.0)
stations = r.json()
print(f'Total stations: {len(stations)}')
for s in stations[:10]:
    print(f"{s['name']} -> AQI: {s['aqi']} | Pollutants: {s['pollutants']}")
