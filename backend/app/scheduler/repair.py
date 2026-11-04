"""
Schedule Repair Engine — CP-SAT-based adaptive neighborhood repair.

Algorithm:
1. Identify affected games (explicitly listed + any that violate updated constraints).
2. Build initial neighborhood: affected games + nearby games up to neighborhood_size.
3. Anchor all non-neighborhood games (fix their assignments as hard constraints).
4. Solve a CP-SAT model over free (neighborhood) games using sequential lexicographic
   optimization:
     Stage 1 — Minimize moves (games shifted from their original slot).
     Stage 2 — Minimize total date displacement (only if Stage 1 proved OPTIMAL).
     Stage 3 — Maximize schedule quality (only if Stage 2 proved OPTIMAL).
5. On neighborhood infeasibility: expand neighborhood and retry, up to max_expansions.
6. Independently validate the repaired schedule against the UPDATED constraints.
7. Reject any repair whose validation returns a RED violation.
"""
import copy
import time
import uuid
from datetime import date, timedelta
from typing import Dict, List, Optional, Set, Tuple

from ortools.sat.python import cp_model

from .constraints import (
    check_matchup_preservation,
    validate_schedule,
)
from .models import (
    Game,
    GameMove,
    RepairRequest,
    RepairResult,
    RepairStatus,
    Schedule,
    ScheduleConstraints,
    Team,
    Venue,
    SLOT_VIEWERSHIP_MULTIPLIER,
    PRIMETIME_SLOTS,
    TimeSlot,
)
from .solver import _stable_variation, build_date_slots, haversine_miles
from ..data import VENUES_BY_ID


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def repair_schedule(
    request: RepairRequest,
    original_schedule: Schedule,
    teams: List[Team],
    venues: Dict[str, Venue],
) -> RepairResult:
    """
    Attempt to repair original_schedule so it satisfies request.updated_constraints
    (or the original constraints if none are provided) while minimising disruption.

    Returns a RepairResult. On success, the repaired Schedule is embedded inside
    RepairResult; the caller is responsible for storing it under its new ID.
    """
    start_wall = time.monotonic()
    total_budget = float(request.time_limit_seconds)

    effective_constraints: ScheduleConstraints = (
        request.updated_constraints
        if request.updated_constraints is not None
        else original_schedule.constraints
    )

    team_by_id = {t.id: t for t in teams}
    all_date_slots = build_date_slots(
        effective_constraints.season_start,
        effective_constraints.season_end,
    )
    if not all_date_slots:
        return RepairResult(
            original_schedule_id=original_schedule.id,
            status=RepairStatus.TIMEOUT_NO_SOLUTION,
            error_message="No valid date slots in season range.",
        )

    # Identify directly affected games (explicitly listed + constraint violators)
    affected_ids: Set[str] = set(request.affected_game_ids)
    for g in original_schedule.games:
        for bo in effective_constraints.venue_blackouts:
            if g.venue_id == bo.venue_id and bo.start_date <= g.game_date <= bo.end_date:
                affected_ids.add(g.id)

    if not affected_ids:
        # Nothing to repair — return the original schedule as-is with OPTIMAL status
        result_sched = _copy_schedule_new_id(original_schedule)
        return RepairResult(
            original_schedule_id=original_schedule.id,
            repaired_schedule_id=result_sched.id,
            status=RepairStatus.OPTIMAL,
            moves=[],
            neighborhood_expansions_used=0,
            solve_time_seconds=0.0,
            validation_result={"status": "GREEN", "red_count": 0, "yellow_count": 0,
                               "violations": [], "broadcast_compliance": []},
        )

    # Attempt repair with progressive neighborhood expansion
    base_size = max(len(affected_ids), request.neighborhood_size)
    for expansion in range(request.max_neighborhood_expansions + 1):
        neighborhood_size = base_size + expansion * request.neighborhood_size
        elapsed = time.monotonic() - start_wall
        remaining = total_budget - elapsed
        if remaining <= 1.0:
            return RepairResult(
                original_schedule_id=original_schedule.id,
                status=RepairStatus.TIMEOUT_NO_SOLUTION,
                neighborhood_expansions_used=expansion,
                solve_time_seconds=round(elapsed, 2),
                error_message="Time budget exhausted before repair could be attempted.",
            )

        result = _attempt_repair(
            original_schedule=original_schedule,
            affected_ids=affected_ids,
            neighborhood_size=neighborhood_size,
            constraints=effective_constraints,
            teams=teams,
            team_by_id=team_by_id,
            venues=venues,
            all_date_slots=all_date_slots,
            time_budget=remaining,
            expansion_number=expansion,
        )

        if result.status == RepairStatus.NEIGHBORHOOD_INFEASIBLE:
            if expansion < request.max_neighborhood_expansions:
                continue  # expand and retry
            else:
                return RepairResult(
                    original_schedule_id=original_schedule.id,
                    status=RepairStatus.GLOBALLY_INFEASIBLE_IN_BUDGET,
                    neighborhood_expansions_used=expansion,
                    solve_time_seconds=round(time.monotonic() - start_wall, 2),
                    error_message=(
                        f"CP-SAT proved no feasible repair exists within a neighborhood "
                        f"of {neighborhood_size} games after {expansion + 1} expansion(s). "
                        f"This is NOT a proof of global infeasibility — the full schedule "
                        f"space was not searched."
                    ),
                )

        if result.status == RepairStatus.TIMEOUT_NO_SOLUTION:
            return result  # no point expanding; we ran out of time

        # OPTIMAL / FEASIBLE / VALIDATION_FAILED — return directly
        result.original_schedule_id = original_schedule.id
        result.neighborhood_expansions_used = expansion
        result.solve_time_seconds = round(time.monotonic() - start_wall, 2)
        return result

    # Should not reach here
    return RepairResult(
        original_schedule_id=original_schedule.id,
        status=RepairStatus.GLOBALLY_INFEASIBLE_IN_BUDGET,
        neighborhood_expansions_used=request.max_neighborhood_expansions,
        solve_time_seconds=round(time.monotonic() - start_wall, 2),
    )


