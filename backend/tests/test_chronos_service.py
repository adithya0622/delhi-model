"""Chronos T5 service + endpoint: AQI helpers, probabilistic inference, fallback.

Offline by construction: the happy-path tests mount a FAKE Chronos pipeline
(deterministic token-sample tensor) so no weights, downloads, or long generate
loops are needed; fallback paths are exercised via the same loader seams.

The _FakePipeline mocks construct torch tensors at fixture time. When the OS
blocks torch's DLLs (Windows Application Control can — WinError 4551), those
inference tests SKIP honestly rather than fail: the runtime genuinely cannot
serve the model on such a machine, and the endpoint degrades to the ML
fallback by design (covered by the loader-failure tests below).
"""
from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from app.services import chronos_forecast_service as cfs
from app.api.v1.ml_forecast_endpoint import compute_hour_aqi


def _torch_available() -> bool:
    try:
        import torch  # noqa: F401
        return True
    except Exception:
        return False


_requires_torch = pytest.mark.skipif(
    not _torch_available(),
    reason="torch unavailable on this machine (OS policy blocked its DLLs); "
           "runtime degrades to the ML fallback path",
)


# ── AQI helper consistency with the rest of the API ─────────────────────────

CONC_SETS = [
    {"pm25": 180.0, "pm10": 300.0, "no2": 60.0, "o3": 40.0, "so2": 20.0, "co": 800.0},
    {"pm25": 60.0, "pm10": 70.0, "no2": 20.0, "o3": 150.0, "so2": 10.0, "co": 500.0},
    {"pm25": 12.0, "pm10": 30.0, "no2": 10.0, "o3": 20.0, "so2": 5.0, "co": 400.0},
]


@pytest.mark.parametrize("conc", CONC_SETS)
@pytest.mark.parametrize("mode", ["instant", "epa"])
def test_hour_aqi_matches_serving_breakpoint_tables(conc, mode):
    """Chronos AQI arithmetic == the endpoint's compute_hour_aqi, exactly."""
    ours = cfs._hour_aqi(conc, mode)
    theirs = compute_hour_aqi(conc, mode)
    assert ours["aqi"] == theirs["aqi"]
    assert ours["category"] == theirs["category"]
    assert ours["dominant_pollutant"] == theirs["dominant_pollutant"]


def test_hour_aqi_missing_species_cannot_win_and_all_none_is_unknown():
    assert cfs._hour_aqi({"no2": 40.0}, "instant")["aqi"] == compute_hour_aqi({"no2": 40.0}, "instant")["aqi"]
    empty = cfs._hour_aqi({k: None for k in ("pm25", "pm10", "no2", "o3", "so2", "co")}, "instant")
    assert empty["aqi"] == 0 and empty["dominant_pollutant"] == "unknown"


# ── predict_72hr_chronos: unavailable-artifact contract ─────────────────────

@pytest.fixture()
def _loader_none(monkeypatch):
    monkeypatch.setattr(cfs, "_load_pipeline", lambda: (None, "test loader unavailable"))
    yield


def _grid(hours=72, start="2026-09-12T00:00"):
    from datetime import timedelta
    t0 = datetime.fromisoformat(start)
    return [ (t0 + timedelta(hours=h)).isoformat() for h in range(hours) ]


def test_predict_returns_none_with_reason_when_loader_fails(_loader_none):
    history = {s: [40.0] * 168 for s in ("pm2_5", "pm10", "no2", "o3", "so2", "co")}
    hours, status = cfs.predict_72hr_chronos(history, {"hourly": {"time": _grid()}})
    assert hours is None
    assert status["available"] is False and status["used"] is False
    assert status.get("reason")


def test_predict_requires_72h_grid(_loader_none):
    history = {s: [40.0] * 168 for s in ("pm2_5", "pm10", "no2", "o3", "so2", "co")}
    hours, status = cfs.predict_72hr_chronos(history, {"hourly": {"time": _grid(10)}})
    assert hours is None


