"""
Run this locally to pre-generate the default NPL schedule.
Output: app/pregenerated_schedule.json
Usage: python generate_prebuilt.py  (from the backend/ directory)
"""
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.scheduler.models import ScheduleConstraints
from app.scheduler.solver import solve_schedule
from app.scheduler.constraints import validate_schedule
from app.data import LEAGUES_BY_ID, VENUES_BY_ID, DEFAULT_RIVALRY_PAIRS


def build_summary(schedule, teams):
    team_home = {}
    team_away = {}
    for t in teams:
        team_home[t.id] = sum(1 for g in schedule.games if g.home_team_id == t.id)
        team_away[t.id] = sum(1 for g in schedule.games if g.away_team_id == t.id)
    return {
        "total_games": schedule.total_games,
        "games_per_team": {
            t.id: {
                "home": team_home.get(t.id, 0),
                "away": team_away.get(t.id, 0),
                "total": team_home.get(t.id, 0) + team_away.get(t.id, 0),
            }
            for t in teams
        },
        "rivalry_games": sum(1 for g in schedule.games if g.is_rivalry),
        "primetime_games": sum(
            1 for g in schedule.games
            if any(p in g.timeslot for p in ["Saturday 8", "Sunday 4", "Friday 7"])
        ),
        "solver_status": schedule.solver_status,
    }


def main():
    league_id = "NPL"
    league = LEAGUES_BY_ID[league_id]

    constraints = ScheduleConstraints(
        league_id=league_id,
        season_start=date(2026, 10, 1),
        season_end=date(2027, 4, 30),
        min_rest_days=2,
        max_travel_miles_per_week=600,
        primetime_slots=["Saturday 8:00 PM", "Sunday 4:00 PM", "Friday 7:00 PM"],
        rivalry_pairs=DEFAULT_RIVALRY_PAIRS.get(league_id, []),
        home_away_balanced=True,
        no_back_to_back_away=True,
        weather_constraint=False,
        max_games_per_slot_per_week=2,
        min_distinct_slots_per_week=3,
        even_distribution=True,
        target_games_per_week=4,
        games_per_week_tolerance=1,
    )

    print("Running OR-Tools CP-SAT solver (this may take up to 60s)...")
    schedule = solve_schedule(constraints, league.teams, VENUES_BY_ID)
    print(f"Solver status: {schedule.solver_status}")
    print(f"Games generated: {schedule.total_games}")

    validation = validate_schedule(schedule.games, constraints, league.teams)
    summary = build_summary(schedule, league.teams)

    payload = {
        "schedule": schedule.dict(),
        "validation": validation,
        "summary": summary,
    }

    out_path = Path(__file__).parent / "app" / "pregenerated_schedule.json"
    with open(out_path, "w") as f:
        json.dump(payload, f, default=str, indent=2)

    print(f"Saved to {out_path}")


if __name__ == "__main__":
    main()
