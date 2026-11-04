"""
Regression tests for the back-to-back away constraint fix.

Root cause: solver.py used max_gap_days = max(7, 2*min_rest+1) = 7 days, so pairs of
away games more than 7 days apart were never constrained by CP-SAT even when
no_back_to_back_away=True.  At NPL cadence (~7 games/team over 30 weeks) essentially
ALL consecutive game pairs fall outside that window, making the constraint a no-op.

Fix: max_gap_days = season_days (full season length) so every pair of away dates is
evaluated.  The between_vars logic already correctly handles home-game breaks.
"""
from datetime import date
from typing import List

import pytest

from app.scheduler.constraints import check_back_to_back_away
from app.scheduler.models import (
    Game,
    Schedule,
    ScheduleConstraints,
    Team,
    Venue,
    TimeSlot,
)
from app.scheduler.solver import solve_schedule, _repair_back_to_back_away, build_date_slots

# ---------------------------------------------------------------------------
# Shared fixtures (kept minimal — only 3 teams/venues needed here)
# ---------------------------------------------------------------------------

VENUES = {
    "v_alpha": Venue(id="v_alpha", name="Alpha Arena", city="City A",
                     capacity=15000, latitude=35.2, longitude=-80.8, is_outdoor=False),
    "v_beta":  Venue(id="v_beta",  name="Beta Bowl",  city="City B",
                     capacity=12000, latitude=35.5, longitude=-80.5, is_outdoor=False),
    "v_gamma": Venue(id="v_gamma", name="Gamma Ground", city="City C",
                     capacity=18000, latitude=35.8, longitude=-79.9, is_outdoor=False),
}

TEAMS: List[Team] = [
    Team(id="T_A", name="Alpha FC", city="City A", league="TEST",
         market_size="medium", home_venue_id="v_alpha", color="#ff0000"),
    Team(id="T_B", name="Beta SC",  city="City B", league="TEST",
         market_size="small",  home_venue_id="v_beta",  color="#00ff00"),
    Team(id="T_C", name="Gamma FC", city="City C", league="TEST",
         market_size="large",  home_venue_id="v_gamma", color="#0000ff"),
]

_DAY_SLOT_MAP = {
    0: TimeSlot.MON_EVENING,
    1: TimeSlot.TUE_EVENING,
    2: TimeSlot.WED_EVENING,
    3: TimeSlot.THU_EVENING,
    4: TimeSlot.FRI_EVENING,
    5: TimeSlot.SAT_PRIMETIME,
    6: TimeSlot.SUN_AFTERNOON,
}


def g(gid: str, home: str, away: str, venue: str, d: date) -> Game:
    return Game(
        id=gid, home_team_id=home, away_team_id=away, venue_id=venue,
        game_date=d, timeslot=_DAY_SLOT_MAP[d.weekday()], travel_miles=50.0,
    )


# ---------------------------------------------------------------------------
# Unit tests: check_back_to_back_away (no CP-SAT)
# ---------------------------------------------------------------------------

class TestB2BCheckUnitTests:
    """Pure unit tests for the validator.  No solver, no CP-SAT."""

    def test_b2b_check_detects_consecutive_away_beyond_7_days(self):
        """
        Specific regression: T_B plays away March 10 and March 20 (10 days apart).
        No T_B game between them.  The old solver window (7 days) would NOT have
        constrained this pair; the validator must still detect it.
        """
        games = [
            g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 10)),  # T_B away, Monday
            g("g2", "T_C", "T_B", "v_gamma", date(2025, 3, 20)),  # T_B away, Thursday (+10 d)
        ]
        violations = check_back_to_back_away("T_B", games)
        assert len(violations) == 1
        v = violations[0]
        assert v["type"] == "back_to_back_away"
        assert v["team_id"] == "T_B"
        assert v["game1_id"] == "g1"
        assert v["game2_id"] == "g2"

    def test_b2b_check_does_not_flag_away_home_away(self):
        """
        Away → Home → Away is valid; the home game breaks the consecutive sequence.
        Must return zero violations regardless of the gap.
        """
        games = [
            g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 10)),  # T_B away
            g("g2", "T_B", "T_C", "v_beta",  date(2025, 3, 17)),  # T_B HOME
            g("g3", "T_A", "T_B", "v_alpha", date(2025, 3, 24)),  # T_B away again
        ]
        violations = check_back_to_back_away("T_B", games)
        assert violations == [], (
            f"Away → Home → Away must not be flagged as a violation; got: {violations}"
        )

    def test_b2b_check_flags_consecutive_away_no_intervening_game(self):
        """
        Away → Away with no T_B game between them must be flagged, regardless of
        how many days apart the two away games are.
        """
        games = [
            g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 10)),  # T_B away
            g("g2", "T_C", "T_B", "v_gamma", date(2025, 3, 17)),  # T_B away, 7 days later
        ]
        violations = check_back_to_back_away("T_B", games)
        assert len(violations) == 1
        v = violations[0]
        assert v["type"] == "back_to_back_away"
        assert v["team_id"] == "T_B"


