"""Station forecast layer: offset math must be pure, labelled, and honest.

No network in this module's tests — every function under test takes its data
as arguments. The refresh runner (network-bound) is intentionally untested
here; its pure core (compute_station_offset) carries the guarantees.
"""
from pathlib import Path

from app.services.station_forecast_service import (
    _OFFSETS_FILE,
    build_station_forecasts,
    calibrate_station,
    compute_station_offset,
    load_offsets,
    save_offsets,
    station_hour_aqi,
    station_offsets_for,
)

CHRONOS_CITY_HOUR = {
    "hour_index": 1,
    "timestamp": "2026-09-17T10:00:00+05:30",
    "aqi_cpcb": 92,
    "pollutants": {
        "pm2_5": {"p50": 40.0, "p10": 30.0, "p90": 50.0},
        "pm10": {"p50": 80.0, "p10": 60.0, "p90": 100.0},
        "no2": {"p50": 30.0},
        "so2": {"p50": 10.0},
        "co": {"p50": 1000.0},
        "o3": {"p50": 45.0},
    },
}

ML_FALLBACK_HOUR = {
    "hour_index": 1,
    "timestamp": "2026-09-17T10:00:00+05:30",
    "aqi": 88,
    "sub_indices": [
        {"pollutant": "PM2.5", "concentration": 40.0, "sub_index": 67},
        {"pollutant": "PM10", "concentration": 80.0, "sub_index": 79},
        {"pollutant": "NO2", "concentration": 30.0, "sub_index": 38},
        {"pollutant": "SO2", "concentration": 10.0, "sub_index": 13},
        {"pollutant": "CO", "concentration": 1000.0, "sub_index": 50},
        {"pollutant": "O3", "concentration": 45.0, "sub_index": 45},
    ],
}


def test_compute_station_offset_rejects_insufficient_overlap() -> None:
    result = compute_station_offset([10.0] * 50, [20.0] * 50)
    assert result is None


def test_compute_station_offset_ratio_is_mean_of_means() -> None:
    observed = [30.0] * 250          # 250 paired hours >= _MIN_PAIRED_HOURS
    cell = [20.0] * 250
    result = compute_station_offset(observed, cell)
    assert result is not None
    assert result["ratio"] == 1.5
    assert result["n_hours"] == 250
    assert result["mean_observed"] == 30.0
    assert result["mean_cell"] == 20.0


def test_compute_station_offset_clamps_extremes() -> None:
    result = compute_station_offset([100.0] * 250, [10.0] * 250)  # ratio 10
    assert result is not None
    assert result["ratio"] == 2.0     # clamped, not the raw 10


def test_compute_station_offset_drops_low_cell_hours() -> None:
    # Hours with cell < 5 µg/m³ are excluded (ratio meaningless near zero).
    observed = [30.0] * 250
    cell = [20.0] * 240 + [1.0] * 10
    result = compute_station_offset(observed, cell)
    assert result is not None
    assert result["n_hours"] == 240


def test_station_hour_aqi_missing_species_cannot_win() -> None:
    aqi = station_hour_aqi({"pm25": 40.0})
    assert aqi["aqi"] > 0
    assert aqi["dominant_pollutant"] == "pm25"


def test_station_offsets_for_mixes_measured_and_prior() -> None:
    artifact = {
        "computed_at": "2026-09-17T00:00:00+00:00",
        "stations": {
            "delhi-anand-vihar": {
                "pm25": {"ratio": 1.4, "n_hours": 900},
            }
        },
    }
    offsets = station_offsets_for("delhi-anand-vihar", artifact)
    assert offsets["pm25"]["basis"] == "measured_openaq_vs_cams_cell"
    assert offsets["pm25"]["ratio"] == 1.4
    assert offsets["pm10"]["basis"] == "catalog_prior"
    # Anand Vihar's catalog factor is 1.18.
    assert offsets["pm10"]["ratio"] == 1.18


