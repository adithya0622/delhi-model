"""IITM SAFAR / EWS — free operational WRF-Chem reference for Delhi NCR.

IITM Pune runs the SAFAR (System of Air Quality and Weather Forecasting and
Research) and EWS (Early Warning System) models **operationally** for exactly
this domain — a coupled meteorology–chemistry system built on WRF-Chem. The
public bulletin endpoints are keyless. Ingesting them gives the project a real
coupled-model reference series (meteorology + PM2.5/PM10/O3/NO2 from an
operational WRF-Chem-class model) without compiling WRF or buying compute —
the practical "WRF-Chem for free" lever for this repo.

EWS public bulletin (JSON, keyless, updated twice daily):
    https://ews.tropmet.res.in/ews-api/… — verified live shape at build time:
    `https://ews.tropmet.res.in/delhi/pollution-data` returns hourly
    PM2.5 / PM10 / O3 / NO2 / CO / SO2 with timestamps.

Honesty rules (same as every provider in this repo):
- Only data actually returned by the upstream is surfaced; nothing synthesised.
- Any failure raises RuntimeError with the precise reason — callers translate
  that into 502/503, never into silent fallback values.
- No API key is needed, so there is no key management in this module.
"""
from __future__ import annotations

import re
from typing import Any

import httpx

DELHI_LAT, DELHI_LON = 28.6139, 77.2090

# Candidate bulletin URLs tried in order. IITM has rotated paths before; each
# candidate is independent so one 404 does not kill the chain.
_EWS_URLS = [
    "https://ews.tropmet.res.in/delhi/pollution-data",
    "https://ews.tropmet.res.in/ews-api/delhi/pollution-data",
]

# Reachable-from-anywhere fallback: SAFAR's public forecast page embeds one
# table per station (date / category / AQI) straight from the operational
# WRF-Chem run. The dedicated EWS JSON host geo-blocks outside India, but this
# page answers globally — verified live at build time.
_SAFAR_FORECAST_URL = "https://safar.tropmet.res.in/delhi_ncr_forecast.php"

# SAFAR public sites (bulletin pages, no JSON API) — surfaced as references.
_SAFAR_PAGES = {
    "safar_delhi": "https://safar.tropmet.res.in/",
    "ews_delhi": "https://ews.tropmet.res.in/",
}

# Per-candidate cap, not a global budget: a geo-blocked host (the common
# failure outside India) hangs rather than refusing, so this keeps a dead
# bulletin from stalling the request longer than ~2× this value.
_TIMEOUT_S = 10.0


def _pollutant_map() -> dict[str, str]:
    """Canonical pollutant key → EWS payload key candidates (case-insensitive)."""
    return {
        "PM2.5": "pm25",
        "PM10": "pm10",
        "O3": "o3",
        "NO2": "no2",
        "SO2": "so2",
        "CO": "co",
    }


def _extract_series(payload: Any) -> list[dict[str, Any]]:
    """Best-effort extraction of an hourly series from an EWS JSON payload.

    EWS shapes seen in the wild: either `{"data": {"rows": [...]}}`-style
    structured payloads or flat lists of dicts with mixed-case keys
    ("PM2.5"/"pm25", "DateTime"/"date"). We normalise rather than assume.
    """
    rows: list[Any]
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        for candidate in ("data", "rows", "records", "pollution_data", "values"):
            inner = payload.get(candidate)
            if isinstance(inner, list):
                rows = inner
                break
            if isinstance(inner, dict):
                maybe = inner.get("rows") or inner.get("records")
                if isinstance(maybe, list):
                    rows = maybe
                    break
        else:
            rows = []
    else:
        rows = []

    pmap = _pollutant_map()
    series: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        lowered = {str(k).strip().lower(): v for k, v in row.items()}
        time_val = None
        for tkey in ("datetime", "date", "time", "timestamp", "date_time"):
            if lowered.get(tkey) is not None:
                time_val = str(lowered[tkey])
                break
        if time_val is None:
            continue
        entry: dict[str, Any] = {"time": time_val}
        for canonical, short in pmap.items():
            v = lowered.get(short)
            if v is None:
                v = lowered.get(canonical.lower())
            if v is not None:
                try:
                    entry[short] = float(v)
                except (TypeError, ValueError):
                    entry[short] = None
            else:
                entry[short] = None
        if any(entry[s] is not None for s in pmap.values()):
            series.append(entry)
    return series


def _parse_forecast_page(html: str) -> list[dict[str, Any]]:
    """Extract per-station forecast tables from the SAFAR forecast page.

    Page shape (verified live): a JS map array of blocks like
        {"title":'Alipur', "lat":'28.7...', "lng":'77.1...', "description":'<table …'}
    where each description holds rows of Date | Category | AQI ('NA' in the
    clean season). Splitting on the block marker keeps the parser immune to
    nested quotes inside the HTML descriptions.
    """
    marker = '{"title":\''
    chunks = html.split(marker)[1:]
    stations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for chunk in chunks:
        try:
            name = chunk.split("'", 1)[0].strip()
            lat_m = re.search(r'"lat"\s*:\s*\'([\d.]+)\'', chunk)
            lng_m = re.search(r'"lng"\s*:\s*\'([\d.]+)\'', chunk)
        except (IndexError, ValueError):
            continue
        if not name or name in seen or lat_m is None or lng_m is None:
            continue
        seen.add(name)
        forecasts: list[dict[str, Any]] = []
        for day, category, aqi in re.findall(
            r">(\d{4}-\d{2}-\d{2})</td>\s*<td[^>]*>\s*([A-Za-z ]{3,20})\s*</td>\s*<td[^>]*>\s*(NA|\d{1,3})\s*</td>",
            chunk,
        ):
            forecasts.append({
                "date": day,
                "category": category.strip(),
                "aqi": None if aqi == "NA" else int(aqi),
            })
        if forecasts:
            stations.append({
                "name": name,
                "lat": float(lat_m.group(1)),
                "lon": float(lng_m.group(1)),
                "forecasts": forecasts,
            })
    return stations


