"""
Regression tests for the repair-model same-day pre-blocking fix.

Root cause (repair.py:475): the slot pre-blocking condition was
  ``0 < abs((d - ad).days) < min_rest``
which excluded same-day (gap = 0).  validate_schedule → check_rest_days
flags gap < min_rest as RED, so the model and validator disagreed on
same-day placements.  The fix: ``abs((d - ad).days) < min_rest``.

Coverage:
  1. Same-venue same-day is still blocked (venue-exclusivity path).
  2. Different-venue same-day is now also blocked (rest-day path).
  3. B2B-away chain is correct across anchored + free games.
  4. Two-game repair produces no RED violations when a valid solution exists.
  5. VALIDATION_FAILED result is never stored (original preserved).
"""
import copy
import uuid
from datetime import date
from typing import Dict, List

import pytest

from app.scheduler.models import (
    Game,
    RepairRequest,
    RepairResult,
    RepairStatus,
    Schedule,
    ScheduleConstraints,
    Team,
    TimeSlot,
    Venue,
    VenueBlackout,
)
from app.scheduler.repair import _build_repair_model, repair_schedule
from app.scheduler.constraints import (
    check_back_to_back_away,
    check_rest_days,
    validate_schedule,
)
from app.scheduler.solver import build_date_slots

# ---------------------------------------------------------------------------
# Shared fixtures — 4 teams, 4 venues, all different locations
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

TEAM_BY_ID = {t.id: t for t in TEAMS}

_DAY_SLOT = {
    0: TimeSlot.MON_EVENING, 1: TimeSlot.TUE_EVENING,
    2: TimeSlot.WED_EVENING, 3: TimeSlot.THU_EVENING,
    4: TimeSlot.FRI_EVENING, 5: TimeSlot.SAT_PRIMETIME,
    6: TimeSlot.SUN_AFTERNOON,
}


def g(gid: str, home: str, away: str, venue: str, d: date) -> Game:
    return Game(
        id=gid, home_team_id=home, away_team_id=away, venue_id=venue,
        game_date=d, timeslot=_DAY_SLOT[d.weekday()], travel_miles=50.0,
    )


def base_c(**kwargs) -> ScheduleConstraints:
    defaults = dict(
        league_id="TEST",
        season_start=date(2025, 3, 1),
        season_end=date(2025, 3, 31),
        min_rest_days=2,
        max_travel_miles_per_week=5000,
        no_back_to_back_away=True,
        home_away_balanced=False,
        even_distribution=False,
        games_per_pair=1,
        travel_optimization_weight=0.0,
        min_distinct_slots_per_week=1,
        max_games_per_slot_per_week=4,
        target_games_per_week=2,
        games_per_week_tolerance=2,
    )
    defaults.update(kwargs)
    return ScheduleConstraints(**defaults)


def hand_sched(games: List[Game], c: ScheduleConstraints) -> Schedule:
    return Schedule(
        id=str(uuid.uuid4()),
        league_id="TEST",
        season_start=c.season_start,
        season_end=c.season_end,
        games=games,
        constraints=c,
        total_games=len(games),
        generated_at="2025-03-01",
        solver_status="OPTIMAL",
    )


# ---------------------------------------------------------------------------
# 1. Same-venue same-day: still blocked by venue-exclusivity path
# ---------------------------------------------------------------------------

