"""
API v1 Endpoints
================
Read-only (GET) endpoints are public but rate-limited.
Mutation (POST /ingest) requires X-API-Key header.
"""

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request, HTTPException, Response
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
import httpx


from app.core.security import require_api_key
from app.physics.inversion_engine import compute_inversion_series, fetch_inversion_data
from app.physics.plume_advection import compute_plume_vectors
from app.schemas.forecast import (
    CityAggregateResponse,
    DelhiBBox,
    ExposureRequest,
    ExposureResponse,
    ForecastResponse,
    InversionStatus,
    PlumeVectorsResponse,
    SourceApportionmentResponse,
    SourceTimeSeriesResponse,
    StationObservation,
    VehicleBreakdown,
)
from app.services.aqi_service import build_72h_forecast, compute_city_aggregate
from app.services.consensus_service import collect_consensus
from app.services.emission_service import EmissionService
from app.services.exposure_service import calculate_personalized_exposure
from app.services.realtime_service import (
    fetch_all_stations,
    fetch_city_overview,
    fetch_station_detail,
    fetch_iqair_realtime,
    fetch_weatherapi_realtime,
)
from app.schemas.industry import IndustryResponse
from app.services.industry_service import fetch_delhi_industries
from app.api.v1.ml_forecast_endpoint import router as ml_router
from app.api.v1.chronos_endpoint import router as chronos_router
from app.api.v1.backtest_endpoint import router as backtest_router

router = APIRouter(prefix="/api/v1")
router.include_router(ml_router)
router.include_router(chronos_router)
router.include_router(backtest_router)
limiter = Limiter(key_func=get_remote_address)


# ── GET /forecast/72hr ───────────────────────────────────────────────────────

@router.get(
    "/forecast/72hr",
    response_model=ForecastResponse,
    summary="72-hour AQI forecast for Delhi NCR",
    tags=["Forecast"],
)
@limiter.limit("30/minute")
async def forecast_72hr(
    request: Request,
    lat: float = Query(28.6139, ge=28.0, le=29.0, description="Station latitude"),
    lon: float = Query(77.2090, ge=76.5, le=77.8, description="Station longitude"),
    station_name: str = Query("Delhi-ITO", max_length=64),
    base_aqi: int | None = Query(None, ge=0, le=500, description="Live station AQI for hour-0 anchoring"),
) -> ForecastResponse:
    """
    Returns a 72-hour hourly AQI forecast including:
    - CPCB sub-indices (PM2.5, PM10, O3, NO2, SO2, CO)
    - PBL height and thermal inversion strength
    - Stubble-burn plume contribution fraction
    - Two-way aerosol-radiation feedback applied
    """
    # Validate coordinate in NCR bbox
    DelhiBBox(lat=lat, lon=lon)  # raises 422 if invalid
    # Anchor hour 0 to live observations so the forecast starts from observed
    # air rather than from climatology. Priority is deliberate:
    # 1. Consensus city value — a single real observation (Open-Meteo/CAMS or a
    #    keyed provider), no spatial modelling applied.
    # 2. Nearest-station value — only when per-station keys are configured.
    #    Without keys the station list is the city value scaled by fixed
    #    climatological factors, so anchoring to it injects factor noise
    #    (e.g. 79.5 vs the observed 65.7) and degrades the match to IQAir.
    live_pollutants = None
    live_pm25 = None
    live_pm10 = None
    try:
        from app.core.config import get_settings as _get_settings

        _settings = _get_settings()
        _real_station_obs = any(
            key and not str(key).startswith("your-")
            for key in (
                _settings.openaq_api_key,
                _settings.iqair_api_key,
                _settings.weatherapi_api_key,
            )
        )
    except Exception:
        _real_station_obs = False
    if _real_station_obs:
        try:
            stations = await fetch_all_stations(mode="instant")
            for s in stations:
                slat = s.get("lat", 0)
                slon = s.get("lon", 0)
                dist = ((slat - lat) ** 2 + (slon - lon) ** 2) ** 0.5
                if dist < 0.15:  # ~15 km in the Delhi latitude band
                    polls = s.get("pollutants", {})
                    live_pollutants = polls
                    live_pm25 = polls.get("PM2.5")
                    live_pm10 = polls.get("PM10")
                    break
        except (ValueError, RuntimeError, httpx.HTTPError, KeyError):
            pass  # fall back to the consensus anchor below

    # Consensus city anchor: the primary live truth when station obs are factored.
    if (live_pm25 is None or not live_pollutants) and base_aqi is None:
        try:
            c_data = await collect_consensus()
            if c_data and "metrics" in c_data:
                c_m = c_data["metrics"]
                live_pollutants = {
                    "PM2.5": float(c_m["pm25"]) if c_m.get("pm25") is not None else None,
                    "PM10": float(c_m["pm10"]) if c_m.get("pm10") is not None else None,
                    "NO2": float(c_m["no2"]) if c_m.get("no2") is not None else None,
                    "O3": float(c_m["o3"]) if c_m.get("o3") is not None else None,
                    "SO2": float(c_m["so2"]) if c_m.get("so2") is not None else None,
                    "CO": float(c_m["co"]) if c_m.get("co") is not None else None,
                }
                if c_m.get("pm25") is not None:
                    live_pm25 = float(c_m["pm25"])
                if c_m.get("pm10") is not None:
                    live_pm10 = float(c_m["pm10"])
        except Exception:
            pass

    try:
        data = await build_72h_forecast(
            lat, lon, station_name,
            live_pm25=live_pm25, live_pm10=live_pm10,
            base_aqi=base_aqi,
            live_pollutants=live_pollutants,
        )
        return ForecastResponse(**data)
    except (ValueError, RuntimeError, httpx.HTTPError) as e:
        raise HTTPException(status_code=502, detail=f"Live upstream unavailable: {str(e)}")