# ── predict_72hr_chronos: happy path with a deterministic fake pipeline ─────

class _FakePipeline:
    """Constant token-sample trajectories: median = base per species."""

    base = {"pm2_5": 80.0, "pm10": 150.0, "no2": 40.0, "o3": 30.0, "so2": 10.0, "co": 1.0}

    def predict(self, context, prediction_length=None, num_samples=None, limit_prediction_length=False):
        import torch
        order = ("pm2_5", "pm10", "no2", "o3", "so2", "co")
        out = torch.ones((len(order), num_samples, prediction_length))
        for k, s in enumerate(order):
            out[k] = self.base[s]
        return out


@pytest.fixture()
def _fake_loader(monkeypatch):
    meta = {
        "artifact_dir": "fake",
        "vocabulary_size": 4096,
        "n_special_tokens": 2,
        "model_context_length": 512,
        "native_prediction_length": 64,
        "model_type": "seq2seq",
        "num_samples_default": 20,
    }
    monkeypatch.setattr(cfs, "_load_pipeline", lambda: ((_FakePipeline(), meta), ""))
    yield


def _full_history():
    return {s: [_FakePipeline.base[s]] * 168 for s in ("pm2_5", "pm10", "no2", "o3", "so2", "co")}


@_requires_torch
def test_predict_happy_path_shape_and_quantiles(_fake_loader):
    history = _full_history()
    history["co"] = [1.2] * 168  # mg/m³ native scale → factor 1000 for AQI
    hours, status = cfs.predict_72hr_chronos(history, {"hourly": {"time": _grid()}}, num_samples=7)
    assert status["used"] is True and len(hours) == 72
    h0 = hours[0]
    assert h0["hour_index"] == 1
    assert h0["pollutants"]["pm2_5"] == {"p10": 80.0, "p50": 80.0, "p90": 80.0}
    assert h0["pollutants"]["no2"] == {"p50": 40.0}
    assert status["co_ugm3_factor"] == 1000.0
    # AQI must be computed from the canonical µg/m³ concentrations (CO ×1000).
    expected = compute_hour_aqi(
        {"pm25": 80.0, "pm10": 150.0, "no2": 40.0, "o3": 30.0, "so2": 10.0, "co": 1200.0}, "instant"
    )
    assert h0["aqi_cpcb"] == expected["aqi"]
    assert h0["dominant_pollutant"] == expected["dominant_pollutant"]
    assert h0["aqi_epa"] == compute_hour_aqi(
        {"pm25": 80.0, "pm10": 150.0, "no2": 40.0, "o3": 30.0, "so2": 10.0, "co": 1200.0}, "epa"
    )["aqi"]
    assert hours[-1]["hour_index"] == 72


@_requires_torch
def test_predict_rejects_species_without_history(_fake_loader):
    history = _full_history()
    history["o3"] = []
    hours, status = cfs.predict_72hr_chronos(history, {"hourly": {"time": _grid()}})
    assert hours is None and "o3" in (status.get("reason") or "")


@_requires_torch
def test_predict_clamps_negatives_and_pads_short_history(_fake_loader):
    history = {s: [_FakePipeline.base[s]] * 168 for s in ("pm2_5", "pm10", "no2", "o3", "so2", "co")}
    history["pm2_5"] = [None] * 100 + [-5.0, float("nan")] + [90.0] * 66
    hours, status = cfs.predict_72hr_chronos(history, {"hourly": {"time": _grid()}})
    assert hours is not None
    assert status["context_hours_report"]["pm2_5"] == 66


# ── CAMS context builder (endpoint-side, pure) ──────────────────────────────