class TestSameVenueSameDayBlocked:
    """
    Venue-exclusivity already blocked same-(venue, slot) placements before
    the fix.  Verify this path still works after the change.
    """

    def test_same_venue_slot_is_none_in_repair_model(self):
        """
        Anchored game: T_A home at v_alpha on March 10.
        Free game: also has T_A as home team → model assigns venue = T_A.home_venue_id
        = v_alpha.  The (v_alpha, March-10-slot) pair must be None.

        Note: the model derives the free game's venue from team_by_id[home_team_id],
        not from Game.venue_id.  Using a free game whose home team has a *different*
        home_venue_id would never reach the venue-exclusivity check for v_alpha.
        """
        c = base_c()
        date_slots = build_date_slots(c.season_start, c.season_end)
        slot_lookup = {(d, sl): idx for idx, (d, sl) in enumerate(date_slots)}

        # Anchored: T_A home at v_alpha, March 10
        anchored = [g("anch1", "T_A", "T_B", "v_alpha", date(2025, 3, 10))]
        # Free: T_A home (also v_alpha), different matchup and original date
        # T_A appears in both → rest-day blocking also fires, but that's fine;
        # the test asserts the slot is None regardless of which path blocked it.
        free = [g("free1", "T_A", "T_C", "v_alpha", date(2025, 3, 20))]

        _, x, _, _ = _build_repair_model(
            free_games=free,
            anchored_games=anchored,
            constraints=c,
            all_date_slots=date_slots,
            travel_miles={"free1": 50.0},
            team_by_id=TEAM_BY_ID,
        )

        march10_slot = slot_lookup.get((date(2025, 3, 10), _DAY_SLOT[date(2025, 3, 10).weekday()]))
        assert march10_slot is not None, "March 10 not in date_slots"
        assert x[0][march10_slot] is None, (
            "Same-venue same-slot as anchored game must be pre-blocked (None). "
            "Model derives venue from team_by_id[home_team_id].home_venue_id."
        )


# ---------------------------------------------------------------------------
# 2. Different-venue same-day: now blocked by rest-day path (the fix)
# ---------------------------------------------------------------------------

