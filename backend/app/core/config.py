"""
App-wide configuration loaded from environment via pydantic-settings.
All secrets come from .env — never hardcoded.
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env from THIS file's location, not the process working directory.
# It was previously the relative string "../.env", which only resolved correctly
# when uvicorn happened to be launched from inside backend/. Started from the
# repo root instead, "../.env" pointed at the parent of the repo, the file was
# silently not found, and openaq_api_key stayed "" until a request failed with a
# confusing ValueError. backend/app/core/config.py -> parents[3] is the repo root.
_ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"
_BACKEND_ENV = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(_ROOT_ENV, _BACKEND_ENV),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────
    app_env: str = "development"
    app_debug: bool = False
    app_api_key: str = "change-me"

    # ── CORS ─────────────────────────────────────────────────
    # Comma-separated list in the env var; split once via the `cors_origins`
    # property below rather than on every request. Defaults cover the two local
    # front-ends: Streamlit (8501) and the Vite dev server for the React console
    # (5173). The production console is served same-origin from /console, so it
    # needs no CORS entry.
    allowed_origins: str = "*"

    @property
    def cors_origins(self) -> list[str]:
        if self.allowed_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.allowed_origins.split(",")]

    # ── Rate limit ────────────────────────────────────────────
    # Per-route limits are declared with @limiter.limit(...) in
    # api/v1/endpoints.py, because they differ per endpoint (20-120/min). There
    # is deliberately no global RATE_LIMIT setting: one previously existed here,
    # was read by nothing, and implied a knob that did not work.

    firms_api_key: str = ""
    openaq_api_key: str = ""
    openweather_api_key: str = ""
    api_ninjas_api_key: str = ""
    meteosource_api_key: str = ""
    iqair_api_key: str = ""
    cpcb_api_key: str = ""
    weatherapi_api_key: str = ""
    weather_provider_order: str = "weatherapi"

    @property
    def weather_providers(self) -> list[str]:
        order = [p.strip().lower() for p in self.weather_provider_order.split(",") if p.strip()]
        return order or ["weatherapi"]

    openaq_max_reading_age_hours: float = 24.0

    supabase_url: str = ""
    supabase_key: str = ""
    supabase_anon_key: str = ""

    # No REDIS_URL / SECRET_KEY. Both were declared here and read by nothing:
    # caching is an in-process TTLCache in services/realtime_service.py and there
    # is no JWT layer. Leftover env keys are harmless now that extra="ignore".


@lru_cache
def get_settings() -> Settings:
    return Settings()
