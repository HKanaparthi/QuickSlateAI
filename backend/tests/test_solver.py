"""
Regression tests for existing schedule generation (solver.py).
Uses a minimal 4-team fixture with a short season so tests run quickly.
Tests verify structural correctness and hard-constraint compliance,
not exact game placement (which depends on CP-SAT internal search order).
"""
from datetime import date
from collections import Counter

import pytest

from app.scheduler.solver import solve_schedule, build_date_slots, _stable_variation
from app.scheduler.constraints import validate_schedule
from app.scheduler.models import ScheduleConstraints, Team, Venue


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

VENUES = {
    "v_alpha": Venue(id="v_alpha", name="Alpha Arena", city="City A",
                     capacity=15000, latitude=35.2, longitude=-80.8, is_outdoor=False),
    "v_beta":  Venue(id="v_beta",  name="Beta Bowl",  city="City B",
                     capacity=12000, latitude=35.5, longitude=-80.5, is_outdoor=False),
    "v_gamma": Venue(id="v_gamma", name="Gamma Ground", city="City C",
                     capacity=18000, latitude=35.8, longitude=-79.9, is_outdoor=False),
    "v_delta": Venue(id="v_delta", name="Delta Dome",  city="City D",
                     capacity=10000, latitude=36.1, longitude=-79.5, is_outdoor=False),
}

TEAMS = [
    Team(id="T_A", name="Alpha FC", city="City A", league="TEST",
         market_size="medium", home_venue_id="v_alpha", color="#ff0000"),
    Team(id="T_B", name="Beta SC",  city="City B", league="TEST",
         market_size="small",  home_venue_id="v_beta",  color="#00ff00"),
    Team(id="T_C", name="Gamma FC", city="City C", league="TEST",
         market_size="large",  home_venue_id="v_gamma", color="#0000ff"),
    Team(id="T_D", name="Delta SC", city="City D", league="TEST",
         market_size="medium", home_venue_id="v_delta", color="#ffff00"),
]


def make_constraints(**kwargs) -> ScheduleConstraints:
    defaults = dict(
        league_id="TEST",
        season_start=date(2025, 3, 1),
        season_end=date(2025, 5, 31),
        min_rest_days=2,
        max_travel_miles_per_week=800,
        games_per_pair=2,
        no_back_to_back_away=False,  # simplify for fast tests
        home_away_balanced=False,
        even_distribution=False,
        travel_optimization_weight=1.0,
    )
    defaults.update(kwargs)
    return ScheduleConstraints(**defaults)


# ---------------------------------------------------------------------------
# _stable_variation — determinism guarantee
# ---------------------------------------------------------------------------

class TestStableVariation:
    def test_range_is_in_0_7_to_1_0(self):
        v = _stable_variation("T_A", "T_B", date(2025, 3, 10), "Monday 7:00 PM")
        assert 0.7 <= v <= 1.0

    def test_same_inputs_same_output(self):
        v1 = _stable_variation("T_A", "T_B", date(2025, 3, 10), "Saturday 8:00 PM")
        v2 = _stable_variation("T_A", "T_B", date(2025, 3, 10), "Saturday 8:00 PM")
        assert v1 == v2

    def test_different_matchup_different_output(self):
        v1 = _stable_variation("T_A", "T_B", date(2025, 3, 10), "Monday 7:00 PM")
        v2 = _stable_variation("T_C", "T_D", date(2025, 3, 10), "Monday 7:00 PM")
        assert v1 != v2

    def test_different_date_different_output(self):
        v1 = _stable_variation("T_A", "T_B", date(2025, 3, 10), "Monday 7:00 PM")
        v2 = _stable_variation("T_A", "T_B", date(2025, 3, 17), "Monday 7:00 PM")
        assert v1 != v2


# ---------------------------------------------------------------------------
# build_date_slots
# ---------------------------------------------------------------------------

class TestBuildDateSlots:
    def test_one_week_has_seven_slots(self):
        slots = build_date_slots(date(2025, 3, 3), date(2025, 3, 9))
        # Mon–Sun = 7 days, one slot each
        assert len(slots) == 7

    def test_all_slots_within_bounds(self):
        start, end = date(2025, 3, 1), date(2025, 3, 31)
        slots = build_date_slots(start, end)
        for d, _ in slots:
            assert start <= d <= end

    def test_empty_range_returns_empty(self):
        assert build_date_slots(date(2025, 3, 10), date(2025, 3, 9)) == []


# ---------------------------------------------------------------------------
# solve_schedule — structural correctness
# ---------------------------------------------------------------------------

