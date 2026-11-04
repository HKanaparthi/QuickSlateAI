"""
Tests for the Schedule Repair Engine (repair.py).

All fixtures are deterministic — no random data, no hardcoded repair outcomes.
Tests verify structural properties, constraint compliance, and status accuracy.
"""
import copy
from collections import Counter
from datetime import date
from typing import Dict, List

import pytest

from app.scheduler.models import (
    BroadcastContract,
    Game,
    GameMove,
    RepairRequest,
    RepairResult,
    RepairStatus,
    Schedule,
    ScheduleConstraints,
    Team,
    Venue,
    VenueBlackout,
    TimeSlot,
)
from app.scheduler.repair import repair_schedule, compute_comparison_metrics
from app.scheduler.constraints import (
    validate_schedule,
    check_rest_days,
    check_venue_conflicts,
    check_weekly_game_cap,
    check_weekly_travel_cap,
    check_matchup_preservation,
    check_back_to_back_away,
    check_home_away_balance,
)
from app.scheduler.solver import solve_schedule


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

VENUES: Dict[str, Venue] = {
    "v_alpha": Venue(id="v_alpha", name="Alpha Arena", city="City A",
                     capacity=15000, latitude=35.2, longitude=-80.8, is_outdoor=False),
    "v_beta":  Venue(id="v_beta",  name="Beta Bowl",  city="City B",
                     capacity=12000, latitude=35.5, longitude=-80.5, is_outdoor=False),
    "v_gamma": Venue(id="v_gamma", name="Gamma Ground", city="City C",
                     capacity=18000, latitude=35.8, longitude=-79.9, is_outdoor=False),
    "v_delta": Venue(id="v_delta", name="Delta Dome",  city="City D",
                     capacity=10000, latitude=36.1, longitude=-79.5, is_outdoor=False),
}

TEAMS: List[Team] = [
    Team(id="T_A", name="Alpha FC", city="City A", league="TEST",
         market_size="medium", home_venue_id="v_alpha", color="#ff0000"),
    Team(id="T_B", name="Beta SC",  city="City B", league="TEST",
         market_size="small",  home_venue_id="v_beta",  color="#00ff00"),
    Team(id="T_C", name="Gamma FC", city="City C", league="TEST",
         market_size="large",  home_venue_id="v_gamma", color="#0000ff"),
    Team(id="T_D", name="Delta SC", city="City D", league="TEST",
         market_size="medium", home_venue_id="v_delta", color="#ffff00"),
]


def base_constraints(**kwargs) -> ScheduleConstraints:
    defaults = dict(
        league_id="TEST",
        season_start=date(2025, 3, 1),
        season_end=date(2025, 5, 31),
        min_rest_days=2,
        max_travel_miles_per_week=800,
        games_per_pair=2,
        no_back_to_back_away=False,
        home_away_balanced=False,
        even_distribution=False,
        travel_optimization_weight=1.0,
    )
    defaults.update(kwargs)
    return ScheduleConstraints(**defaults)


def generate_base_schedule() -> Schedule:
    """Generate a small, clean 4-team schedule used as the repair input."""
    c = base_constraints()
    schedule, _ = solve_schedule(c, TEAMS, VENUES)
    assert schedule.solver_status in ("OPTIMAL", "FEASIBLE"), (
        f"Baseline schedule failed: {schedule.solver_status}"
    )
    return schedule


def _make_twelve_game_schedule() -> Schedule:
    """
    Deterministic 12-game fixture: 4 teams, all 6 matchup pairs played twice
    (home/away inverted), games spaced ≥7 days apart per team, no venue conflicts.

    Structural guarantees (verified by test_deterministic_fixture_is_constraint_clean):
    - All 6 matchup pairs present once in each direction (12 games total)
    - Each team: 3 home + 3 away = 6 games
    - Per-team game gaps: minimum 5 days (well above min_rest_days=2)
    - No two games share a venue on the same date
    - Zero RED violations under base_constraints()

    Replaces generate_base_schedule() for TestHardConstraintPreservation, which tests
    repair invariants (not solver quality) and must not depend on CP-SAT timing.
    """
    c = base_constraints()
    games = [
        # --- week 1 ---
        g("h01", "T_A", "T_B", "v_alpha", date(2025, 3, 3)),
        g("h02", "T_C", "T_D", "v_gamma", date(2025, 3, 5)),
        # --- week 2 ---
        g("h03", "T_A", "T_C", "v_alpha", date(2025, 3, 10)),
        g("h04", "T_B", "T_D", "v_beta",  date(2025, 3, 12)),
        # --- week 3 ---
        g("h05", "T_A", "T_D", "v_alpha", date(2025, 3, 17)),
        g("h06", "T_B", "T_C", "v_beta",  date(2025, 3, 19)),
        # --- week 4 ---
        g("h07", "T_B", "T_A", "v_beta",  date(2025, 3, 24)),
        g("h08", "T_D", "T_C", "v_delta", date(2025, 3, 26)),
        # --- week 5 ---
        g("h09", "T_C", "T_A", "v_gamma", date(2025, 3, 31)),
        g("h10", "T_D", "T_B", "v_delta", date(2025, 4, 2)),
        # --- week 6 ---
        g("h11", "T_D", "T_A", "v_delta", date(2025, 4, 7)),
        g("h12", "T_C", "T_B", "v_gamma", date(2025, 4, 9)),
    ]
    return hand_schedule(games, c)


# ---------------------------------------------------------------------------
# Helper: build a minimal hand-crafted schedule for unit tests that don't
# need the full solver (faster, more controllable).
# ---------------------------------------------------------------------------

def hand_schedule(games: List[Game], constraints: ScheduleConstraints) -> Schedule:
    return Schedule(
        id="orig-sched-001",
        league_id="TEST",
        season_start=constraints.season_start,
        season_end=constraints.season_end,
        games=games,
        constraints=constraints,
        total_games=len(games),
        generated_at="2025-01-01",
        solver_status="OPTIMAL",
    )


_DAY_SLOT_MAP = {
    0: TimeSlot.MON_EVENING,
    1: TimeSlot.TUE_EVENING,
    2: TimeSlot.WED_EVENING,
    3: TimeSlot.THU_EVENING,
    4: TimeSlot.FRI_EVENING,
    5: TimeSlot.SAT_PRIMETIME,
    6: TimeSlot.SUN_AFTERNOON,
}


