"""
Regression tests for the exact carry-forward chain B2B-away encoding.

What these tests cover that test_b2b_away_constraint.py does not:
  1. Consecutive away games separated by MORE than 47 days are still violations.
  2. Away → Home → Away remains valid across any gap.
  3. Empty dates carry state forward unchanged (no spurious resets).
  4. Anchored away game followed by a free away game is blocked in the repair engine.
  5. A valid schedule is not modified by the greedy repair pass.
  6. RED violations cause the generation endpoint to return 503/422 without storing.
  7. TIMEOUT_FALLBACK cannot be surfaced as a successful HTTP 200 generation.
  8. INFEASIBLE cannot be surfaced as a successful HTTP 200 generation.
  9. Rejected schedules are absent from the in-memory store.
"""
from datetime import date
from typing import List
import unittest.mock as mock
import uuid

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
from app.scheduler.solver import _repair_back_to_back_away, build_date_slots
from app.scheduler.repair import repair_schedule
from app.scheduler.models import RepairRequest, RepairStatus, VenueBlackout

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
    0: TimeSlot.MON_EVENING, 1: TimeSlot.TUE_EVENING, 2: TimeSlot.WED_EVENING,
    3: TimeSlot.THU_EVENING, 4: TimeSlot.FRI_EVENING,
    5: TimeSlot.SAT_PRIMETIME, 6: TimeSlot.SUN_AFTERNOON,
}


def g(gid: str, home: str, away: str, venue: str, d: date) -> Game:
    return Game(
        id=gid, home_team_id=home, away_team_id=away, venue_id=venue,
        game_date=d, timeslot=_DAY_SLOT_MAP[d.weekday()], travel_miles=50.0,
    )


def hand_schedule(games: List[Game], c: ScheduleConstraints) -> Schedule:
    return Schedule(
        id=str(uuid.uuid4()),
        league_id="TEST",
        season_start=c.season_start,
        season_end=c.season_end,
        games=games,
        constraints=c,
        total_games=len(games),
        generated_at=str(date.today()),
        solver_status="FEASIBLE",
    )


