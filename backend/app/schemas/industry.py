"""
Industry Schema
===============
Pydantic models for Delhi industrial and point-source emissions data.
"""
from typing import Optional
from pydantic import BaseModel, Field


class IndustryRecord(BaseModel):
    """An industrial facility or point-source record from Supabase."""
    id: Optional[str | int] = None
    name: str = Field(..., description="Name of the industrial facility")
    city: str = Field(default="Delhi", description="City (strictly filtered to Delhi)")
    state: str = Field(default="Delhi", description="State (strictly filtered to Delhi)")
    latitude: float = Field(..., description="Latitude coordinate")
    longitude: float = Field(..., description="Longitude coordinate")
    category: Optional[str] = Field(default=None, description="Industry sector / category")
    sector: Optional[str] = Field(default=None, description="Industry sub-sector")
    status: Optional[str] = Field(default=None, description="Operational status")
    capacity: Optional[str | float] = Field(default=None, description="Operating capacity or output")
    address: Optional[str] = Field(default=None, description="Facility address in Delhi")


class IndustryResponse(BaseModel):
    """Response payload for Delhi industry points."""
    city: str = "Delhi"
    state: str = "Delhi"
    count: int = Field(..., description="Number of Delhi industry records returned")
    source: str = Field(default="supabase", description="Data source indicator")
    records: list[IndustryRecord] = Field(default_factory=list, description="List of Delhi industry records")
