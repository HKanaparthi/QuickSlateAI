import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List, Dict, Optional
from datetime import date

from ..scheduler.models import ScheduleConstraints, Schedule, Game, BroadcastContract, VenueBlackout
from ..scheduler.solver import solve_schedule, analyze_feasibility
from ..scheduler.constraints import validate_schedule
from ..ai.explainer import explain_schedule, explain_single_game
from ..data import LEAGUES_BY_ID, VENUES_BY_ID, TEAMS_BY_ID, DEFAULT_RIVALRY_PAIRS, CBA_PROFILES, CBA_PROFILES_BY_ID

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
    broadcast_contracts: List[dict] = []
    venue_blackouts: List[dict] = []
    travel_optimization_weight: float = 1.0
    cba_profile_id: Optional[str] = None


class UpdateGameRequest(BaseModel):
    game_id: str
    new_date: date
    new_timeslot: str


@router.get("/cba-profiles")
def get_cba_profiles():
    return CBA_PROFILES


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

    # Apply CBA profile if one was selected — overrides individual constraint fields
    profile = CBA_PROFILES_BY_ID.get(req.cba_profile_id or "")
    min_rest_days = profile["min_rest_days"] if profile else req.min_rest_days
    max_travel = profile["max_travel_miles_per_week"] if profile else req.max_travel_miles_per_week
    no_b2b = profile["no_back_to_back_away"] if profile else req.no_back_to_back_away
    home_away = profile["home_away_balanced"] if profile else req.home_away_balanced
    even_dist = profile["even_distribution"] if profile else req.even_distribution
    target_gpw = profile["target_games_per_week"] if profile else req.target_games_per_week
    gpw_tol = profile["games_per_week_tolerance"] if profile else req.games_per_week_tolerance
    min_slots = profile["min_distinct_slots_per_week"] if profile else req.min_distinct_slots_per_week
    max_per_slot = profile["max_games_per_slot_per_week"] if profile else req.max_games_per_slot_per_week
    travel_weight = profile["travel_optimization_weight"] if profile else req.travel_optimization_weight

    rivalry_pairs = req.rivalry_pairs
    if req.use_default_rivalries and not rivalry_pairs:
        rivalry_pairs = DEFAULT_RIVALRY_PAIRS.get(req.league_id, [])

    broadcast_contracts = [
        BroadcastContract(**c) if isinstance(c, dict) else c
        for c in req.broadcast_contracts
    ]

    venue_blackouts = [
        VenueBlackout(**b) if isinstance(b, dict) else b
        for b in req.venue_blackouts
    ]

    constraints = ScheduleConstraints(
        league_id=req.league_id,
        season_start=req.season_start,
        season_end=req.season_end,
        min_rest_days=min_rest_days,
        max_travel_miles_per_week=max_travel,
        primetime_slots=req.primetime_slots,
        rivalry_pairs=rivalry_pairs,
        home_away_balanced=home_away,
        no_back_to_back_away=no_b2b,
        weather_constraint=req.weather_constraint,
        broadcast_contracts=broadcast_contracts,
        venue_blackouts=venue_blackouts,
        travel_optimization_weight=travel_weight,
        max_games_per_slot_per_week=max_per_slot,
        min_distinct_slots_per_week=min_slots,
        even_distribution=even_dist,
        target_games_per_week=target_gpw,
        games_per_week_tolerance=gpw_tol,
    )

    feasibility = analyze_feasibility(constraints, league.teams, VENUES_BY_ID)

    schedule, solver_metrics = solve_schedule(constraints, league.teams, VENUES_BY_ID)
    _schedule_store[schedule.id] = schedule

    explanations = explain_schedule(schedule, {t.id: t for t in league.teams})
    for game in schedule.games:
        if game.id in explanations:
            game.ai_explanation = explanations[game.id]

    _explanation_store[schedule.id] = explanations
    _schedule_store[schedule.id] = schedule

    validation = validate_schedule(schedule.games, constraints, league.teams)
    summary = _build_summary(schedule, league.teams, validation)

    # Augment solver metrics with post-validation constraint satisfaction stats
    solver_metrics["venue_conflicts"] = sum(1 for v in validation["violations"] if v["type"] == "venue_conflict")
    solver_metrics["rest_violations"] = sum(1 for v in validation["violations"] if v["type"] == "rest_days")
    solver_metrics["back_to_back_away_count"] = sum(1 for v in validation["violations"] if v["type"] == "back_to_back_away")
    solver_metrics["home_away_imbalance_count"] = sum(1 for v in validation["violations"] if v["type"] == "home_away_imbalance")
    solver_metrics["broadcaster_satisfied"] = sum(1 for b in validation["broadcast_compliance"] if b["status"] == "OK")
    solver_metrics["broadcaster_total"] = len(validation["broadcast_compliance"])
    solver_metrics["cba_profile_applied"] = profile["name"] if profile else None

    return {
        "schedule": schedule.model_dump(),
        "validation": validation,
        "summary": summary,
        "feasibility_analysis": feasibility,
        "solver_metrics": solver_metrics,
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
        "schedule": schedule.model_dump(),
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
        "updated_game": game.model_dump(),
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


def _build_summary(schedule: Schedule, teams, validation: Optional[Dict] = None) -> Dict:
    team_home: Dict[str, int] = {}
    team_away: Dict[str, int] = {}
    for t in teams:
        team_home[t.id] = sum(1 for g in schedule.games if g.home_team_id == t.id)
        team_away[t.id] = sum(1 for g in schedule.games if g.away_team_id == t.id)

    # Compute home/away imbalance as % deviation from 50/50 across all teams
    imbalance_sum = 0.0
    imbalance_count = 0
    for t in teams:
        total = team_home.get(t.id, 0) + team_away.get(t.id, 0)
        if total > 0:
            ratio = team_home.get(t.id, 0) / total
            imbalance_sum += abs(ratio - 0.5)
            imbalance_count += 1
    avg_imbalance_pct = round(imbalance_sum / max(imbalance_count, 1) * 100, 1)

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
        "avg_home_away_imbalance_pct": avg_imbalance_pct,
    }