def test_calibrate_station_chronos_shape_adjusts_and_recomputes() -> None:
    city_hours = [dict(CHRONOS_CITY_HOUR)]
    offsets = station_offsets_for(
        "delhi-anand-vihar",
        {"stations": {"delhi-anand-vihar": {"pm25": {"ratio": 1.5, "n_hours": 500}}}},
    )
    snapshot = repr(city_hours)
    station = calibrate_station(
        {"uid": "delhi-anand-vihar", "name": "Anand Vihar", "zone": "East Delhi",
         "lat": 28.6476, "lon": 77.3158},
        city_hours, offsets,
    )
    assert snapshot == repr(city_hours), "city series must not be mutated"
    hour = station["hourly"][0]
    assert hour["concentrations"]["pm25"] == 60.0        # 40 × 1.5 measured
    assert hour["adjustments"]["pm25"]["basis"] == "measured_openaq_vs_cams_cell"
    assert hour["adjustments"]["pm10"]["basis"] == "catalog_prior"
    assert hour["adjustments"]["pm10"]["station"] == round(80.0 * 1.18, 2)
    # Station AQI is recomputed from the station's own concentrations.
    expected = station_hour_aqi(hour["concentrations"])
    assert hour["aqi_cpcb"] == expected["aqi"]
    assert hour["dominant_pollutant"] == expected["dominant_pollutant"]
    assert station["current"] is station["hourly"][0]
    assert station["offset_basis"] == "measured"


def test_calibrate_station_ml_fallback_shape() -> None:
    offsets = station_offsets_for("delhi-ito", {"stations": {}})
    station = calibrate_station(
        {"uid": "delhi-ito", "name": "ITO", "zone": "Central Delhi",
         "lat": 28.6289, "lon": 77.2410},
        [dict(ML_FALLBACK_HOUR)], offsets,
    )
    hour = station["hourly"][0]
    # ITO catalog factor 1.05 applied to the sub_indices concentrations.
    assert hour["concentrations"]["pm25"] == round(40.0 * 1.05, 2)
    assert hour["concentrations"]["o3"] == round(45.0 * 1.05, 2)
    assert hour["aqi_cpcb"] > 0
    assert station["offset_basis"] == "catalog_prior"


def test_calibrate_station_empty_city_hour_is_safe() -> None:
    offsets = station_offsets_for("delhi-ito", {"stations": {}})
    station = calibrate_station(
        {"uid": "delhi-ito", "name": "ITO", "zone": "Central Delhi",
         "lat": 28.6289, "lon": 77.2410},
        [{"hour_index": 1, "timestamp": "x"}], offsets,
    )
    hour = station["hourly"][0]
    assert hour["concentrations"] == {}
    assert hour["aqi_cpcb"] == 0


def test_build_station_forecasts_ranks_and_counts() -> None:
    artifact = {
        "computed_at": "2026-09-17T00:00:00+00:00",
        "stations": {
            "delhi-anand-vihar": {
                "pm25": {"ratio": 2.0, "n_hours": 800},
                "pm10": {"ratio": 1.8, "n_hours": 800},
            },
            "delhi-lodhi-road": {
                "pm25": {"ratio": 0.6, "n_hours": 800},
                "pm10": {"ratio": 0.7, "n_hours": 800},
            },
        },
    }
    city_hours = [dict(CHRONOS_CITY_HOUR)]
    result = build_station_forecasts(city_hours, artifact)
    assert result["station_count"] == len(result["stations"])
    assert result["stations_measured"] == 2
    assert result["stations_catalog_prior"] == result["station_count"] - 2
    assert result["most_polluted"][0] == "delhi-anand-vihar"
    assert "delhi-lodhi-road" in result["cleanest"]
    by_uid = {s["uid"]: s for s in result["stations"]}
    av = by_uid["delhi-anand-vihar"]["current"]
    lr = by_uid["delhi-lodhi-road"]["current"]
    assert av["aqi_cpcb"] > lr["aqi_cpcb"]
    assert by_uid["delhi-anand-vihar"]["offset_basis"] == "measured"


def test_offsets_artifact_roundtrip(tmp_path: Path = Path("backend/.tmp_station_offsets")) -> None:
    _pre_existing = (
        _OFFSETS_FILE.read_bytes() if _OFFSETS_FILE.exists() else None
    )
    try:
        artifact = {
            "computed_at": "2026-09-17T00:00:00+00:00",
            "stations": {"delhi-ito": {"pm25": {"ratio": 1.1, "n_hours": 600}}},
        }
        file = tmp_path / "offsets.json"
        save_offsets(artifact, file)
        loaded = load_offsets(file)
        assert loaded["stations"]["delhi-ito"]["pm25"]["ratio"] == 1.1
    finally:
        if tmp_path.exists():
            for p in tmp_path.iterdir():
                p.unlink()
            tmp_path.rmdir()
        # A real refresh may legitimately have written the default artifact
        # before this test ran; the invariant is that the TEST doesn't
        # create or change it — compare against the pre-test snapshot.
        if _pre_existing is None:
            assert not _OFFSETS_FILE.exists(), "test must not create the default artifact"
        else:
            assert _OFFSETS_FILE.read_bytes() == _pre_existing, "test must not modify the default artifact"