# ── GET /forecast/consensus ───────────────────────────────────────────────────

@router.get(
    "/forecast/consensus",
    summary="Five-source consensus current conditions and deterministic 72-hour projection",
    tags=["Forecast"],
)
@limiter.limit("20/minute")
async def forecast_consensus(request: Request) -> dict:
    """Fetch provider feeds concurrently and return a best-effort consensus forecast."""
    try:
        return await collect_consensus()
    except Exception as e:
        # The service normally catches provider failures itself; this final guard
        # prevents one unexpected payload from taking down the dashboard.
        raise HTTPException(status_code=502, detail=f"Consensus service unavailable: {e}")


# ── GET /inversion/status ────────────────────────────────────────────────────

@router.get(
    "/inversion/status",
    response_model=list[InversionStatus],
    summary="Current 72-hour atmospheric inversion diagnostics",
    tags=["Meteorology"],
)
@limiter.limit("30/minute")
async def inversion_status(request: Request) -> list[InversionStatus]:
    """
    Returns per-hour inversion diagnostics for the next 72 hours:
    - ΔT = T(925hPa) − T(1000hPa)
    - PBL height with inversion suppression
    - Environmental lapse rate (K/km)
    - AQI amplification factor
    """
    try:
        met_data = await fetch_inversion_data()
        hourly_times = met_data["hourly"]["time"][:72]
        series = compute_inversion_series(met_data)

        return [
            InversionStatus(
                timestamp=datetime.fromisoformat(t),
                **s,
            )
            for t, s in zip(hourly_times, series)
        ]
    except (ValueError, RuntimeError, httpx.HTTPError, KeyError) as e:
        raise HTTPException(status_code=502, detail=f"Meteorology upstream unavailable: {str(e)}")


# ── GET /plume/vectors ───────────────────────────────────────────────────────