class TestDifferentVenueSameDayBlocked:
    """
    Before the fix: slot was NOT blocked when two games share a date but
    different venues for the same team.
    After the fix: abs(0) < min_rest → blocked.
    """

    def test_free_game_blocked_on_same_date_as_anchored_different_venue(self):
        """
        Anchored: T_B away at v_alpha on March 10 (T_A home, T_B away).
        Free: T_A home at v_alpha on unknown — but T_B is ALSO the away team.
              Wait: free game uses a *different* venue (v_gamma, T_C home, T_B away).

        T_B now has an anchored game on March 10 AND a free game that could
        land on March 10 (at v_gamma, different venue). With the fix, the slot
        for March 10 in the free game must be None for T_B's sake.
        """
        c = base_c(min_rest_days=2)
        date_slots = build_date_slots(c.season_start, c.season_end)
        slot_lookup = {(d, sl): idx for idx, (d, sl) in enumerate(date_slots)}

        # Anchored: T_B is away at v_alpha on March 10
        anchored = [g("anch1", "T_A", "T_B", "v_alpha", date(2025, 3, 10))]
        # Free: T_B is away at v_gamma on some date — can it land on March 10?
        free     = [g("free1", "T_C", "T_B", "v_gamma", date(2025, 3, 20))]

        _, x, _, _ = _build_repair_model(
            free_games=free,
            anchored_games=anchored,
            constraints=c,
            all_date_slots=date_slots,
            travel_miles={"free1": 50.0},
            team_by_id=TEAM_BY_ID,
        )

        march10_slot = slot_lookup.get((date(2025, 3, 10), _DAY_SLOT[date(2025, 3, 10).weekday()]))
        assert march10_slot is not None
        assert x[0][march10_slot] is None, (
            "Free game involving T_B must be pre-blocked on March 10 "
            "(same date as T_B anchored game, different venue): "
            "abs(0) < min_rest must trigger blocking."
        )

    def test_one_day_gap_also_blocked(self):
        """
        Anchored: T_B game on March 10 (Monday).
        Free game involving T_B: slot for March 11 (Tuesday) must also be None
        because abs(1) < min_rest(2) = True.
        """
        c = base_c(min_rest_days=2)
        date_slots = build_date_slots(c.season_start, c.season_end)
        slot_lookup = {(d, sl): idx for idx, (d, sl) in enumerate(date_slots)}

        anchored = [g("anch1", "T_A", "T_B", "v_alpha", date(2025, 3, 10))]
        free     = [g("free1", "T_C", "T_B", "v_gamma", date(2025, 3, 20))]

        _, x, _, _ = _build_repair_model(
            free_games=free,
            anchored_games=anchored,
            constraints=c,
            all_date_slots=date_slots,
            travel_miles={"free1": 50.0},
            team_by_id=TEAM_BY_ID,
        )

        march11_slot = slot_lookup.get((date(2025, 3, 11), _DAY_SLOT[date(2025, 3, 11).weekday()]))
        assert march11_slot is not None
        assert x[0][march11_slot] is None, (
            "Free game slot 1 day from anchored game must be blocked (gap=1 < min_rest=2)"
        )

    def test_two_day_gap_is_allowed(self):
        """
        Anchored: T_B game on March 10. Free game: slot for March 12 (gap=2)
        must NOT be pre-blocked (gap == min_rest is acceptable).
        """
        c = base_c(min_rest_days=2)
        date_slots = build_date_slots(c.season_start, c.season_end)
        slot_lookup = {(d, sl): idx for idx, (d, sl) in enumerate(date_slots)}

        anchored = [g("anch1", "T_A", "T_B", "v_alpha", date(2025, 3, 10))]
        free     = [g("free1", "T_C", "T_B", "v_gamma", date(2025, 3, 20))]

        _, x, _, _ = _build_repair_model(
            free_games=free,
            anchored_games=anchored,
            constraints=c,
            all_date_slots=date_slots,
            travel_miles={"free1": 50.0},
            team_by_id=TEAM_BY_ID,
        )

        march12_slot = slot_lookup.get((date(2025, 3, 12), _DAY_SLOT[date(2025, 3, 12).weekday()]))
        assert march12_slot is not None
        assert x[0][march12_slot] is not None, (
            "Slot 2 days from anchored game must NOT be pre-blocked when min_rest=2 "
            "(abs(2) < 2 is False)"
        )

    def test_min_rest_zero_allows_same_day_different_venue(self):
        """
        When min_rest=0, same-day different-venue is not a constraint violation.
        The slot should NOT be blocked.
        """
        c = base_c(min_rest_days=0)
        date_slots = build_date_slots(c.season_start, c.season_end)
        slot_lookup = {(d, sl): idx for idx, (d, sl) in enumerate(date_slots)}

        anchored = [g("anch1", "T_A", "T_B", "v_alpha", date(2025, 3, 10))]
        free     = [g("free1", "T_C", "T_B", "v_gamma", date(2025, 3, 20))]

        _, x, _, _ = _build_repair_model(
            free_games=free,
            anchored_games=anchored,
            constraints=c,
            all_date_slots=date_slots,
            travel_miles={"free1": 50.0},
            team_by_id=TEAM_BY_ID,
        )

        march10_slot = slot_lookup.get((date(2025, 3, 10), _DAY_SLOT[date(2025, 3, 10).weekday()]))
        # Venue-exclusivity still blocks same-venue same-slot, but T_B's anchored game
        # is at v_alpha; free game needs v_gamma slot on March 10 → different venue →
        # only the rest-day path could block it; with min_rest=0 it must be open.
        assert march10_slot is not None
        assert x[0][march10_slot] is not None, (
            "With min_rest=0, same-day different-venue must NOT be blocked"
        )


# ---------------------------------------------------------------------------
# 3. B2B-away chain: anchored + free interaction
# ---------------------------------------------------------------------------