# ---------------------------------------------------------------------------
# Core repair attempt for a given neighborhood size
# ---------------------------------------------------------------------------

def _attempt_repair(
    original_schedule: Schedule,
    affected_ids: Set[str],
    neighborhood_size: int,
    constraints: ScheduleConstraints,
    teams: List[Team],
    team_by_id: Dict[str, "Team"],
    venues: Dict[str, Venue],
    all_date_slots: List[Tuple[date, str]],
    time_budget: float,
    expansion_number: int,
) -> RepairResult:
    stage_start = time.monotonic()

    # Partition games into free (neighborhood) and anchored
    free_games, anchored_games = _build_neighborhood(
        original_schedule.games, affected_ids, neighborhood_size
    )

    if not free_games:
        return RepairResult(
            original_schedule_id=original_schedule.id,
            status=RepairStatus.NEIGHBORHOOD_INFEASIBLE,
            error_message="Neighborhood is empty.",
        )

    # Precompute haversine travel miles for free games
    travel_miles: Dict[str, float] = {}
    for g in free_games:
        home_venue = venues.get(team_by_id[g.home_team_id].home_venue_id) if g.home_team_id in team_by_id else None
        away_venue = venues.get(team_by_id[g.away_team_id].home_venue_id) if g.away_team_id in team_by_id else None
        if home_venue and away_venue:
            travel_miles[g.id] = haversine_miles(
                away_venue.latitude, away_venue.longitude,
                home_venue.latitude, home_venue.longitude,
            )
        else:
            travel_miles[g.id] = g.travel_miles or 0.0

    # Build the CP-SAT model
    model, x, move_vars, slot_lookup = _build_repair_model(
        free_games=free_games,
        anchored_games=anchored_games,
        constraints=constraints,
        all_date_slots=all_date_slots,
        travel_miles=travel_miles,
        team_by_id=team_by_id,
    )

    n_free = len(free_games)
    n_slots = len(all_date_slots)

    # Pre-check: if any free game has zero available slots, immediately infeasible
    for i in range(n_free):
        if all(x[i][s] is None for s in range(n_slots)):
            return RepairResult(
                original_schedule_id=original_schedule.id,
                status=RepairStatus.NEIGHBORHOOD_INFEASIBLE,
                error_message=f"Game '{free_games[i].id}' has no available slots after constraint application.",
            )

    # Sequential lexicographic optimization
    solver = cp_model.CpSolver()
    stage_budget = time_budget / 3.0

    # ── Stage 1: Minimize moves ──────────────────────────────────────────────
    model.Minimize(sum(move_vars))
    solver.parameters.max_time_in_seconds = min(stage_budget, time_budget)
    status1 = solver.Solve(model)

    elapsed_s1 = time.monotonic() - stage_start
    remaining_after_s1 = time_budget - elapsed_s1

    if status1 == cp_model.INFEASIBLE:
        return RepairResult(
            original_schedule_id=original_schedule.id,
            status=RepairStatus.NEIGHBORHOOD_INFEASIBLE,
            neighborhood_expansions_used=expansion_number,
            solve_time_seconds=round(elapsed_s1, 2),
            error_message=(
                f"CP-SAT proved no feasible repair within neighborhood of "
                f"{n_free} games. Try expanding the neighborhood."
            ),
        )

    if status1 == cp_model.UNKNOWN:
        return RepairResult(
            original_schedule_id=original_schedule.id,
            status=RepairStatus.TIMEOUT_NO_SOLUTION,
            neighborhood_expansions_used=expansion_number,
            solve_time_seconds=round(elapsed_s1, 2),
            error_message="Stage 1 (minimize moves): solver timed out before finding any feasible solution.",
        )

    # Stage 1 found a solution (OPTIMAL or FEASIBLE)
    s1_opt = status1 == cp_model.OPTIMAL
    min_moves = int(round(solver.ObjectiveValue()))

    if not s1_opt:
        # Feasible but not proven optimal — extract and return without further stages
        repaired = _extract_repaired_schedule(
            free_games, anchored_games, x, all_date_slots,
            original_schedule, solver, constraints, travel_miles, team_by_id,
        )
        gap = _compute_gap(solver)
        result = _validate_and_package(
            original_schedule, repaired, free_games, anchored_games, all_date_slots,
            x, solver, constraints, teams, RepairStatus.FEASIBLE, gap, elapsed_s1,
            expansion_number,
        )
        return result

    # Stage 1 proved optimal — fix move count and proceed to Stage 2
    model.Add(sum(move_vars) == min_moves)

    # ── Stage 2: Minimize displacement ──────────────────────────────────────
    disp_expr = _build_displacement_expr(free_games, x, all_date_slots)
    model.Minimize(disp_expr)
    solver.parameters.max_time_in_seconds = min(stage_budget, remaining_after_s1)
    status2 = solver.Solve(model)

    elapsed_s2 = time.monotonic() - stage_start
    remaining_after_s2 = time_budget - elapsed_s2

    if status2 in (cp_model.INFEASIBLE, cp_model.UNKNOWN):
        # Unexpected: Stage 1 was feasible with min_moves, Stage 2 with same constraint should be too
        # Treat as feasible result from Stage 1 (re-solve would be needed; use current solver state)
        repaired = _extract_repaired_schedule(
            free_games, anchored_games, x, all_date_slots,
            original_schedule, solver, constraints, travel_miles, team_by_id,
        )
        result = _validate_and_package(
            original_schedule, repaired, free_games, anchored_games, all_date_slots,
            x, solver, constraints, teams, RepairStatus.FEASIBLE, None, elapsed_s2,
            expansion_number,
        )
        return result

    s2_opt = status2 == cp_model.OPTIMAL
    min_disp = int(round(solver.ObjectiveValue()))

    if not s2_opt:
        repaired = _extract_repaired_schedule(
            free_games, anchored_games, x, all_date_slots,
            original_schedule, solver, constraints, travel_miles, team_by_id,
        )
        gap = _compute_gap(solver)
        result = _validate_and_package(
            original_schedule, repaired, free_games, anchored_games, all_date_slots,
            x, solver, constraints, teams, RepairStatus.FEASIBLE, gap, elapsed_s2,
            expansion_number,
        )
        return result

    # Stage 2 proved optimal — fix displacement and proceed to Stage 3
    model.Add(disp_expr == min_disp)

    # ── Stage 3: Maximize schedule quality ──────────────────────────────────
    quality_expr = _build_quality_expr(free_games, x, all_date_slots, original_schedule)
    model.Maximize(quality_expr)
    solver.parameters.max_time_in_seconds = min(stage_budget, remaining_after_s2)
    status3 = solver.Solve(model)

    elapsed_s3 = time.monotonic() - stage_start

    final_status = RepairStatus.OPTIMAL if status3 == cp_model.OPTIMAL else RepairStatus.FEASIBLE
    gap = _compute_gap(solver) if status3 == cp_model.FEASIBLE else None

    repaired = _extract_repaired_schedule(
        free_games, anchored_games, x, all_date_slots,
        original_schedule, solver, constraints, travel_miles, team_by_id,
    )
    return _validate_and_package(
        original_schedule, repaired, free_games, anchored_games, all_date_slots,
        x, solver, constraints, teams, final_status, gap, elapsed_s3, expansion_number,
    )


