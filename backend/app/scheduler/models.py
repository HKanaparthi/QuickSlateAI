from pydantic import BaseModel
from typing import List, Optional
from datetime import date, time
from enum import Enum


class TimeSlot(str, Enum):
    SAT_PRIMETIME = "Saturday 8:00 PM"
    SUN_AFTERNOON = "Sunday 4:00 PM"
    FRI_EVENING = "Friday 7:00 PM"
    MON_EVENING = "Monday 7:00 PM"
    TUE_EVENING = "Tuesday 6:00 PM"
    WED_EVENING = "Wednesday 7:00 PM"
    THU_EVENING = "Thursday 7:00 PM"


SLOT_VIEWERSHIP_MULTIPLIER = {
    TimeSlot.SAT_PRIMETIME: 1.5,
    TimeSlot.SUN_AFTERNOON: 1.4,
    TimeSlot.FRI_EVENING: 1.2,
    TimeSlot.MON_EVENING: 1.0,
    TimeSlot.WED_EVENING: 0.9,
    TimeSlot.THU_EVENING: 0.85,
    TimeSlot.TUE_EVENING: 0.7,
}

PRIMETIME_SLOTS = {TimeSlot.SAT_PRIMETIME, TimeSlot.SUN_AFTERNOON, TimeSlot.FRI_EVENING}


class Venue(BaseModel):
    id: str
    name: str
    city: str
    capacity: int
    latitude: float
    longitude: float
    is_outdoor: bool = False


class Team(BaseModel):
    id: str
    name: str
    city: str
    league: str
    market_size: str  # "large", "medium", "small"
    home_venue_id: str
    color: str


class League(BaseModel):
    id: str
    name: str
    short_name: str
    teams: List[Team]


class ScheduleConstraints(BaseModel):
    league_id: str
    season_start: date
    season_end: date
    min_rest_days: int = 2
    max_travel_miles_per_week: int = 500
    primetime_slots: List[str] = ["Saturday 8:00 PM", "Sunday 4:00 PM", "Friday 7:00 PM"]
    rivalry_pairs: List[List[str]] = []
    home_away_balanced: bool = True
    no_back_to_back_away: bool = True
    weather_constraint: bool = False
    # Timeslot distribution
    max_games_per_slot_per_week: int = 2      # No more than N games in same timeslot per week
    min_distinct_slots_per_week: int = 3       # At least N different timeslots used per week
    # Even weekly distribution
    even_distribution: bool = True
    target_games_per_week: int = 4             # Aim for this many total games per week
    games_per_week_tolerance: int = 1          # Allow ±tolerance from target


class Game(BaseModel):
    id: str
    home_team_id: str
    away_team_id: str
    venue_id: str
    game_date: date
    timeslot: str
    is_rivalry: bool = False
    ai_explanation: Optional[str] = None
    projected_viewership: Optional[int] = None


class Schedule(BaseModel):
    id: str
    league_id: str
    season_start: date
    season_end: date
    games: List[Game]
    constraints: ScheduleConstraints
    total_games: int
    generated_at: str
    solver_status: str