@router.get(
    "/plume/vectors",
    response_model=PlumeVectorsResponse,
    summary="Stubble-burn plume trajectories and hotspots",
    tags=["Plume Dispersion"],
)
@limiter.limit("20/minute")
async def plume_vectors(request: Request) -> PlumeVectorsResponse:
    """
    Returns current fire hotspots (NASA FIRMS, VIIRS + MODIS NRT) and their
    Lagrangian plume trajectories advected on the 850 hPa wind.

    Each plume includes:
    - Origin hotspot with Fire Radiative Power (MW) and detection confidence
    - 72-hour trajectory as lat/lon waypoints at hourly steps
    - Closest approach to Delhi and the along-path travel distance to it
    - PM2.5 column loading (µg/m²) and transport-layer concentration (µg/m³)

    Concentrations are TRANSPORT-LAYER values, not surface values. How much of
    an arriving plume reaches the ground depends on Delhi's mixing depth that
    hour, which the forecast's box model resolves.

    If FIRMS is unreachable the hotspot list is empty. No synthetic fires are
    ever returned.
    """
    data = await compute_plume_vectors()
    now = datetime.now(timezone.utc)
    return PlumeVectorsResponse(timestamp=now, **data)


# ── POST /ingest/observation ─────────────────────────────────────────────────

@router.post(
    "/ingest/observation",
    status_code=202,
    summary="Ingest a live station observation (requires API key)",
    tags=["Ingestion"],
)
@limiter.limit("120/minute")
async def ingest_observation(
    request: Request,
    obs: StationObservation,
    _key: str = Depends(require_api_key),
) -> dict:
    """
    Accepts a validated station observation for assimilation.
    Requires X-API-Key header with valid key.

    Returns 202 Accepted. Persistence is deliberately out of scope: there is no
    time-series database in this deployment, so the observation is validated and
    acknowledged but not stored. Do not treat a 202 here as durable.
    """
    return {
        "accepted": True,
        "station_id": obs.station_id,
        "timestamp": obs.timestamp.isoformat(),
        "message": "Observation accepted for assimilation",
    }


# ── GET /health ──────────────────────────────────────────────────────────────

@router.get("/health", tags=["System"])
async def health() -> dict:
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


# ── GET /realtime/overview ────────────────────────────────────────────────────

@router.get(
    "/realtime/overview",
    summary="Live Delhi city-level AQI from OpenAQ",
    tags=["Real-Time"],
)
@limiter.limit("60/minute")
async def realtime_overview(request: Request, mode: str = Query("instant", description="AQI calc mode (instant or nowcast)")) -> dict:
    """Returns the current overall Delhi AQI, PM2.5, PM10, O3, NO2."""
    try:
        return await fetch_city_overview(mode)
    except (ValueError, RuntimeError, httpx.HTTPError) as e:
        raise HTTPException(status_code=502, detail=f"Live OpenAQ upstream unavailable: {str(e)}")


# ── GET /realtime/stations ────────────────────────────────────────────────────

@router.get(
    "/realtime/stations",
    summary="All Delhi NCR monitoring stations with live AQI",
    tags=["Real-Time"],
)
@limiter.limit("30/minute")
async def realtime_stations(request: Request, mode: str = Query("instant", description="AQI calc mode (instant or nowcast)")) -> list:
    """
    Returns all CPCB monitoring stations in Delhi NCR with:
    - Real-time AQI (from OpenAQ)
    - Lat/lon for map plotting
    - AQI category and colour code
    Data updates every ~1 hour from CPCB stations.
    """
    try:
        return await fetch_all_stations(mode)
    except (ValueError, RuntimeError, httpx.HTTPError) as e:
        raise HTTPException(status_code=502, detail=f"Live OpenAQ upstream unavailable: {str(e)}")


# ── GET /realtime/station/{uid} ───────────────────────────────────────────────

@router.get(
    "/realtime/station/{uid}",
    summary="Full pollutant breakdown for a single station",
    tags=["Real-Time"],
)
@limiter.limit("60/minute")
async def realtime_station_detail(
    request: Request,
    uid: str,
    mode: str = Query("instant", description="AQI calc mode (instant or nowcast)"),
) -> dict:
    """
    Returns full pollutant data for a station (by OpenAQ location id):
    PM2.5, PM10, O3, NO2, SO2, CO, temperature, humidity, wind speed.

    `mode` must match whatever the caller displays elsewhere — `instant` labels
    with CPCB 2014 categories, `nowcast` with US EPA 2012 ones. The two scales
    are not interchangeable.
    """
    try:
        return await fetch_station_detail(uid, mode)
    except (ValueError, RuntimeError, httpx.HTTPError) as e:
        raise HTTPException(status_code=502, detail=f"Live OpenAQ upstream unavailable: {str(e)}")


