"""
Dynamic Source Apportionment Service (NO2 Chemical Tracer & Diurnal Fleet Breakdown)
===================================================================================
Deterministic chemical-proxy model that infers real-time vehicular emissions
using ambient Nitrogen Dioxide (NO2) concentrations as a tracer for fossil fuel
combustion, and models diurnal vehicle fleet dynamics across Delhi NCR.
"""

from datetime import datetime, timedelta, timezone
from typing import Any
from pydantic import BaseModel


NO2_BASELINE_DELHI_UG_M3 = 60.0
BASE_TRANSPORT_PCT = 25.0
BASE_DUST_PCT = 30.0
BASE_BIOMASS_PCT = 25.0
BASE_INDUSTRY_PCT = 20.0


class VehicleBreakdown(BaseModel):
    heavy_trucks_pct: float
    two_three_wheelers_pct: float
    cars_pct: float
    heavy_trucks_mcg: float
    two_three_wheelers_mcg: float
    cars_mcg: float


class SourceApportionmentResponse(BaseModel):
    total_pm25: float
    transport_pct: float
    dust_pct: float
    biomass_pct: float
    industry_pct: float
    transport_mcg: float
    dust_mcg: float
    biomass_mcg: float
    industry_mcg: float
    vehicle_breakdown: VehicleBreakdown
    proxy_status: str


class ApportionmentHour(BaseModel):
    timestamp: str  # e.g., "Tue 14:00"
    total_pm25: float
    dust_mcg: float
    biomass_mcg: float
    industry_mcg: float
    trucks_mcg: float
    two_wheelers_mcg: float
    cars_mcg: float


class SourceTimeSeriesResponse(BaseModel):
    forecast: list[ApportionmentHour]


