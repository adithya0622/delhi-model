"""
Unit tests for EmissionService (Dynamic Source Apportionment & NO2 Chemical Proxy).
"""

from app.services.emission_service import EmissionService


def test_normal_baseline_apportionment():
    res = EmissionService.calculate_source_apportionment(
        current_pm25=100.0,
        current_no2=60.0,
        hour=14,  # daytime
    )
    assert res.total_pm25 == 100.0
    assert res.transport_pct == 25.0
    assert res.dust_pct == 30.0
    assert res.biomass_pct == 25.0
    assert res.industry_pct == 20.0
    assert round(res.transport_pct + res.dust_pct + res.biomass_pct + res.industry_pct, 1) == 100.0
    assert res.transport_mcg == 25.0
    assert res.dust_mcg == 30.0
    assert res.biomass_mcg == 25.0
    assert res.industry_mcg == 20.0
    assert "Normal Traffic" in res.proxy_status


def test_lockdown_strike_deficit_redistribution():
    # NO2 = 30 ug/m3 -> traffic_ratio = 0.5 -> transport = 12.5%
    # missing 12.5% split 3 ways = +4.166% each
    res = EmissionService.calculate_source_apportionment(
        current_pm25=100.0,
        current_no2=30.0,
        hour=14,
    )
    assert res.transport_pct == 12.5
    assert abs(res.dust_pct - 34.17) < 0.1
    assert abs(res.biomass_pct - 29.17) < 0.1
    assert abs(res.industry_pct - 24.16) < 0.1
    assert round(res.transport_pct + res.dust_pct + res.biomass_pct + res.industry_pct, 1) == 100.0
    assert "Low Traffic" in res.proxy_status or "Reduction" in res.proxy_status


def test_nighttime_truck_entry_rule():
    # Hour 23: Nighttime Truck Entry rule
    res_night = EmissionService.calculate_source_apportionment(
        current_pm25=100.0,
        current_no2=60.0,
        hour=23,
    )
    vb = res_night.vehicle_breakdown
    assert vb.heavy_trucks_pct == 61.0
    assert vb.two_three_wheelers_pct == 25.0
    assert vb.cars_pct == 14.0
    assert vb.heavy_trucks_mcg == round(25.0 * 0.61, 2)

    # Hour 2: Also nighttime
    res_2am = EmissionService.calculate_source_apportionment(
        current_pm25=100.0,
        current_no2=60.0,
        hour=2,
    )
    assert res_2am.vehicle_breakdown.heavy_trucks_pct == 61.0


def test_rush_hour_rule():
    # Hour 9: Morning Rush Hour (8-11)
    res_am = EmissionService.calculate_source_apportionment(
        current_pm25=100.0,
        current_no2=60.0,
        hour=9,
    )
    vb_am = res_am.vehicle_breakdown
    assert vb_am.heavy_trucks_pct == 10.0
    assert vb_am.two_three_wheelers_pct == 60.0
    assert vb_am.cars_pct == 30.0

    # Hour 18: Evening Rush Hour (17-20)
    res_pm = EmissionService.calculate_source_apportionment(
        current_pm25=100.0,
        current_no2=60.0,
        hour=18,
    )
    assert res_pm.vehicle_breakdown.two_three_wheelers_pct == 60.0


def test_normal_daytime_fleet():
    # Hour 14: Normal Daytime
    res_day = EmissionService.calculate_source_apportionment(
        current_pm25=80.0,
        current_no2=60.0,
        hour=14,
    )
    vb = res_day.vehicle_breakdown
    assert vb.heavy_trucks_pct == 30.0
    assert vb.two_three_wheelers_pct == 50.0
    assert vb.cars_pct == 20.0
    # Mass calculations
    assert vb.heavy_trucks_mcg == round(20.0 * 0.30, 2)  # 25% of 80 = 20 mcg transport


def test_build_72h_source_timeseries():
    pm25_series = [100.0] * 72
    res = EmissionService.build_72h_source_timeseries(pm25_series=pm25_series)
    assert len(res.forecast) == 72
    
    # Check that each hour has exact macro mass summing to total PM2.5
    for h in res.forecast:
        assert h.total_pm25 == 100.0
        assert h.dust_mcg == 30.0
        assert h.biomass_mcg == 25.0
        assert h.industry_mcg == 20.0
        # Vehicle components sum to transport total (25.0)
        transport_sum = round(h.trucks_mcg + h.two_wheelers_mcg + h.cars_mcg, 2)
        assert abs(transport_sum - 25.0) <= 0.02

    # Check that night hours have truck dominance (61%) and rush hours have 2-wheeler dominance (60%)
    truck_values = [h.trucks_mcg for h in res.forecast]
    assert max(truck_values) == 15.25  # 25.0 * 0.61
    assert min(truck_values) == 2.50   # 25.0 * 0.10