# ── GET /realtime/iqair ───────────────────────────────────────────────────────

@router.get(
    "/realtime/iqair",
    summary="Live Delhi AQI from IQAir /nearest_city endpoint",
    tags=["Real-Time"],
)
@limiter.limit("60/minute")
async def realtime_iqair(request: Request) -> dict:
    """Returns real-time AQI from IQAir city aggregate for Delhi.
    Primary live source: IQAir /city endpoint for Delhi + WeatherAPI concentrations.
    Includes full pollutant breakdown, weather, and AQI category.
    """
    try:
        return await fetch_iqair_realtime()
    except (ValueError, RuntimeError, httpx.HTTPError) as e:
        raise HTTPException(status_code=502, detail=f"IQAir unavailable: {str(e)}")


# ── GET /realtime/weatherapi ──────────────────────────────────────────────────

@router.get(
    "/realtime/weatherapi",
    summary="Live Delhi weather from WeatherAPI",
    tags=["Real-Time"],
)
@limiter.limit("60/minute")
async def realtime_weatherapi(request: Request) -> dict:
    """Returns real-time weather from WeatherAPI for Delhi.
    Includes temperature, humidity, wind, pressure, condition, and air quality.
    """
    try:
        return await fetch_weatherapi_realtime()
    except (ValueError, RuntimeError, httpx.HTTPError) as e:
        raise HTTPException(status_code=502, detail=f"WeatherAPI unavailable: {str(e)}")


# ── GET /history/7d ───────────────────────────────────────────────────────────

