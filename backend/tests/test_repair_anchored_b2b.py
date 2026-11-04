"""
Regression tests for the anchored-away B2B prohibition fix in repair.py.

Background
----------
The repair engine encodes a carry-forward chain: ``prev_pwa`` (prev-was-away)
threads through each team's game dates chronologically.  For *free* away games
the constraint is ``sum(free_away) + prev_pwa <= 1``; for *anchored* away games
the equivalent constant-argument form is ``model.Add(prev_pwa == 0)``.

The fix adds ``if is_anch_away: model.Add(prev_pwa == 0)`` inside the anchored
branch.  Without it, free home games that originally separated two anchored away
games could be relocated during repair, leaving ``prev_pwa=1`` before the second
anchored away game — a B2B violation the model never caught (only the independent
validator did, returning VALIDATION_FAILED instead of a model infeasibility).
"""
from datetime import date
from typing import Dict, List

from app.scheduler.models import (
    Game,
    RepairRequest,
    RepairStatus,
    Schedule,
    ScheduleConstraints,
    Team,
    Venue,
    VenueBlackout,
    TimeSlot,
)
from app.scheduler.repair import repair_schedule
from app.scheduler.constraints import validate_schedule


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

_DAY_SLOT_MAP = {
    0: TimeSlot.MON_EVENING,
    1: TimeSlot.TUE_EVENING,
    2: TimeSlot.WED_EVENING,
    3: TimeSlot.THU_EVENING,
    4: TimeSlot.FRI_EVENING,
    5: TimeSlot.SAT_PRIMETIME,
    6: TimeSlot.SUN_AFTERNOON,
}


def base_constraints(**kwargs) -> ScheduleConstraints:
    defaults = dict(
        league_id="TEST",
        season_start=date(2025, 3, 1),
        season_end=date(2025, 5, 31),
        min_rest_days=2,
        max_travel_miles_per_week=800,
        games_per_pair=2,
        no_back_to_back_away=True,
        home_away_balanced=False,
        even_distribution=False,
        travel_optimization_weight=1.0,
    )
    defaults.update(kwargs)
    return ScheduleConstraints(**defaults)


def g(gid, home, away, venue, d, miles=50.0) -> Game:
    slot = _DAY_SLOT_MAP[d.weekday()]
    return Game(
        id=gid, home_team_id=home, away_team_id=away, venue_id=venue,
        game_date=d, timeslot=slot, travel_miles=miles,
    )


def hand_schedule(games, constraints) -> Schedule:
    return Schedule(
        id="test-anch-b2b-001",
        league_id="TEST",
        season_start=constraints.season_start,
        season_end=constraints.season_end,
        games=games,
        constraints=constraints,
        total_games=len(games),
        generated_at="2025-01-01",
        solver_status="OPTIMAL",
    )


# ---------------------------------------------------------------------------
# Category 1: Anchored Away → Movable Home stays between → Anchored Away
# ---------------------------------------------------------------------------