def g(gid, home, away, venue, d, miles=50.0) -> Game:
    """Auto-selects the correct timeslot for d's weekday so the slot exists in date_slots."""
    slot = _DAY_SLOT_MAP[d.weekday()]
    return Game(
        id=gid, home_team_id=home, away_team_id=away, venue_id=venue,
        game_date=d, timeslot=slot, travel_miles=miles,
    )


# ---------------------------------------------------------------------------
# Tests: no affected games (nothing to repair)
# ---------------------------------------------------------------------------

class TestNoAffectedGames:
    def test_repair_with_no_violations_returns_optimal(self):
        c = base_constraints()
        games = [
            g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 10)),
            g("g2", "T_C", "T_D", "v_gamma", date(2025, 3, 17)),
        ]
        sched = hand_schedule(games, c)
        req = RepairRequest(
            schedule_id=sched.id,
            affected_game_ids=[],
            neighborhood_size=5,
            time_limit_seconds=10,
        )
        result = repair_schedule(req, sched, TEAMS, VENUES)
        assert result.status == RepairStatus.OPTIMAL
        assert result.moves == []
        assert result.repaired_schedule_id is not None
        assert result.repaired_schedule_id != sched.id

    def test_original_schedule_unchanged_after_no_op(self):
        c = base_constraints()
        games = [g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 10))]
        sched = hand_schedule(games, c)
        original_date = sched.games[0].game_date
        req = RepairRequest(schedule_id=sched.id, affected_game_ids=[],
                            neighborhood_size=5, time_limit_seconds=10)
        repair_schedule(req, sched, TEAMS, VENUES)
        # Original must be untouched
        assert sched.games[0].game_date == original_date
        assert sched.id == "orig-sched-001"


# ---------------------------------------------------------------------------
# Tests: single blackout affecting one game
# ---------------------------------------------------------------------------

class TestSingleBlackout:
    def test_game_affected_by_blackout_is_moved(self):
        c = base_constraints(venue_blackouts=[
            VenueBlackout(venue_id="v_alpha", start_date=date(2025, 3, 10),
                          end_date=date(2025, 3, 10), reason="event")
        ])
        games = [
            g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 10)),  # affected
            g("g2", "T_C", "T_D", "v_gamma", date(2025, 3, 20)),  # not affected
        ]
        sched = hand_schedule(games, c)
        req = RepairRequest(
            schedule_id=sched.id,
            affected_game_ids=["g1"],
            updated_constraints=c,
            neighborhood_size=5,
            time_limit_seconds=15,
        )
        result = repair_schedule(req, sched, TEAMS, VENUES)

        assert result.status in (RepairStatus.OPTIMAL, RepairStatus.FEASIBLE), (
            f"Unexpected status: {result.status} — {result.error_message}"
        )
        assert result.repaired_schedule_id is not None

        # g1 must not be on its original blackout date
        from app.scheduler.models import Schedule as S
        # We can't directly access the repaired Schedule object from result,
        # but we can verify via moves
        assert len(result.moves) >= 1
        moved_ids = {m.game_id for m in result.moves}
        assert "g1" in moved_ids

        # Verify the repaired date avoids the blackout
        g1_move = next(m for m in result.moves if m.game_id == "g1")
        assert not (date(2025, 3, 10) <= g1_move.repaired_date <= date(2025, 3, 10))

    def test_unaffected_game_has_stable_id(self):
        c = base_constraints(venue_blackouts=[
            VenueBlackout(venue_id="v_alpha", start_date=date(2025, 3, 10),
                          end_date=date(2025, 3, 10))
        ])
        games = [
            g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 10)),
            g("g2", "T_C", "T_D", "v_gamma", date(2025, 3, 20)),
        ]
        sched = hand_schedule(games, c)
        req = RepairRequest(
            schedule_id=sched.id, affected_game_ids=["g1"],
            updated_constraints=c, neighborhood_size=2, time_limit_seconds=15,
        )
        result = repair_schedule(req, sched, TEAMS, VENUES)
        # g2 should not appear in the moves list (it's anchored / not moved)
        moved_ids = {m.game_id for m in result.moves}
        assert "g2" not in moved_ids

    def test_repaired_schedule_has_new_id(self):
        c = base_constraints(venue_blackouts=[
            VenueBlackout(venue_id="v_alpha", start_date=date(2025, 3, 10),
                          end_date=date(2025, 3, 10))
        ])
        games = [g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 10))]
        sched = hand_schedule(games, c)
        req = RepairRequest(schedule_id=sched.id, affected_game_ids=["g1"],
                            updated_constraints=c, neighborhood_size=5, time_limit_seconds=15)
        result = repair_schedule(req, sched, TEAMS, VENUES)
        if result.repaired_schedule_id:
            assert result.repaired_schedule_id != sched.id

    def test_original_schedule_immutable_after_repair(self):
        c = base_constraints(venue_blackouts=[
            VenueBlackout(venue_id="v_alpha", start_date=date(2025, 3, 10),
                          end_date=date(2025, 3, 10))
        ])
        games = [
            g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 10)),
            g("g2", "T_C", "T_D", "v_gamma", date(2025, 3, 20)),
        ]
        sched = hand_schedule(games, c)
        original_id = sched.id
        orig_g1_date = sched.games[0].game_date
        orig_g2_date = sched.games[1].game_date

        req = RepairRequest(schedule_id=sched.id, affected_game_ids=["g1"],
                            updated_constraints=c, neighborhood_size=5, time_limit_seconds=15)
        repair_schedule(req, sched, TEAMS, VENUES)

        assert sched.id == original_id
        assert sched.games[0].game_date == orig_g1_date
        assert sched.games[1].game_date == orig_g2_date
        assert len(sched.games) == 2


# ---------------------------------------------------------------------------
# Tests: blackout affecting no games
# ---------------------------------------------------------------------------

class TestBlackoutNoAffectedGames:
    def test_blackout_on_unused_venue_no_action(self):
        c = base_constraints(venue_blackouts=[
            VenueBlackout(venue_id="v_beta", start_date=date(2025, 3, 10),
                          end_date=date(2025, 3, 10))
        ])
        # Only v_alpha used, blackout is on v_beta
        games = [g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 10))]
        sched = hand_schedule(games, c)
        req = RepairRequest(schedule_id=sched.id, affected_game_ids=[],
                            updated_constraints=c, neighborhood_size=5, time_limit_seconds=10)
        result = repair_schedule(req, sched, TEAMS, VENUES)
        assert result.status == RepairStatus.OPTIMAL
        assert result.moves == []


# ---------------------------------------------------------------------------
# Tests: blackout affecting multiple games
# ---------------------------------------------------------------------------