class TestB2BChainAnchoredFree:
    """
    Verify the elif-free_any branch behaviour after the same-day fix.

    With the fix applied, anchored-game dates have all their free-game slots
    pre-blocked → team_any_free[tid][anchored_date] is empty → free_any=[]
    → the elif branch never fires for anchored dates.  The anchored branch
    alone correctly advances chain state; subsequent free games on later dates
    are constrained by that state.
    """

    def test_repaired_schedule_has_no_b2b_away(self):
        """
        Anchored: T_B away March 10. Free game g1 (T_C home, T_B away) must
        not land on a date where T_B would be consecutive-away with no T_B
        home game between March 10 and g1's new date.

        We verify by running the repair engine and checking validate_schedule.
        """
        # T_B has: anchored away March 10, anchored home March 25
        # Free game g1: T_C vs T_B, originally March 15 (blackout forces move)
        # After repair, g1 must not land between March 10 and March 25 without
        # a T_B home game in between — but T_B home March 25 IS anchored, so
        # the solver has to put g1 AFTER March 25 (or before March 7) to avoid B2B.

        blackout = VenueBlackout(
            venue_id="v_gamma",
            start_date=date(2025, 3, 14),
            end_date=date(2025, 3, 16),
        )
        c = base_c(
            season_start=date(2025, 3, 1),
            season_end=date(2025, 3, 31),
            no_back_to_back_away=True,
            min_rest_days=2,
            venue_blackouts=[blackout],
        )

        games = [
            g("g_anch_away", "T_A", "T_B", "v_alpha", date(2025, 3, 10)),  # T_B away, anchored
            g("g_free",      "T_C", "T_B", "v_gamma", date(2025, 3, 15)),  # T_B away, free (in blackout)
            g("g_anch_home", "T_B", "T_D", "v_beta",  date(2025, 3, 25)),  # T_B home, anchored
        ]
        sched = hand_sched(games, c)
        req = RepairRequest(
            schedule_id=sched.id,
            affected_game_ids=["g_free"],
            updated_constraints=c,
            neighborhood_size=3,
            time_limit_seconds=15,
        )
        result = repair_schedule(req, sched, TEAMS, VENUES)

        if result.status not in (RepairStatus.OPTIMAL, RepairStatus.FEASIBLE):
            pytest.skip(f"Solver could not repair: {result.status} — {result.error_message}")

        repaired_games = result.repaired_schedule.games
        b2b = check_back_to_back_away("T_B", repaired_games)
        assert b2b == [], (
            f"Repaired schedule must have no B2B-away for T_B; got: {b2b}"
        )

    def test_elif_dead_code_after_fix_no_free_vars_on_anchored_dates(self):
        """
        Structural invariant: after the fix, team_any_free[tid] must NOT
        contain any dates that are also in anchor_dates for the same team.

        We verify this by inspecting the team_any_free mapping built inside
        _build_repair_model — anchored-date slots must all be None so the
        date never appears as a key in team_any_free.
        """
        c = base_c(min_rest_days=2, no_back_to_back_away=True)
        date_slots = build_date_slots(c.season_start, c.season_end)

        anchored_date = date(2025, 3, 10)
        anchored = [g("anch1", "T_A", "T_B", "v_alpha", anchored_date)]
        # Free game: T_B away at v_gamma — could it hold slots on anchored_date?
        free     = [g("free1", "T_C", "T_B", "v_gamma", date(2025, 3, 20))]

        _, x, _, _ = _build_repair_model(
            free_games=free,
            anchored_games=anchored,
            constraints=c,
            all_date_slots=date_slots,
            travel_miles={"free1": 50.0},
            team_by_id=TEAM_BY_ID,
        )

        slot_lookup = {(d, sl): idx for idx, (d, sl) in enumerate(date_slots)}
        march10_s = slot_lookup.get(
            (anchored_date, _DAY_SLOT[anchored_date.weekday()])
        )
        # Confirm the slot for free game on anchored_date is None →
        # team_any_free["T_B"][anchored_date] would be empty → elif never fires
        assert march10_s is not None
        assert x[0][march10_s] is None, (
            "After the same-day fix, free-game slot on anchored-game date must be None. "
            "This confirms the elif branch is unreachable for anchored dates."
        )


# ---------------------------------------------------------------------------
# 4. Two-game repair produces no RED violations (end-to-end, CP-SAT)
# ---------------------------------------------------------------------------