class TestAnchoredAwayHomeResetsChain:
    """
    T_B: anch_away Mar 7, free_home Mar 12 (blacked out Mar 10–15), anch_away Mar 25.

    All valid positions for the free home game fall between the two anchored away
    games (Mar 9 or Mar 16–23), resetting prev_pwa to 0 before Mar 25.
    The repair must succeed without any RED back_to_back_away violations.
    """

    def _make_fixture(self):
        c_orig = base_constraints()
        games = [
            g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 7)),   # T_B anch_away
            g("g2", "T_B", "T_A", "v_beta",  date(2025, 3, 12)),  # T_B free_home (affected)
            g("g3", "T_C", "T_B", "v_gamma", date(2025, 3, 25)),  # T_B anch_away
        ]
        c_repair = base_constraints(venue_blackouts=[
            VenueBlackout(venue_id="v_beta", start_date=date(2025, 3, 10),
                          end_date=date(2025, 3, 15), reason="arena event"),
        ])
        return hand_schedule(games, c_orig), c_repair

    def test_repair_succeeds(self):
        sched, c_repair = self._make_fixture()
        req = RepairRequest(
            schedule_id=sched.id,
            affected_game_ids=["g2"],
            updated_constraints=c_repair,
            neighborhood_size=1,
            max_neighborhood_expansions=0,
            time_limit_seconds=15,
        )
        result = repair_schedule(req, sched, TEAMS, VENUES)

        assert result.status in (RepairStatus.OPTIMAL, RepairStatus.FEASIBLE), (
            f"Expected feasible repair; got {result.status}: {result.error_message}"
        )
        assert result.repaired_schedule is not None

    def test_no_b2b_red_violations_in_repaired_schedule(self):
        sched, c_repair = self._make_fixture()
        req = RepairRequest(
            schedule_id=sched.id,
            affected_game_ids=["g2"],
            updated_constraints=c_repair,
            neighborhood_size=1,
            max_neighborhood_expansions=0,
            time_limit_seconds=15,
        )
        result = repair_schedule(req, sched, TEAMS, VENUES)

        if result.repaired_schedule is None:
            return  # already caught by test_repair_succeeds

        val = validate_schedule(result.repaired_schedule.games, c_repair, TEAMS)
        b2b_red = [
            v for v in val["violations"]
            if v["type"] == "back_to_back_away" and v.get("severity") == "RED"
        ]
        assert b2b_red == [], f"Unexpected RED B2B violations: {b2b_red}"

    def test_repaired_home_game_not_in_blackout(self):
        sched, c_repair = self._make_fixture()
        req = RepairRequest(
            schedule_id=sched.id,
            affected_game_ids=["g2"],
            updated_constraints=c_repair,
            neighborhood_size=1,
            max_neighborhood_expansions=0,
            time_limit_seconds=15,
        )
        result = repair_schedule(req, sched, TEAMS, VENUES)

        if result.status not in (RepairStatus.OPTIMAL, RepairStatus.FEASIBLE):
            return

        g2_move = next((m for m in result.moves if m.game_id == "g2"), None)
        if g2_move:
            assert not (date(2025, 3, 10) <= g2_move.repaired_date <= date(2025, 3, 15)), (
                f"g2 placed inside blackout at {g2_move.repaired_date}"
            )


# ---------------------------------------------------------------------------
# Category 2: Home forced outside interval → chain cannot be reset
# ---------------------------------------------------------------------------

class TestAnchoredAwayNoHomeCanResetChain:
    """
    T_B: anch_away Mar 7, free_home (blacked out Mar 6–23), anch_away Mar 22.

    The wide blackout forces the free home game to land either before Mar 7 or
    after Mar 22.  Neither position can reset prev_pwa between the two anchored
    away games.  With the fix, model.Add(prev_pwa == 0) at Mar 22 makes the
    repair model infeasible internally, so the status is
    GLOBALLY_INFEASIBLE_IN_BUDGET — NOT VALIDATION_FAILED.
    """

    def _make_fixture(self):
        c_orig = base_constraints()
        games = [
            g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 7)),   # T_B anch_away
            g("g2", "T_B", "T_D", "v_beta",  date(2025, 3, 12)),  # T_B free_home (affected)
            g("g3", "T_C", "T_B", "v_gamma", date(2025, 3, 22)),  # T_B anch_away
        ]
        c_repair = base_constraints(venue_blackouts=[
            VenueBlackout(venue_id="v_beta", start_date=date(2025, 3, 6),
                          end_date=date(2025, 3, 23), reason="renovation"),
        ])
        return hand_schedule(games, c_orig), c_repair

    def test_infeasible_not_validation_failed(self):
        sched, c_repair = self._make_fixture()
        req = RepairRequest(
            schedule_id=sched.id,
            affected_game_ids=["g2"],
            updated_constraints=c_repair,
            neighborhood_size=1,
            max_neighborhood_expansions=0,
            time_limit_seconds=15,
        )
        result = repair_schedule(req, sched, TEAMS, VENUES)

        # Critical assertion: the fix ensures the model catches the B2B violation
        # itself; VALIDATION_FAILED would mean the model let a violation through.
        assert result.status != RepairStatus.VALIDATION_FAILED, (
            f"Model should enforce B2B at constraint level, not post-solve validation. "
            f"Got: {result.status}"
        )
        assert result.status == RepairStatus.GLOBALLY_INFEASIBLE_IN_BUDGET, (
            f"Expected GLOBALLY_INFEASIBLE_IN_BUDGET; got {result.status}: {result.error_message}"
        )

    def test_infeasible_produces_no_repaired_schedule(self):
        sched, c_repair = self._make_fixture()
        req = RepairRequest(
            schedule_id=sched.id,
            affected_game_ids=["g2"],
            updated_constraints=c_repair,
            neighborhood_size=1,
            max_neighborhood_expansions=0,
            time_limit_seconds=15,
        )
        result = repair_schedule(req, sched, TEAMS, VENUES)

        assert result.repaired_schedule is None
        assert result.repaired_schedule_id is None