class TestSolveSchedule:
    def test_returns_schedule_and_metrics(self):
        c = make_constraints()
        schedule, metrics = solve_schedule(c, TEAMS, VENUES)
        assert schedule is not None
        assert isinstance(metrics, dict)

    def test_game_count_matches_matchup_count(self):
        # 4 teams × games_per_pair=2 → 4C2 × 2 = 12 matchups → 12 games
        c = make_constraints(games_per_pair=2)
        schedule, _ = solve_schedule(c, TEAMS, VENUES)
        # Each (i,j) pair generates ceil(2/2) + floor(2/2) = 1+1 = 2 entries
        # 4C2 = 6 pairs × 2 = 12 games
        assert schedule.total_games == len(schedule.games)
        assert schedule.total_games == 12

    def test_all_matchups_present_exactly_once_per_direction(self):
        c = make_constraints(games_per_pair=2)
        schedule, _ = solve_schedule(c, TEAMS, VENUES)
        team_ids = [t.id for t in TEAMS]
        matchup_counts: Counter = Counter()
        for g in schedule.games:
            matchup_counts[(g.home_team_id, g.away_team_id)] += 1
        for i, t1 in enumerate(team_ids):
            for j, t2 in enumerate(team_ids):
                if i == j:
                    continue
                total = matchup_counts.get((t1, t2), 0) + matchup_counts.get((t2, t1), 0)
                assert total == 2, f"Expected 2 games between {t1} and {t2}, got {total}"

    def test_solver_status_is_optimal_or_feasible(self):
        c = make_constraints()
        schedule, metrics = solve_schedule(c, TEAMS, VENUES)
        assert schedule.solver_status in ("OPTIMAL", "FEASIBLE", "TIMEOUT_FALLBACK")

    def test_all_games_within_season_dates(self):
        c = make_constraints()
        schedule, _ = solve_schedule(c, TEAMS, VENUES)
        for g in schedule.games:
            assert c.season_start <= g.game_date <= c.season_end

    def test_no_venue_conflicts(self):
        c = make_constraints()
        schedule, _ = solve_schedule(c, TEAMS, VENUES)
        from app.scheduler.constraints import check_venue_conflicts
        assert check_venue_conflicts(schedule.games) == []

    def test_rest_days_respected(self):
        c = make_constraints(min_rest_days=2)
        schedule, _ = solve_schedule(c, TEAMS, VENUES)
        from app.scheduler.constraints import check_rest_days
        for t in TEAMS:
            violations = check_rest_days(t.id, schedule.games, 2)
            assert violations == [], f"Rest violation for {t.id}: {violations}"

    def test_validate_schedule_returns_no_red_violations(self):
        c = make_constraints()
        schedule, _ = solve_schedule(c, TEAMS, VENUES)
        result = validate_schedule(schedule.games, c, TEAMS)
        # Allow YELLOW (soft constraints) but no RED (hard constraint violations)
        assert result["red_count"] == 0, (
            f"Unexpected RED violations: "
            f"{[v for v in result['violations'] if v['severity'] == 'RED']}"
        )

    def test_games_are_sorted_by_date(self):
        c = make_constraints()
        schedule, _ = solve_schedule(c, TEAMS, VENUES)
        dates = [g.game_date for g in schedule.games]
        assert dates == sorted(dates)

    def test_projected_viewership_deterministic(self):
        c = make_constraints()
        s1, _ = solve_schedule(c, TEAMS, VENUES)
        s2, _ = solve_schedule(c, TEAMS, VENUES)
        # CP-SAT may produce different placements across runs with multiple workers
        # but all games assigned to the same (home, away, date, slot) must have
        # identical projected_viewership.
        s1_map = {(g.home_team_id, g.away_team_id, g.game_date, g.timeslot): g.projected_viewership
                  for g in s1.games}
        s2_map = {(g.home_team_id, g.away_team_id, g.game_date, g.timeslot): g.projected_viewership
                  for g in s2.games}
        for key in s1_map:
            if key in s2_map:
                assert s1_map[key] == s2_map[key], (
                    f"Non-deterministic viewership for {key}: {s1_map[key]} vs {s2_map[key]}"
                )

    def test_projected_viewership_is_positive(self):
        c = make_constraints()
        schedule, _ = solve_schedule(c, TEAMS, VENUES)
        for g in schedule.games:
            assert g.projected_viewership is not None
            assert g.projected_viewership > 0

    def test_venue_blackout_respected(self):
        from app.scheduler.models import VenueBlackout
        c = make_constraints(venue_blackouts=[
            VenueBlackout(venue_id="v_alpha", start_date=date(2025, 3, 1), end_date=date(2025, 3, 31),
                          reason="renovation")
        ])
        schedule, _ = solve_schedule(c, TEAMS, VENUES)
        for g in schedule.games:
            if g.venue_id == "v_alpha":
                assert not (date(2025, 3, 1) <= g.game_date <= date(2025, 3, 31)), (
                    f"Game at blacked-out venue v_alpha on {g.game_date}"
                )

    def test_infeasible_constraints_return_infeasible_status(self):
        # 1-day season with 4 teams = impossible
        c = make_constraints(
            season_start=date(2025, 3, 10),
            season_end=date(2025, 3, 10),
            even_distribution=False,
        )
        schedule, metrics = solve_schedule(c, TEAMS, VENUES)
        # Solver may return INFEASIBLE or TIMEOUT_FALLBACK
        assert schedule.solver_status in ("INFEASIBLE", "TIMEOUT_FALLBACK")

    def test_metrics_include_expected_keys(self):
        c = make_constraints()
        _, metrics = solve_schedule(c, TEAMS, VENUES)
        for key in ("decisions_evaluated", "solve_time_seconds", "solver_status",
                    "n_matchups", "n_slots", "total_variables"):
            assert key in metrics, f"Missing metric key: {key}"

    def test_schedule_id_is_unique_across_runs(self):
        c = make_constraints()
        s1, _ = solve_schedule(c, TEAMS, VENUES)
        s2, _ = solve_schedule(c, TEAMS, VENUES)
        assert s1.id != s2.id