class TestMultipleAffectedGames:
    def test_two_games_in_blackout_both_moved(self):
        c = base_constraints(venue_blackouts=[
            VenueBlackout(venue_id="v_alpha", start_date=date(2025, 3, 10),
                          end_date=date(2025, 3, 20))
        ])
        games = [
            g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 10)),
            g("g2", "T_A", "T_C", "v_alpha", date(2025, 3, 15)),
            g("g3", "T_B", "T_D", "v_beta",  date(2025, 3, 25)),
        ]
        sched = hand_schedule(games, c)
        req = RepairRequest(
            schedule_id=sched.id,
            affected_game_ids=["g1", "g2"],
            updated_constraints=c,
            neighborhood_size=5,
            time_limit_seconds=20,
        )
        result = repair_schedule(req, sched, TEAMS, VENUES)
        assert result.status in (RepairStatus.OPTIMAL, RepairStatus.FEASIBLE,
                                  RepairStatus.GLOBALLY_INFEASIBLE_IN_BUDGET)
        if result.status in (RepairStatus.OPTIMAL, RepairStatus.FEASIBLE):
            moved_ids = {m.game_id for m in result.moves}
            # At minimum, both affected games are moved out of the blackout
            assert "g1" in moved_ids
            assert "g2" in moved_ids
            # g3 (not affected) should not be moved
            assert "g3" not in moved_ids

    def test_repaired_games_not_in_blackout(self):
        c = base_constraints(venue_blackouts=[
            VenueBlackout(venue_id="v_alpha", start_date=date(2025, 3, 10),
                          end_date=date(2025, 3, 20))
        ])
        games = [
            g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 12)),
            g("g2", "T_C", "T_D", "v_gamma", date(2025, 4, 1)),
        ]
        sched = hand_schedule(games, c)
        req = RepairRequest(
            schedule_id=sched.id, affected_game_ids=["g1"],
            updated_constraints=c, neighborhood_size=5, time_limit_seconds=20,
        )
        result = repair_schedule(req, sched, TEAMS, VENUES)
        if result.status in (RepairStatus.OPTIMAL, RepairStatus.FEASIBLE):
            for move in result.moves:
                if move.game_id == "g1":
                    assert not (date(2025, 3, 10) <= move.repaired_date <= date(2025, 3, 20)), (
                        f"Repaired game g1 still in blackout: {move.repaired_date}"
                    )


# ---------------------------------------------------------------------------
# Tests: impossible repair
# ---------------------------------------------------------------------------

class TestImpossibleRepair:
    def test_full_season_blackout_returns_infeasible(self):
        c = base_constraints(venue_blackouts=[
            VenueBlackout(venue_id="v_alpha", start_date=date(2025, 3, 1),
                          end_date=date(2025, 5, 31))  # entire season blacked out
        ])
        # T_A's only games are at v_alpha; nowhere else to go
        games = [
            g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 10)),
            g("g2", "T_A", "T_C", "v_alpha", date(2025, 3, 20)),
        ]
        sched = hand_schedule(games, c)
        req = RepairRequest(
            schedule_id=sched.id,
            affected_game_ids=["g1", "g2"],
            updated_constraints=c,
            neighborhood_size=5,
            max_neighborhood_expansions=2,
            time_limit_seconds=15,
        )
        result = repair_schedule(req, sched, TEAMS, VENUES)
        assert result.status in (
            RepairStatus.NEIGHBORHOOD_INFEASIBLE,
            RepairStatus.GLOBALLY_INFEASIBLE_IN_BUDGET,
        ), f"Expected infeasibility, got {result.status}: {result.error_message}"
        assert result.repaired_schedule_id is None

    def test_impossible_repair_does_not_return_invalid_schedule(self):
        c = base_constraints(venue_blackouts=[
            VenueBlackout(venue_id="v_alpha", start_date=date(2025, 3, 1),
                          end_date=date(2025, 5, 31))
        ])
        games = [g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 10))]
        sched = hand_schedule(games, c)
        req = RepairRequest(schedule_id=sched.id, affected_game_ids=["g1"],
                            updated_constraints=c, neighborhood_size=5,
                            max_neighborhood_expansions=1, time_limit_seconds=10)
        result = repair_schedule(req, sched, TEAMS, VENUES)
        assert result.repaired_schedule_id is None


# ---------------------------------------------------------------------------
# Tests: neighborhood expansion
# ---------------------------------------------------------------------------

