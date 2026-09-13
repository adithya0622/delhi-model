"""Canonical pollutant units and gas-concentration conversions.

All concentrations inside the application use micrograms per cubic metre. AQI
standards retain their published input units at the calculation boundary only:
EPA uses micrograms per cubic metre for particulate matter, ppm for CO, and ppb
for O3/NO2/SO2; CPCB uses mg/m3 for CO and micrograms per cubic metre otherwise.
"""

from __future__ import annotations

import math

CANONICAL_CONCENTRATION_UNIT = "ug/m3"
CANONICAL_CONCENTRATION_LABEL = "µg/m³"
MOLAR_VOLUME_L_PER_MOL = 24.45  # 25 C, 1 atm

MOLECULAR_WEIGHT_G_PER_MOL = {
    "co": 28.01,
    "no2": 46.0055,
    "nox": 46.0055,
    "o3": 48.0,
    "so2": 64.066,
}

EPA_AQI_UNITS = {
    "pm25": "ug/m3",
    "pm10": "ug/m3",
    "o3": "ppb",
    "no2": "ppb",
    "so2": "ppb",
    "co": "ppm",
}

EPA_AQI_UNIT_LABELS = {
    "ug/m3": "µg/m³",
    "ppm": "ppm",
    "ppb": "ppb",
}

_PARAMETER_ALIASES = {
    "pm2.5": "pm25",
    "pm2_5": "pm25",
    "pm25": "pm25",
    "pm10": "pm10",
    "ozone": "o3",
    "nitrogen_dioxide": "no2",
    "sulphur_dioxide": "so2",
    "sulfur_dioxide": "so2",
    "carbon_monoxide": "co",
}


def canonical_parameter(parameter: str) -> str:
    """Return the pollutant key shared by APIs, AQI arithmetic, and physics."""
    value = str(parameter or "").strip().casefold()
    return _PARAMETER_ALIASES.get(value, value)


def unit_key(unit: str | None) -> str:
    """Normalize provider spelling and damaged unicode unit strings."""
    return (
        str(unit or "")
        .casefold()
        .replace("µ", "u")
        .replace("μ", "u")
        .replace("�", "u")
        .replace("²", "2")
        .replace("³", "3")
        .replace(" ", "")
    )


def _finite_nonnegative(value: float | int | str | None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def to_ug_m3(parameter: str, value: float | int | str | None, unit: str | None) -> float | None:
    """Convert a supported ambient concentration into canonical ug/m3."""
    number = _finite_nonnegative(value)
    if number is None:
        return None
    pollutant = canonical_parameter(parameter)
    source_unit = unit_key(unit)
    is_ug = "ug/m" in source_unit
    is_mg = "mg/m" in source_unit

    if pollutant in {"pm25", "pm10"}:
        if is_ug:
            return number
        if is_mg:
            return number * 1000.0
        return None

    molecular_weight = MOLECULAR_WEIGHT_G_PER_MOL.get(pollutant)
    if molecular_weight is None:
        return None
    if is_ug:
        return number
    if is_mg:
        return number * 1000.0
    if source_unit == "ppm":
        return number * molecular_weight * 1000.0 / MOLAR_VOLUME_L_PER_MOL
    if source_unit == "ppb":
        return number * molecular_weight / MOLAR_VOLUME_L_PER_MOL
    return None


def from_ug_m3(parameter: str, value_ug_m3: float | int | str | None, unit: str) -> float | None:
    """Convert a canonical ambient concentration to an explicitly requested unit."""
    number = _finite_nonnegative(value_ug_m3)
    if number is None:
        return None
    pollutant = canonical_parameter(parameter)
    target_unit = unit_key(unit)
    if target_unit == "ug/m3":
        return number
    if target_unit == "mg/m3":
        return number / 1000.0
    molecular_weight = MOLECULAR_WEIGHT_G_PER_MOL.get(pollutant)
    if molecular_weight is None:
        return None
    if target_unit == "ppm":
        return number * MOLAR_VOLUME_L_PER_MOL / (molecular_weight * 1000.0)
    if target_unit == "ppb":
        return number * MOLAR_VOLUME_L_PER_MOL / molecular_weight
    return None


def epa_aqi_input(parameter: str, value_ug_m3: float | int | str | None) -> tuple[float, str] | None:
    """Return an EPA AQI concentration and its published input unit."""
    pollutant = canonical_parameter(parameter)
    unit = EPA_AQI_UNITS.get(pollutant)
    if unit is None:
        return None
    value = from_ug_m3(pollutant, value_ug_m3, unit)
    return (value, unit) if value is not None else None


def to_si_weather(parameter: str, value: float | int | str | None, unit: str | None) -> float | None:
    """Normalize OpenAQ weather readings to C, %, m/s, or degrees."""
    number = _finite_nonnegative(value)
    if number is None:
        return None
    name = str(parameter or "").strip().casefold()
    source = unit_key(unit)
    if name == "temperature":
        if source in {"c", "uc", "degc", "celsius", "°c"} or "degc" in source:
            return number
        if source in {"f", "degf", "fahrenheit", "°f"} or "degf" in source:
            return (number - 32.0) * 5.0 / 9.0
        return None
    if name == "relativehumidity":
        return number if source in {"%", "percent", "percentage"} else None
    if name == "wind_speed":
        if source in {"m/s", "ms-1", "ms^-1", "meterpersecond", "metrespersecond"}:
            return number
        if source in {"km/h", "kph", "kmh", "kilometerperhour", "kilometresperhour"}:
            return number / 3.6
        if source in {"mph", "mi/h"}:
            return number * 0.44704
        if source in {"kn", "knot", "knots"}:
            return number * 0.514444
        return None
    if name == "wind_direction":
        return number % 360.0 if source in {"°", "deg", "degree", "degrees"} else None
    return None