# ---------------------------------------------------------------------------
# New validator regression — weekly game cap and travel cap
# ---------------------------------------------------------------------------

class TestWeeklyGameCapValidator:
    def test_no_violation_within_cap(self):
        from app.scheduler.constraints import check_weekly_game_cap
        from app.scheduler.models import Game, TimeSlot
        games = [
            Game(id="g1", home_team_id="T_A", away_team_id="T_B", venue_id="v1",
                 game_date=date(2025, 3, 10), timeslot=TimeSlot.MON_EVENING),
            Game(id="g2", home_team_id="T_A", away_team_id="T_C", venue_id="v1",
                 game_date=date(2025, 3, 15), timeslot=TimeSlot.SAT_PRIMETIME),
        ]
        assert check_weekly_game_cap(games, ["T_A"]) == []

    def test_violation_when_four_games_in_one_week(self):
        from app.scheduler.constraints import check_weekly_game_cap
        from app.scheduler.models import Game, TimeSlot
        # ISO week of 2025-03-10 is week 11
        games = [
            Game(id=f"g{i}", home_team_id="T_A", away_team_id="T_B", venue_id="v1",
                 game_date=date(2025, 3, 10 + i), timeslot=TimeSlot.MON_EVENING)
            for i in range(4)  # Mon–Thu same week
        ]
        violations = check_weekly_game_cap(games, ["T_A"])
        assert len(violations) == 1
        assert violations[0]["severity"] == "RED"
        assert violations[0]["count"] == 4


class TestWeeklyTravelCapValidator:
    def test_no_violation_within_cap(self):
        from app.scheduler.constraints import check_weekly_travel_cap
        from app.scheduler.models import Game, TimeSlot
        c = make_constraints(max_travel_miles_per_week=800)
        games = [
            Game(id="g1", home_team_id="T_X", away_team_id="T_A", venue_id="v1",
                 game_date=date(2025, 3, 10), timeslot=TimeSlot.MON_EVENING,
                 travel_miles=200.0),
        ]
        assert check_weekly_travel_cap(games, ["T_A"], c) == []

    def test_violation_over_cap(self):
        from app.scheduler.constraints import check_weekly_travel_cap
        from app.scheduler.models import Game, TimeSlot
        c = make_constraints(max_travel_miles_per_week=400)
        games = [
            Game(id="g1", home_team_id="T_X", away_team_id="T_A", venue_id="v1",
                 game_date=date(2025, 3, 10), timeslot=TimeSlot.MON_EVENING,
                 travel_miles=250.0),
            Game(id="g2", home_team_id="T_Y", away_team_id="T_A", venue_id="v2",
                 game_date=date(2025, 3, 13), timeslot=TimeSlot.THU_EVENING,
                 travel_miles=250.0),
        ]
        violations = check_weekly_travel_cap(games, ["T_A"], c)
        assert len(violations) == 1
        assert violations[0]["severity"] == "RED"
        assert violations[0]["miles"] == 500.0