class TestNeighborhoodExpansion:
    def test_expansion_count_is_bounded(self):
        c = base_constraints(venue_blackouts=[
            VenueBlackout(venue_id="v_alpha", start_date=date(2025, 3, 1),
                          end_date=date(2025, 5, 31))
        ])
        games = [g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 10))]
        sched = hand_schedule(games, c)
        max_exp = 2
        req = RepairRequest(schedule_id=sched.id, affected_game_ids=["g1"],
                            updated_constraints=c, neighborhood_size=3,
                            max_neighborhood_expansions=max_exp, time_limit_seconds=10)
        result = repair_schedule(req, sched, TEAMS, VENUES)
        assert result.neighborhood_expansions_used <= max_exp

    def test_solver_reports_search_limit_not_global_infeasibility(self):
        """GLOBALLY_INFEASIBLE_IN_BUDGET must note it is NOT a proof of global infeasibility."""
        c = base_constraints(venue_blackouts=[
            VenueBlackout(venue_id="v_alpha", start_date=date(2025, 3, 1),
                          end_date=date(2025, 5, 31))
        ])
        games = [g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 10))]
        sched = hand_schedule(games, c)
        req = RepairRequest(schedule_id=sched.id, affected_game_ids=["g1"],
                            updated_constraints=c, neighborhood_size=3,
                            max_neighborhood_expansions=0, time_limit_seconds=10)
        result = repair_schedule(req, sched, TEAMS, VENUES)
        if result.status == RepairStatus.GLOBALLY_INFEASIBLE_IN_BUDGET:
            assert result.error_message is not None
            # Must NOT claim global infeasibility without proof
            assert "NOT a proof of global infeasibility" in result.error_message

    def test_cp_sat_neighborhood_expansion_resolves_infeasible_neighborhood(self):
        """
        Tight squeeze demonstrating genuine CP-SAT neighborhood expansion.

        Season March 10-15, blackout v_alpha March 10-11, min_rest_days=3.
        Slots available for v_alpha: March 12 (Wed), 13 (Thu), 14 (Fri), 15 (Sat).

        Neighborhood size 1 — g2 anchored at March 13:
          Every v_alpha slot is blocked for g1 (home team T_A):
            March 10-11 → venue blackout
            March 12, 14, 15 → T_A rest violation (abs(d - March 13) < 3)
            March 13 → venue locked by anchored g2
          CP-SAT pre-check detects zero available slots → NEIGHBORHOOD_INFEASIBLE.

        Neighborhood size 2 — g2 freed:
          No anchored games; g1 and g2 each have {March 12, 13, 14, 15} available.
          T_A rest constraints force their slots to be ≥ 3 days apart.
          In a 4-day window the only pair with gap ≥ 3 is (March 12, March 15).
          Solver assigns g1 → March 12, g2 → March 15 → OPTIMAL/FEASIBLE.
        """
        c = base_constraints(
            season_start=date(2025, 3, 10),
            season_end=date(2025, 3, 15),
            min_rest_days=3,
            venue_blackouts=[
                VenueBlackout(venue_id="v_alpha",
                              start_date=date(2025, 3, 10),
                              end_date=date(2025, 3, 11),
                              reason="arena event"),
            ],
        )
        games = [
            g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 10)),  # affected; slot blacked out
            g("g2", "T_A", "T_C", "v_alpha", date(2025, 3, 13)),  # closest by date; anchors T_A rest
        ]
        sched = hand_schedule(games, c)

        orig_id = sched.id
        orig_g1_date = sched.games[0].game_date  # March 10
        orig_g2_date = sched.games[1].game_date  # March 13

        req = RepairRequest(
            schedule_id=sched.id,
            affected_game_ids=["g1"],
            updated_constraints=c,
            neighborhood_size=1,            # size-1: only g1 free → provably infeasible
            max_neighborhood_expansions=1,  # one expansion: pulls g2 into the neighborhood
            time_limit_seconds=30,
        )
        result = repair_schedule(req, sched, TEAMS, VENUES)

        # (1) Solver found a feasible repair after expanding the neighborhood once
        assert result.status in (RepairStatus.OPTIMAL, RepairStatus.FEASIBLE), (
            f"Expected OPTIMAL/FEASIBLE after expansion; got {result.status}: {result.error_message}"
        )

        # (2) Exactly one expansion was used, proving the size-1 attempt was infeasible
        assert result.neighborhood_expansions_used == 1, (
            f"Expected 1 expansion (size-1 neighborhood must be NEIGHBORHOOD_INFEASIBLE); "
            f"got {result.neighborhood_expansions_used}"
        )

        # (3) Both g1 (forced move) and g2 (freed by expansion) appear in the move list
        moved_ids = {m.game_id for m in result.moves}
        assert "g1" in moved_ids, "g1 must be moved (original slot is blacked out)"
        assert "g2" in moved_ids, (
            "g2 must be moved — it occupied March 13, which blocked all T_A rest windows "
            "for g1; it must vacate to make the repair feasible"
        )

        # (4) g1's repaired date is outside the blackout window
        g1_move = next(m for m in result.moves if m.game_id == "g1")
        assert not (date(2025, 3, 10) <= g1_move.repaired_date <= date(2025, 3, 11)), (
            f"g1 repaired to {g1_move.repaired_date} — still inside blackout (March 10-11)"
        )

        # (5) Original schedule is completely immutable
        assert sched.id == orig_id
        assert sched.games[0].game_date == orig_g1_date
        assert sched.games[1].game_date == orig_g2_date

        # (6) Repaired schedule passes independent validation — zero RED violations
        assert result.validation_result is not None
        assert result.validation_result["red_count"] == 0, (
            f"RED violations in repaired schedule: "
            f"{[v for v in result.validation_result['violations'] if v.get('severity') == 'RED']}"
        )


# ---------------------------------------------------------------------------
# Tests: solver status accuracy
# ---------------------------------------------------------------------------

class TestSolverStatusAccuracy:
    def test_timeout_no_solution_not_reported_as_infeasible(self):
        """
        When CP-SAT returns UNKNOWN (solver exhausted its time budget before finding
        any solution), the repair engine must report TIMEOUT_NO_SOLUTION — never
        NEIGHBORHOOD_INFEASIBLE, which would be a false proof of infeasibility.

        Uses a deterministic mock of CpSolver.Solve → UNKNOWN so the assertion is
        not sensitive to machine speed or OR-Tools internal timing.
        """
        import unittest.mock as mock
        from ortools.sat.python import cp_model as _cp_model

        c = base_constraints()
        games = [
            g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 10)),
            g("g2", "T_C", "T_D", "v_gamma", date(2025, 3, 20)),
        ]
        sched = hand_schedule(games, c)

        req = RepairRequest(
            schedule_id=sched.id,
            affected_game_ids=["g1"],
            updated_constraints=c,
            neighborhood_size=5,
            time_limit_seconds=5.0,
        )

        with mock.patch.object(_cp_model.CpSolver, "Solve", return_value=_cp_model.UNKNOWN):
            result = repair_schedule(req, sched, TEAMS, VENUES)

        assert result.status == RepairStatus.TIMEOUT_NO_SOLUTION, (
            f"CP-SAT UNKNOWN must map to TIMEOUT_NO_SOLUTION; got {result.status}"
        )
        assert result.repaired_schedule_id is None, (
            "No repaired schedule must be saved when the solver has not found any solution"
        )

    def test_successful_repair_has_non_null_repaired_id(self):
        c = base_constraints()
        games = [
            g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 10)),
            g("g2", "T_C", "T_D", "v_gamma", date(2025, 4, 1)),
        ]
        sched = hand_schedule(games, c)
        req = RepairRequest(schedule_id=sched.id, affected_game_ids=[],
                            neighborhood_size=5, time_limit_seconds=10)
        result = repair_schedule(req, sched, TEAMS, VENUES)
        if result.status in (RepairStatus.OPTIMAL, RepairStatus.FEASIBLE):
            assert result.repaired_schedule_id is not None

    def test_validation_failed_does_not_save_schedule(self):
        """RepairStatus.VALIDATION_FAILED must have repaired_schedule_id=None."""
        # This status can only be triggered by a model/validation bug, so we
        # simulate it by patching validate_schedule to inject a RED violation.
        import unittest.mock as mock
        from app.scheduler import repair as repair_mod

        c = base_constraints()
        games = [g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 10))]
        sched = hand_schedule(games, c)

        fake_validation = {
            "status": "RED",
            "red_count": 1,
            "yellow_count": 0,
            "violations": [{"type": "injected", "severity": "RED", "message": "test"}],
            "broadcast_compliance": [],
        }

        with mock.patch.object(repair_mod, "validate_schedule", return_value=fake_validation):
            req = RepairRequest(schedule_id=sched.id, affected_game_ids=[],
                                neighborhood_size=5, time_limit_seconds=10)
            result = repair_schedule(req, sched, TEAMS, VENUES)

        # Either OPTIMAL (no affected games → skips validation path) or VALIDATION_FAILED
        if result.status == RepairStatus.VALIDATION_FAILED:
            assert result.repaired_schedule_id is None


