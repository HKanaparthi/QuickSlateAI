import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import List, Dict, Optional
from datetime import date

from ..scheduler.models import (
    ScheduleConstraints, Schedule, Game, BroadcastContract, VenueBlackout,
    RepairRequest as EngineRepairRequest, RepairStatus,
)
from ..scheduler.solver import solve_schedule, analyze_feasibility
from ..scheduler.constraints import validate_schedule
from ..scheduler.repair import repair_schedule as _repair_schedule_engine, compute_comparison_metrics
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
    # Opponent rotation
    games_per_pair: int = 2
    divisions: List[List[str]] = []
    games_between_division_opponents: int = 4
    games_between_nondivision_opponents: int = 2


class UpdateGameRequest(BaseModel):
    game_id: str
    new_date: date
    new_timeslot: str


class ScheduleRepairRequest(BaseModel):
    venue_id: str
    blackout_start: date
    blackout_end: date
    reason: str = ""
    neighborhood_size: int = 5
    max_neighborhood_expansions: int = 3
    time_limit_seconds: float = Field(default=30.0, gt=0)


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
        broadcast_contracts=broadcast_contracts,
        venue_blackouts=venue_blackouts,
        travel_optimization_weight=travel_weight,
        max_games_per_slot_per_week=max_per_slot,
        min_distinct_slots_per_week=min_slots,
        even_distribution=even_dist,
        target_games_per_week=target_gpw,
        games_per_week_tolerance=gpw_tol,
        games_per_pair=req.games_per_pair,
        divisions=req.divisions,
        games_between_division_opponents=req.games_between_division_opponents,
        games_between_nondivision_opponents=req.games_between_nondivision_opponents,
    )

    feasibility = analyze_feasibility(constraints, league.teams, VENUES_BY_ID)

    schedule, solver_metrics = solve_schedule(constraints, league.teams, VENUES_BY_ID)

    # Gate 1 — solver must have found a feasible/optimal solution.
    if schedule.solver_status in ("TIMEOUT_FALLBACK", "INFEASIBLE"):
        reasons = solver_metrics.get("infeasibility_reasons") or []
        hint = (
            "; ".join(reasons)
            if reasons
            else "Try extending the season, reducing min_rest_days, or relaxing constraints."
        )
        raise HTTPException(
            status_code=503,
            detail=f"Schedule generation failed ({schedule.solver_status}). {hint}",
        )

    # Gate 2 — independent validation BEFORE the schedule enters the store.
    # This catches any residual hard violations the solver may have missed
    # (e.g., from the greedy post-solve repair pass).
    validation = validate_schedule(schedule.games, constraints, league.teams)
    red_violations = [v for v in validation["violations"] if v.get("severity") == "RED"]
    if red_violations:
        type_counts: Dict[str, int] = {}
        for v in red_violations:
            type_counts[v["type"]] = type_counts.get(v["type"], 0) + 1
        desc = ", ".join(
            f"{cnt} {t.replace('_', ' ')}"
            for t, cnt in sorted(type_counts.items())
        )
        raise HTTPException(
            status_code=422,
            detail=(
                f"Generated schedule has {len(red_violations)} hard constraint "
                f"violation(s) ({desc}). "
                "The solver may need more time or relaxed constraints."
            ),
        )

    # Schedule passed all gates — safe to store.
    _schedule_store[schedule.id] = schedule

    explanations = explain_schedule(schedule, {t.id: t for t in league.teams})
    for game in schedule.games:
        if game.id in explanations:
            game.ai_explanation = explanations[game.id]

    _explanation_store[schedule.id] = explanations
    _schedule_store[schedule.id] = schedule

    summary = _build_summary(schedule, league.teams, validation)

    # Augment solver metrics with post-validation stats
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


@router.get("/compare/{original_id}/{repaired_id}")
def compare_schedules(original_id: str, repaired_id: str):
    original = _schedule_store.get(original_id)
    if not original:
        raise HTTPException(status_code=404, detail=f"Schedule '{original_id}' not found")
    repaired = _schedule_store.get(repaired_id)
    if not repaired:
        raise HTTPException(status_code=404, detail=f"Schedule '{repaired_id}' not found")
    return compute_comparison_metrics(original, repaired)


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


@router.post("/{schedule_id}/repair")
def repair_schedule_endpoint(schedule_id: str, req: ScheduleRepairRequest):
    schedule = _schedule_store.get(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail=f"Schedule '{schedule_id}' not found")

    if req.venue_id not in VENUES_BY_ID:
        raise HTTPException(status_code=400, detail=f"Venue '{req.venue_id}' not found")

    if req.blackout_start > req.blackout_end:
        raise HTTPException(
            status_code=400, detail="blackout_start must be on or before blackout_end"
        )

    affected_game_ids = [
        g.id for g in schedule.games
        if g.venue_id == req.venue_id
        and req.blackout_start <= g.game_date <= req.blackout_end
    ]

    if not affected_game_ids:
        return {
            "status": "NO_GAMES_AFFECTED",
            "message": (
                f"No games at venue '{req.venue_id}' between "
                f"{req.blackout_start} and {req.blackout_end}. "
                "Original schedule is unaffected."
            ),
            "original_schedule_id": schedule_id,
            "repaired_schedule_id": None,
            "moves": [],
        }

    new_blackout = VenueBlackout(
        venue_id=req.venue_id,
        start_date=req.blackout_start,
        end_date=req.blackout_end,
        reason=req.reason,
    )
    updated_constraints = schedule.constraints.model_copy(
        update={"venue_blackouts": schedule.constraints.venue_blackouts + [new_blackout]}
    )

    league = LEAGUES_BY_ID.get(schedule.league_id)
    teams = league.teams if league else []

    engine_req = EngineRepairRequest(
        schedule_id=schedule_id,
        affected_game_ids=affected_game_ids,
        updated_constraints=updated_constraints,
        neighborhood_size=req.neighborhood_size,
        max_neighborhood_expansions=req.max_neighborhood_expansions,
        time_limit_seconds=req.time_limit_seconds,
        repair_reason=req.reason,
    )

    result = _repair_schedule_engine(engine_req, schedule, teams, VENUES_BY_ID)

    if (
        result.status in (RepairStatus.OPTIMAL, RepairStatus.FEASIBLE)
        and result.repaired_schedule is not None
        and result.repaired_schedule_id is not None
    ):
        _schedule_store[result.repaired_schedule_id] = result.repaired_schedule

    return {
        "original_schedule_id": schedule_id,
        "repaired_schedule_id": result.repaired_schedule_id,
        "status": result.status,
        "moves": [m.model_dump() for m in result.moves],
        "neighborhood_expansions_used": result.neighborhood_expansions_used,
        "solve_time_seconds": result.solve_time_seconds,
        "objective_gap": result.objective_gap,
        "validation_result": result.validation_result,
        "affected_game_ids": affected_game_ids,
        "error_message": result.error_message,
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
