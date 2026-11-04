"""
Tests for constraint validation — venue blackout compliance (Phase 1 addition)
and regression coverage for existing constraint checks.
"""
from datetime import date

import pytest

from app.scheduler.constraints import (
    check_back_to_back_away,
    check_home_away_balance,
    check_rest_days,
    check_venue_blackout_compliance,
    check_venue_conflicts,
    validate_schedule,
)
from app.scheduler.models import (
    Game,
    ScheduleConstraints,
    Team,
    TimeSlot,
    VenueBlackout,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def make_game(
    gid: str,
    home: str,
    away: str,
    venue: str,
    game_date: date,
    timeslot: str = TimeSlot.MON_EVENING,
) -> Game:
    return Game(
        id=gid,
        home_team_id=home,
        away_team_id=away,
        venue_id=venue,
        game_date=game_date,
        timeslot=timeslot,
    )


def make_constraints(**kwargs) -> ScheduleConstraints:
    defaults = dict(
        league_id="TEST",
        season_start=date(2025, 1, 1),
        season_end=date(2025, 6, 30),
        no_back_to_back_away=True,
        home_away_balanced=True,
    )
    defaults.update(kwargs)
    return ScheduleConstraints(**defaults)


def make_team(tid: str) -> Team:
    return Team(
        id=tid,
        name=tid,
        city="TestCity",
        league="TEST",
        market_size="medium",
        home_venue_id=f"venue_{tid}",
        color="#000000",
    )


# ---------------------------------------------------------------------------
# check_venue_blackout_compliance
# ---------------------------------------------------------------------------

class TestVenueBlackoutCompliance:
    def test_no_blackouts_returns_empty(self):
        g = make_game("g1", "A", "B", "v1", date(2025, 3, 15))
        c = make_constraints()
        assert check_venue_blackout_compliance([g], c) == []

    def test_game_on_blackout_start_date_is_violation(self):
        g = make_game("g1", "A", "B", "v1", date(2025, 3, 15))
        c = make_constraints(venue_blackouts=[
            VenueBlackout(venue_id="v1", start_date=date(2025, 3, 15), end_date=date(2025, 3, 20))
        ])
        violations = check_venue_blackout_compliance([g], c)
        assert len(violations) == 1
        assert violations[0]["severity"] == "RED"
        assert violations[0]["game_id"] == "g1"
        assert violations[0]["type"] == "venue_blackout"

    def test_game_inside_blackout_is_violation(self):
        g = make_game("g1", "A", "B", "v1", date(2025, 3, 17))
        c = make_constraints(venue_blackouts=[
            VenueBlackout(venue_id="v1", start_date=date(2025, 3, 15), end_date=date(2025, 3, 20))
        ])
        assert len(check_venue_blackout_compliance([g], c)) == 1

    def test_game_on_blackout_end_date_is_violation(self):
        g = make_game("g1", "A", "B", "v1", date(2025, 3, 20))
        c = make_constraints(venue_blackouts=[
            VenueBlackout(venue_id="v1", start_date=date(2025, 3, 15), end_date=date(2025, 3, 20))
        ])
        assert len(check_venue_blackout_compliance([g], c)) == 1

    def test_game_one_day_after_blackout_passes(self):
        g = make_game("g1", "A", "B", "v1", date(2025, 3, 21))
        c = make_constraints(venue_blackouts=[
            VenueBlackout(venue_id="v1", start_date=date(2025, 3, 15), end_date=date(2025, 3, 20))
        ])
        assert check_venue_blackout_compliance([g], c) == []

    def test_game_one_day_before_blackout_passes(self):
        g = make_game("g1", "A", "B", "v1", date(2025, 3, 14))
        c = make_constraints(venue_blackouts=[
            VenueBlackout(venue_id="v1", start_date=date(2025, 3, 15), end_date=date(2025, 3, 20))
        ])
        assert check_venue_blackout_compliance([g], c) == []

    def test_different_venue_not_affected(self):
        g = make_game("g1", "A", "B", "v2", date(2025, 3, 17))
        c = make_constraints(venue_blackouts=[
            VenueBlackout(venue_id="v1", start_date=date(2025, 3, 15), end_date=date(2025, 3, 20))
        ])
        assert check_venue_blackout_compliance([g], c) == []

    def test_multiple_games_multiple_blackouts(self):
        games = [
            make_game("g1", "A", "B", "v1", date(2025, 3, 17)),  # inside blackout1
            make_game("g2", "A", "B", "v1", date(2025, 4, 10)),  # inside blackout2
            make_game("g3", "A", "B", "v1", date(2025, 5, 1)),   # clear
        ]
        c = make_constraints(venue_blackouts=[
            VenueBlackout(venue_id="v1", start_date=date(2025, 3, 15), end_date=date(2025, 3, 20)),
            VenueBlackout(venue_id="v1", start_date=date(2025, 4, 8), end_date=date(2025, 4, 12)),
        ])
        violations = check_venue_blackout_compliance(games, c)
        assert len(violations) == 2
        assert {v["game_id"] for v in violations} == {"g1", "g2"}

    def test_violation_message_includes_reason(self):
        g = make_game("g1", "A", "B", "v1", date(2025, 3, 17))
        c = make_constraints(venue_blackouts=[
            VenueBlackout(
                venue_id="v1",
                start_date=date(2025, 3, 15),
                end_date=date(2025, 3, 20),
                reason="NCAA Tournament",
            )
        ])
        violations = check_venue_blackout_compliance([g], c)
        assert "NCAA Tournament" in violations[0]["message"]

    def test_violation_message_no_reason_no_parentheses(self):
        g = make_game("g1", "A", "B", "v1", date(2025, 3, 17))
        c = make_constraints(venue_blackouts=[
            VenueBlackout(venue_id="v1", start_date=date(2025, 3, 15), end_date=date(2025, 3, 20))
        ])
        violations = check_venue_blackout_compliance([g], c)
        assert "()" not in violations[0]["message"]

    def test_single_day_blackout_exact_match(self):
        g = make_game("g1", "A", "B", "v1", date(2025, 3, 17))
        c = make_constraints(venue_blackouts=[
            VenueBlackout(venue_id="v1", start_date=date(2025, 3, 17), end_date=date(2025, 3, 17))
        ])
        assert len(check_venue_blackout_compliance([g], c)) == 1

    def test_single_day_blackout_adjacent_passes(self):
        g_before = make_game("g1", "A", "B", "v1", date(2025, 3, 16))
        g_after = make_game("g2", "A", "B", "v1", date(2025, 3, 18))
        c = make_constraints(venue_blackouts=[
            VenueBlackout(venue_id="v1", start_date=date(2025, 3, 17), end_date=date(2025, 3, 17))
        ])
        assert check_venue_blackout_compliance([g_before, g_after], c) == []

    def test_validate_schedule_surfaces_blackout_as_red(self):
        g = make_game("g1", "A", "B", "v1", date(2025, 3, 17))
        c = make_constraints(venue_blackouts=[
            VenueBlackout(venue_id="v1", start_date=date(2025, 3, 15), end_date=date(2025, 3, 20))
        ])
        result = validate_schedule([g], c, [])
        assert result["status"] == "RED"
        assert result["red_count"] >= 1
        bv = [v for v in result["violations"] if v["type"] == "venue_blackout"]
        assert len(bv) == 1

    def test_validate_schedule_clean_no_blackout_violations(self):
        g = make_game("g1", "A", "B", "v1", date(2025, 5, 1))
        c = make_constraints(venue_blackouts=[
            VenueBlackout(venue_id="v1", start_date=date(2025, 3, 15), end_date=date(2025, 3, 20))
        ])
        result = validate_schedule([g], c, [])
        bv = [v for v in result["violations"] if v["type"] == "venue_blackout"]
        assert bv == []


# ---------------------------------------------------------------------------
# Regression tests — existing constraint checks
# ---------------------------------------------------------------------------

class TestRestDays:
    def test_violation_when_gap_below_minimum(self):
        games = [
            make_game("g1", "T1", "T2", "v1", date(2025, 3, 10)),
            make_game("g2", "T1", "T3", "v2", date(2025, 3, 11)),  # 1 day — below min 2
        ]
        violations = check_rest_days("T1", games, min_rest=2)
        assert len(violations) == 1
        assert violations[0]["severity"] == "RED"
        assert "1 rest days" in violations[0]["message"]

    def test_no_violation_when_gap_equals_minimum(self):
        games = [
            make_game("g1", "T1", "T2", "v1", date(2025, 3, 10)),
            make_game("g2", "T1", "T3", "v2", date(2025, 3, 12)),  # exactly 2 days
        ]
        assert check_rest_days("T1", games, min_rest=2) == []

    def test_no_violation_when_gap_exceeds_minimum(self):
        games = [
            make_game("g1", "T1", "T2", "v1", date(2025, 3, 10)),
            make_game("g2", "T1", "T3", "v2", date(2025, 3, 15)),
        ]
        assert check_rest_days("T1", games, min_rest=2) == []

    def test_only_own_team_games_counted(self):
        games = [
            make_game("g1", "T1", "T2", "v1", date(2025, 3, 10)),
            make_game("g2", "T3", "T4", "v2", date(2025, 3, 11)),  # unrelated game
        ]
        assert check_rest_days("T1", games, min_rest=2) == []


class TestVenueConflicts:
    def test_conflict_same_venue_same_date_same_slot(self):
        games = [
            make_game("g1", "T1", "T2", "v1", date(2025, 3, 10), TimeSlot.MON_EVENING),
            make_game("g2", "T3", "T4", "v1", date(2025, 3, 10), TimeSlot.MON_EVENING),
        ]
        violations = check_venue_conflicts(games)
        assert len(violations) == 1
        assert violations[0]["severity"] == "RED"
        assert set(violations[0]["game_ids"]) == {"g1", "g2"}

    def test_no_conflict_different_timeslot(self):
        games = [
            make_game("g1", "T1", "T2", "v1", date(2025, 3, 10), TimeSlot.MON_EVENING),
            make_game("g2", "T3", "T4", "v1", date(2025, 3, 10), TimeSlot.WED_EVENING),
        ]
        assert check_venue_conflicts(games) == []

    def test_no_conflict_different_date(self):
        games = [
            make_game("g1", "T1", "T2", "v1", date(2025, 3, 10), TimeSlot.MON_EVENING),
            make_game("g2", "T3", "T4", "v1", date(2025, 3, 11), TimeSlot.MON_EVENING),
        ]
        assert check_venue_conflicts(games) == []

    def test_no_conflict_different_venue(self):
        games = [
            make_game("g1", "T1", "T2", "v1", date(2025, 3, 10), TimeSlot.MON_EVENING),
            make_game("g2", "T3", "T4", "v2", date(2025, 3, 10), TimeSlot.MON_EVENING),
        ]
        assert check_venue_conflicts(games) == []


class TestBackToBackAway:
    def test_consecutive_away_detected(self):
        games = [
            make_game("g1", "T2", "T1", "v2", date(2025, 3, 10)),  # T1 away
            make_game("g2", "T3", "T1", "v3", date(2025, 3, 15)),  # T1 away again
        ]
        violations = check_back_to_back_away("T1", games)
        assert len(violations) == 1
        assert violations[0]["severity"] == "YELLOW"

    def test_home_then_away_not_flagged(self):
        games = [
            make_game("g1", "T1", "T2", "v1", date(2025, 3, 10)),  # T1 home
            make_game("g2", "T3", "T1", "v3", date(2025, 3, 15)),  # T1 away
        ]
        assert check_back_to_back_away("T1", games) == []


class TestValidateScheduleIntegration:
    def test_clean_schedule_is_green(self):
        teams = [make_team("T1"), make_team("T2")]
        games = [
            make_game("g1", "T1", "T2", "v1", date(2025, 3, 10)),
            make_game("g2", "T2", "T1", "v2", date(2025, 3, 15)),
        ]
        result = validate_schedule(games, make_constraints(), teams)
        assert result["status"] == "GREEN"
        assert result["red_count"] == 0
        assert result["yellow_count"] == 0

    def test_rest_violation_makes_schedule_red(self):
        teams = [make_team("T1"), make_team("T2")]
        games = [
            make_game("g1", "T1", "T2", "v1", date(2025, 3, 10)),
            make_game("g2", "T2", "T1", "v2", date(2025, 3, 11)),  # 1-day gap for both teams
        ]
        result = validate_schedule(games, make_constraints(min_rest_days=2), teams)
        assert result["status"] == "RED"

    def test_blackout_violation_independent_of_other_violations(self):
        teams = [make_team("T1"), make_team("T2")]
        games = [
            make_game("g1", "T1", "T2", "v1", date(2025, 3, 17)),
            make_game("g2", "T2", "T1", "v2", date(2025, 3, 20)),
        ]
        c = make_constraints(venue_blackouts=[
            VenueBlackout(venue_id="v1", start_date=date(2025, 3, 15), end_date=date(2025, 3, 20))
        ])
        result = validate_schedule(games, c, teams)
        assert result["status"] == "RED"
        types = {v["type"] for v in result["violations"]}
        assert "venue_blackout" in types