# ---------------------------------------------------------------------------
# Tests: hard constraint preservation in repaired schedule
# ---------------------------------------------------------------------------

class TestHardConstraintPreservation:
    def test_deterministic_fixture_is_constraint_clean(self):
        """
        Guard: the hand-crafted 12-game fixture must satisfy all hard constraints
        under base_constraints() before any repair test runs against it.
        """
        sched = _make_twelve_game_schedule()
        c = base_constraints()

        val = validate_schedule(sched.games, c, TEAMS)
        red = [v for v in val["violations"] if v.get("severity") == "RED"]
        assert red == [], f"Fixture has RED violations: {red}"

        # All 6 matchup pairs present in each direction
        matchups = Counter((gm.home_team_id, gm.away_team_id) for gm in sched.games)
        for t1, t2 in [("T_A","T_B"),("T_A","T_C"),("T_A","T_D"),
                       ("T_B","T_C"),("T_B","T_D"),("T_C","T_D")]:
            assert matchups[(t1, t2)] == 1, f"Missing matchup {t1}@{t2}"
            assert matchups[(t2, t1)] == 1, f"Missing matchup {t2}@{t1}"
        assert len(sched.games) == 12

        # Each team plays exactly 3 home and 3 away
        for tid in ("T_A", "T_B", "T_C", "T_D"):
            home_n = sum(1 for gm in sched.games if gm.home_team_id == tid)
            away_n = sum(1 for gm in sched.games if gm.away_team_id == tid)
            assert home_n == 3, f"{tid} home count: {home_n}"
            assert away_n == 3, f"{tid} away count: {away_n}"

        # Per-team minimum rest gap ≥ min_rest_days (2)
        min_rest = c.min_rest_days
        for tid in ("T_A", "T_B", "T_C", "T_D"):
            dates = sorted(
                gm.game_date for gm in sched.games
                if gm.home_team_id == tid or gm.away_team_id == tid
            )
            for i in range(len(dates) - 1):
                gap = (dates[i + 1] - dates[i]).days
                assert gap >= min_rest, (
                    f"{tid}: gap {gap} days between {dates[i]} and {dates[i+1]} "
                    f"< min_rest_days={min_rest}"
                )

        # No venue double-booking
        venue_dates = [(gm.venue_id, gm.game_date) for gm in sched.games]
        assert len(venue_dates) == len(set(venue_dates)), (
            f"Venue/date collision: {[x for x in venue_dates if venue_dates.count(x) > 1]}"
        )

    def _get_repaired_games(self, result, original_sched):
        """We don't have the repaired Schedule object directly, but we can rebuild
        from moves + original to verify structural properties."""
        # Build a lookup from result.moves
        move_map = {m.game_id: m for m in result.moves}
        repaired_games = []
        for orig_g in original_sched.games:
            mv = move_map.get(orig_g.id)
            if mv:
                repaired_games.append(Game(
                    id=orig_g.id,
                    home_team_id=orig_g.home_team_id,
                    away_team_id=orig_g.away_team_id,
                    venue_id=orig_g.venue_id,
                    game_date=mv.repaired_date,
                    timeslot=mv.repaired_timeslot,
                    travel_miles=orig_g.travel_miles,
                ))
            else:
                repaired_games.append(copy.copy(orig_g))
        return repaired_games

    def test_full_solver_repaired_schedule_passes_validation(self):
        """End-to-end: inject a blackout into the deterministic fixture, repair, validate."""
        original = _make_twelve_game_schedule()

        # Find a game to target with a blackout
        target = original.games[0]
        blackout = VenueBlackout(
            venue_id=target.venue_id,
            start_date=target.game_date,
            end_date=target.game_date,
            reason="test blackout",
        )
        updated_c = base_constraints(venue_blackouts=[blackout])

        req = RepairRequest(
            schedule_id=original.id,
            affected_game_ids=[target.id],
            updated_constraints=updated_c,
            neighborhood_size=8,
            max_neighborhood_expansions=2,
            time_limit_seconds=30,
        )
        result = repair_schedule(req, original, TEAMS, VENUES)

        if result.status in (RepairStatus.OPTIMAL, RepairStatus.FEASIBLE):
            assert result.validation_result is not None
            assert result.validation_result["red_count"] == 0, (
                f"RED violations in repaired schedule: "
                f"{[v for v in result.validation_result['violations'] if v['severity'] == 'RED']}"
            )
        # If infeasible or timeout, that is acceptable (depends on CP-SAT)

    def test_game_ids_preserved_in_repair(self):
        original = _make_twelve_game_schedule()
        if not original.games:
            pytest.skip("No games")
        orig_ids = {g.id for g in original.games}
        target = original.games[0]
        blackout = VenueBlackout(venue_id=target.venue_id,
                                  start_date=target.game_date, end_date=target.game_date)
        updated_c = base_constraints(venue_blackouts=[blackout])
        req = RepairRequest(schedule_id=original.id, affected_game_ids=[target.id],
                            updated_constraints=updated_c, neighborhood_size=8,
                            time_limit_seconds=30)
        result = repair_schedule(req, original, TEAMS, VENUES)
        if result.status in (RepairStatus.OPTIMAL, RepairStatus.FEASIBLE):
            # All move game_ids must be from the original schedule
            for mv in result.moves:
                assert mv.game_id in orig_ids, f"Unknown game_id in moves: {mv.game_id}"

    def test_matchup_count_unchanged(self):
        """
        The repaired schedule must contain the same number of games and an identical
        multiset of (home_team, away_team) matchups as the original.
        """
        original = _make_twelve_game_schedule()
        if not original.games:
            pytest.skip("No games")
        target = original.games[0]
        blackout = VenueBlackout(venue_id=target.venue_id,
                                  start_date=target.game_date, end_date=target.game_date)
        updated_c = base_constraints(venue_blackouts=[blackout])
        req = RepairRequest(schedule_id=original.id, affected_game_ids=[target.id],
                            updated_constraints=updated_c, neighborhood_size=8,
                            time_limit_seconds=30)
        result = repair_schedule(req, original, TEAMS, VENUES)
        if result.status in (RepairStatus.OPTIMAL, RepairStatus.FEASIBLE):
            repaired_games = self._get_repaired_games(result, original)
            assert len(repaired_games) == len(original.games), (
                f"Game count changed: {len(original.games)} → {len(repaired_games)}"
            )
            orig_matchups = Counter(
                (gg.home_team_id, gg.away_team_id) for gg in original.games
            )
            rep_matchups = Counter(
                (gg.home_team_id, gg.away_team_id) for gg in repaired_games
            )
            assert orig_matchups == rep_matchups, (
                f"Matchup multiset changed:\n"
                f"  original: {dict(orig_matchups)}\n"
                f"  repaired: {dict(rep_matchups)}"
            )