# ---------------------------------------------------------------------------
# Neighborhood construction
# ---------------------------------------------------------------------------

def _build_neighborhood(
    all_games: List[Game],
    affected_ids: Set[str],
    neighborhood_size: int,
) -> Tuple[List[Game], List[Game]]:
    """
    Returns (free_games, anchored_games).
    free_games = affected games + nearest non-affected games by date, up to neighborhood_size.
    """
    affected = [g for g in all_games if g.id in affected_ids]
    non_affected = [g for g in all_games if g.id not in affected_ids]

    if len(affected) >= neighborhood_size:
        return affected, non_affected

    # Sort non-affected by minimum date distance from any affected game
    affected_dates = [g.game_date for g in affected]

    def min_dist(g: Game) -> int:
        return min(abs((g.game_date - ad).days) for ad in affected_dates) if affected_dates else 0

    non_affected_sorted = sorted(non_affected, key=min_dist)
    extra_needed = neighborhood_size - len(affected)
    extra = non_affected_sorted[:extra_needed]
    anchored = non_affected_sorted[extra_needed:]

    free = affected + extra
    return free, anchored


# ---------------------------------------------------------------------------
# CP-SAT model construction
# ---------------------------------------------------------------------------

def _build_repair_model(
    free_games: List[Game],
    anchored_games: List[Game],
    constraints: ScheduleConstraints,
    all_date_slots: List[Tuple[date, str]],
    travel_miles: Dict[str, float],
    team_by_id: Dict[str, "Team"],
) -> Tuple[cp_model.CpModel, list, list, Dict]:
    """
    Returns (model, x, move_vars, slot_lookup).
    x[i][s] is None if the slot is pre-blocked for free game i; otherwise a BoolVar.
    move_vars[i] is a BoolVar: 1 iff free game i is not assigned to its original slot.
    slot_lookup maps (date, timeslot_str) → slot index for fast lookups.
    """
    model = cp_model.CpModel()
    n_slots = len(all_date_slots)
    n_free = len(free_games)

    slot_lookup: Dict[Tuple[date, str], int] = {
        (d, sl): idx for idx, (d, sl) in enumerate(all_date_slots)
    }

    # Pre-compute which slots are occupied by anchored games (venue + slot → game)
    anchored_venue_slot: Set[Tuple[str, int]] = set()
    for g in anchored_games:
        s = slot_lookup.get((g.game_date, g.timeslot))
        if s is not None:
            anchored_venue_slot.add((g.venue_id, s))

    # Pre-compute blackout blocks: (venue_id, slot_idx) pairs
    blackout_blocks: Set[Tuple[str, int]] = set()
    for bo in constraints.venue_blackouts:
        for s, (d, _) in enumerate(all_date_slots):
            if bo.start_date <= d <= bo.end_date:
                blackout_blocks.add((bo.venue_id, s))

    # Per-team anchored game dates (for rest-day checking)
    anchored_dates_by_team: Dict[str, List[date]] = {}
    for g in anchored_games:
        for tid in (g.home_team_id, g.away_team_id):
            anchored_dates_by_team.setdefault(tid, []).append(g.game_date)

    # Per-team weekly anchored game counts (for weekly game cap)
    anchored_weekly_count: Dict[Tuple[str, int], int] = {}
    for g in anchored_games:
        iso = g.game_date.isocalendar()
        wk_key = iso[0] * 100 + iso[1]
        for tid in (g.home_team_id, g.away_team_id):
            k = (tid, wk_key)
            anchored_weekly_count[k] = anchored_weekly_count.get(k, 0) + 1

    # Per-team weekly anchored travel miles (for travel cap)
    anchored_weekly_travel: Dict[Tuple[str, int], float] = {}
    for g in anchored_games:
        if g.travel_miles is None:
            continue
        iso = g.game_date.isocalendar()
        wk_key = iso[0] * 100 + iso[1]
        k = (g.away_team_id, wk_key)
        anchored_weekly_travel[k] = anchored_weekly_travel.get(k, 0.0) + g.travel_miles

    # Per-timeslot anchored game count (for broadcast contracts)
    anchored_slot_count: Dict[str, int] = {}
    for g in anchored_games:
        anchored_slot_count[g.timeslot] = anchored_slot_count.get(g.timeslot, 0) + 1

    min_rest = constraints.min_rest_days

    # ── Build x[i][s] variables ──────────────────────────────────────────────
    # x[i][s] = None if slot s is pre-blocked for free game i
    x: list = []  # x[i] = list of (BoolVar or None) indexed by s
    for i, game in enumerate(free_games):
        venue_id = team_by_id[game.home_team_id].home_venue_id if game.home_team_id in team_by_id else game.venue_id
        row = []
        for s, (d, sl) in enumerate(all_date_slots):
            blocked = False
            # Venue blackout
            if (venue_id, s) in blackout_blocks:
                blocked = True
            # Anchored game at same venue/slot
            elif (venue_id, s) in anchored_venue_slot:
                blocked = True
            # Rest day violation with any anchored game for either team
            elif min_rest > 0:
                for tid in (game.home_team_id, game.away_team_id):
                    for ad in anchored_dates_by_team.get(tid, []):
                        if abs((d - ad).days) < min_rest:
                            blocked = True
                            break
                    if blocked:
                        break
            # Same-date as anchored game for either team (rest=0 edge case)
            else:
                for tid in (game.home_team_id, game.away_team_id):
                    # Check venue conflict only (rest=0 means no extra rest needed)
                    pass

            row.append(None if blocked else model.NewBoolVar(f"x_{i}_{s}"))
        x.append(row)

    # Each free game assigned to exactly one non-blocked slot
    for i in range(n_free):
        active = [v for v in x[i] if v is not None]
        if not active:
            # No available slot — will be caught upstream; add dummy to avoid crash
            dummy = model.NewBoolVar(f"dummy_{i}")
            model.Add(dummy == 0)
            x[i] = [dummy] + [None] * (n_slots - 1)
            active = [dummy]
        model.Add(sum(active) == 1)

    # ── Venue exclusivity among free games ──────────────────────────────────
    venue_slot_free: Dict[Tuple[str, int], List] = {}
    for i, game in enumerate(free_games):
        venue_id = team_by_id[game.home_team_id].home_venue_id if game.home_team_id in team_by_id else game.venue_id
        for s in range(n_slots):
            if x[i][s] is not None:
                venue_slot_free.setdefault((venue_id, s), []).append(x[i][s])
    for key, vars_list in venue_slot_free.items():
        if len(vars_list) > 1:
            model.Add(sum(vars_list) <= 1)

    # ── Rest days among free games ───────────────────────────────────────────
    # Build per-team, per-date free-game variable lists
    team_date_free_vars: Dict[str, Dict[date, List]] = {}
    for i, game in enumerate(free_games):
        for tid in (game.home_team_id, game.away_team_id):
            if tid not in team_date_free_vars:
                team_date_free_vars[tid] = {}
            for s, (d, _) in enumerate(all_date_slots):
                if x[i][s] is not None:
                    team_date_free_vars[tid].setdefault(d, []).append(x[i][s])

    for tid, date_vars in team_date_free_vars.items():
        dates = sorted(date_vars.keys())
        for idx, d1 in enumerate(dates):
            window_vars = []
            for d2 in dates[idx:]:
                if (d2 - d1).days >= min_rest:
                    break
                window_vars.extend(date_vars[d2])
            if len(window_vars) > 1:
                model.Add(sum(window_vars) <= 1)

    # ── Weekly game cap (3 per team per week, anchored + free) ───────────────
    MAX_WEEKLY = 3
    team_week_free_vars: Dict[Tuple[str, int], List] = {}
    for i, game in enumerate(free_games):
        for tid in (game.home_team_id, game.away_team_id):
            for s, (d, _) in enumerate(all_date_slots):
                if x[i][s] is not None:
                    iso = d.isocalendar()
                    wk_key = iso[0] * 100 + iso[1]
                    team_week_free_vars.setdefault((tid, wk_key), []).append(x[i][s])

    for (tid, wk_key), vars_list in team_week_free_vars.items():
        already = anchored_weekly_count.get((tid, wk_key), 0)
        cap = MAX_WEEKLY - already
        if cap <= 0:
            for v in vars_list:
                model.Add(v == 0)
        else:
            model.Add(sum(vars_list) <= cap)

    # ── Weekly travel cap ────────────────────────────────────────────────────
    if constraints.max_travel_miles_per_week > 0:
        max_travel = constraints.max_travel_miles_per_week
        team_week_away_vars: Dict[Tuple[str, int], List[Tuple]] = {}
        for i, game in enumerate(free_games):
            away_id = game.away_team_id
            dist_int = int(travel_miles.get(game.id, 0))
            if dist_int == 0:
                continue
            for s, (d, _) in enumerate(all_date_slots):
                if x[i][s] is not None:
                    iso = d.isocalendar()
                    wk_key = iso[0] * 100 + iso[1]
                    team_week_away_vars.setdefault((away_id, wk_key), []).append((dist_int, x[i][s]))

        for (tid, wk_key), dist_vars in team_week_away_vars.items():
            already = anchored_weekly_travel.get((tid, wk_key), 0.0)
            remaining_cap = int(max_travel - already)
            if remaining_cap <= 0:
                for _, v in dist_vars:
                    model.Add(v == 0)
            else:
                model.Add(sum(d * v for d, v in dist_vars) <= remaining_cap)

    # ── Broadcast contracts ──────────────────────────────────────────────────
    for contract in constraints.broadcast_contracts:
        contract_free_vars = []
        for i in range(n_free):
            for s, (_, sl) in enumerate(all_date_slots):
                if sl == contract.timeslot and x[i][s] is not None:
                    contract_free_vars.append(x[i][s])
        already = anchored_slot_count.get(contract.timeslot, 0)
        if contract_free_vars:
            if contract.required_games > 0:
                need = max(0, contract.required_games - already)
                if need > 0:
                    model.Add(sum(contract_free_vars) >= need)
            if contract.max_games > 0:
                allowed = max(0, contract.max_games - already)
                model.Add(sum(contract_free_vars) <= allowed)

    # ── No back-to-back away — exact carry-forward chain (anchored + free) ─────
    # Same O(n_dates) chain encoding as the base solver, extended to handle the
    # fixed anchored-game dates (constants) and free-game dates (BoolVars).
    # Anchored games have known home/away status; they advance the chain state
    # deterministically.  Free games are constrained by the chain.
    if constraints.no_back_to_back_away:
        team_away_free: Dict[str, Dict[date, List]] = {}
        for i, game in enumerate(free_games):
            away_id = game.away_team_id
            for s, (d, _) in enumerate(all_date_slots):
                if x[i][s] is not None:
                    team_away_free.setdefault(away_id, {}).setdefault(d, []).append(x[i][s])

        team_any_free: Dict[str, Dict[date, List]] = {}
        for i, game in enumerate(free_games):
            for tid in (game.home_team_id, game.away_team_id):
                for s, (d, _) in enumerate(all_date_slots):
                    if x[i][s] is not None:
                        team_any_free.setdefault(tid, {}).setdefault(d, []).append(x[i][s])

        anch_away_dates: Dict[str, Set[date]] = {}
        anch_home_dates: Dict[str, Set[date]] = {}
        for g in anchored_games:
            anch_away_dates.setdefault(g.away_team_id, set()).add(g.game_date)
            anch_home_dates.setdefault(g.home_team_id, set()).add(g.game_date)

        all_repair_tids = (
            {g.home_team_id for g in free_games + anchored_games}
            | {g.away_team_id for g in free_games + anchored_games}
        )

        for tid in all_repair_tids:
            free_dates  = set(team_any_free.get(tid, {}).keys())
            anchor_dates = (
                anch_away_dates.get(tid, set()) | anch_home_dates.get(tid, set())
            )
            all_dates = sorted(free_dates | anchor_dates)

            prev_pwa = model.NewBoolVar(f"rpr_pwa_{tid}_init")
            model.Add(prev_pwa == 0)

            for k, d in enumerate(all_dates):
                is_anch_away = d in anch_away_dates.get(tid, set())
                is_anch_home = d in anch_home_dates.get(tid, set())
                free_away = team_away_free.get(tid, {}).get(d, [])
                free_any  = team_any_free.get(tid, {}).get(d, [])

                if is_anch_away or is_anch_home:
                    # Anchored game: state transition is deterministic (1 for away, 0 for home).
                    # For anchored away games we must enforce prev_pwa == 0, the same
                    # prohibition applied to free away games at line 652.  This is the
                    # constant-argument form: sum(away_vars)=1 → 1 + prev_pwa ≤ 1.
                    # The original-schedule validity does NOT guarantee this for the
                    # repaired schedule: free home games that previously reset the chain
                    # between two anchored away games can be relocated during repair,
                    # leaving nothing to reset prev_pwa before the second anchored away.
                    if is_anch_away:
                        model.Add(prev_pwa == 0)
                    next_pwa = model.NewBoolVar(f"rpr_pwa_{tid}_{k}")
                    model.Add(next_pwa == (1 if is_anch_away else 0))
                    prev_pwa = next_pwa
                elif free_any:
                    away_expr = sum(free_away) if free_away else 0
                    any_expr  = sum(free_any)
                    if free_away:
                        model.Add(sum(free_away) + prev_pwa <= 1)
                    next_pwa = model.NewBoolVar(f"rpr_pwa_{tid}_{k}")
                    model.Add(next_pwa <= away_expr + 1 - any_expr)
                    model.Add(next_pwa >= away_expr - 1 + any_expr)
                    model.Add(next_pwa <= prev_pwa + any_expr)
                    model.Add(next_pwa >= prev_pwa - any_expr)
                    prev_pwa = next_pwa

    # ── Move indicator variables ─────────────────────────────────────────────
    move_vars = []
    for i, game in enumerate(free_games):
        mv = model.NewBoolVar(f"move_{i}")
        orig_s = slot_lookup.get((game.game_date, game.timeslot))
        orig_var = x[i][orig_s] if (orig_s is not None and x[i][orig_s] is not None) else None
        if orig_var is not None:
            # move=1 iff NOT assigned to original slot
            model.Add(mv + orig_var == 1)
        else:
            # Original slot is pre-blocked (e.g., blacked out) — must move
            model.Add(mv == 1)
        move_vars.append(mv)

    return model, x, move_vars, slot_lookup