# ---------------------------------------------------------------------------
# Category 3: Free Away → Anchored Away allowed only if home intervenes first
# ---------------------------------------------------------------------------

class TestFreeAwayAnchoredAwayProhibition:
    """
    T_B: anch_home Mar 3, free_away Mar 10 (blacked out Mar 8–15), anch_away Mar 20.

    Placing the free away game after the anchored home Mar 3 creates B2B with
    the anchored away Mar 20 — the fix's model.Add(prev_pwa == 0) at Mar 20
    rejects all such placements.

    The only valid position is Mar 1: the away game lands BEFORE the anchored
    home, which then resets prev_pwa to 0 before the anchored away Mar 20.
    """

    def test_free_away_before_intervening_home_is_valid(self):
        """Solver finds the one valid position (Mar 1) and returns a clean schedule."""
        c_orig = base_constraints()
        games = [
            g("g1", "T_B", "T_A", "v_beta",  date(2025, 3, 3)),   # T_B anch_home
            g("g2", "T_C", "T_B", "v_gamma", date(2025, 3, 10)),  # T_B free_away (affected)
            g("g3", "T_A", "T_B", "v_alpha", date(2025, 3, 20)),  # T_B anch_away
        ]
        c_repair = base_constraints(venue_blackouts=[
            VenueBlackout(venue_id="v_gamma", start_date=date(2025, 3, 8),
                          end_date=date(2025, 3, 15), reason="concert series"),
        ])
        sched = hand_schedule(games, c_orig)
        req = RepairRequest(
            schedule_id=sched.id,
            affected_game_ids=["g2"],
            updated_constraints=c_repair,
            neighborhood_size=1,
            max_neighborhood_expansions=0,
            time_limit_seconds=15,
        )
        result = repair_schedule(req, sched, TEAMS, VENUES)

        assert result.status in (RepairStatus.OPTIMAL, RepairStatus.FEASIBLE), (
            f"Expected feasible repair; got {result.status}: {result.error_message}"
        )
        assert result.repaired_schedule is not None

        val = validate_schedule(result.repaired_schedule.games, c_repair, TEAMS)
        b2b_red = [
            v for v in val["violations"]
            if v["type"] == "back_to_back_away" and v.get("severity") == "RED"
        ]
        assert b2b_red == [], f"Unexpected RED B2B violations after repair: {b2b_red}"

    def test_free_away_placed_after_home_all_positions_rejected(self):
        """
        Block v_gamma Mar 1–15, forcing g2 to Mar 16–18 only (all after home Mar 3).
        Every such placement creates B2B with anch_away Mar 20 → model infeasible.
        Status must NOT be VALIDATION_FAILED.
        """
        c_orig = base_constraints()
        games = [
            g("g1", "T_B", "T_A", "v_beta",  date(2025, 3, 3)),
            g("g2", "T_C", "T_B", "v_gamma", date(2025, 3, 10)),
            g("g3", "T_A", "T_B", "v_alpha", date(2025, 3, 20)),
        ]
        # Block all v_gamma dates before the blackout AND the blackout itself,
        # forcing g2 to Mar 16–18 (after home Mar 3 → B2B with anch_away Mar 20).
        c_repair = base_constraints(venue_blackouts=[
            VenueBlackout(venue_id="v_gamma", start_date=date(2025, 3, 1),
                          end_date=date(2025, 3, 7), reason="setup"),
            VenueBlackout(venue_id="v_gamma", start_date=date(2025, 3, 8),
                          end_date=date(2025, 3, 15), reason="concert series"),
        ])
        sched = hand_schedule(games, c_orig)
        req = RepairRequest(
            schedule_id=sched.id,
            affected_game_ids=["g2"],
            updated_constraints=c_repair,
            neighborhood_size=1,
            max_neighborhood_expansions=0,
            time_limit_seconds=15,
        )
        result = repair_schedule(req, sched, TEAMS, VENUES)

        assert result.status != RepairStatus.VALIDATION_FAILED, (
            f"Model must reject B2B at constraint level, not post-solve validation. "
            f"Got: {result.status}"
        )
        assert result.status in (
            RepairStatus.GLOBALLY_INFEASIBLE_IN_BUDGET,
            RepairStatus.NEIGHBORHOOD_INFEASIBLE,
        ), f"Expected model-level infeasibility; got {result.status}: {result.error_message}"