@router.get(
    "/history/7d",
    summary="Real historical hourly air quality for past 7 days (168 hours)",
    tags=["Historical"],
)
@limiter.limit("30/minute")
async def historical_7d(request: Request) -> dict:
    """Returns real observed/reanalysis hourly air quality measurements for the past 7 days in Delhi NCR.
    Provides timestamps, PM2.5, PM10, NO2, O3, SO2, and US AQI without synthetic data.
    """
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            r = await client.get(
                "https://air-quality-api.open-meteo.com/v1/air-quality",
                params={
                    "latitude": 28.6139,
                    "longitude": 77.2090,
                    "hourly": "pm2_5,pm10,nitrogen_dioxide,ozone,sulphur_dioxide,carbon_monoxide,us_aqi",
                    "past_days": 7,
                    "forecast_days": 0,
                    "timezone": "Asia/Kolkata",
                },
            )
            r.raise_for_status()
            data = r.json()

        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        pm25 = hourly.get("pm2_5", [])
        pm10 = hourly.get("pm10", [])
        no2 = hourly.get("nitrogen_dioxide", [])
        o3 = hourly.get("ozone", [])
        so2 = hourly.get("sulphur_dioxide", [])
        co = hourly.get("carbon_monoxide", [])
        aqi = hourly.get("us_aqi", [])

        records = []
        for i in range(len(times)):
            records.append({
                "timestamp": times[i],
                "pm25": pm25[i] if i < len(pm25) else None,
                "pm10": pm10[i] if i < len(pm10) else None,
                "no2": no2[i] if i < len(no2) else None,
                "o3": o3[i] if i < len(o3) else None,
                "so2": so2[i] if i < len(so2) else None,
                "co": round(float(co[i]) / 1000.0, 2) if i < len(co) and co[i] is not None else None,
                "aqi": aqi[i] if i < len(aqi) else None,
            })

        return {
            "source": "Open-Meteo Air Quality Historical Reanalysis",
            "count": len(records),
            "hours": records,
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Historical data unavailable: {str(e)}")


# ── POST /exposure/calculate ──────────────────────────────────────────────────

@router.post(
    "/exposure/calculate",
    response_model=ExposureResponse,
    summary="Personalized PM2.5 Inhaled Dose, Cigarette Equivalence & Smart Activity Planner",
    tags=["Exposure"],
)
@limiter.limit("60/minute")
async def calculate_exposure(
    request: Request,
    payload: ExposureRequest,
) -> ExposureResponse:
    """
    Calculates:
    1. Inhaled PM2.5 mass (µg) based on user activity ventilation rate (resting, walking, running).
    2. Cigarette consumption equivalent (Berkeley Earth 22 µg/m³ 24h benchmark).
    3. Exertion health danger warning.
    4. 72-hour sliding window optimal activity window to minimize pollution exposure.
    """
    forecast_points = payload.forecast_72h
    # If client didn't supply 72h forecast array, fetch live 72h forecast automatically
    if not forecast_points:
        try:
            fc = await build_72h_forecast(28.6139, 77.2090, "Delhi-NCR")
            forecast_points = fc.get("forecast_hours", [])
        except Exception:
            forecast_points = []

    res = calculate_personalized_exposure(
        activity_type=payload.activity_type,
        duration_hours=payload.duration_hours,
        target_time=payload.target_time,
        current_pm25=payload.current_pm25,
        forecast_72h=forecast_points,
    )
    return ExposureResponse(**res)


# ── GET /forecast/source-apportionment ───────────────────────────────────────

@router.get(
    "/forecast/source-apportionment",
    response_model=SourceApportionmentResponse,
    summary="Dynamic PM2.5 Source Apportionment via NO2 Chemical Proxy & Fleet Breakdown",
    tags=["Source Apportionment"],
)
@limiter.limit("60/minute")
async def get_source_apportionment(
    request: Request,
    pm25: float | None = Query(None, ge=0.0, le=1000.0, description="Ambient PM2.5 in µg/m³"),
    no2: float | None = Query(None, ge=0.0, le=500.0, description="Ambient NO2 tracer in µg/m³"),
    hour: int | None = Query(None, ge=0, le=23, description="Hour of day (0-23 in IST)"),
) -> SourceApportionmentResponse:
    """
    Computes dynamic chemical-proxy source apportionment:
    - Uses ambient NO2 as a tracer for vehicle exhaust relative to Delhi's 60 µg/m³ baseline.
    - Dynamically scales the 25% Transport share and redistributes anomalies to Dust, Biomass, and Industry.
    - Applies diurnal fleet sub-breakdown: Nighttime Truck Entry (22:00-06:00), Rush Hour (08:00-11:00 & 17:00-20:00), and Normal Day.
    """
    if pm25 is None or no2 is None:
        try:
            consensus = await collect_consensus()
            metrics = consensus.get("metrics", {})
            if pm25 is None:
                pm25 = float(metrics.get("pm25", 53.8))
            if no2 is None:
                no2 = float(metrics.get("no2", 38.5))
        except Exception:
            if pm25 is None:
                pm25 = 53.8
            if no2 is None:
                no2 = 38.5

    return EmissionService.calculate_source_apportionment(
        current_pm25=pm25,
        current_no2=no2,
        hour=hour,
    )


# ── GET /forecast/source-timeseries ──────────────────────────────────────────

@router.get(
    "/forecast/source-timeseries",
    response_model=SourceTimeSeriesResponse,
    summary="72-Hour Predictive Source Apportionment & Diurnal Vehicle Fleet Time-Series",
    tags=["Source Apportionment"],
)
@limiter.limit("60/minute")
async def get_source_timeseries(
    request: Request,
) -> SourceTimeSeriesResponse:
    """
    Simulates 72-hour hourly predictive source apportionment and vehicle fleet dynamics:
    - Dust (30%), Biomass (25%), Industry (20%), Transport (25%).
    - Diurnal Vehicle Fleet Dynamics:
      - Nighttime (22:00-06:00): Trucks 61%, 2/3-Wheelers 25%, Cars 14%.
      - Rush Hour (08:00-11:00 & 17:00-20:00): Trucks 10%, 2/3-Wheelers 60%, Cars 30%.
      - Standard Day: Trucks 30%, 2/3-Wheelers 50%, Cars 20%.
    - Anchored to the 72-hour prognostic PM2.5 atmospheric forecast.
    """
    pm25_series: list[float] = []
    try:
        fc = await build_72h_forecast(28.6139, 77.2090, "Delhi-NCR")
        for h in fc.get("forecast_hours", []):
            if "pm25" in h:
                pm25_series.append(float(h["pm25"]))
            elif "sub_indices" in h:
                found = False
                for s in h["sub_indices"]:
                    if "25" in s.get("pollutant", "") or "2.5" in s.get("pollutant", ""):
                        pm25_series.append(float(s.get("concentration", 50.0)))
                        found = True
                        break
                if not found:
                    pm25_series.append(50.0)
            else:
                pm25_series.append(50.0)
    except Exception:
        pm25_series = []

    return EmissionService.build_72h_source_timeseries(pm25_series=pm25_series)


# ── GET /current-aggregate ───────────────────────────────────────────────────

@router.get(
    "/current-aggregate",
    response_model=CityAggregateResponse,
    summary="Harmonized Delhi NCR City-Wide Aggregate AQI & CPCB Multi-Pollutant Maximum",
    tags=["City Aggregate"],
)
@limiter.limit("60/minute")
async def get_current_aggregate(
    request: Request,
    mode: str = Query("epa", pattern="^(instant|nowcast|epa|cpcb)$", description="AQI calculation mode"),
) -> CityAggregateResponse:
    """
    Computes the unified Delhi NCR City Aggregate AQI across all 43 monitoring stations.
    Applies the official CPCB multi-pollutant maximum index rule across all species.
    """
    return await compute_city_aggregate(mode=mode)


# ── POST /health/chat ────────────────────────────────────────────────────────

class HealthChatPayload(BaseModel):
    messages: list[dict]
    api_key: str | None = None
    temperature: float = 0.6
    max_tokens: int = 1800


@router.post(
    "/health/chat",
    summary="Delhi NCR Health Care Assistant Groq Inference Proxy with Model Fallback",
    tags=["Health Assistant"],
)
@limiter.limit("60/minute")
async def health_chat_proxy(request: Request, payload: HealthChatPayload) -> dict:
    """
    Proxies chat queries to Groq using a resilient 7-tier model fallback sequence.
    Handles server-side execution with zero CORS or CSP preflight blocks.
    """
    key = (payload.api_key or "").strip() or os.getenv("GROQ_API_KEY", "")

    models = [
        {"id": "qwen/qwen3.8-27b", "name": "Qwen 3.8 27B"},
        {"id": "openai/gpt-oss-120b", "name": "GPT-OSS 120B"},
        {"id": "qwen/qwen3.6-27b", "name": "Qwen 3.6 27B"},
        {"id": "openai/gpt-oss-20b", "name": "GPT-OSS 20B"},
        {"id": "groq/compound-mini", "name": "Groq Compound Mini"},
        {"id": "allam-2-7b", "name": "ALLaM 2 7B"},
    ]

    attempts = []
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }

    import time

    async with httpx.AsyncClient(timeout=30.0) as client:
        for m in models:
            start = time.perf_counter()
            try:
                resp = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers=headers,
                    json={
                        "model": m["id"],
                        "messages": payload.messages,
                        "temperature": payload.temperature,
                        "max_tokens": payload.max_tokens,
                    },
                )
                elapsed_ms = int((time.perf_counter() - start) * 1000)

                if resp.status_code == 200:
                    data = resp.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    if content:
                        if "</think>" in content:
                            content = content.split("</think>")[-1].strip()
                        attempts.append({"model": m["name"], "success": True, "durationMs": elapsed_ms})
                        return {
                            "content": content,
                            "modelUsed": m["name"],
                            "latencyMs": elapsed_ms,
                            "attempts": attempts,
                        }
                else:
                    err_msg = f"HTTP {resp.status_code}"
                    try:
                        err_json = resp.json()
                        err_msg = err_json.get("error", {}).get("message", err_msg)
                    except Exception:
                        pass
                    attempts.append({"model": m["name"], "success": False, "error": err_msg, "durationMs": elapsed_ms})
            except Exception as e:
                elapsed_ms = int((time.perf_counter() - start) * 1000)
                attempts.append({"model": m["name"], "success": False, "error": str(e), "durationMs": elapsed_ms})

    error_summary = "\n".join(f"• {a['model']}: {a.get('error', 'Failed')}" for a in attempts)
    raise HTTPException(status_code=502, detail=f"All {len(models)} fallback models failed:\n{error_summary}")


