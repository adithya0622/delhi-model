"""
Live end-to-end hindcast: anchors one 72 h window in the past, runs the
production physics integrator on analysis meteorology, and scores it against
the real CAMS archive.

Network-dependent: skipped when the upstream APIs are unreachable. This is the
test that produces the accuracy numbers quoted in the README.
"""
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.backtest_service import (
    compute_metrics,
    fetch_analysis_met,
    fetch_cams_history,
    run_hindcast_backtest,
)


async def _upstream_reachable() -> bool:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                "https://air-quality-api.open-meteo.com/v1/air-quality",
                params={"latitude": 28.6139, "longitude": 77.2090, "hourly": "pm2_5", "past_days": 1},
            )
            return r.status_code == 200
    except httpx.HTTPError:
        return False


@pytest.mark.asyncio
async def test_single_window_hindcast_produces_finite_scores():
    if not await _upstream_reachable():
        pytest.skip("CAMS archive unreachable — validation needs the live upstream")

    from datetime import datetime, timedelta, timezone

    # Window anchored 6 days back (ends ≥ 3 days ago, per the protocol).
    ist = timedelta(hours=5, minutes=30)
    start_day = (datetime.now(timezone.utc) + ist - timedelta(days=6)).date()
    start_s = f"{start_day:%Y-%m-%d}T00:00"

    cams = await fetch_cams_history(days_back=8)
    assert len(cams["time"]) > 72, "CAMS archive returned too little history"

    met = await fetch_analysis_met(start_s)
    times = met["hourly"]["time"]
    assert len(times) == 72

    cams_index = {t: i for i, t in enumerate(cams["time"])}

    def cams_at(stamp: str) -> float | None:
        i = cams_index.get(stamp)
        v = cams["pm25"][i] if i is not None and i < len(cams["pm25"]) else None
        return float(v) if v is not None else None

    start_dt = datetime.fromisoformat(start_s)
    anchor_stamp = (start_dt - timedelta(hours=1)).strftime("%Y-%m-%dT%H:00")
    anchor = cams_at(anchor_stamp)
    assert anchor is not None, "no CAMS anchor value available"

    from app.services.aqi_service import build_72h_forecast

    result = await build_72h_forecast(
        28.6139,
        77.2090,
        "Delhi-ITO (hindcast)",
        live_pm25=anchor,
        met_data_override=met,
        plume_override={"hotspots": [], "plumes": []},
        use_ml=False,
    )
    hours = result["forecast_hours"]
    assert len(hours) == 72

    pred = []
    for h in hours:
        si = next((s for s in h["sub_indices"] if s["pollutant"] == "PM2.5"), None)
        assert si is not None, "every hour must expose a PM2.5 sub-index"
        pred.append(float(si["concentration"]))

    # Anti-leakage: hour 0 inherits the anchor; hours 1.. must be projections.
    assert abs(pred[0] - anchor) < 0.15 * max(anchor, 1.0)
    assert len({round(p, 1) for p in pred[1:]}) > 10, "hindcast degenerated to a flat line"

    obs = [cams_at(t) for t in times]
    m = compute_metrics(obs, pred)
    assert m["n"] >= 0.85 * 72, f"CAMS coverage too thin: {m['n']}/72"
    assert m["mae_ug_m3"] < 200.0, f"hindcast MAE exploded: {m['mae_ug_m3']}"

    # Persist the numbers the docs quote, so regressions are visible in CI logs.
    # ASCII only: Windows CI consoles are frequently cp1252.
    print(
        "\nHINDCAST WINDOW {} -> MAE {} ug/m3 | RMSE {} | r {} | MBE {}".format(
            times[0], m["mae_ug_m3"], m["rmse_ug_m3"], m["pearson_r"], m["mbe_ug_m3"]
        )
    )


@pytest.mark.asyncio
async def test_full_backtest_report_shape():
    if not await _upstream_reachable():
        pytest.skip("CAMS archive unreachable — validation needs the live upstream")

    report = await run_hindcast_backtest(max_windows=2)
    assert report["available"] is True
    assert report["protocol"]["windows"] >= 1
    assert "exclusions" in report["protocol"]
    pooled = report["pooled"]
    for key in ("mae_ug_m3", "rmse_ug_m3", "pearson_r", "nash_sutcliffe_e"):
        assert key in pooled
    assert report["skill_vs_persistence"]["mae_skill_score"] is not None
    assert len(report["by_lead"]) == 4