# ---------------------------------------------------------------------------
# Category 4: Infeasibility status is never VALIDATION_FAILED
# ---------------------------------------------------------------------------

class TestInfeasibilityNotValidationFailed:
    """
    When the B2B constraint makes a repair impossible, the engine must report a
    model-level infeasibility status.  VALIDATION_FAILED means CP-SAT found a
    solution but the independent validator rejected it — that was the broken
    pre-fix behaviour.
    """

    def test_b2b_infeasible_does_not_return_validation_failed(self):
        """Wide blackout scenario: no valid home placement resets the B2B chain."""
        c_orig = base_constraints()
        games = [
            g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 7)),
            g("g2", "T_B", "T_D", "v_beta",  date(2025, 3, 15)),
            g("g3", "T_C", "T_B", "v_gamma", date(2025, 3, 25)),
        ]
        c_repair = base_constraints(venue_blackouts=[
            VenueBlackout(venue_id="v_beta", start_date=date(2025, 3, 5),
                          end_date=date(2025, 3, 27), reason="renovation"),
        ])
        sched = hand_schedule(games, c_orig)
        req = RepairRequest(
            schedule_id=sched.id,
            affected_game_ids=["g2"],
            updated_constraints=c_repair,
            neighborhood_size=1,
            max_neighborhood_expansions=0,
            time_limit_seconds=15,
        )
        result = repair_schedule(req, sched, TEAMS, VENUES)

        assert result.status != RepairStatus.VALIDATION_FAILED, (
            f"B2B must be enforced inside the model; VALIDATION_FAILED means the "
            f"model let a violation through.  Got: {result.status}"
        )
        assert result.repaired_schedule is None

    def test_expansion_still_infeasible_when_no_home_can_interpose(self):
        """
        Allow one neighborhood expansion; the expanded neighborhood includes an
        unrelated game (g4) that cannot serve as a chain reset for T_B between the
        two anchored away games.  Result must still not be VALIDATION_FAILED.
        """
        c_orig = base_constraints()
        games = [
            g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 7)),
            g("g2", "T_B", "T_D", "v_beta",  date(2025, 3, 15)),
            g("g3", "T_C", "T_B", "v_gamma", date(2025, 3, 25)),
            g("g4", "T_D", "T_C", "v_delta", date(2025, 3, 10)),  # unrelated; may enter nbhd
        ]
        c_repair = base_constraints(venue_blackouts=[
            VenueBlackout(venue_id="v_beta", start_date=date(2025, 3, 5),
                          end_date=date(2025, 3, 27), reason="renovation"),
        ])
        sched = hand_schedule(games, c_orig)
        req = RepairRequest(
            schedule_id=sched.id,
            affected_game_ids=["g2"],
            updated_constraints=c_repair,
            neighborhood_size=2,
            max_neighborhood_expansions=1,
            time_limit_seconds=15,
        )
        result = repair_schedule(req, sched, TEAMS, VENUES)

        assert result.status != RepairStatus.VALIDATION_FAILED, (
            f"Status must not be VALIDATION_FAILED even with expansion. "
            f"Got: {result.status}"
        )


