"""
Personalized Exposure Tracker & Activity Planner Service
========================================================
Translates macro-level atmospheric AQI forecasts into micro-level,
actionable human-health metrics:

1. Inhaled PM2.5 dose (µg) based on activity-specific ventilation rates.
2. Cigarette equivalent consumption (Berkeley Earth 22 µg/m³ 24h baseline).
3. 72-hour sliding-window activity optimization to minimize pollution intake.
4. Actionable exertion warnings based on CPCB health risk tiers.
"""

from datetime import datetime, timezone
import math
from typing import Any


# ── Breathing Rate Constants (m³/hour) ─────────────────────────────────────────
BREATHING_RATES: dict[str, float] = {
    "resting": 0.5,    # Indoors, sleeping, sedentary desk work
    "moderate": 1.5,   # Walking, light commuting, yoga
    "heavy": 3.0,      # Running, cycling, high-intensity outdoor sports
}

# ── Cigarette Equivalence Baseline ─────────────────────────────────────────────
# 22 µg/m³ of PM2.5 ambient concentration over a 24-hour period ≈ smoking 1 cigarette.
CIGARETTE_BASELINE_PM25_UG_M3 = 22.0
CIGARETTE_BASELINE_HOURS = 24.0


def get_breathing_rate(activity_type: str) -> float:
    """Return breathing rate in m³/hour for a given activity type."""
    key = str(activity_type or "").strip().lower()
    if "rest" in key or "indoor" in key or "sedentary" in key:
        return BREATHING_RATES["resting"]
    if "mod" in key or "walk" in key or "commute" in key:
        return BREATHING_RATES["moderate"]
    if "heavy" in key or "run" in key or "cycl" in key or "sport" in key or "exert" in key:
        return BREATHING_RATES["heavy"]
    return BREATHING_RATES.get(key, BREATHING_RATES["moderate"])


def calculate_inhaled_dose(
    pm25_concentration: float,
    breathing_rate: float,
    duration_hours: float,
) -> float:
    """
    Calculate total inhaled PM2.5 mass in micrograms (µg).
    Dose = PM2.5 (µg/m³) * Breathing Rate (m³/h) * Duration (h)
    """
    conc = max(0.0, float(pm25_concentration))
    rate = max(0.1, float(breathing_rate))
    duration = max(0.1, float(duration_hours))
    return round(conc * rate * duration, 1)


def calculate_cigarette_equivalent(
    pm25_concentration: float,
    duration_hours: float,
) -> float:
    """
    Calculate cigarette equivalence based on the Berkeley Earth formula:
    cigarettes = (PM2.5 / 22) * (duration / 24)
    """
    conc = max(0.0, float(pm25_concentration))
    duration = max(0.0, float(duration_hours))
    cig = (conc / CIGARETTE_BASELINE_PM25_UG_M3) * (duration / CIGARETTE_BASELINE_HOURS)
    return round(cig, 2)


def generate_health_warning(pm25_concentration: float, activity_type: str) -> str:
    """Generate medical / health exertion warning based on ambient PM2.5 and activity."""
    conc = float(pm25_concentration)
    rate = get_breathing_rate(activity_type)
    is_heavy = rate >= 2.5

    if conc <= 30:
        return "Air quality is good. Safe for all outdoor activities and vigorous exercise."
    if conc <= 60:
        if is_heavy:
            return "Air quality is satisfactory. Sensitive individuals should monitor for respiratory symptoms during intense workouts."
        return "Air quality is satisfactory. Low health risk for general activities."
    if conc <= 90:
        if is_heavy:
            return "Moderate pollution. Heavy outdoor exertion increases particulate lung penetration. Consider reducing workout intensity."
        return "Moderate pollution. Unusually sensitive individuals may experience minor breathing discomfort."
    if conc <= 120:
        if is_heavy:
            return "High exertion in current conditions is dangerous. Elevated alveolar deposition of toxic particulates. Move high-intensity training indoors."
        return "Poor air quality. Prolonged outdoor exposure may cause breathing discomfort to people with lung/heart diseases."
    if conc <= 250:
        if is_heavy:
            return "Severe pollution emergency. Vigorous outdoor exercise carries acute cardiovascular and pulmonary risks. Strict indoor protocol advised."
        return "Very poor air quality. Avoid prolonged outdoor exertion. Wear N95 respirator if stepping outside."
    return "Hazardous atmospheric toxicity. Outdoor physical activity is strictly discouraged. Keep HEPA filtration active indoors."