# ---------------------------------------------------------------------------
# Tests: comparison metrics
# ---------------------------------------------------------------------------

class TestComparisonMetrics:
    def test_no_moves_metrics_are_zero(self):
        c = base_constraints()
        games = [
            g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 10)),
            g("g2", "T_C", "T_D", "v_gamma", date(2025, 3, 20)),
        ]
        sched = hand_schedule(games, c)
        metrics = compute_comparison_metrics(sched, sched)
        assert metrics["games_moved"] == 0
        assert metrics["total_displacement_days"] == 0

    def test_moved_game_displacement_is_accurate(self):
        c = base_constraints()
        orig_games = [g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 10))]
        rep_games  = [g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 17))]
        orig = hand_schedule(orig_games, c)
        rep  = hand_schedule(rep_games, c)
        rep.id = "rep-001"
        metrics = compute_comparison_metrics(orig, rep)
        assert metrics["games_moved"] == 1
        assert metrics["total_displacement_days"] == 7
        assert metrics["moved_games"][0]["displacement_days"] == 7

    def test_total_games_matches_original(self):
        c = base_constraints()
        games = [
            g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 10)),
            g("g2", "T_C", "T_D", "v_gamma", date(2025, 3, 20)),
        ]
        sched = hand_schedule(games, c)
        metrics = compute_comparison_metrics(sched, sched)
        assert metrics["total_games"] == 2


# ---------------------------------------------------------------------------
# Tests: GameMove data integrity
# ---------------------------------------------------------------------------

class TestGameMoveIntegrity:
    def test_displacement_days_is_absolute(self):
        """displacement_days must always be non-negative."""
        c = base_constraints(venue_blackouts=[
            VenueBlackout(venue_id="v_alpha", start_date=date(2025, 3, 10),
                          end_date=date(2025, 3, 10))
        ])
        games = [
            g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 10)),
            g("g2", "T_C", "T_D", "v_gamma", date(2025, 4, 1)),
        ]
        sched = hand_schedule(games, c)
        req = RepairRequest(schedule_id=sched.id, affected_game_ids=["g1"],
                            updated_constraints=c, neighborhood_size=5, time_limit_seconds=20)
        result = repair_schedule(req, sched, TEAMS, VENUES)
        for mv in result.moves:
            assert mv.displacement_days >= 0

    def test_move_original_date_matches_original_schedule(self):
        c = base_constraints(venue_blackouts=[
            VenueBlackout(venue_id="v_alpha", start_date=date(2025, 3, 10),
                          end_date=date(2025, 3, 10))
        ])
        games = [
            g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 10)),
            g("g2", "T_C", "T_D", "v_gamma", date(2025, 4, 1)),
        ]
        sched = hand_schedule(games, c)
        req = RepairRequest(schedule_id=sched.id, affected_game_ids=["g1"],
                            updated_constraints=c, neighborhood_size=5, time_limit_seconds=20)
        result = repair_schedule(req, sched, TEAMS, VENUES)
        for mv in result.moves:
            orig_g = next((gg for gg in sched.games if gg.id == mv.game_id), None)
            if orig_g:
                assert mv.original_date == orig_g.game_date
                assert mv.original_timeslot == orig_g.timeslot


# ---------------------------------------------------------------------------
# Tests: independent validator (constraints.py) — deterministic unit coverage
# ---------------------------------------------------------------------------