# ── GET /health/tts ──────────────────────────────────────────────────────────

@router.get(
    "/health/tts",
    summary="Multilingual Text-to-Speech Audio Stream for Tamil, Hindi, and English",
    tags=["Health Assistant"],
)
async def get_multilingual_tts(
    text: str = Query(..., description="Text to synthesize to speech"),
    lang: str = Query("en", description="Language code: en, hi, ta"),
) -> Response:
    """
    Streams studio-quality MP3 speech audio for English, Hindi, and Tamil text
    using Google's neural speech synthesis server-side proxy.
    """
    lang_code = "ta" if lang == "ta" else ("hi" if lang == "hi" else "en")
    clean_text = text.strip()[:200]

    if not clean_text:
        raise HTTPException(status_code=400, detail="Text parameter cannot be empty")

    url = f"https://translate.google.com/translate_tts?ie=UTF-8&q={clean_text}&tl={lang_code}&client=tw-ob"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://translate.google.com/",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200 and resp.content:
                return Response(
                    content=resp.content,
                    media_type="audio/mpeg",
                    headers={
                        "Cache-Control": "public, max-age=86400",
                        "Content-Type": "audio/mpeg",
                        "Access-Control-Allow-Origin": "*",
                    },
                )
            else:
                raise HTTPException(status_code=resp.status_code, detail="TTS service upstream error")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"TTS synthesis error: {str(e)}")