def test_build_history_series_maps_vars_and_filters_future():
    from app.api.v1.chronos_endpoint import build_history_series

    cams = {
        "time": ["2026-09-12T00:00", "2026-09-12T01:00", "2026-09-12T02:00"],
        "pm2_5": [80.0, 90.0, 100.0],
        "nitrogen_dioxide": [40.0, 41.0, 42.0],
        "carbon_monoxide": [1.0, None, -3.0],
    }
    origin = datetime.fromisoformat("2026-09-12T02:00")
    series = build_history_series(cams, origin)
    assert series["pm2_5"] == [80.0, 90.0]
    assert series["no2"] == [40.0, 41.0]
    assert series["co"] == [1.0, None]  # negative → None, future row excluded


# ── Endpoint: fallback + happy path (offline) ───────────────────────────────

def _make_request(path="/api/v1/forecast/72hr-chronos"):
    from starlette.requests import Request
    scope = {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1", "method": "GET", "scheme": "http",
        "path": path, "raw_path": path.encode(), "query_string": b"",
        "root_path": "", "server": ("127.0.0.1", 8000), "client": ("127.0.0.1", 55590),
        "headers": [],
    }
    return Request(scope)


@pytest.fixture()
def _offline_endpoint(monkeypatch):
    ep = pytest.importorskip("app.api.v1.chronos_endpoint")
    times = _grid()
    # CAMS archive shape: 14 past days of hourly stamps BEFORE the forecast origin.
    origin = datetime.fromisoformat(times[0])
    from datetime import timedelta
    hist_times = [(origin - timedelta(hours=k)).isoformat() for k in range(200, 0, -1)]
    async def fake_met(lat, lon):
        return {"hourly": {"time": times}, "weather_source": "open-meteo", "provider_failures": []}
    async def fake_cams(lat, lon, past_days=14):
        return {
            "time": hist_times,
            **{v: [50.0] * len(hist_times) for v in ("pm2_5", "pm10", "nitrogen_dioxide", "ozone", "sulphur_dioxide", "carbon_monoxide")},
        }
    monkeypatch.setattr(ep, "fetch_forecast_weather", fake_met)
    monkeypatch.setattr(ep, "fetch_cams_context", fake_cams)
    # Pin the serving model so tests never depend on machine-local
    # model_comparison.json state (the measured winner may flip either way).
    monkeypatch.setattr(ep, "serving_model", lambda: "t5")
    return ep


def test_endpoint_falls_back_when_chronos_unavailable(_offline_endpoint, monkeypatch, _loader_none):
    ep = _offline_endpoint

    async def fake_ml(request, *, lat, lon, station_name):
        return {"forecast_hours": [{"timestamp": "x"}], "model": "ml"}

    monkeypatch.setattr(ep, "_ml_forecast_handler", fake_ml)
    result = asyncio.run(ep.forecast_72hr_chronos(
        _make_request(), lat=28.6139, lon=77.2090, station_name="X", num_samples=20
    ))
    assert result["fallback_used"] is True
    assert result["model"] == "ml"
    assert result["chronos_status"].get("reason")


@_requires_torch
def test_endpoint_serves_chronos_forecast(_offline_endpoint, monkeypatch, _fake_loader):
    ep = _offline_endpoint
    result = asyncio.run(ep.forecast_72hr_chronos(
        _make_request(), lat=28.6139, lon=77.2090, station_name="Delhi-ITO", num_samples=20
    ))
    assert result["fallback_used"] is False
    assert result["model_name"] == "Amazon Chronos T5 (Open Source Foundation Model)"
    assert result["vocabulary_size"] == 4096
    assert result["forecast_horizon_hours"] == 72
    assert len(result["hourly"]) == 72
    h0 = result["hourly"][0]
    assert h0["pollutants"]["pm2_5"]["p50"] == _FakePipeline.base["pm2_5"]  # fake pipeline's constant output
    assert result["chronos_status"]["context_hours_report"]["pm2_5"] == 168  # full context consumed
    assert h0["aqi_cpcb"] > 0 and h0["aqi_category"]
    assert isinstance(result["verification"], dict)