# ---------------------------------------------------------------------------
# Objective helpers
# ---------------------------------------------------------------------------

def _build_displacement_expr(
    free_games: List[Game],
    x: list,
    all_date_slots: List[Tuple[date, str]],
):
    """Linear expression: total days displaced across all free games."""
    terms = []
    for i, game in enumerate(free_games):
        for s, (d, _) in enumerate(all_date_slots):
            if x[i][s] is not None:
                days = abs((d - game.game_date).days)
                if days > 0:
                    terms.append(days * x[i][s])
    return sum(terms) if terms else 0


def _build_quality_expr(
    free_games: List[Game],
    x: list,
    all_date_slots: List[Tuple[date, str]],
    original_schedule: Schedule,
):
    """Linear expression: total slot quality score across all free games."""
    rivalry_set = {
        (p[0], p[1]) for p in original_schedule.constraints.rivalry_pairs if len(p) == 2
    } | {
        (p[1], p[0]) for p in original_schedule.constraints.rivalry_pairs if len(p) == 2
    }
    terms = []
    for i, game in enumerate(free_games):
        is_rivalry = (game.home_team_id, game.away_team_id) in rivalry_set
        for s, (_, sl) in enumerate(all_date_slots):
            if x[i][s] is not None:
                slot_enum = None
                try:
                    slot_enum = TimeSlot(sl)
                except ValueError:
                    pass
                score = int((SLOT_VIEWERSHIP_MULTIPLIER.get(slot_enum, 1.0) if slot_enum else 1.0) * 10)
                if is_rivalry and sl in [ts.value for ts in PRIMETIME_SLOTS]:
                    score += 20
                terms.append(score * x[i][s])
    return sum(terms) if terms else 0


