"""
Domain vocabulary shared by the physics core and the API layer.

Deliberately dependency-free — stdlib only. The physics modules (`box_model`,
`aqi_service`) need the pollutant and category names, and they used to import
them from `app.schemas.forecast`, which meant the dispersion model could not be
imported (or unit-tested) without pydantic and the whole HTTP response layer.
Nothing here validates anything; it is just the vocabulary.

`app.schemas.forecast` re-exports both names, so existing imports keep working.
"""

from enum import Enum


class AQICategory(str, Enum):
    """Category names used by CPCB and US EPA AQI scales."""
    GOOD = "Good"
    SATISFACTORY = "Satisfactory"
    MODERATE = "Moderate"
    POOR = "Poor"
    VERY_POOR = "Very Poor"
    SEVERE = "Severe"
    UNHEALTHY_FOR_SENSITIVE_GROUPS = "Unhealthy for Sensitive Groups"
    UNHEALTHY = "Unhealthy"
    VERY_UNHEALTHY = "Very Unhealthy"
    HAZARDOUS = "Hazardous"


class Pollutant(str, Enum):
    """Six criteria-pollutant series used by AQI calculation."""
    PM25 = "PM2.5"
    PM10 = "PM10"
    O3 = "O3"
    NO2 = "NO2"
    SO2 = "SO2"
    CO = "CO"