def test_status_endpoint_shape(_loader_none):
    status = cfs.chronos_model_status()
    assert status["available"] is False
    assert status["mode"] == "none" and status.get("reason")


@_requires_torch
def test_endpoint_serves_chronos2_when_selected(_offline_endpoint, monkeypatch, _fake_loader):
    """When the measured winner is Chronos-2, the endpoint dispatches to the
    C2 path with covariates and labels the response honestly."""
    ep = _offline_endpoint
    monkeypatch.setattr(ep, "serving_model", lambda: "chronos2")
    monkeypatch.setattr(cfs, "_load_chronos2", lambda: (_FakeC2Pipeline(), "loaded fake"))

    async def fake_met_context(lat, lon):
        from datetime import timedelta
        origin = datetime.fromisoformat(_grid()[0])
        past = [(origin - timedelta(hours=k)).isoformat() for k in range(200, 0, -1)]
        future = _grid()
        times = past + future
        return {
            "time": times,
            **{v: [10.0] * len(times) for v in (
                "temperature_2m", "relative_humidity_2m", "wind_speed_10m",
                "boundary_layer_height", "shortwave_radiation",
            )},
        }

    monkeypatch.setattr(ep, "fetch_met_context", fake_met_context)
    result = asyncio.run(ep.forecast_72hr_chronos(
        _make_request(), lat=28.6139, lon=77.2090, station_name="Delhi-ITO", num_samples=20
    ))
    assert result["fallback_used"] is False
    assert "Chronos-2" in result["model_name"]
    assert result["vocabulary_size"] is None  # C2 has no 4096-token vocabulary
    assert result["chronos_status"]["model"] == "chronos2"
    assert result["chronos_status"]["covariates_passed"]  # met covariates rode along
    assert len(result["hourly"]) == 72


# ── Chronos-2 serving path + winner selection ───────────────────────────────

class _FakeC2Pipeline:
    quantiles = [0.1, 0.5, 0.9]

    def predict(self, inputs, prediction_length=None, **kwargs):
        import torch
        return [torch.ones((6, 3, prediction_length)) * 45.0]


@_requires_torch
def test_predict_c2_happy_path_with_covariates(_fake_loader, monkeypatch):
    monkeypatch.setattr(cfs, "_load_chronos2", lambda: (_FakeC2Pipeline(), "loaded fake"))
    history = _full_history()
    history["co"] = [1.1] * 168
    covs = {"temperature_2m": ([20.0] * 168, [22.0] * 72)}
    hours, status = cfs.predict_72hr_chronos_c2(history, {"hourly": {"time": _grid()}}, covs)
    assert status["used"] is True and status["model"] == "chronos2"
    assert len(hours) == 72
    assert status["covariates_passed"] == ["temperature_2m"]
    assert hours[0]["pollutants"]["pm2_5"] == {"p10": 45.0, "p50": 45.0, "p90": 45.0}
    assert hours[0]["aqi_cpcb"] > 0


def test_predict_c2_reason_when_loader_fails(monkeypatch):
    monkeypatch.setattr(cfs, "_load_chronos2", lambda: (None, "no chronos-2 checkpoint"))
    history = _full_history()
    hours, status = cfs.predict_72hr_chronos_c2(history, {"hourly": {"time": _grid()}})
    assert hours is None and "chronos-2" in (status.get("reason") or "")


def test_serving_model_default_and_override(monkeypatch):
    monkeypatch.delenv("CHRONOS_MODEL", raising=False)
    monkeypatch.setattr(cfs, "_metrics_json", lambda: {})
    assert cfs.serving_model() == "t5"  # judge-mandated default
    monkeypatch.setenv("CHRONOS_MODEL", "chronos2")
    assert cfs.serving_model() == "chronos2"
    monkeypatch.delenv("CHRONOS_MODEL", raising=False)
    monkeypatch.setattr(
        cfs, "_metrics_json",
        lambda: {"model_comparison": {"winner_by_aqi_mae": "chronos2_zero_shot"}},
    )
    assert cfs.serving_model() == "chronos2"  # measured winner decides