# ---------------------------------------------------------------------------
# Category 5: Regression — existing one-game repair and validation gating
# ---------------------------------------------------------------------------

class TestRegressionOneGameRepair:
    """The anchored-away fix must not break existing repair or introduce false infeasibility."""

    def test_basic_one_game_blackout_repair_still_works(self):
        """Single game blocked by a new blackout is correctly relocated."""
        c_orig = base_constraints(no_back_to_back_away=False)
        games = [
            g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 10)),
            g("g2", "T_C", "T_D", "v_gamma", date(2025, 3, 20)),
        ]
        c_repair = base_constraints(
            no_back_to_back_away=False,
            venue_blackouts=[
                VenueBlackout(venue_id="v_alpha", start_date=date(2025, 3, 10),
                              end_date=date(2025, 3, 10), reason="event"),
            ],
        )
        sched = hand_schedule(games, c_orig)
        req = RepairRequest(
            schedule_id=sched.id,
            affected_game_ids=["g1"],
            updated_constraints=c_repair,
            neighborhood_size=5,
            time_limit_seconds=15,
        )
        result = repair_schedule(req, sched, TEAMS, VENUES)

        assert result.status in (RepairStatus.OPTIMAL, RepairStatus.FEASIBLE), (
            f"One-game repair failed: {result.status} — {result.error_message}"
        )
        moved_ids = {m.game_id for m in result.moves}
        assert "g1" in moved_ids
        assert "g2" not in moved_ids

    def test_no_b2b_constraint_inactive_does_not_cause_false_infeasibility(self):
        """With no_back_to_back_away=False, the B2B fix path is skipped entirely."""
        c_orig = base_constraints(no_back_to_back_away=False)
        games = [
            g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 7)),
            g("g2", "T_B", "T_A", "v_beta",  date(2025, 3, 12)),  # affected
            g("g3", "T_C", "T_B", "v_gamma", date(2025, 3, 25)),
        ]
        c_repair = base_constraints(
            no_back_to_back_away=False,
            venue_blackouts=[
                VenueBlackout(venue_id="v_beta", start_date=date(2025, 3, 10),
                              end_date=date(2025, 3, 15), reason="event"),
            ],
        )
        sched = hand_schedule(games, c_orig)
        req = RepairRequest(
            schedule_id=sched.id,
            affected_game_ids=["g2"],
            updated_constraints=c_repair,
            neighborhood_size=1,
            max_neighborhood_expansions=0,
            time_limit_seconds=15,
        )
        result = repair_schedule(req, sched, TEAMS, VENUES)

        assert result.status in (RepairStatus.OPTIMAL, RepairStatus.FEASIBLE), (
            f"B2B-inactive repair unexpectedly failed: {result.status} — {result.error_message}"
        )

    def test_unaffected_anchored_game_not_moved(self):
        """Anchored games outside the neighborhood must remain at their original date."""
        c_orig = base_constraints()
        games = [
            g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 7)),
            g("g2", "T_B", "T_A", "v_beta",  date(2025, 3, 12)),  # affected
            g("g3", "T_C", "T_B", "v_gamma", date(2025, 3, 25)),
        ]
        c_repair = base_constraints(venue_blackouts=[
            VenueBlackout(venue_id="v_beta", start_date=date(2025, 3, 10),
                          end_date=date(2025, 3, 15), reason="event"),
        ])
        sched = hand_schedule(games, c_orig)
        req = RepairRequest(
            schedule_id=sched.id,
            affected_game_ids=["g2"],
            updated_constraints=c_repair,
            neighborhood_size=1,
            max_neighborhood_expansions=0,
            time_limit_seconds=15,
        )
        result = repair_schedule(req, sched, TEAMS, VENUES)

        if result.status in (RepairStatus.OPTIMAL, RepairStatus.FEASIBLE):
            moved_ids = {m.game_id for m in result.moves}
            assert "g1" not in moved_ids, "Anchored game g1 must not be moved"
            assert "g3" not in moved_ids, "Anchored game g3 must not be moved"