class EmissionService:
    """
    Computes dynamic PM2.5 source apportionment using NO2 chemical proxy
    and diurnal vehicle sub-breakdowns, as well as 72-hour predictive time-series.
    """

    @classmethod
    def calculate_source_apportionment(
        cls,
        current_pm25: float,
        current_no2: float,
        hour: int | None = None,
    ) -> SourceApportionmentResponse:
        pm25 = max(0.0, float(current_pm25))
        no2 = max(0.0, float(current_no2))

        # 1. NO2 Chemical Tracer & Traffic Ratio
        # Normal baseline for Delhi is 60 µg/m³
        traffic_ratio = min(1.0, max(0.0, no2 / NO2_BASELINE_DELHI_UG_M3))
        dynamic_transport_pct = round(BASE_TRANSPORT_PCT * traffic_ratio, 2)

        # 2. Deficit Redistribution
        # If traffic_ratio < 1.0 (e.g. strike/lockdown), distribute missing share evenly
        missing_pct = BASE_TRANSPORT_PCT - dynamic_transport_pct
        if missing_pct > 0.001:
            share_add = missing_pct / 3.0
            dust_pct = round(BASE_DUST_PCT + share_add, 2)
            biomass_pct = round(BASE_BIOMASS_PCT + share_add, 2)
            # Ensure exact 100% sum
            industry_pct = round(100.0 - dynamic_transport_pct - dust_pct - biomass_pct, 2)
        else:
            dust_pct = BASE_DUST_PCT
            biomass_pct = BASE_BIOMASS_PCT
            industry_pct = BASE_INDUSTRY_PCT

        # Mass concentrations in µg/m³
        transport_mcg = round(pm25 * (dynamic_transport_pct / 100.0), 2)
        dust_mcg = round(pm25 * (dust_pct / 100.0), 2)
        biomass_mcg = round(pm25 * (biomass_pct / 100.0), 2)
        industry_mcg = round(pm25 * (industry_pct / 100.0), 2)

        # 3. Vehicle Sub-Breakdown & Diurnal Time Multipliers
        if hour is None:
            # Default to current IST hour (UTC + 5:30)
            ist_dt = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=5, minutes=30)))
            current_hour = ist_dt.hour
        else:
            current_hour = int(hour) % 24

        # Rule A: Nighttime Truck Entry (22:00 to 06:00)
        # Delhi bans large heavy trucks during the day; entry opens at night.
        if current_hour >= 22 or current_hour < 6:
            trucks_share = 61.0
            two_three_share = 25.0
            cars_share = 14.0
            time_rule_desc = "Nighttime Heavy Truck Entry Window (22:00-06:00)"
        # Rule B: Peak Rush Hour (08:00-11:00 & 17:00-20:00)
        elif (8 <= current_hour < 11) or (17 <= current_hour < 20):
            trucks_share = 10.0
            two_three_share = 60.0
            cars_share = 30.0
            time_rule_desc = "Peak Commuter Rush Hour"
        # Rule C: Normal Daytime (all other hours)
        else:
            trucks_share = 30.0
            two_three_share = 50.0
            cars_share = 20.0
            time_rule_desc = "Standard Daytime Fleet Distribution"

        # Vehicle absolute mass contributions from transport total
        heavy_trucks_mcg = round(transport_mcg * (trucks_share / 100.0), 2)
        two_three_wheelers_mcg = round(transport_mcg * (two_three_share / 100.0), 2)
        cars_mcg = round(transport_mcg * (cars_share / 100.0), 2)

        # 4. Proxy Status Description
        if traffic_ratio >= 0.95:
            proxy_status = f"Normal Traffic ({time_rule_desc})"
        elif traffic_ratio < 0.5:
            proxy_status = f"Significant Traffic Reduction / Anomaly Detected (NO2 Proxy: {int(traffic_ratio * 100)}%)"
        else:
            proxy_status = f"Low Traffic Detected (NO2 Proxy: {int(traffic_ratio * 100)}%)"

        return SourceApportionmentResponse(
            total_pm25=round(pm25, 1),
            transport_pct=dynamic_transport_pct,
            dust_pct=dust_pct,
            biomass_pct=biomass_pct,
            industry_pct=industry_pct,
            transport_mcg=transport_mcg,
            dust_mcg=dust_mcg,
            biomass_mcg=biomass_mcg,
            industry_mcg=industry_mcg,
            vehicle_breakdown=VehicleBreakdown(
                heavy_trucks_pct=trucks_share,
                two_three_wheelers_pct=two_three_share,
                cars_pct=cars_share,
                heavy_trucks_mcg=heavy_trucks_mcg,
                two_three_wheelers_mcg=two_three_wheelers_mcg,
                cars_mcg=cars_mcg,
            ),
            proxy_status=proxy_status,
        )

    @classmethod
    def build_72h_source_timeseries(
        cls,
        pm25_series: list[float] | None = None,
        start_dt: datetime | None = None,
    ) -> SourceTimeSeriesResponse:
        """
        Simulates 72-hour hourly predictive source apportionment and vehicle fleet dynamics.
        """
        # If no PM2.5 series provided, build a realistic 72-hour diurnal baseline
        if not pm25_series:
            pm25_series = []
            for h in range(72):
                # Realistic diurnal cycle: nocturnal peak at 02:00, afternoon dip at 14:00
                hr = (h % 24)
                if hr < 6 or hr >= 22:
                    val = 140.0 + (6 - abs(hr - 2)) * 8.0
                elif 8 <= hr <= 11 or 17 <= hr <= 20:
                    val = 90.0 + (10 - abs(hr - 9)) * 5.0
                else:
                    val = 55.0 + (hr - 12) * 2.0
                pm25_series.append(max(20.0, round(val, 1)))

        ist_tz = timezone(timedelta(hours=5, minutes=30))
        base_time = (start_dt or datetime.now(timezone.utc)).astimezone(ist_tz)

        output: list[ApportionmentHour] = []
        for h in range(min(72, len(pm25_series))):
            current_time = base_time + timedelta(hours=h)
            time_str = current_time.strftime("%a %H:%M")
            hour_of_day = current_time.hour
            pm25_h = max(0.0, float(pm25_series[h]))

            # 1. Macro Sectors (Future forecasts assume normal nominal shares)
            dust_mcg = round(pm25_h * 0.30, 2)
            biomass_mcg = round(pm25_h * 0.25, 2)
            industry_mcg = round(pm25_h * 0.20, 2)
            transport_total_mcg = pm25_h * 0.25

            # 2. Diurnal Fleet Dynamics
            # Nighttime (22:00 to 05:59): Heavy truck entry window
            if hour_of_day >= 22 or hour_of_day < 6:
                trucks_share = 0.61
                two_share = 0.25
                cars_share = 0.14
            # Rush Hour (08:00-10:59 & 17:00-19:59): Commuter 2/3-wheelers dominance
            elif (8 <= hour_of_day <= 10) or (17 <= hour_of_day <= 19):
                trucks_share = 0.10
                two_share = 0.60
                cars_share = 0.30
            # Standard Day (all other hours)
            else:
                trucks_share = 0.30
                two_share = 0.50
                cars_share = 0.20

            trucks_mcg = round(transport_total_mcg * trucks_share, 2)
            two_wheelers_mcg = round(transport_total_mcg * two_share, 2)
            cars_mcg = round(transport_total_mcg * cars_share, 2)

            output.append(
                ApportionmentHour(
                    timestamp=time_str,
                    total_pm25=round(pm25_h, 1),
                    dust_mcg=dust_mcg,
                    biomass_mcg=biomass_mcg,
                    industry_mcg=industry_mcg,
                    trucks_mcg=trucks_mcg,
                    two_wheelers_mcg=two_wheelers_mcg,
                    cars_mcg=cars_mcg,
                )
            )

        return SourceTimeSeriesResponse(forecast=output)