# ── Delhi fine-tuned Chronos-2 specialists (chronos2_ft serving variant) ─────

class _FakeFTPipeline:
    """Per-species fake: constant quantile output, records the covariate order."""

    quantiles = [0.1, 0.5, 0.9]
    seen_covariate_orders: dict[str, list[str]] = {}

    def __init__(self, species: str, value: float = 45.0):
        self._species = species
        self._value = value

    def predict(self, inputs, prediction_length=None, **kwargs):
        import torch
        inp = inputs[0]
        _FakeFTPipeline.seen_covariate_orders[self._species] = list(
            inp.get("past_covariates", {}).keys()
        )
        return [torch.ones((1, 3, prediction_length)) * self._value]


def _patch_ft_ready(monkeypatch, value: float = 45.0):
    """Gates PASS + fake pipelines for every species."""
    metrics = {
        "gates_verdict": "PASS",
        "gates": {"pm2_5_rmse_lt_15": True, "pm2_5_r2_gt_087": True},
        "species": {"pm2_5": {"mae": 9.0, "rmse": 11.5, "r2": 0.91, "n": 3456}},
        "ablation": {"pm2_5_no_future_covariates": {"rmse": 40.1, "r2": 0.2}},
        "leakage_note": "test note",
        "holdout_start": "2025-09-12",
        "eval_origins": 48,
    }
    monkeypatch.setattr(cfs, "_finetune_metrics", lambda: metrics)
    monkeypatch.setattr(cfs, "finetuned_serving_ready", lambda: True)  # checkpoints exist on disk

    def _loader(species, cell_subdir: str = ""):
        # cell_subdir: per-cell adopted checkpoints (chronos2_cells/) — the
        # fake pipelines are city/cell-agnostic, so the subdir is ignored.
        return _FakeFTPipeline(species, value), ""

    monkeypatch.setattr(cfs, "_load_ft_pipeline", _loader)


_FT_HISTORY = {s: [40.0] * 800 for s in ("pm2_5", "pm10", "no2", "o3", "so2", "co")}


def test_ft_covariate_order_matches_trainer():
    order = cfs.chronos2_covariate_order("pm2_5")
    # The target species' own past rides in the TARGET channel (C2 native
    # schema), NOT as a covariate — its own future can never leak through.
    assert order[0] == "cam_pm10"
    assert "cam_pm2_5" not in order and "cam_pm10" in order  # target never a covariate
    assert order[-4:] == ["cal_hod_sin", "cal_hod_cos", "cal_doy_sin", "cal_doy_cos"]
    assert len(order) == 5 + 2 + 9 + 4  # 5 co-pollutants + AOD/dust + 9 met + 4 calendar


@_requires_torch
def test_predict_ft_happy_path_and_self_past_channel(monkeypatch):
    _patch_ft_ready(monkeypatch)
    covs = {
        "cam_pm10": ([10.0] * 730, [11.0] * 72),
        "met_temperature_2m": ([20.0] * 730, [21.0] * 72),
        "cal_hod_sin": ([0.0] * 730, [0.0] * 72),
    }
    hours, status = cfs.predict_72hr_chronos2_finetuned(
        _FT_HISTORY, covs, {"hourly": {"time": _grid()}}
    )
    assert status["used"] is True
    assert status["serving_variant"] == "chronos2_delhi_finetuned"
    assert status["serving_context_hours"] == 720
    assert len(hours) == 72
    assert hours[0]["pollutants"]["pm2_5"] == {"p10": 45.0, "p50": 45.0, "p90": 45.0}
    # Every specialist received its channels in EXACTLY the trained order
    # (own history travels in the target channel; never as a covariate).
    for species, order in _FakeFTPipeline.seen_covariate_orders.items():
        assert order == cfs.chronos2_covariate_order(species)
    assert "cam_pm2_5" not in _FakeFTPipeline.seen_covariate_orders["pm2_5"]