# ---------------------------------------------------------------------------
# Greedy repair pass: original schedule preservation
# ---------------------------------------------------------------------------

class TestGreedyRepairPassPreservation:
    """Verify _repair_back_to_back_away does not disturb an already-valid schedule."""

    def test_valid_schedule_not_modified_by_greedy_repair(self):
        """
        A schedule with Away → Home → Away for T_B has no B2B violation.
        The greedy repair pass must leave all game dates/timeslots unchanged.
        """
        games = [
            g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 10)),  # T_B away
            g("g2", "T_B", "T_C", "v_beta",  date(2025, 3, 17)),  # T_B home
            g("g3", "T_A", "T_B", "v_alpha", date(2025, 3, 24)),  # T_B away
        ]
        date_slots = build_date_slots(date(2025, 3, 1), date(2025, 3, 31))
        team_ids = ["T_A", "T_B", "T_C"]

        original_state = [(gm.game_date, gm.timeslot) for gm in games]
        result = _repair_back_to_back_away(games, team_ids, date_slots, min_rest=2)

        assert [(gm.game_date, gm.timeslot) for gm in result] == original_state, (
            "Greedy repair must not modify a schedule that already satisfies no-B2B-away"
        )


# ---------------------------------------------------------------------------
# Small CP-SAT solver regression
# ---------------------------------------------------------------------------

class TestB2BConstraintSolver:
    """
    Minimal CP-SAT regression: 3 teams, 2 games/pair, 1-month season.
    T_C has 2 away games and 2 home games.  With the old 7-day window the
    solver would not have constrained the away pair (they'd naturally land
    >7 days apart).  The fix extends max_gap_days to the full season so the
    constraint fires and forces a T_C home game between the two away dates.
    """

    def _make_constraints(self) -> ScheduleConstraints:
        return ScheduleConstraints(
            league_id="TEST_B2B",
            season_start=date(2025, 3, 1),
            season_end=date(2025, 3, 31),
            min_rest_days=1,
            max_travel_miles_per_week=5000,
            no_back_to_back_away=True,
            home_away_balanced=False,
            even_distribution=False,
            games_per_pair=2,
            travel_optimization_weight=0.0,
            # Relax distribution constraints so the small instance isn't
            # over-constrained by defaults designed for full seasons.
            min_distinct_slots_per_week=1,
            max_games_per_slot_per_week=4,
            target_games_per_week=2,
            games_per_week_tolerance=2,
        )

    def test_solver_enforces_b2b_away_beyond_7_day_window(self):
        """
        Generated schedule must have zero back-to-back away violations when
        no_back_to_back_away=True, even though game pairs fall >7 days apart.
        """
        c = self._make_constraints()
        schedule, metrics = solve_schedule(c, TEAMS, VENUES)

        assert schedule.solver_status in ("OPTIMAL", "FEASIBLE"), (
            f"Solver returned '{schedule.solver_status}'. "
            f"infeasibility_reasons: {metrics.get('infeasibility_reasons')}"
        )

        b2b_violations = []
        for tid in [t.id for t in TEAMS]:
            b2b_violations.extend(check_back_to_back_away(tid, schedule.games))

        assert b2b_violations == [], (
            f"B2B away violations found despite no_back_to_back_away=True — "
            f"max_gap_days fix may not be working:\n"
            + "\n".join(
                f"  {v['team_id']}: {v['game1_id']} → {v['game2_id']}"
                for v in b2b_violations
            )
        )

    def test_solver_metrics_do_not_report_residual_b2b_violations(self):
        """
        infeasibility_reasons must be empty when the schedule passes the B2B check.
        A non-empty list here means the greedy repair pass failed and the
        requirement-6 safety net fired — that would indicate the fix is incomplete.
        """
        c = self._make_constraints()
        _, metrics = solve_schedule(c, TEAMS, VENUES)

        b2b_reasons = [
            r for r in metrics.get("infeasibility_reasons", [])
            if "back-to-back away" in r
        ]
        assert b2b_reasons == [], (
            f"Solver metrics report residual B2B violations after greedy repair:\n"
            + "\n".join(f"  {r}" for r in b2b_reasons)
        )