# ── GET /industries ──────────────────────────────────────────────────────────

@router.get(
    "/industries",
    response_model=IndustryResponse,
    summary="Delhi-Only Industrial Facilities & Point-Source Emission Hubs",
    tags=["Industries"],
)
@limiter.limit("60/minute")
async def get_delhi_industries(
    request: Request,
    min_lat: float | None = Query(None, description="Optional minimum latitude for viewport filtering"),
    max_lat: float | None = Query(None, description="Optional maximum latitude for viewport filtering"),
    min_lon: float | None = Query(None, description="Optional minimum longitude for viewport filtering"),
    max_lon: float | None = Query(None, description="Optional maximum longitude for viewport filtering"),
) -> IndustryResponse:
    """
    Retrieves industrial facility records strictly filtered to Delhi (city='Delhi' AND state='Delhi').
    Queries Supabase directly with server-side database-level filtering, completely excluding
    Chennai, Tamil Nadu, or any other non-Delhi regions.
    """
    return await fetch_delhi_industries(
        min_lat=min_lat,
        max_lat=max_lat,
        min_lon=min_lon,
        max_lon=max_lon,
    )


# ── GET /forecast/field ────────────────────────────────────────────────────

@router.get(
    "/forecast/field",
    summary="N-station coupled forecast field with IDW-interpolated AQI grid",
    tags=["Forecast"],
)
@limiter.limit("20/minute")
async def forecast_field(
    request: Request,
    n_stations: int = Query(12, ge=1, le=30, description="Station columns (spread-sampled)"),
    hour_index: int = Query(0, ge=0, le=71, description="Hour to interpolate onto the grid"),
) -> dict:
    """Run the coupled column per station (shared met + plume) and interpolate.

    Physics-only field: the trained PM2.5 model stays on the single-point
    endpoint to avoid N duplicate chemistry fetches. Each column keeps its own
    live anchor, so spatial differences are observed seeds, not met gradients.
    """
    from app.services.field_service import build_forecast_field

    try:
        return await build_forecast_field(n_stations=n_stations, hour_index=hour_index)
    except (ValueError, RuntimeError, httpx.HTTPError) as e:
        raise HTTPException(status_code=502, detail=f"Forecast field unavailable: {str(e)}")