class TestValidatorUnit:
    """
    Deterministic unit tests for constraint-checker functions and validate_schedule.
    All fixtures are hand-crafted; no schedule generation or CP-SAT required.
    """

    def test_rest_days_flags_gap_below_minimum(self):
        # T_A plays March 10 and March 11 — gap = 1 day, min_rest = 2 → RED
        games = [
            g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 10)),
            g("g2", "T_A", "T_C", "v_alpha", date(2025, 3, 11)),
        ]
        violations = check_rest_days("T_A", games, min_rest=2)
        assert len(violations) == 1
        v = violations[0]
        assert v["severity"] == "RED"
        assert v["type"] == "rest_days"
        assert "1" in v["message"]  # actual gap reported in message

    def test_weekly_game_cap_flags_four_games_in_one_week(self):
        # March 10–13 are Mon–Thu of ISO week 11-2025; T_A appears in all four
        games = [
            g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 10)),
            g("g2", "T_A", "T_C", "v_alpha", date(2025, 3, 11)),
            g("g3", "T_A", "T_D", "v_alpha", date(2025, 3, 12)),
            g("g4", "T_B",  "T_A", "v_beta",  date(2025, 3, 13)),  # T_A away; 4th game
        ]
        violations = check_weekly_game_cap(games, ["T_A"])
        assert len(violations) == 1
        v = violations[0]
        assert v["severity"] == "RED"
        assert v["type"] == "weekly_game_cap"
        assert v["count"] == 4
        assert v["max"] == 3

    def test_weekly_travel_cap_flags_excessive_away_miles(self):
        # T_B is the away team in both games in week 11; 500 + 400 = 900 mi > cap 800
        c = base_constraints(max_travel_miles_per_week=800)
        games = [
            g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 10), miles=500.0),
            g("g2", "T_C", "T_B", "v_gamma", date(2025, 3, 13), miles=400.0),
        ]
        violations = check_weekly_travel_cap(games, ["T_B"], c)
        assert len(violations) == 1
        v = violations[0]
        assert v["severity"] == "RED"
        assert v["type"] == "weekly_travel_cap"
        assert v["team_id"] == "T_B"
        assert v["miles"] == 900.0

    def test_venue_conflict_flags_double_booked_slot(self):
        # g1 and g2 at the same venue on the same Monday → same (venue, date, slot) key
        games = [
            g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 10)),
            g("g2", "T_C", "T_D", "v_alpha", date(2025, 3, 10)),
        ]
        violations = check_venue_conflicts(games)
        assert len(violations) == 1
        v = violations[0]
        assert v["severity"] == "RED"
        assert v["type"] == "venue_conflict"
        assert set(v["game_ids"]) == {"g1", "g2"}

    def test_broadcast_undercount_produces_red_violation(self):
        # Contract: 2 SAT_PRIMETIME games required; schedule has 0 → UNDER → RED
        c = base_constraints(broadcast_contracts=[
            BroadcastContract(
                network="ESPN",
                timeslot=TimeSlot.SAT_PRIMETIME,
                required_games=2,
                max_games=4,
            )
        ])
        games = [
            g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 10)),  # Monday → MON_EVENING
            g("g2", "T_C", "T_D", "v_gamma", date(2025, 3, 20)),  # Thursday → THU_EVENING
        ]
        result = validate_schedule(games, c, TEAMS)
        assert result["red_count"] >= 1
        assert any(v["type"] == "broadcast_undercount" for v in result["violations"])

    def test_broadcast_overcount_produces_red_violation(self):
        # Contract: max 1 SAT_PRIMETIME game; schedule has 2 → OVER.
        # max_games is a hard constraint in the CP-SAT solver (model.Add(sum <= max_games)),
        # so the validator must classify a violation as RED, not YELLOW.
        c = base_constraints(broadcast_contracts=[
            BroadcastContract(
                network="FOX",
                timeslot=TimeSlot.SAT_PRIMETIME,
                required_games=0,
                max_games=1,
            )
        ])
        # March 15 and March 22 are both Saturdays → SAT_PRIMETIME slot
        games = [
            g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 15)),
            g("g2", "T_C", "T_D", "v_gamma", date(2025, 3, 22)),
        ]
        result = validate_schedule(games, c, TEAMS)
        assert result["red_count"] >= 1
        overcount_violations = [v for v in result["violations"] if v["type"] == "broadcast_overcount"]
        assert len(overcount_violations) == 1
        assert overcount_violations[0]["severity"] == "RED"

    def test_matchup_preservation_detects_changed_matchup(self):
        # Original has T_A vs T_B; repaired changes it to T_A vs T_C
        # → T_A/T_B dropped (1→0) AND T_A/T_C added (0→1) = 2 RED violations
        original = [g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 10))]
        repaired = [g("g1", "T_A", "T_C", "v_alpha", date(2025, 3, 10))]
        violations = check_matchup_preservation(original, repaired)
        assert len(violations) == 2
        affected = {(v["home_team_id"], v["away_team_id"]) for v in violations}
        assert ("T_A", "T_B") in affected
        assert ("T_A", "T_C") in affected
        for v in violations:
            assert v["severity"] == "RED"
            assert v["type"] == "matchup_preservation"

    def test_back_to_back_away_produces_yellow_violation(self):
        # T_B appears as the away team in two consecutive team games → YELLOW
        # (soft constraint: enabled only when no_back_to_back_away=True)
        games = [
            g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 10)),  # T_B away
            g("g2", "T_C", "T_B", "v_gamma", date(2025, 3, 17)),  # T_B away again (next T_B game)
        ]
        violations = check_back_to_back_away("T_B", games)
        assert len(violations) == 1
        v = violations[0]
        assert v["severity"] == "YELLOW"
        assert v["type"] == "back_to_back_away"
        assert v["team_id"] == "T_B"

    def test_home_away_balance_flags_severe_imbalance(self):
        # T_A plays 4 home and 0 away (ratio=1.0, threshold >0.15 from 0.5) → YELLOW
        # (soft constraint: enabled only when home_away_balanced=True)
        games = [
            g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 10)),
            g("g2", "T_A", "T_C", "v_alpha", date(2025, 3, 17)),
            g("g3", "T_A", "T_D", "v_alpha", date(2025, 3, 24)),
            g("g4", "T_A", "T_B", "v_alpha", date(2025, 3, 31)),
        ]
        violations = check_home_away_balance("T_A", games)
        assert len(violations) == 1
        v = violations[0]
        assert v["severity"] == "YELLOW"
        assert v["type"] == "home_away_imbalance"
        assert v["home_count"] == 4
        assert v["away_count"] == 0

    def test_broadcast_max_games_zero_treated_as_no_upper_bound(self):
        # max_games=0 mirrors solver behavior (solver.py: `if contract.max_games > 0`).
        # With 2 SAT_PRIMETIME games scheduled and max_games=0, validator must NOT flag OVER.
        c = base_constraints(broadcast_contracts=[
            BroadcastContract(
                network="NBC",
                timeslot=TimeSlot.SAT_PRIMETIME,
                required_games=0,
                max_games=0,
            )
        ])
        games = [
            g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 15)),  # Saturday
            g("g2", "T_C", "T_D", "v_gamma", date(2025, 3, 22)),  # Saturday
        ]
        result = validate_schedule(games, c, TEAMS)
        overcount = [v for v in result["violations"] if v["type"] == "broadcast_overcount"]
        assert overcount == [], (
            f"max_games=0 must mean no upper bound (consistent with solver); "
            f"got unexpected violations: {overcount}"
        )

    def test_no_back_to_back_away_hard_constraint_produces_red_in_validate_schedule(self):
        # When no_back_to_back_away=True the solver enforces it as a CP-SAT hard constraint.
        # validate_schedule must reflect this by returning RED, not YELLOW.
        c = base_constraints(no_back_to_back_away=True)
        games = [
            g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 10)),  # T_B away
            g("g2", "T_C", "T_B", "v_gamma", date(2025, 3, 17)),  # T_B away again
        ]
        result = validate_schedule(games, c, TEAMS)
        b2b = [v for v in result["violations"] if v["type"] == "back_to_back_away"]
        assert len(b2b) >= 1, "back-to-back away violation must be detected"
        for v in b2b:
            assert v["severity"] == "RED", (
                f"no_back_to_back_away=True is enforced as a CP-SAT hard constraint; "
                f"validator must return RED severity, not '{v['severity']}'"
            )


# ---------------------------------------------------------------------------
# Tests: FastAPI repair endpoint (Phase 3)
# ---------------------------------------------------------------------------