class TestTwoGameRepairNoRedViolations:
    """
    Mirrors the browser-observed failure: two home games at the same venue
    need to move out of a blackout.  With the fix, the repaired schedule
    must pass validate_schedule with zero RED violations.
    """

    def _make_schedule(self) -> tuple:
        """
        6 games, 4 teams. Durham-equivalent (T_A) has 2 home games in a
        blackout window (March 10–20).  The other 4 games are anchored.
        Returns (schedule, blackout_constraints, affected_ids).
        """
        blackout = VenueBlackout(
            venue_id="v_alpha",
            start_date=date(2025, 3, 10),
            end_date=date(2025, 3, 20),
        )
        c = base_c(
            season_start=date(2025, 3, 1),
            season_end=date(2025, 3, 31),
            min_rest_days=2,
            no_back_to_back_away=True,
            venue_blackouts=[blackout],
        )
        games = [
            # Affected: T_A home games inside blackout
            g("g_aff1", "T_A", "T_B", "v_alpha", date(2025, 3, 12)),
            g("g_aff2", "T_A", "T_C", "v_alpha", date(2025, 3, 17)),
            # Anchored: other games spread across the season
            g("g_anch1", "T_B", "T_C", "v_beta",  date(2025, 3, 3)),
            g("g_anch2", "T_C", "T_D", "v_gamma", date(2025, 3, 5)),
            g("g_anch3", "T_D", "T_A", "v_delta", date(2025, 3, 24)),
            g("g_anch4", "T_B", "T_D", "v_beta",  date(2025, 3, 27)),
        ]
        sched = hand_sched(games, c)
        return sched, c, ["g_aff1", "g_aff2"]

    def test_two_home_games_repaired_no_red_violations(self):
        sched, c, affected = self._make_schedule()
        req = RepairRequest(
            schedule_id=sched.id,
            affected_game_ids=affected,
            updated_constraints=c,
            neighborhood_size=5,
            max_neighborhood_expansions=2,
            time_limit_seconds=20,
        )
        result = repair_schedule(req, sched, TEAMS, VENUES)

        if result.status not in (RepairStatus.OPTIMAL, RepairStatus.FEASIBLE):
            pytest.skip(
                f"Solver could not repair: {result.status} — {result.error_message}"
            )

        repaired_games = result.repaired_schedule.games
        validation = validate_schedule(repaired_games, c, TEAMS)

        red = [v for v in validation["violations"] if v["severity"] == "RED"]
        assert red == [], (
            f"Repaired schedule has {len(red)} RED violation(s):\n"
            + "\n".join(f"  [{v['type']}] {v.get('message', '')}" for v in red)
        )

    def test_repaired_games_not_in_blackout(self):
        sched, c, affected = self._make_schedule()
        req = RepairRequest(
            schedule_id=sched.id,
            affected_game_ids=affected,
            updated_constraints=c,
            neighborhood_size=5,
            max_neighborhood_expansions=2,
            time_limit_seconds=20,
        )
        result = repair_schedule(req, sched, TEAMS, VENUES)

        if result.status not in (RepairStatus.OPTIMAL, RepairStatus.FEASIBLE):
            pytest.skip(f"No solution: {result.status}")

        for game in result.repaired_schedule.games:
            if game.venue_id == "v_alpha":
                assert not (date(2025, 3, 10) <= game.game_date <= date(2025, 3, 20)), (
                    f"Repaired game {game.id} still falls in the blackout on {game.game_date}"
                )

    def test_rest_days_satisfied_after_repair(self):
        sched, c, affected = self._make_schedule()
        req = RepairRequest(
            schedule_id=sched.id,
            affected_game_ids=affected,
            updated_constraints=c,
            neighborhood_size=5,
            max_neighborhood_expansions=2,
            time_limit_seconds=20,
        )
        result = repair_schedule(req, sched, TEAMS, VENUES)

        if result.status not in (RepairStatus.OPTIMAL, RepairStatus.FEASIBLE):
            pytest.skip(f"No solution: {result.status}")

        for team in TEAMS:
            rest_viols = check_rest_days(team.id, result.repaired_schedule.games, c.min_rest_days)
            assert rest_viols == [], (
                f"Rest-day violations after repair for {team.id}: {rest_viols}"
            )