async def _fetch_safar_forecast_page(client: httpx.AsyncClient) -> dict[str, Any]:
    """Scrape the public SAFAR per-station forecast tables (keyless, global)."""
    response = await client.get(
        _SAFAR_FORECAST_URL,
        headers={"User-Agent": "delhi-aqi-forecast/1.0 (research)"},
    )
    response.raise_for_status()
    stations = _parse_forecast_page(response.text)
    if not stations:
        raise RuntimeError("SAFAR forecast page returned no parseable station tables (page format changed?)")
    days = sorted({f["date"] for s in stations for f in s["forecasts"]})
    return {
        "source": "IITM SAFAR operational forecast, Delhi (WRF-Chem-based), public bulletin page",
        "model": "WRF-Chem (SAFAR operational configuration)",
        "url": _SAFAR_FORECAST_URL,
        "station_count": len(stations),
        "stations": stations,
        "forecast_dates": days,
        "note": (
            "Official SAFAR (operational WRF-Chem) daily per-station forecasts for Delhi, "
            "parsed from the public bulletin page — no API key, no download. AQI shows 'NA' "
            "when SAFAR publishes category-only in the clean season. Daily granularity by "
            "design; for hourly series use your own WRF-Chem run via /validation/wrf-compare."
        ),
    }


def _client() -> httpx.AsyncClient:
    """Client that also accepts SAFAR's weak-DH TLS (DH_KEY_TOO_SMALL).

    IITM serves the bulletin with 1024-bit Diffie-Hellman parameters, which
    modern OpenSSL refuses by default. curl connects fine; we lower the
    security floor deliberately for these two trusted government hosts only —
    the payload is a public weather bulletin, not a secret exchange.
    """
    try:
        import ssl

        ctx = ssl.create_default_context()
        ctx.set_ciphers("DEFAULT:@SECLEVEL=1")
        return httpx.AsyncClient(timeout=_TIMEOUT_S, follow_redirects=True, verify=ctx)
    except Exception:
        # Very old/odd OpenSSL without SECLEVEL support — plain client, which
        # simply keeps the EWS fallback unavailable.
        return httpx.AsyncClient(timeout=_TIMEOUT_S, follow_redirects=True)


async def fetch_ews_delhi_series(client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    """Fetch SAFAR/EWS operational output (keyless), with graceful fallback.

    Order: EWS JSON bulletin (hourly, richest — but geo-blocked outside India),
    then the public SAFAR forecast page (daily per-station, reachable
    globally). Raises RuntimeError with the precise upstream reason when both
    fail.
    """
    own_client = client is None
    client = client or _client()
    try:
        last_error = "no candidate URL succeeded"
        for url in _EWS_URLS:
            try:
                response = await client.get(
                    url,
                    headers={"User-Agent": "delhi-aqi-forecast/1.0 (research)"},
                )
                if response.status_code != 200:
                    last_error = f"{url} -> HTTP {response.status_code}"
                    continue
                payload = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                last_error = f"{url} -> {exc}"
                continue
            series = _extract_series(payload)
            if not series:
                last_error = f"{url} -> 200 but no parseable hourly rows"
                continue
            return {
                "source": "IITM EWS (WRF-Chem-based operational forecast, Delhi)",
                "model": "WRF-Chem (SAFAR/EWS operational configuration)",
                "url": url,
                "station": "Delhi (city aggregate bulletin)",
                "hours": series,
                "note": (
                    "Operational coupled WRF-Chem output for this exact domain. "
                    "Use as an external reference for the surrogate's 72h series; "
                    "bulletin timestamps and species coverage vary — rows are "
                    "passed through as returned, never interpolated."
                ),
            }
        # EWS unreachable (typical outside India) — public bulletin page next.
        try:
            return await _fetch_safar_forecast_page(client)
        except (httpx.HTTPError, RuntimeError) as exc:
            raise RuntimeError(
                f"IITM SAFAR/EWS unavailable: EWS bulletin failed ({last_error}); "
                f"forecast page failed ({exc})"
            ) from exc
    finally:
        if own_client:
            await client.aclose()


def safar_references() -> dict[str, Any]:
    """Static reference links surfaced in the dashboard / API docs."""
    return {
        "provider": "IITM Pune SAFAR / EWS",
        "model_class": "WRF-Chem (coupled meteorology–chemistry)",
        "domain": "Delhi NCR (operational)",
        "bulletin_pages": _SAFAR_PAGES,
        "api_key_required": False,
        "note": (
            "Free operational coupled-model reference for the exact domain of "
            "this project. For genuine wrfout intercomparison use the offline "
            "run described in scripts/wrfchem/kaggle_wrfchem_run.ipynb and the "
            "/validation/wrf-compare endpoint."
        ),
    }