def test_predict_ft_refuses_when_gates_fail(monkeypatch):
    metrics = {"gates_verdict": "FAIL", "species": {"pm2_5": {"rmse": 44.0, "r2": 0.3}}}
    monkeypatch.setattr(cfs, "_finetune_metrics", lambda: metrics)
    hours, status = cfs.predict_72hr_chronos2_finetuned(
        _FT_HISTORY, {}, {"hourly": {"time": _grid()}}
    )
    assert hours is None
    assert "gates" in (status.get("reason") or "")


def test_ft_serving_model_gates_and_override(monkeypatch):
    monkeypatch.delenv("CHRONOS_MODEL", raising=False)
    monkeypatch.setattr(cfs, "_metrics_json", lambda: {})
    monkeypatch.setattr(cfs, "finetuned_serving_ready", lambda: True)
    assert cfs.serving_model() == "chronos2_ft"  # gates passed → fine-tuned serves
    monkeypatch.setenv("CHRONOS_MODEL", "t5")  # explicit override wins
    assert cfs.serving_model() == "t5"
    monkeypatch.delenv("CHRONOS_MODEL", raising=False)
    monkeypatch.setattr(cfs, "finetuned_serving_ready", lambda: False)
    assert cfs.serving_model() == "t5"  # default when gates not PASS


@_requires_torch
def test_endpoint_serves_ft_variant(_offline_endpoint, monkeypatch):
    ep = _offline_endpoint
    monkeypatch.setattr(ep, "serving_model", lambda: "chronos2_ft")
    _patch_ft_ready(monkeypatch)

    async def fake_met(lat, lon):
        return {"hourly": {"time": _grid()}, "weather_source": "open-meteo", "provider_failures": []}

    async def fake_cams(lat, lon, past_days=14):
        from datetime import timedelta
        origin = datetime.fromisoformat(_grid()[0])
        hist_times = [(origin - timedelta(hours=k)).isoformat() for k in range(200, 0, -1)]
        return {
            "time": hist_times + _grid(),
            **{v: [50.0] * (len(hist_times) + 72) for v in (
                "pm2_5", "pm10", "nitrogen_dioxide", "ozone", "sulphur_dioxide",
                "carbon_monoxide", "aerosol_optical_depth", "dust",
            )},
        }

    async def fake_met_context(lat, lon):
        from datetime import timedelta
        origin = datetime.fromisoformat(_grid()[0])
        past = [(origin - timedelta(hours=k)).isoformat() for k in range(200, 0, -1)]
        times = past + _grid()
        return {
            "time": times,
            **{v: [10.0] * len(times) for v in (
                "temperature_2m", "relative_humidity_2m", "wind_speed_10m",
                "wind_direction_10m", "precipitation", "boundary_layer_height",
                "shortwave_radiation", "temperature_1000hPa", "temperature_925hPa",
            )},
        }

    monkeypatch.setattr(ep, "fetch_forecast_weather", fake_met)
    monkeypatch.setattr(ep, "fetch_cams_context", fake_cams)
    monkeypatch.setattr(ep, "fetch_met_context", fake_met_context)

    result = asyncio.run(ep.forecast_72hr_chronos(
        _make_request(), lat=28.6139, lon=77.2090, station_name="Delhi-ITO", num_samples=20
    ))
    assert result["fallback_used"] is False
    assert "Delhi fine-tuned" in result["model_name"]
    assert result["context_hours"] == 720
    assert result["verification"]["delhi_finetune_gates"]["verdict"] == "PASS"
    assert result["verification"]["delhi_finetune_gates"]["pm2_5_rmse"] == 11.5
    assert any("leak-free" in lim for lim in result["limitations"])
    assert len(result["hourly"]) == 72