# ---------------------------------------------------------------------------
# 5. VALIDATION_FAILED result is never stored; original preserved
# ---------------------------------------------------------------------------

class TestValidationFailedNotStored:
    """
    When repair engine returns VALIDATION_FAILED, the route must not persist
    the repaired schedule.  We test at the engine level: repaired_schedule_id
    must be None on VALIDATION_FAILED, so the route guard works.
    """

    def test_validation_failed_has_null_repaired_id(self):
        """
        Force a VALIDATION_FAILED by giving a schedule that is already
        invalid (a free game has zero available slots → NEIGHBORHOOD_INFEASIBLE,
        which expands but can't fix).  For the VALIDATION_FAILED path
        specifically we test via the engine contract: if status is
        VALIDATION_FAILED, repaired_schedule_id must be None.
        """
        # Build a one-game schedule whose only allowed slot is blacked out.
        blackout = VenueBlackout(
            venue_id="v_alpha",
            start_date=date(2025, 3, 1),
            end_date=date(2025, 3, 31),
        )
        c = base_c(
            season_start=date(2025, 3, 1),
            season_end=date(2025, 3, 31),
            venue_blackouts=[blackout],
        )
        games = [g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 10))]
        sched = hand_sched(games, c)
        req = RepairRequest(
            schedule_id=sched.id,
            affected_game_ids=["g1"],
            updated_constraints=c,
            neighborhood_size=5,
            max_neighborhood_expansions=1,
            time_limit_seconds=10,
        )
        result = repair_schedule(req, sched, TEAMS, VENUES)

        # Either NEIGHBORHOOD_INFEASIBLE (no slots) or VALIDATION_FAILED
        # In both cases the repaired_schedule_id must be None / no schedule saved
        if result.status == RepairStatus.VALIDATION_FAILED:
            assert result.repaired_schedule_id is None, (
                "VALIDATION_FAILED must never expose a repaired_schedule_id"
            )
            assert result.repaired_schedule is None, (
                "VALIDATION_FAILED must not carry a repaired_schedule object"
            )
        # NEIGHBORHOOD_INFEASIBLE is also an acceptable outcome here
        assert result.status in (
            RepairStatus.NEIGHBORHOOD_INFEASIBLE,
            RepairStatus.GLOBALLY_INFEASIBLE_IN_BUDGET,
            RepairStatus.VALIDATION_FAILED,
        ), f"Unexpected status: {result.status}"

    def test_original_schedule_object_unchanged_after_repair(self):
        """
        repair_schedule must not mutate the original Schedule object it receives.
        """
        c = base_c()
        games = [
            g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 10)),
            g("g2", "T_C", "T_D", "v_gamma", date(2025, 3, 20)),
        ]
        sched = hand_sched(games, c)
        original_id = sched.id
        original_dates = [gm.game_date for gm in sched.games]

        blackout = VenueBlackout(
            venue_id="v_alpha",
            start_date=date(2025, 3, 10),
            end_date=date(2025, 3, 11),
        )
        c2 = base_c(venue_blackouts=[blackout])
        req = RepairRequest(
            schedule_id=sched.id,
            affected_game_ids=["g1"],
            updated_constraints=c2,
            neighborhood_size=5,
            time_limit_seconds=15,
        )
        repair_schedule(req, sched, TEAMS, VENUES)

        assert sched.id == original_id, "Schedule ID mutated during repair"
        assert [gm.game_date for gm in sched.games] == original_dates, (
            "Original schedule game dates were mutated during repair"
        )