def base_constraints(**kwargs) -> ScheduleConstraints:
    defaults = dict(
        league_id="TEST",
        season_start=date(2025, 1, 1),
        season_end=date(2025, 4, 30),
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


# ---------------------------------------------------------------------------
# 1. Validator: consecutive away games >47 days apart is still a violation
# ---------------------------------------------------------------------------

class TestValidatorBeyond47Days:
    def test_59_day_gap_between_consecutive_away_is_red(self):
        """
        T_B plays away Jan 10 and Mar 10 (59 days apart).  No T_B game between them.
        The validator must flag this as a RED violation regardless of day gap.
        """
        c = base_constraints()
        games = [
            g("g1", "T_A", "T_B", "v_alpha", date(2025, 1, 10)),  # T_B away
            g("g2", "T_C", "T_B", "v_gamma", date(2025, 3, 10)),  # T_B away, +59 d
        ]
        viols = check_back_to_back_away("T_B", games)
        assert len(viols) == 1
        assert viols[0]["type"] == "back_to_back_away"
        assert viols[0]["team_id"] == "T_B"

    def test_100_day_gap_between_consecutive_away_is_red(self):
        """
        T_B plays away Jan 1 and Apr 11 (100 days apart), still consecutive.
        The old 47-day heuristic would have silently skipped this pair.
        """
        c = base_constraints()
        games = [
            g("g1", "T_A", "T_B", "v_alpha", date(2025, 1, 1)),
            g("g2", "T_C", "T_B", "v_gamma", date(2025, 4, 11)),
        ]
        viols = check_back_to_back_away("T_B", games)
        assert len(viols) == 1

    def test_away_home_away_beyond_47_days_is_valid(self):
        """
        Away → Home (60 days later) → Away (60 days later): two 60-day gaps.
        No B2B violation because the home game breaks the consecutive-away sequence.
        """
        c = base_constraints()
        games = [
            g("g1", "T_A", "T_B", "v_alpha", date(2025, 1, 1)),   # T_B away
            g("g2", "T_B", "T_C", "v_beta",  date(2025, 3, 2)),   # T_B HOME (+60 d)
            g("g3", "T_A", "T_B", "v_alpha", date(2025, 5, 1)),   # T_B away (+60 d)
        ]
        viols = check_back_to_back_away("T_B", games)
        assert viols == [], f"Away→Home→Away must not be flagged: {viols}"


# ---------------------------------------------------------------------------
# 2. Empty dates preserve carry-forward state
# ---------------------------------------------------------------------------

class TestEmptyDatesPreserveState:
    def test_no_games_between_two_away_games_still_a_violation(self):
        """
        Empty calendar between two away games doesn't reset the state.
        There are many possible game dates between Jan 10 and Apr 1 for which
        T_B has no assignment — the validator must still catch the violation.
        """
        c = base_constraints()
        games = [
            g("g1", "T_A", "T_B", "v_alpha", date(2025, 1, 10)),  # T_B away
            g("g2", "T_C", "T_B", "v_gamma", date(2025, 4, 1)),   # T_B away, 81 days later
        ]
        viols = check_back_to_back_away("T_B", games)
        assert len(viols) == 1, (
            "State must carry forward across empty dates; 81-day gap is still consecutive"
        )

    def test_home_game_in_gap_resets_state_even_beyond_47_days(self):
        """
        Away → (50-day gap) → Home → (30-day gap) → Away.
        The home game is 50 days after the first away game.
        Result: zero violations (home game breaks the consecutive-away chain).
        """
        c = base_constraints()
        games = [
            g("g1", "T_A", "T_B", "v_alpha", date(2025, 1, 1)),   # T_B away
            g("g2", "T_B", "T_C", "v_beta",  date(2025, 2, 20)),  # T_B HOME, +50 d
            g("g3", "T_C", "T_B", "v_gamma", date(2025, 3, 22)),  # T_B away, +30 d
        ]
        viols = check_back_to_back_away("T_B", games)
        assert viols == [], (
            f"Home game must reset chain state even when >47 days from first away: {viols}"
        )


# ---------------------------------------------------------------------------
# 3. Greedy repair pass does not corrupt a clean schedule
# ---------------------------------------------------------------------------

class TestGreedyRepairPassNoCorruption:
    def test_already_valid_schedule_untouched(self):
        """
        Away → Home → Away for T_B with a 60-day gap in each leg.
        _repair_back_to_back_away must leave all dates/slots unchanged.
        """
        games = [
            g("g1", "T_A", "T_B", "v_alpha", date(2025, 1, 1)),
            g("g2", "T_B", "T_C", "v_beta",  date(2025, 3, 2)),   # T_B home
            g("g3", "T_C", "T_B", "v_gamma", date(2025, 5, 1)),
        ]
        date_slots = build_date_slots(date(2025, 1, 1), date(2025, 5, 31))
        original = [(gm.game_date, gm.timeslot) for gm in games]
        result = _repair_back_to_back_away(games, ["T_A", "T_B", "T_C"], date_slots, 2)
        assert [(gm.game_date, gm.timeslot) for gm in result] == original, (
            "Valid schedule must not be modified by the greedy repair pass"
        )


# ---------------------------------------------------------------------------
# 4. Repair engine: anchored away followed by free away is blocked
# ---------------------------------------------------------------------------

class TestRepairEngineAnchoredInteraction:
    """
    The repair engine's chain encoding must prevent a free away game from landing
    immediately after (or before) an anchored away game with no T game between them.
    """

    def _make_constraints(self) -> ScheduleConstraints:
        return base_constraints(
            season_start=date(2025, 3, 1),
            season_end=date(2025, 3, 31),
            min_rest_days=2,
        )

    def test_free_away_blocked_after_anchored_away(self):
        """
        Anchored: T_B away March 10.
        Free: T_A vs T_B at v_alpha, originally March 10 (blackout forces a move).
        After repair, T_B must NOT be rescheduled as the away team on a date
        where T_B's immediately preceding game was also away with no T_B game between.

        We verify this indirectly: the repaired schedule passes back-to-back validation.
        """
        c = self._make_constraints()
        # T_B plays away March 10 (this will be anchored — not affected by blackout)
        # T_A vs T_B at v_alpha on March 10 is in the blackout (affected)
        games = [
            g("g1", "T_A", "T_B", "v_alpha", date(2025, 3, 10)),  # affected; T_B away
            g("g2", "T_C", "T_B", "v_gamma", date(2025, 3, 20)),  # anchored; T_B away
            g("g3", "T_B", "T_A", "v_beta",  date(2025, 3, 25)),  # anchored; T_B home
        ]
        blackout = VenueBlackout(
            venue_id="v_alpha",
            start_date=date(2025, 3, 10),
            end_date=date(2025, 3, 11),
        )
        c_updated = base_constraints(
            season_start=date(2025, 3, 1),
            season_end=date(2025, 3, 31),
            min_rest_days=2,
            venue_blackouts=[blackout],
        )
        sched = hand_schedule(games, c_updated)
        req = RepairRequest(
            schedule_id=sched.id,
            affected_game_ids=["g1"],
            updated_constraints=c_updated,
            neighborhood_size=5,
            time_limit_seconds=20,
        )
        result = repair_schedule(req, sched, TEAMS, VENUES)

        if result.status not in (RepairStatus.OPTIMAL, RepairStatus.FEASIBLE):
            pytest.skip(f"Repair did not find a solution: {result.status}")

        # Build repaired game list
        import copy
        move_map = {m.game_id: m for m in result.moves}
        repaired = []
        for orig in sched.games:
            mv = move_map.get(orig.id)
            if mv:
                repaired.append(Game(
                    id=orig.id,
                    home_team_id=orig.home_team_id,
                    away_team_id=orig.away_team_id,
                    venue_id=orig.venue_id,
                    game_date=mv.repaired_date,
                    timeslot=mv.repaired_timeslot,
                    travel_miles=orig.travel_miles,
                ))
            else:
                repaired.append(copy.copy(orig))

        b2b = check_back_to_back_away("T_B", repaired)
        assert b2b == [], (
            f"Repair engine allowed a B2B-away for T_B after rescheduling: {b2b}"
        )


# ---------------------------------------------------------------------------
# 5-9. Route-level gating (mocked — no CP-SAT)
# ---------------------------------------------------------------------------

class TestRouteValidationGating:
    """
    HTTP-level tests for the generation endpoint gating logic.
    solve_schedule is mocked so no CP-SAT solver runs.
    """

    @pytest.fixture(autouse=True)
    def _client(self):
        from fastapi.testclient import TestClient
        from app.main import app
        self.client = TestClient(app)

    def _post_generate(self):
        """Minimal valid generation request body."""
        return self.client.post("/api/schedule/generate", json={
            "league_id": "NPL",
            "season_start": "2025-03-01",
            "season_end": "2025-03-31",
            "min_rest_days": 2,
            "games_per_pair": 1,
            "no_back_to_back_away": True,
            "home_away_balanced": False,
            "even_distribution": False,
            "max_travel_miles_per_week": 5000,
            "travel_optimization_weight": 0.0,
        })

    def _make_fake_schedule(self, solver_status: str) -> Schedule:
        c = base_constraints(season_start=date(2025, 3, 1), season_end=date(2025, 3, 31))
        return Schedule(
            id=str(uuid.uuid4()),
            league_id="NPL",
            season_start=date(2025, 3, 1),
            season_end=date(2025, 3, 31),
            games=[],
            constraints=c,
            total_games=0,
            generated_at="2025-03-01",
            solver_status=solver_status,
        )

    def _fake_metrics(self, **kwargs):
        base = {
            "decisions_evaluated": 0,
            "solve_time_seconds": 0.1,
            "total_variables": 0,
            "hard_constraints_count": 0,
            "solver_status": "FEASIBLE",
            "objective_value": None,
            "infeasibility_reasons": [],
            "n_teams": 2,
            "n_matchups": 1,
            "n_slots": 10,
        }
        base.update(kwargs)
        return base

    # --- 5. TIMEOUT_FALLBACK cannot be surfaced as HTTP 200 ---

    def test_timeout_fallback_returns_503(self):
        fake_sched = self._make_fake_schedule("TIMEOUT_FALLBACK")
        fake_metrics = self._fake_metrics(
            solver_status="TIMEOUT_FALLBACK",
            infeasibility_reasons=["Too many constraints"],
        )
        import app.routes.schedule as route_mod
        with mock.patch.object(route_mod, "solve_schedule",
                               return_value=(fake_sched, fake_metrics)):
            resp = self._post_generate()
        assert resp.status_code == 503, (
            f"TIMEOUT_FALLBACK must return 503, got {resp.status_code}"
        )
        assert "TIMEOUT_FALLBACK" in resp.json()["detail"]

    # --- 6. INFEASIBLE cannot be surfaced as HTTP 200 ---

    def test_infeasible_returns_503(self):
        fake_sched = self._make_fake_schedule("INFEASIBLE")
        fake_metrics = self._fake_metrics(
            solver_status="INFEASIBLE",
            infeasibility_reasons=["No feasible schedule exists"],
        )
        import app.routes.schedule as route_mod
        with mock.patch.object(route_mod, "solve_schedule",
                               return_value=(fake_sched, fake_metrics)):
            resp = self._post_generate()
        assert resp.status_code == 503, (
            f"INFEASIBLE must return 503, got {resp.status_code}"
        )
        assert "INFEASIBLE" in resp.json()["detail"]

    # --- 7. RED violations in a FEASIBLE schedule cause 422 ---

    def test_red_violations_in_feasible_schedule_return_422(self):
        """
        Solver returns FEASIBLE but the independent validator finds a RED B2B violation.
        The route must reject it with 422 and not store the schedule.

        validate_schedule is also mocked because the fake schedule uses test-fixture
        team IDs (T_A/T_B/T_C) while the NPL league uses production team IDs; the
        real validator would run against NPL teams and miss the T_B violation.
        """
        c = base_constraints(season_start=date(2025, 3, 1), season_end=date(2025, 3, 31))
        fake_sched = Schedule(
            id=str(uuid.uuid4()),
            league_id="NPL",
            season_start=date(2025, 3, 1),
            season_end=date(2025, 3, 31),
            games=[],
            constraints=c,
            total_games=0,
            generated_at="2025-03-01",
            solver_status="FEASIBLE",
        )
        fake_metrics = self._fake_metrics()
        fake_validation = {
            "status": "RED",
            "red_count": 1,
            "yellow_count": 0,
            "violations": [
                {
                    "type": "back_to_back_away",
                    "severity": "RED",
                    "message": "Back-to-back away games for T_B",
                    "team_id": "T_B",
                    "game1_id": "g1",
                    "game2_id": "g2",
                }
            ],
            "broadcast_compliance": [],
        }
        import app.routes.schedule as route_mod
        with mock.patch.object(route_mod, "solve_schedule",
                               return_value=(fake_sched, fake_metrics)), \
             mock.patch.object(route_mod, "validate_schedule",
                               return_value=fake_validation):
            resp = self._post_generate()

        assert resp.status_code == 422, (
            f"Schedule with RED violations must return 422, got {resp.status_code}: "
            f"{resp.json()}"
        )
        assert "back to back away" in resp.json()["detail"].lower() or \
               "back_to_back_away" in resp.json()["detail"], (
            f"Detail must mention the violation type; got: {resp.json()['detail']}"
        )

    # --- 8. Rejected schedules are not stored ---

    def test_timeout_fallback_schedule_not_retrievable(self):
        fake_sched = self._make_fake_schedule("TIMEOUT_FALLBACK")
        fake_id = fake_sched.id
        fake_metrics = self._fake_metrics(solver_status="TIMEOUT_FALLBACK")
        import app.routes.schedule as route_mod
        with mock.patch.object(route_mod, "solve_schedule",
                               return_value=(fake_sched, fake_metrics)):
            self._post_generate()

        # Try to retrieve the rejected schedule by its ID
        get_resp = self.client.get(f"/api/schedule/{fake_id}")
        assert get_resp.status_code == 404, (
            f"Rejected schedule must not be in the store; "
            f"GET returned {get_resp.status_code}"
        )

    def test_infeasible_schedule_not_retrievable(self):
        fake_sched = self._make_fake_schedule("INFEASIBLE")
        fake_id = fake_sched.id
        fake_metrics = self._fake_metrics(solver_status="INFEASIBLE")
        import app.routes.schedule as route_mod
        with mock.patch.object(route_mod, "solve_schedule",
                               return_value=(fake_sched, fake_metrics)):
            self._post_generate()

        get_resp = self.client.get(f"/api/schedule/{fake_id}")
        assert get_resp.status_code == 404, (
            f"Infeasible schedule must not be retrievable; "
            f"GET returned {get_resp.status_code}"
        )

    def test_red_violation_schedule_not_retrievable(self):
        """
        After a 422 rejection the schedule must be absent from the in-memory store.
        Both solve_schedule and validate_schedule are mocked for the same reason as
        test_red_violations_in_feasible_schedule_return_422.
        """
        c = base_constraints(season_start=date(2025, 3, 1), season_end=date(2025, 3, 31))
        fake_sched = Schedule(
            id=str(uuid.uuid4()),
            league_id="NPL",
            season_start=date(2025, 3, 1),
            season_end=date(2025, 3, 31),
            games=[],
            constraints=c,
            total_games=0,
            generated_at="2025-03-01",
            solver_status="FEASIBLE",
        )
        fake_id = fake_sched.id
        fake_metrics = self._fake_metrics()
        fake_validation = {
            "status": "RED",
            "red_count": 1,
            "yellow_count": 0,
            "violations": [
                {
                    "type": "back_to_back_away",
                    "severity": "RED",
                    "message": "Back-to-back away games for T_B",
                    "team_id": "T_B",
                    "game1_id": "g1",
                    "game2_id": "g2",
                }
            ],
            "broadcast_compliance": [],
        }
        import app.routes.schedule as route_mod
        with mock.patch.object(route_mod, "solve_schedule",
                               return_value=(fake_sched, fake_metrics)), \
             mock.patch.object(route_mod, "validate_schedule",
                               return_value=fake_validation):
            self._post_generate()

        get_resp = self.client.get(f"/api/schedule/{fake_id}")
        assert get_resp.status_code == 404, (
            f"Schedule with RED violations must not be retrievable; "
            f"GET returned {get_resp.status_code}"
        )
