import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List, Dict, Optional
from datetime import date

from ..scheduler.models import ScheduleConstraints, Schedule, Game
from ..scheduler.solver import solve_schedule
from ..scheduler.constraints import validate_schedule
from ..ai.explainer import explain_schedule, explain_single_game
from ..data import LEAGUES_BY_ID, VENUES_BY_ID, TEAMS_BY_ID, DEFAULT_RIVALRY_PAIRS

router = APIRouter(prefix="/api/schedule", tags=["schedule"])

_schedule_store: Dict[str, Schedule] = {}
_explanation_store: Dict[str, Dict[str, str]] = {}


class GenerateRequest(BaseModel):
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
    use_default_rivalries: bool = True
    max_games_per_slot_per_week: int = 2
    min_distinct_slots_per_week: int = 3
    even_distribution: bool = True
    target_games_per_week: int = 4
    games_per_week_tolerance: int = 1


class UpdateGameRequest(BaseModel):
    game_id: str
    new_date: date
    new_timeslot: str


@router.get("/leagues")
def get_leagues():
    return [
        {
            "id": lg.id,
            "name": lg.name,
            "short_name": lg.short_name,
            "teams": [
                {
                    "id": t.id,
                    "name": t.name,
                    "city": t.city,
                    "market_size": t.market_size,
                    "home_venue_id": t.home_venue_id,
                    "color": t.color,
                }
                for t in lg.teams
            ],
        }
        for lg in LEAGUES_BY_ID.values()
    ]


@router.get("/venues")
def get_venues():
    return [
        {
            "id": v.id,
            "name": v.name,
            "city": v.city,
            "capacity": v.capacity,
            "latitude": v.latitude,
            "longitude": v.longitude,
            "is_outdoor": v.is_outdoor,
        }
        for v in VENUES_BY_ID.values()
    ]


@router.post("/generate")
def generate_schedule(req: GenerateRequest):
    league = LEAGUES_BY_ID.get(req.league_id)
    if not league:
        raise HTTPException(status_code=404, detail=f"League '{req.league_id}' not found")

    rivalry_pairs = req.rivalry_pairs
    if req.use_default_rivalries and not rivalry_pairs:
        rivalry_pairs = DEFAULT_RIVALRY_PAIRS.get(req.league_id, [])

    constraints = ScheduleConstraints(
        league_id=req.league_id,
        season_start=req.season_start,
        season_end=req.season_end,
        min_rest_days=req.min_rest_days,
        max_travel_miles_per_week=req.max_travel_miles_per_week,
        primetime_slots=req.primetime_slots,
        rivalry_pairs=rivalry_pairs,
        home_away_balanced=req.home_away_balanced,
        no_back_to_back_away=req.no_back_to_back_away,
        weather_constraint=req.weather_constraint,
        max_games_per_slot_per_week=req.max_games_per_slot_per_week,
        min_distinct_slots_per_week=req.min_distinct_slots_per_week,
        even_distribution=req.even_distribution,
        target_games_per_week=req.target_games_per_week,
        games_per_week_tolerance=req.games_per_week_tolerance,
    )

    schedule = solve_schedule(constraints, league.teams, VENUES_BY_ID)
    _schedule_store[schedule.id] = schedule

    explanations = explain_schedule(schedule, {t.id: t for t in league.teams})
    for game in schedule.games:
        if game.id in explanations:
            game.ai_explanation = explanations[game.id]

    _explanation_store[schedule.id] = explanations
    _schedule_store[schedule.id] = schedule

    validation = validate_schedule(schedule.games, constraints, league.teams)

    return {
        "schedule": schedule.model_dump(),
        "validation": validation,
        "summary": _build_summary(schedule, league.teams),
    }


@router.get("/{schedule_id}")
def get_schedule(schedule_id: str):
    schedule = _schedule_store.get(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    league = LEAGUES_BY_ID.get(schedule.league_id)
    teams = league.teams if league else []
    validation = validate_schedule(schedule.games, schedule.constraints, teams)
    return {
        "schedule": schedule.dict(),
        "validation": validation,
        "summary": _build_summary(schedule, teams),
    }


@router.post("/{schedule_id}/update-game")
def update_game(schedule_id: str, req: UpdateGameRequest):
    schedule = _schedule_store.get(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    game = next((g for g in schedule.games if g.id == req.game_id), None)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

    old_date = game.game_date
    old_slot = game.timeslot
    game.game_date = req.new_date
    game.timeslot = req.new_timeslot

    league = LEAGUES_BY_ID.get(schedule.league_id)
    teams = league.teams if league else []
    validation = validate_schedule(schedule.games, schedule.constraints, teams)

    game.ai_explanation = explain_single_game(
        game,
        f"Game was moved from {old_date} {old_slot} to {req.new_date} {req.new_timeslot}",
    )

    return {
        "updated_game": game.dict(),
        "validation": validation,
    }


@router.get("/{schedule_id}/game/{game_id}/explain")
def explain_game(schedule_id: str, game_id: str):
    schedule = _schedule_store.get(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    game = next((g for g in schedule.games if g.id == game_id), None)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

    explanation = explain_single_game(game)
    game.ai_explanation = explanation
    return {"game_id": game_id, "explanation": explanation}


def _build_summary(schedule: Schedule, teams) -> Dict:
    team_home: Dict[str, int] = {}
    team_away: Dict[str, int] = {}
    for t in teams:
        team_home[t.id] = sum(1 for g in schedule.games if g.home_team_id == t.id)
        team_away[t.id] = sum(1 for g in schedule.games if g.away_team_id == t.id)

    return {
        "total_games": schedule.total_games,
        "games_per_team": {
            t.id: {"home": team_home.get(t.id, 0), "away": team_away.get(t.id, 0),
                   "total": team_home.get(t.id, 0) + team_away.get(t.id, 0)}
            for t in teams
        },
        "rivalry_games": sum(1 for g in schedule.games if g.is_rivalry),
        "primetime_games": sum(
            1 for g in schedule.games
            if any(p in g.timeslot for p in ["Saturday 8", "Sunday 4", "Friday 7"])
        ),
        "solver_status": schedule.solver_status,
    }
