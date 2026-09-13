"""Hindcast validation endpoint — serves the leak-free backtest metrics.

The full backtest integrates up to 12 x 72 h of coupled physics and is far too
heavy to compute per request, so the report is computed once in the background
and cached in-process (refreshed every VALIDATION_TTL_H hours). While the first
computation is still running the endpoint says so instead of blocking.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import APIRouter, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.services.backtest_service import run_hindcast_backtest

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)

_TTL_S = 6 * 3600.0

_cache: dict[str, Any] | None = None
_cache_at: float = 0.0
_refresh_task: asyncio.Task | None = None


async def _compute_and_store() -> None:
    global _cache, _cache_at
    try:
        report = await run_hindcast_backtest()
        _cache = report
        _cache_at = time.monotonic()
    except Exception:
        # Leave any previous cache in place; a failed refresh is not fatal.
        if _cache is None:
            _cache = {
                "available": False,
                "reason": "backtest computation failed; see server logs",
            }
            _cache_at = time.monotonic()


def _maybe_start_refresh() -> None:
    global _refresh_task
    if _refresh_task is not None and not _refresh_task.done():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    _refresh_task = loop.create_task(_compute_and_store())


def warm_backtest_cache() -> None:
    """Fire the first computation at app startup (called from main.py)."""
    _maybe_start_refresh()


@router.get(
    "/validation/backtest",
    summary="Hindcast validation: 72 h physics-only forecasts scored against CAMS reanalysis",
    tags=["Validation"],
)
@limiter.limit("30/minute")
async def validation_backtest(request: Request, force: int = 0) -> dict[str, Any]:
    """
    Returns the cached hindcast validation report: pooled MBE/MAE/RMSE/r/NSE
    for PM2.5 against CAMS reanalysis, skill vs the persistence baseline,
    per-lead breakdown, and a paired bootstrap CI.

    The report is computed in the background at startup and refreshed every
    6 hours; this endpoint never blocks on the computation itself. `?force=1`
    schedules an immediate recompute (still served from cache until done).
    Protocol and exclusions are inline — see `protocol.exclusions`.
    """
    fresh = _cache is not None and (time.monotonic() - _cache_at) < _TTL_S
    if not fresh or force:
        _maybe_start_refresh()

    if _cache is None:
        return {
            "available": False,
            "status": "computing",
            "reason": "first hindcast validation is still running; retry shortly",
        }

    age_s = int(time.monotonic() - _cache_at)
    return {
        **_cache,
        "cache": {"age_s": age_s, "fresh": fresh, "refresh_interval_h": _TTL_S / 3600.0},
    }
