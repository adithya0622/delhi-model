"""Consolidation regression: /api/forecast must serve the SAME coupled engine
as /api/v1/forecast/72hr.

The route previously proxied a second, hand-tuned feedback loop (fixed magic
constants: -0.015 C per ug/m3 temp penalty, a flat 40 ug/m3 stubble injection,
no coupling solver). That duplicate is gone; this test pins the replacement so
the weak implementation cannot silently return.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_api_forecast_serves_the_coupled_engine():
    response = client.get("/api/forecast")
    assert response.status_code == 200, response.text
    body = response.json()

    hours = body["forecast_hours"]
    assert len(hours) == 72

    # Coupled-engine diagnostics must be present and coherent on every hour.
    for h in hours:
        assert h["feedback_iterations"] >= 1
        assert 0.0 <= h["pbl_suppression_pct"] <= 100.0
        assert h["pbl_height_m"] > 0
        assert 0.0 <= h["aerosol_optical_depth"] <= 3.0

    # AQI is max(sub-indices) — the project's load-bearing invariant.
    for h in hours:
        max_si = max(s["sub_index"] for s in h["sub_indices"])
        assert h["aqi"] == max_si

    # Path dependence: an hour's PM2.5 is inherited, not regenerated, so the
    # nocturnal accumulation signature must exist somewhere in the window.
    pm25 = [h["sub_indices"][0]["concentration"] for h in hours]
    assert max(pm25) > min(pm25)