def find_optimal_activity_window(
    duration_hours: float,
    current_pm25: float,
    forecast_72h: list[dict[str, Any]],
    target_start_index: int = 0,
) -> dict[str, Any]:
    """
    Scans the 72-hour prognostic forecast with a sliding window of length `duration_hours`
    to identify the continuous time window with the lowest average PM2.5 exposure.
    """
    window_len = max(1, min(24, int(math.ceil(duration_hours))))
    
    # Extract PM2.5 time series from forecast points
    series: list[dict[str, Any]] = []
    for idx, pt in enumerate(forecast_72h):
        pm_val = None
        # Support various forecast point structures
        if "pm25" in pt:
            pm_val = float(pt["pm25"])
        elif "pm2_5" in pt:
            pm_val = float(pt["pm2_5"])
        elif "sub_indices" in pt:
            for s in pt["sub_indices"]:
                p_name = str(s.get("pollutant", ""))
                if "25" in p_name or "2.5" in p_name or "PM25" in p_name:
                    pm_val = float(s.get("concentration", 0.0))
                    break
        elif "pollutants" in pt and "PM2.5" in pt["pollutants"]:
            pm_val = float(pt["pollutants"]["PM2.5"])

        if pm_val is None:
            pm_val = float(current_pm25)

        time_str = pt.get("dt") or pt.get("time") or pt.get("timestamp") or f"+{idx}h"
        series.append({"index": idx, "pm25": pm_val, "time": str(time_str)})

    # Fallback if forecast series is empty
    if not series:
        return {
            "recommended_hour": "+0h",
            "recommended_timestamp": datetime.now(timezone.utc).isoformat(),
            "optimal_avg_pm25": round(current_pm25, 1),
            "projected_exposure_reduction_percent": 0,
            "advice_string": "Maintain indoor ventilation; no significant atmospheric variance projected.",
        }

    # Calculate baseline average PM2.5 for the target schedule window
    t_start = max(0, min(len(series) - 1, target_start_index))
    t_end = min(len(series), t_start + window_len)
    target_slice = series[t_start:t_end]
    target_avg = (
        sum(p["pm25"] for p in target_slice) / len(target_slice)
        if target_slice
        else current_pm25
    )

    # Sliding window search for minimum PM2.5 exposure window
    best_start = 0
    best_avg = float("inf")

    for i in range(len(series) - window_len + 1):
        win = series[i : i + window_len]
        avg = sum(p["pm25"] for p in win) / len(win)
        if avg < best_avg:
            best_avg = avg
            best_start = i

    # Compute percentage reduction
    if target_avg > 0:
        reduction_pct = round(((target_avg - best_avg) / target_avg) * 100)
    else:
        reduction_pct = 0
    reduction_pct = max(0, min(95, reduction_pct))

    best_item = series[best_start]
    best_hour_tag = f"+{best_start}h"
    best_time_str = best_item.get("time", best_hour_tag)

    # Format human-friendly time description
    if best_start == 0 or best_start == t_start:
        advice_string = "Your currently selected time slot is already within the optimal exposure window."
    else:
        time_desc = best_hour_tag
        try:
            dt = datetime.fromisoformat(best_time_str.replace("Z", "+00:00"))
            time_desc = dt.strftime("%A at %I:%M %p")
        except Exception:
            if best_start < 24:
                time_desc = f"in {best_start} hours"
            elif best_start < 48:
                time_desc = f"tomorrow (+{best_start}h)"
            else:
                time_desc = f"in {best_start // 24} days (+{best_start}h)"

        dur_text = f"{int(duration_hours)}h" if duration_hours.is_integer() else f"{duration_hours}h"
        advice_string = (
            f"If you shift your {dur_text} activity to {time_desc}, "
            f"you will reduce your PM2.5 exposure by {reduction_pct}%."
        )

    return {
        "recommended_hour": best_hour_tag,
        "recommended_timestamp": best_time_str,
        "optimal_avg_pm25": round(best_avg, 1),
        "target_avg_pm25": round(target_avg, 1),
        "projected_exposure_reduction_percent": reduction_pct,
        "advice_string": advice_string,
    }


def calculate_personalized_exposure(
    activity_type: str,
    duration_hours: float,
    target_time: str = "+0h",
    current_pm25: float = 50.0,
    forecast_72h: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Main orchestrator for personalized pollution exposure and smart activity planning.
    """
    breathing_rate = get_breathing_rate(activity_type)
    duration = max(0.1, float(duration_hours))
    conc = max(0.0, float(current_pm25))

    inhaled_mass = calculate_inhaled_dose(conc, breathing_rate, duration)
    cig_equiv = calculate_cigarette_equivalent(conc, duration)
    warning = generate_health_warning(conc, activity_type)

    # Determine target index from target_time (e.g. "+3h", "3", or ISO)
    target_idx = 0
    clean_target = str(target_time).strip().lower().replace("+", "").replace("h", "")
    if clean_target.isdigit():
        target_idx = int(clean_target)

    smart_schedule = find_optimal_activity_window(
        duration_hours=duration,
        current_pm25=conc,
        forecast_72h=forecast_72h or [],
        target_start_index=target_idx,
    )

    return {
        "inhaled_mass_mcg": inhaled_mass,
        "cigarettes_equivalent": cig_equiv,
        "health_warning": warning,
        "smart_schedule": smart_schedule,
        "activity_metadata": {
            "activity_type": activity_type,
            "breathing_rate_m3_h": breathing_rate,
            "duration_hours": duration,
            "ambient_pm25_ug_m3": conc,
        },
    }