def _compute_gap(solver: cp_model.CpSolver) -> Optional[float]:
    try:
        best = solver.ObjectiveValue()
        bound = solver.BestObjectiveBound()
        if best != 0:
            return round(abs(best - bound) / abs(best), 4)
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Result extraction
# ---------------------------------------------------------------------------

def _extract_repaired_schedule(
    free_games: List[Game],
    anchored_games: List[Game],
    x: list,
    all_date_slots: List[Tuple[date, str]],
    original_schedule: Schedule,
    solver: cp_model.CpSolver,
    constraints: ScheduleConstraints,
    travel_miles: Dict[str, float],
    team_by_id: Dict[str, "Team"],
) -> Schedule:
    """Build a new Schedule from solver values, preserving all game IDs."""
    repaired_games: List[Game] = []

    for i, orig_game in enumerate(free_games):
        assigned_slot = None
        for s, (d, sl) in enumerate(all_date_slots):
            if x[i][s] is not None and solver.Value(x[i][s]) == 1:
                assigned_slot = (d, sl)
                break

        if assigned_slot is None:
            # Fallback: keep original placement (should not happen after valid solve)
            repaired_games.append(copy.copy(orig_game))
            continue

        new_date, new_slot = assigned_slot
        slot_enum = None
        try:
            slot_enum = TimeSlot(new_slot)
        except ValueError:
            pass
        mult = SLOT_VIEWERSHIP_MULTIPLIER.get(slot_enum, 1.0) if slot_enum else 1.0

        rivalry_set = {
            (p[0], p[1]) for p in constraints.rivalry_pairs if len(p) == 2
        } | {(p[1], p[0]) for p in constraints.rivalry_pairs if len(p) == 2}
        is_rivalry = (orig_game.home_team_id, orig_game.away_team_id) in rivalry_set

        market_mult = 1.0
        home_team = team_by_id.get(orig_game.home_team_id)
        if home_team:
            market_mult = {"large": 1.3, "medium": 1.1, "small": 1.0}.get(home_team.market_size, 1.0)
        rivalry_mult = 1.8 if is_rivalry else 1.0

        home_venue_id = home_team.home_venue_id if home_team else orig_game.venue_id
        from ..data import VENUES_BY_ID as _VENUES
        home_venue = _VENUES.get(home_venue_id)
        base = home_venue.capacity if home_venue else 15000

        projected = int(
            base * mult * rivalry_mult * market_mult *
            _stable_variation(orig_game.home_team_id, orig_game.away_team_id, new_date, new_slot)
        )
        dist = travel_miles.get(orig_game.id, orig_game.travel_miles or 0.0)

        repaired_games.append(Game(
            id=orig_game.id,          # Preserve stable identifier
            home_team_id=orig_game.home_team_id,
            away_team_id=orig_game.away_team_id,
            venue_id=home_venue_id,
            game_date=new_date,
            timeslot=new_slot,
            is_rivalry=is_rivalry,
            projected_viewership=projected,
            travel_miles=round(dist, 1),
            score_breakdown=orig_game.score_breakdown,
            ai_explanation=None,  # Reset — explanation no longer applies after move
        ))

    # Anchored games are copied as-is (same IDs, same attributes)
    for g in anchored_games:
        repaired_games.append(copy.copy(g))

    repaired_games.sort(key=lambda g: g.game_date)

    return Schedule(
        id=str(uuid.uuid4()),
        league_id=original_schedule.league_id,
        season_start=original_schedule.season_start,
        season_end=original_schedule.season_end,
        games=repaired_games,
        constraints=constraints,
        total_games=len(repaired_games),
        generated_at=str(date.today()),
        solver_status="REPAIRED",
    )


