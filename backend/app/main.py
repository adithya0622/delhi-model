"""
FastAPI Application Entry Point
================================
- Mounts v1 router
- Applies CORS (restricted to configured origins)
- Injects secure HTTP headers via middleware
- Configures slowapi rate limiter
- Auto-generates OpenAPI docs at /docs
"""
import os
from pathlib import Path

from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
import httpx

from app.api.v1.endpoints import limiter, router
from app.core.config import get_settings
from app.schemas.forecast import ForecastResponse
from app.services.aqi_service import build_72h_forecast
from app.api.v1.backtest_endpoint import warm_backtest_cache
from app.core.security import (
    CONSOLE_CSP,
    CONSOLE_PATH_PREFIX,
    DOCS_CSP,
    DOCS_PATHS,
    SECURE_HEADERS,
)

settings = get_settings()

app = FastAPI(
    title="Delhi NCR AQI Forecasting System",
    description=(
        "72-hour coupled AQI forecast with atmospheric inversion diagnostics, "
        "stubble-burn plume dispersion, and aerosol radiative feedback."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# ── Rate limiter ──────────────────────────────────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["X-API-Key", "Content-Type"],
)

# ── Secure headers middleware ─────────────────────────────────────────────────
@app.middleware("http")
async def add_security_headers(request: Request, call_next) -> Response:
    response = await call_next(request)
    for header, value in SECURE_HEADERS.items():
        response.headers[header] = value
    # /docs and /redoc load their bundles from cdn.jsdelivr.net, which the strict
    # script-src blocks; relax the policy on those two routes only.
    if request.url.path in DOCS_PATHS:
        response.headers["Content-Security-Policy"] = DOCS_CSP
    # The /console document pulls IBM Plex from Google Fonts; relax the policy for
    # the console's own paths only (its JS/CSS are same-origin and already allowed).
    elif request.url.path == CONSOLE_PATH_PREFIX or request.url.path.startswith(
        CONSOLE_PATH_PREFIX + "/"
    ):
        response.headers["Content-Security-Policy"] = CONSOLE_CSP
    return response


# ── Routes ────────────────────────────────────────────────────────────────────
app.include_router(router)


@app.on_event("startup")
async def _startup_tasks() -> None:
    # Kick off the hindcast validation in the background so the first
    # /api/v1/validation/backtest request does not have to wait ~1 minute for
    # the full 4-window coupled integration.
    warm_backtest_cache()


@app.get("/api/forecast", tags=["Deterministic Feedback Forecast"])
async def deterministic_forecast(
    lat: float = 28.6139,
    lon: float = 77.2090,
    station_name: str = "Delhi-NCR",
) -> ForecastResponse:
    """
    72-hour coupled forecast — the SAME two-way aerosol/meteorology feedback
    engine as /api/v1/forecast/72hr (Picard fixed point, inversion diagnostics,
    plume coupling), exposed without the /api/v1 prefix.

    Consolidation note: this route previously served a second, hand-tuned
    feedback loop (fixed constants, no coupling solver). That duplicate was
    removed so the project has exactly one feedback implementation; every
    /forecast response now carries the coupled engine's diagnostics
    (feedback_iterations, pbl_suppression_pct, aerosol_dt_surface_c).
    """
    try:
        data = await build_72h_forecast(lat, lon, station_name)
        return ForecastResponse(**data)
    except (ValueError, RuntimeError, httpx.HTTPError) as exc:
        raise HTTPException(status_code=502, detail=f"Deterministic forecast failed: {exc}") from exc


@app.post("/api/exposure/calculate", tags=["Exposure"])
async def exposure_calculate_direct(request: Request, payload: dict) -> dict:
    """Direct alias for /api/v1/exposure/calculate."""
    from app.schemas.forecast import ExposureRequest
    from app.services.exposure_service import calculate_personalized_exposure
    from app.services.aqi_service import build_72h_forecast

    req = ExposureRequest(**payload)
    forecast_points = req.forecast_72h
    if not forecast_points:
        try:
            fc = await build_72h_forecast(28.6139, 77.2090, "Delhi-NCR")
            forecast_points = fc.get("forecast_hours", [])
        except Exception:
            forecast_points = []

    return calculate_personalized_exposure(
        activity_type=req.activity_type,
        duration_hours=req.duration_hours,
        target_time=req.target_time,
        current_pm25=req.current_pm25,
        forecast_72h=forecast_points,
    )


@app.get("/api/forecast/source-apportionment", tags=["Source Apportionment"])
async def source_apportionment_direct(
    pm25: float | None = None,
    no2: float | None = None,
    hour: int | None = None,
) -> dict:
    """Direct alias for /api/v1/forecast/source-apportionment."""
    from app.services.consensus_service import collect_consensus
    from app.services.emission_service import EmissionService

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

    res = EmissionService.calculate_source_apportionment(
        current_pm25=pm25,
        current_no2=no2,
        hour=hour,
    )
    return res.model_dump()


@app.get("/api/forecast/source-timeseries", tags=["Source Apportionment"])
async def source_timeseries_direct() -> dict:
    """Direct alias for /api/v1/forecast/source-timeseries."""
    from app.services.aqi_service import build_72h_forecast
    from app.services.emission_service import EmissionService

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

    res = EmissionService.build_72h_source_timeseries(pm25_series=pm25_series)
    return res.model_dump()


@app.get("/api/current-aggregate", tags=["City Aggregate"])
async def current_aggregate_direct(mode: str = "instant") -> dict:
    """Direct alias for /api/v1/current-aggregate."""
    from app.services.aqi_service import compute_city_aggregate

    res = await compute_city_aggregate(mode=mode)
    return res.model_dump()






# ── Static console (built React frontend) ─────────────────────────────────────
# The production build in webapp/dist is served same-origin at /console, so its
# /api/v1 calls need no CORS. The directory is resolved from CONSOLE_DIST_DIR when
# set (the Docker image copies the build to a fixed path), otherwise from
# webapp/dist beside the repo. If the build is absent the mount is skipped and the
# API still runs standalone with / returning the JSON service descriptor.
_default_dist = Path(__file__).resolve().parents[2] / "webapp" / "dist"
_console_dir = Path(os.environ.get("CONSOLE_DIST_DIR", str(_default_dist)))
_console_available = (_console_dir / "index.html").is_file()


def _stream_video(request: Request, video_path: Path):
    if not video_path.is_file():
        raise HTTPException(status_code=404, detail="Background video not found")
    file_size = video_path.stat().st_size
    range_header = request.headers.get("range")
    if range_header:
        try:
            h = range_header.replace("bytes=", "").split("-")
            start = int(h[0]) if h[0] else 0
            end = int(h[1]) if len(h) > 1 and h[1] else file_size - 1
            end = min(end, file_size - 1)
            length = end - start + 1
        except Exception:
            start = 0
            end = file_size - 1
            length = file_size

        def iter_range():
            with open(video_path, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(remaining, 64 * 1024))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        headers = {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
            "Content-Type": "video/mp4",
        }
        return StreamingResponse(iter_range(), status_code=206, headers=headers)
    else:
        def iter_file():
            with open(video_path, "rb") as f:
                while chunk := f.read(64 * 1024):
                    yield chunk

        headers = {
            "Content-Length": str(file_size),
            "Accept-Ranges": "bytes",
            "Content-Type": "video/mp4",
        }
        return StreamingResponse(iter_file(), status_code=200, headers=headers)


@app.get("/bg-video.mp4", include_in_schema=False)
@app.get("/console/bg-video.mp4", include_in_schema=False)
async def serve_bg_video(request: Request):
    video_path = _console_dir / "bg-video.mp4"
    if video_path.is_file():
        return _stream_video(request, video_path)
    public_path = Path(__file__).resolve().parents[2] / "webapp" / "public" / "bg-video.mp4"
    if public_path.is_file():
        return _stream_video(request, public_path)
    raise HTTPException(status_code=404, detail="Background video not found")


if _console_available:
    # html=True serves index.html at the mount root; assets resolve under
    # /console/assets/… because the frontend was built with base="/console/".
    app.mount(
        CONSOLE_PATH_PREFIX,
        StaticFiles(directory=str(_console_dir), html=True),
        name="console",
    )


@app.get("/", include_in_schema=False)
async def root():
    # When the console is built, / is the operator's front door — send them to it.
    # Otherwise keep the machine-readable descriptor so the API is usable alone.
    if _console_available:
        return RedirectResponse(url=f"{CONSOLE_PATH_PREFIX}/")
    return {
        "service": "Delhi NCR AQI Forecasting API",
        "docs": "/docs",
        "health": "/api/v1/health",
    }