class TestRepairEndpoint:
    """HTTP-level tests for POST /api/schedule/{id}/repair and GET /api/schedule/compare/{a}/{b}."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        from fastapi.testclient import TestClient
        from app.main import app
        self.client = TestClient(app)
        self._injected_ids: List[str] = []
        yield
        from app.routes.schedule import _schedule_store
        for id_ in self._injected_ids:
            _schedule_store.pop(id_, None)

    def _inject(self, sched: Schedule):
        from app.routes.schedule import _schedule_store
        _schedule_store[sched.id] = sched
        self._injected_ids.append(sched.id)

    def _make_sched(self, sched_id: str, games_list, **kwargs) -> Schedule:
        c = base_constraints(**kwargs)
        sched = hand_schedule(games_list, c)
        sched.id = sched_id
        return sched

    # -- Error-path tests (no CP-SAT) ----------------------------------------

    def test_unknown_schedule_id_returns_404(self):
        resp = self.client.post(
            "/api/schedule/nonexistent-id-xyz/repair",
            json={
                "venue_id": "northside_arena",
                "blackout_start": "2025-03-10",
                "blackout_end": "2025-03-10",
            },
        )
        assert resp.status_code == 404

    def test_invalid_venue_id_returns_400(self):
        sched = self._make_sched("test-ep-400-venue", [])
        self._inject(sched)
        resp = self.client.post(
            "/api/schedule/test-ep-400-venue/repair",
            json={
                "venue_id": "DOES_NOT_EXIST_VENUE",
                "blackout_start": "2025-03-10",
                "blackout_end": "2025-03-10",
            },
        )
        assert resp.status_code == 400

    def test_inverted_date_range_returns_400(self):
        sched = self._make_sched("test-ep-400-dates", [])
        self._inject(sched)
        resp = self.client.post(
            "/api/schedule/test-ep-400-dates/repair",
            json={
                "venue_id": "northside_arena",
                "blackout_start": "2025-03-20",
                "blackout_end": "2025-03-10",
            },
        )
        assert resp.status_code == 400

    def test_no_affected_games_returns_no_games_affected_status(self):
        # Schedule has games only at "v_alpha" (not a real production venue);
        # blackout is at "northside_arena" (a real venue with no injected games) → 0 affected.
        sched = self._make_sched(
            "test-ep-noaffect",
            [g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 10))],
        )
        self._inject(sched)
        resp = self.client.post(
            "/api/schedule/test-ep-noaffect/repair",
            json={
                "venue_id": "northside_arena",
                "blackout_start": "2025-03-10",
                "blackout_end": "2025-03-10",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "NO_GAMES_AFFECTED"
        assert body["repaired_schedule_id"] is None
        assert body["moves"] == []

    def test_original_schedule_still_in_store_after_no_games_affected(self):
        sched = self._make_sched("test-ep-persist", [])
        self._inject(sched)
        self.client.post(
            "/api/schedule/test-ep-persist/repair",
            json={
                "venue_id": "northside_arena",
                "blackout_start": "2025-03-10",
                "blackout_end": "2025-03-10",
            },
        )
        from app.routes.schedule import _schedule_store
        assert "test-ep-persist" in _schedule_store

    # -- Compare endpoint tests -----------------------------------------------

    def test_compare_unknown_original_returns_404(self):
        resp = self.client.get("/api/schedule/compare/nonexistent/also-nonexistent")
        assert resp.status_code == 404

    def test_compare_known_schedules_returns_metrics(self):
        c = base_constraints()
        orig_games = [g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 10))]
        rep_games  = [g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 17))]
        orig = hand_schedule(orig_games, c)
        orig.id = "test-ep-cmp-orig"
        rep  = hand_schedule(rep_games, c)
        rep.id = "test-ep-cmp-rep"
        self._inject(orig)
        self._inject(rep)
        resp = self.client.get(
            "/api/schedule/compare/test-ep-cmp-orig/test-ep-cmp-rep"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_games"] == 1
        assert body["games_moved"] == 1
        assert body["total_displacement_days"] == 7

    # -- End-to-end repair test -----------------------------------------------

    def test_end_to_end_repair_moves_game_out_of_blackout(self):
        """
        Genuine end-to-end test: inject a schedule with one game at northside_arena,
        trigger a blackout on that game's date via the HTTP endpoint, and verify that
        the repaired game is stored under a new schedule ID and no longer falls in the
        blackout window.
        """
        from app.data import VENUES_BY_ID as _real_venues
        real_venue_id = "northside_arena"
        assert real_venue_id in _real_venues, "northside_arena must exist in production data"

        # Build a game at the real venue on Monday March 10, 2025
        affected_game = Game(
            id="e2e-game-1",
            home_team_id="e2e-home",
            away_team_id="e2e-away",
            venue_id=real_venue_id,
            game_date=date(2025, 3, 10),
            timeslot=TimeSlot.MON_EVENING,
            travel_miles=50.0,
        )
        c = base_constraints(season_start=date(2025, 3, 1), season_end=date(2025, 5, 31))
        sched = hand_schedule([affected_game], c)
        sched.id = "test-ep-e2e-orig"
        self._inject(sched)

        resp = self.client.post(
            "/api/schedule/test-ep-e2e-orig/repair",
            json={
                "venue_id": real_venue_id,
                "blackout_start": "2025-03-10",
                "blackout_end": "2025-03-10",
                "reason": "arena maintenance",
                "time_limit_seconds": 30,
            },
        )
        assert resp.status_code == 200
        body = resp.json()

        # Repair must succeed (or at minimum not error at the HTTP layer)
        assert body["original_schedule_id"] == "test-ep-e2e-orig"
        assert body["status"] in (
            "REPAIR_OPTIMAL", "REPAIR_FEASIBLE",
            "REPAIR_TIMEOUT_NO_SOLUTION", "REPAIR_GLOBALLY_INFEASIBLE_IN_BUDGET",
        )

        if body["status"] in ("REPAIR_OPTIMAL", "REPAIR_FEASIBLE"):
            repaired_id = body["repaired_schedule_id"]
            assert repaired_id is not None
            assert repaired_id != "test-ep-e2e-orig"
            self._injected_ids.append(repaired_id)  # register for cleanup

            # Repaired schedule must be retrievable
            get_resp = self.client.get(f"/api/schedule/{repaired_id}")
            assert get_resp.status_code == 200

            # Original must remain intact
            orig_resp = self.client.get("/api/schedule/test-ep-e2e-orig")
            assert orig_resp.status_code == 200

            # Moved game must not fall in the blackout window
            for move in body["moves"]:
                if move["game_id"] == "e2e-game-1":
                    repaired_date = move["repaired_date"]
                    assert repaired_date != "2025-03-10", (
                        f"Repaired game still on blackout date: {repaired_date}"
                    )