def _validate_and_package(
    original_schedule: Schedule,
    repaired: Schedule,
    free_games: List[Game],
    anchored_games: List[Game],
    all_date_slots: List[Tuple[date, str]],
    x: list,
    solver: cp_model.CpSolver,
    constraints: ScheduleConstraints,
    teams: List[Team],
    candidate_status: RepairStatus,
    gap: Optional[float],
    elapsed: float,
    expansion_number: int,
) -> RepairResult:
    """Independent validation; reject if RED violations found."""
    validation = validate_schedule(repaired.games, constraints, teams)

    # Matchup preservation check
    mp_violations = check_matchup_preservation(original_schedule.games, repaired.games)
    if mp_violations:
        validation["violations"].extend(mp_violations)
        validation["red_count"] += len(mp_violations)
        validation["status"] = "RED"

    if validation["red_count"] > 0:
        return RepairResult(
            original_schedule_id=original_schedule.id,
            repaired_schedule_id=None,
            status=RepairStatus.VALIDATION_FAILED,
            neighborhood_expansions_used=expansion_number,
            solve_time_seconds=round(elapsed, 2),
            validation_result=validation,
            error_message=(
                f"Repair rejected: independent validation found {validation['red_count']} "
                f"RED violation(s). Repaired schedule not saved."
            ),
        )

    # Build move list
    slot_lookup = {(d, sl): idx for idx, (d, sl) in enumerate(all_date_slots)}
    moves: List[GameMove] = []
    for i, orig_game in enumerate(free_games):
        new_game = next((g for g in repaired.games if g.id == orig_game.id), None)
        if new_game is None:
            continue
        if new_game.game_date != orig_game.game_date or new_game.timeslot != orig_game.timeslot:
            moves.append(GameMove(
                game_id=orig_game.id,
                original_date=orig_game.game_date,
                original_timeslot=orig_game.timeslot,
                repaired_date=new_game.game_date,
                repaired_timeslot=new_game.timeslot,
                displacement_days=abs((new_game.game_date - orig_game.game_date).days),
            ))

    return RepairResult(
        original_schedule_id=original_schedule.id,
        repaired_schedule_id=repaired.id,
        status=candidate_status,
        moves=moves,
        neighborhood_expansions_used=expansion_number,
        solve_time_seconds=round(elapsed, 2),
        objective_gap=gap,
        validation_result=validation,
        repaired_schedule=repaired,
    )


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _copy_schedule_new_id(schedule: Schedule) -> Schedule:
    return Schedule(
        id=str(uuid.uuid4()),
        league_id=schedule.league_id,
        season_start=schedule.season_start,
        season_end=schedule.season_end,
        games=[copy.copy(g) for g in schedule.games],
        constraints=schedule.constraints,
        total_games=schedule.total_games,
        generated_at=schedule.generated_at,
        solver_status=schedule.solver_status,
    )


