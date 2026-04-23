from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class UserPreferences(BaseModel):
    city: str
    start_date: str = ""
    trip_days: int = Field(default=3, ge=1, le=14)
    travel_type: Literal["leisure", "family", "food", "theme"] = "leisure"
    travelers: str = "friends"
    budget_level: Literal["low", "medium", "high"] = "medium"
    pace: Literal["slow", "balanced", "packed"] = "balanced"
    interests: list[str] = Field(default_factory=list)
    must_visit: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    notes: str = ""
    extra_request: str = ""


class POI(BaseModel):
    name: str
    category: str = "attraction"
    district: str = "Unknown"
    lat: float = 0.0
    lon: float = 0.0
    duration_hours: float = 1.5
    ticket_price: float = 0.0
    price_level: int = Field(default=2, ge=0, le=5)
    indoor_outdoor: Literal["indoor", "outdoor", "mixed"] = "mixed"
    tags: list[str] = Field(default_factory=list)
    source: list[str] = Field(default_factory=list)
    address: str = ""
    open_hours: str = ""
    rating: float | None = None
    visit_reason: str = ""


class WeatherDay(BaseModel):
    date: str
    summary: str
    temp_min: float
    temp_max: float
    precipitation_probability: int = 0
    outdoor_suitability: Literal["good", "mixed", "poor"] = "good"
    suggestions: list[str] = Field(default_factory=list)


class DayPlanItem(BaseModel):
    time_slot: Literal["morning", "afternoon", "evening"]
    poi_name: str
    category: str
    district: str
    duration_hours: float
    est_cost: float
    reasoning: str
    weather_fit: str
    transport_hint: str
    arrival_mode: str = "start"
    arrival_distance_m: int = 0
    arrival_duration_min: int = 0


class DayPlan(BaseModel):
    day_index: int
    area: str
    theme: str
    estimated_cost: float
    weather_summary: str = ""
    inter_stop_distance_m: int = 0
    inter_stop_duration_min: int = 0
    items: list[DayPlanItem] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ReviewFinding(BaseModel):
    level: Literal["info", "warning"] = "info"
    rule: str
    message: str


class ItineraryPlan(BaseModel):
    city: str
    trip_days: int
    overview: str
    total_estimated_cost: float
    selected_pois: list[POI] = Field(default_factory=list)
    days: list[DayPlan] = Field(default_factory=list)
    planning_notes: list[str] = Field(default_factory=list)
    local_tips: list[str] = Field(default_factory=list)
    review_summary: str = ""
    review_findings: list[ReviewFinding] = Field(default_factory=list)