# ── GET /validation/cpcb ───────────────────────────────────────────────────

@router.get(
    "/validation/cpcb",
    summary="CPCB ground-truth validation over archived windows (primary truth)",
    tags=["Validation"],
)
@limiter.limit("10/minute")
async def validation_cpcb(
    request: Request,
    dates: str = Query(..., description="Comma-separated YYYY-MM-DD window starts (max 5)"),
    sensor_id: int = Query(12235610, description="OpenAQ PM2.5 sensor id"),
    hours: int = Query(72, ge=24, le=72, description="Hindcast horizon hours"),
) -> dict:
    """Score archived coupled runs against surface observations, not reanalysis."""
    from app.services.validation_service import validate_cpcb_windows

    try:
        parsed = [d.strip() for d in dates.split(",") if d.strip()]
        return await validate_cpcb_windows(parsed, sensor_id=sensor_id, hours=hours)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except (RuntimeError, httpx.HTTPError) as e:
        raise HTTPException(status_code=502, detail=f"CPCB validation unavailable: {str(e)}")


# ── GET /validation/wrf-status ─────────────────────────────────────────────

@router.get(
    "/validation/wrf-status",
    summary="WRF-Chem offline reference availability",
    tags=["Validation"],
)
@limiter.limit("30/minute")
async def validation_wrf_status(request: Request) -> dict:
    """Report whether a WRF-Chem output directory is mounted for comparison."""
    from app.services.wrf_service import wrf_status

    return wrf_status()


# ── GET /validation/wrf-compare ─────────────────────────────────────────────

@router.get(
    "/validation/wrf-compare",
    summary="Score the WRF-Chem reference run (and optionally the surrogate) against CAMS at the Delhi point",
    tags=["Validation"],
)
@limiter.limit("10/minute")
async def validation_wrf_compare(
    request: Request,
    run: str = Query(..., max_length=128, description="wrfout filename inside WRF_OUTPUT_DIR"),
) -> dict:
    """
    Extracts the Delhi-point PM2.5 series from one offline WRF-Chem wrfout
    file and scores it against the CAMS reanalysis archive — the same
    independent truth upstream as the hindcast backtest. Pass a saved
    surrogate series via the service layer to add a surrogate-vs-WRF block.

    Returns 501-class detail when WRF_OUTPUT_DIR is unset (nothing to compare)
    and 502 when the file exists but cannot be parsed or the truth fetch fails.
    """
    from app.services.wrf_service import compare_surrogate_to_wrf

    try:
        return compare_surrogate_to_wrf(run)
    except RuntimeError as e:
        message = str(e)
        status = 503 if "unavailable" in message.lower() else 502
        raise HTTPException(status_code=status, detail=message)


# ── GET /validation/safar ─────────────────────────────────────────────────

@router.get(
    "/validation/safar",
    summary="IITM SAFAR/EWS operational WRF-Chem reference for Delhi (keyless)",
    tags=["Validation"],
)
@limiter.limit("10/minute")
async def validation_safar(request: Request) -> dict:
    """
    Live series from IITM Pune's SAFAR/EWS operational WRF-Chem run for this
    exact domain — the free coupled-model cross-check for the surrogate. No API
    key required. Returns the bulletin rows as received (never interpolated);
    502 with the precise upstream reason when the bulletin is unreachable.
    """
    from app.services.safar_service import fetch_ews_delhi_series

    try:
        return await fetch_ews_delhi_series()
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get(
    "/validation/safar/references",
    summary="Static SAFAR/EWS reference metadata (model class, domain, links)",
    tags=["Validation"],
)
async def validation_safar_references() -> dict:
    """Reference metadata for the IITM SAFAR/EWS operational coupled model."""
    from app.services.safar_service import safar_references

    return safar_references()