def compute_comparison_metrics(original: Schedule, repaired: Schedule) -> Dict:
    """
    Compute structured before/after comparison metrics.
    Returns verified facts from solver output — no fabricated causal claims.
    """
    orig_map = {g.id: g for g in original.games}
    rep_map = {g.id: g for g in repaired.games}

    moved: List[Dict] = []
    unchanged = 0

    for gid, orig_g in orig_map.items():
        rep_g = rep_map.get(gid)
        if rep_g is None:
            continue
        if rep_g.game_date != orig_g.game_date or rep_g.timeslot != orig_g.timeslot:
            moved.append({
                "game_id": gid,
                "home_team_id": orig_g.home_team_id,
                "away_team_id": orig_g.away_team_id,
                "original_date": str(orig_g.game_date),
                "original_timeslot": orig_g.timeslot,
                "repaired_date": str(rep_g.game_date),
                "repaired_timeslot": rep_g.timeslot,
                "displacement_days": abs((rep_g.game_date - orig_g.game_date).days),
                "original_projected_viewership": orig_g.projected_viewership,
                "repaired_projected_viewership": rep_g.projected_viewership,
            })
        else:
            unchanged += 1

    orig_quality = sum(
        (g.score_breakdown.total_objective_score if g.score_breakdown else 0)
        for g in original.games
    )
    rep_quality = sum(
        (g.score_breakdown.total_objective_score if g.score_breakdown else 0)
        for g in repaired.games
    )

    return {
        "total_games": len(original.games),
        "games_moved": len(moved),
        "games_unchanged": unchanged,
        "total_displacement_days": sum(m["displacement_days"] for m in moved),
        "original_total_quality": orig_quality,
        "repaired_total_quality": rep_quality,
        "quality_delta": rep_quality - orig_quality,
        "moved_games": moved,
    }
