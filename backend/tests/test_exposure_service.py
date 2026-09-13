"""
Tests for Personalized Exposure Tracker & Smart Activity Planner service.
"""

from app.services.exposure_service import (
    BREATHING_RATES,
    calculate_cigarette_equivalent,
    calculate_inhaled_dose,
    calculate_personalized_exposure,
    find_optimal_activity_window,
    generate_health_warning,
    get_breathing_rate,
)


def test_breathing_rates():
    assert get_breathing_rate("resting") == 0.5
    assert get_breathing_rate("indoors") == 0.5
    assert get_breathing_rate("moderate") == 1.5
    assert get_breathing_rate("walking") == 1.5
    assert get_breathing_rate("heavy") == 3.0
    assert get_breathing_rate("running") == 3.0
    assert get_breathing_rate("cycling") == 3.0


def test_dose_calculation():
    # 118 ug/m3 * 3.0 m3/h * 2 h = 708.0 mcg
    dose = calculate_inhaled_dose(118.0, 3.0, 2.0)
    assert dose == 708.0

    # 50 ug/m3 * 0.5 m3/h * 8 h = 200.0 mcg
    dose_rest = calculate_inhaled_dose(50.0, 0.5, 8.0)
    assert dose_rest == 200.0


def test_cigarette_equivalent():
    # (118 / 22) * (2 / 24) = 0.4469 -> 0.45
    cig = calculate_cigarette_equivalent(118.0, 2.0)
    assert cig == 0.45

    # 22 ug/m3 for 24h = exactly 1.0 cigarette
    cig_1 = calculate_cigarette_equivalent(22.0, 24.0)
    assert cig_1 == 1.0


def test_health_warnings():
    w_good = generate_health_warning(25.0, "heavy")
    assert "good" in w_good.lower()

    w_danger = generate_health_warning(118.0, "heavy")
    assert "dangerous" in w_danger.lower() or "high exertion" in w_danger.lower()


def test_sliding_window_optimizer():
    # 72h dummy forecast with dip at hour 24-25
    fc = [{"time": f"+{i}h", "pm25": 100.0} for i in range(72)]
    fc[24]["pm25"] = 25.0
    fc[25]["pm25"] = 25.0

    opt = find_optimal_activity_window(
        duration_hours=2.0,
        current_pm25=100.0,
        forecast_72h=fc,
        target_start_index=0,
    )

    assert opt["recommended_hour"] == "+24h"
    assert opt["optimal_avg_pm25"] == 25.0
    assert opt["projected_exposure_reduction_percent"] == 75
    assert "reduce your PM2.5 exposure by 75%" in opt["advice_string"]


def test_orchestrator_full():
    res = calculate_personalized_exposure(
        activity_type="heavy",
        duration_hours=2.0,
        target_time="+0h",
        current_pm25=118.0,
        forecast_72h=[
            {"time": "+0h", "pm25": 118.0},
            {"time": "+1h", "pm25": 110.0},
            {"time": "+24h", "pm25": 30.0},
            {"time": "+25h", "pm25": 30.0},
        ],
    )
    assert res["inhaled_mass_mcg"] == 708.0
    assert res["cigarettes_equivalent"] == 0.45
    assert res["smart_schedule"]["projected_exposure_reduction_percent"] > 50
