# Manual smoke checks

Scripts in this directory are **not** part of the automated test suite. They hit
live upstream APIs and/or require a backend already running on
`http://localhost:8000`, so they cannot run in CI and must never be collected by
pytest. That is why none of them is named `test_*.py` — they were previously at
the repository root under `test_` names, where pytest picked them up and the
whole suite failed on a machine with no server running.

Automated tests with real assertions live in `backend/tests/`.

| Script | What it checks | Needs |
|---|---|---|
| `check_stations.py` | `/realtime/stations` returns stations with AQI and PM2.5 | running backend |
| `check_station_accuracy.py` | first 10 stations, full pollutant dict | running backend |
| `check_all_stations.py` | station count against the ~46 expected with pagination on | running backend |
| `check_openaq_live.py` | OpenAQ v3 credentials work and locations resolve for Delhi | `OPENAQ_API_KEY` in `.env` |

`sample_openaq_hours.json` is a captured OpenAQ v3 hourly response, kept as a
reference for the payload shape.

Run one with, for example:

```bash
python scripts/manual/check_stations.py
```
