import uuid
import random
from datetime import date, timedelta
from typing import List, Dict, Tuple, Set, Optional
from ortools.sat.python import cp_model

from .models import (
    Game,
    Schedule,
    ScheduleConstraints,
    ScoreBreakdown,
    Team,
    Venue,
    VenueBlackout,
    TimeSlot,
    SLOT_VIEWERSHIP_MULTIPLIER,
    PRIMETIME_SLOTS,
)
from ..data import VENUES_BY_ID


DAY_TO_SLOTS: Dict[int, List[str]] = {
    0: [TimeSlot.MON_EVENING],
    1: [TimeSlot.TUE_EVENING],
    2: [TimeSlot.WED_EVENING],
    3: [TimeSlot.THU_EVENING],
    4: [TimeSlot.FRI_EVENING],
    5: [TimeSlot.SAT_PRIMETIME],
    6: [TimeSlot.SUN_AFTERNOON],
}


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math
    R = 3958.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def build_date_slots(start: date, end: date) -> List[Tuple[date, str]]:
    slots = []
    current = start
    while current <= end:
        day_slots = DAY_TO_SLOTS.get(current.weekday(), [])
        for slot in day_slots:
            slots.append((current, slot))
        current += timedelta(days=1)
    return slots


def analyze_feasibility(
    constraints: ScheduleConstraints,
    teams: List[Team],
    venues: Dict[str, Venue],
) -> Dict:
    """Pre-solve analysis: detect constraint conflicts before running the optimizer."""
    n_teams = len(teams)
    n_games = n_teams * (n_teams - 1)
    date_slots = build_date_slots(constraints.season_start, constraints.season_end)
    n_slots = len(date_slots)
    season_days = (constraints.season_end - constraints.season_start).days

    issues = []
    warnings = []

    # Slot sufficiency
    if n_slots < n_games:
        issues.append({
            "type": "insufficient_slots",
            "severity": "hard",
            "message": f"Only {n_slots} available date-slots for {n_games} required games.",
            "suggestion": f"Extend the season end date, or enable more weekday slots.",
        })

    # Rest constraint tightness
    max_games_per_team = season_days // max(constraints.min_rest_days, 1)
    games_per_team = 2 * (n_teams - 1)
    if max_games_per_team < games_per_team:
        issues.append({
            "type": "rest_constraint_infeasible",
            "severity": "hard",
            "message": (
                f"With {constraints.min_rest_days}-day minimum rest, each team can play "
                f"at most {max_games_per_team} games in {season_days} days, but needs {games_per_team}."
            ),
            "suggestion": f"Reduce min_rest_days to ≤{season_days // games_per_team} or extend the season.",
        })
    elif max_games_per_team < games_per_team * 1.3:
        warnings.append(
            f"Rest constraint is tight — solver has only {(max_games_per_team/games_per_team - 1)*100:.0f}% scheduling margin per team."
        )

    # Broadcast contract feasibility
    slot_date_count: Dict[str, int] = {}
    for (_, slot) in date_slots:
        slot_date_count[slot] = slot_date_count.get(slot, 0) + 1

    for contract in constraints.broadcast_contracts:
        available_dates = slot_date_count.get(contract.timeslot, 0)
        max_possible = available_dates * (n_teams // 2)
        if contract.required_games > max_possible:
            issues.append({
                "type": "broadcast_contract_infeasible",
                "severity": "hard",
                "network": contract.network,
                "message": (
                    f"{contract.network} requires {contract.required_games} games in "
                    f"'{contract.timeslot}', but at most {max_possible} are possible "
                    f"({available_dates} dates × {n_teams//2} simultaneous venues)."
                ),
                "suggestion": f"Reduce required_games to ≤{max_possible} or extend the season.",
            })

    # Venue blackout feasibility
    for blackout in constraints.venue_blackouts:
        blacked_slots = sum(
            1 for (d, _) in date_slots
            if blackout.start_date <= d <= blackout.end_date
        )
        if blacked_slots > 0:
            home_games_needed = sum(
                1 for t in teams if t.home_venue_id == blackout.venue_id
            ) * (n_teams - 1)
            reason = f" ({blackout.reason})" if blackout.reason else ""
            warnings.append(
                f"Venue '{blackout.venue_id}' blacked out {blacked_slots} slot(s) "
                f"({blackout.start_date} – {blackout.end_date}){reason}. "
                f"{home_games_needed} home games still need scheduling in remaining slots."
            )

    # Weekly distribution sanity
    weeks = season_days / 7
    avg_games_per_week = n_games / max(weeks, 1)
    target_min = constraints.target_games_per_week - constraints.games_per_week_tolerance
    if constraints.even_distribution and avg_games_per_week < target_min * 0.5:
        warnings.append(
            f"Target {target_min}+ games/week may be too high for this season — "
            f"math allows only ~{avg_games_per_week:.1f}/week on average."
        )

    return {
        "is_feasible_estimate": not any(i["severity"] == "hard" for i in issues),
        "total_games": n_games,
        "available_slots": n_slots,
        "season_days": season_days,
        "games_per_team": games_per_team,
        "issues": issues,
        "warnings": warnings,
    }


def solve_schedule(
    constraints: ScheduleConstraints,
    teams: List[Team],
    venues: Dict[str, Venue],
) -> Tuple[Schedule, Dict]:
    n_teams = len(teams)
    team_ids = [t.id for t in teams]
    team_by_id = {t.id: t for t in teams}
    rivalry_set: Set[Tuple[str, str]] = set()
    for pair in constraints.rivalry_pairs:
        if len(pair) == 2:
            rivalry_set.add((pair[0], pair[1]))
            rivalry_set.add((pair[1], pair[0]))

    matchups: List[Tuple[str, str]] = []
    for i in range(n_teams):
        for j in range(n_teams):
            if i != j:
                matchups.append((team_ids[i], team_ids[j]))  # (home, away)

    date_slots = build_date_slots(constraints.season_start, constraints.season_end)
    if not date_slots:
        raise ValueError("No valid date slots in the given season range")

    n_matchups = len(matchups)
    n_slots = len(date_slots)

    # Precompute travel distance for each matchup (away team → home venue)
    travel_miles_per_matchup: Dict[int, float] = {}
    for m, (home_id, away_id) in enumerate(matchups):
        home_venue = venues.get(team_by_id[home_id].home_venue_id)
        away_venue = venues.get(team_by_id[away_id].home_venue_id)
        dist = 0.0
        if home_venue and away_venue:
            dist = haversine_miles(
                away_venue.latitude, away_venue.longitude,
                home_venue.latitude, home_venue.longitude,
            )
        travel_miles_per_matchup[m] = dist

    model = cp_model.CpModel()

    # x[m][s] = 1 if matchup m is assigned to slot s
    x = [[model.NewBoolVar(f"x_{m}_{s}") for s in range(n_slots)] for m in range(n_matchups)]

    # Each matchup assigned to exactly one slot
    for m in range(n_matchups):
        model.Add(sum(x[m][s] for s in range(n_slots)) == 1)

    # At most one game per venue per slot (home venue = home team's venue)
    slot_venue_games: Dict[Tuple[int, str], List] = {}
    for m, (home_id, _) in enumerate(matchups):
        venue_id = team_by_id[home_id].home_venue_id
        for s in range(n_slots):
            key = (s, venue_id)
            slot_venue_games.setdefault(key, []).append(x[m][s])
    for key, vars_list in slot_venue_games.items():
        model.Add(sum(vars_list) <= 1)

    # At most 2 games per team per week
    week_team_games: Dict[Tuple[int, str], List] = {}
    for m, (home_id, away_id) in enumerate(matchups):
        for s, (d, _) in enumerate(date_slots):
            iso_week = d.isocalendar()[1]
            iso_year = d.isocalendar()[0]
            week_key_home = (iso_year * 100 + iso_week, home_id)
            week_key_away = (iso_year * 100 + iso_week, away_id)
            week_team_games.setdefault(week_key_home, []).append(x[m][s])
            week_team_games.setdefault(week_key_away, []).append(x[m][s])
    for key, vars_list in week_team_games.items():
        model.Add(sum(vars_list) <= 3)

    # Rest days constraint — sliding window formulation (O(teams × dates × min_rest))
    # For each team and each date d, the team may have at most 1 game in [d, d+min_rest).
    # This is equivalent to "minimum min_rest days between any two consecutive games"
    # and is far more compact than the O(matchup_pairs² × slots) pairwise formulation.
    min_rest = constraints.min_rest_days

    # Build: date → list of (matchup_idx, slot_idx) for fast lookup
    date_to_matchup_slots: Dict[date, List[Tuple[int, int]]] = {}
    for m, (h, a) in enumerate(matchups):
        for s, (d, _) in enumerate(date_slots):
            date_to_matchup_slots.setdefault(d, []).append((m, s))

    for team_id in team_ids:
        # Group this team's game vars by date
        team_date_vars: Dict[date, List] = {}
        for m, (h, a) in enumerate(matchups):
            if h != team_id and a != team_id:
                continue
            for s, (d, _) in enumerate(date_slots):
                team_date_vars.setdefault(d, []).append(x[m][s])

        team_dates = sorted(team_date_vars.keys())
        for i, d1 in enumerate(team_dates):
            # Collect all game vars for this team in the window [d1, d1 + min_rest)
            window_vars = []
            for d2 in team_dates[i:]:
                if (d2 - d1).days >= min_rest:
                    break
                window_vars.extend(team_date_vars[d2])
            # At most 1 game for this team in the min_rest-day window starting at d1
            if len(window_vars) > 1:
                model.Add(sum(window_vars) <= 1)

    # ── Timeslot distribution & even weekly spread ───────────────────────────
    # Build (week_key, slot) → [vars] and week_key → [vars] indices
    slot_week_vars: Dict[Tuple[int, str], List] = {}
    week_total_vars: Dict[int, List] = {}
    for m, (home_id, away_id) in enumerate(matchups):
        for s, (d, slot) in enumerate(date_slots):
            iso = d.isocalendar()
            wk = iso[0] * 100 + iso[1]
            slot_week_vars.setdefault((wk, slot), []).append(x[m][s])
            week_total_vars.setdefault(wk, []).append(x[m][s])

    week_list = sorted(week_total_vars.keys())
    all_slot_names = list({slot for _, slot in date_slots})
    target = constraints.target_games_per_week
    tol = constraints.games_per_week_tolerance
    min_active = max(1, target - tol)
    max_active = target + tol
    min_slots = constraints.min_distinct_slots_per_week
    max_per_slot = constraints.max_games_per_slot_per_week

    # 1. Max N games per (week, timeslot) — prevents any one slot from dominating
    for key, vars_list in slot_week_vars.items():
        model.Add(sum(vars_list) <= max_per_slot)

    # 2. Build week_active vars; apply per-week distribution + distinct-slot constraints
    week_active_vars: Dict[int, object] = {}
    for wk, total_vars in week_total_vars.items():
        wa = model.NewBoolVar(f"wa_{wk}")
        model.Add(sum(total_vars) >= 1).OnlyEnforceIf(wa)
        model.Add(sum(total_vars) == 0).OnlyEnforceIf(wa.Not())
        week_active_vars[wk] = wa

        if constraints.even_distribution:
            # Active weeks must be in the dense target range (no thin 1-2 game weeks)
            model.Add(sum(total_vars) >= min_active).OnlyEnforceIf(wa)
            model.Add(sum(total_vars) <= max_active)

        # Distinct timeslots per active week
        slot_used_this_week = []
        for slot_name in all_slot_names:
            game_vars = slot_week_vars.get((wk, slot_name), [])
            if not game_vars:
                continue
            sv = model.NewBoolVar(f"su_{wk}_{slot_name[:4]}")
            model.Add(sum(game_vars) >= 1).OnlyEnforceIf(sv)
            model.Add(sum(game_vars) == 0).OnlyEnforceIf(sv.Not())
            slot_used_this_week.append(sv)
        if len(slot_used_this_week) >= min_slots:
            model.Add(sum(slot_used_this_week) >= min_slots).OnlyEnforceIf(wa)

    # 3. Even spacing across the season.
    #    Rule A — max gap: every window of 3 consecutive weeks must contain ≥1 active.
    #             This caps the idle stretch to 2 weeks and eliminates holiday voids.
    #    Rule B — min gap: no two consecutive weeks can BOTH be active.
    #             This prevents game weeks from bunching back-to-back.
    #    Together: game weeks are spaced 1–2 idle weeks apart (≈2-week rhythm).
    wa_list = [week_active_vars[wk] for wk in week_list]
    SPACING_WINDOW = 3  # max idle = SPACING_WINDOW - 1 = 2 weeks
    for i in range(len(wa_list) - SPACING_WINDOW + 1):
        model.Add(sum(wa_list[i: i + SPACING_WINDOW]) >= 1)   # max gap
    for i in range(len(wa_list) - 1):
        model.Add(wa_list[i] + wa_list[i + 1] <= 1)           # min gap

    # ── Weekly per-team travel cap (HARD) ────────────────────────────────────
    # For each (team, week): sum of away trip distances must not exceed the cap.
    # This is the first time travel distance feeds directly into the solver.
    max_travel = constraints.max_travel_miles_per_week
    # Build week_key → list of slot indices for fast lookup
    week_slot_indices: Dict[int, List[int]] = {}
    for s, (d, _) in enumerate(date_slots):
        wk = d.isocalendar()[0] * 100 + d.isocalendar()[1]
        week_slot_indices.setdefault(wk, []).append(s)

    for team_id in team_ids:
        for wk, slot_indices in week_slot_indices.items():
            weekly_travel_terms = []
            for m, (home_id, away_id) in enumerate(matchups):
                if away_id != team_id:
                    continue
                dist_int = int(travel_miles_per_matchup[m])
                for s in slot_indices:
                    weekly_travel_terms.append(dist_int * x[m][s])
            if weekly_travel_terms:
                model.Add(sum(weekly_travel_terms) <= max_travel)

    # ── Venue blackout windows (HARD) ────────────────────────────────────────
    # Precompute which (matchup, slot) pairs are blocked by a venue blackout.
    if constraints.venue_blackouts:
        blocked: set = set()
        for blackout in constraints.venue_blackouts:
            for s, (d, _) in enumerate(date_slots):
                if blackout.start_date <= d <= blackout.end_date:
                    blocked.add((blackout.venue_id, s))
        for m, (home_id, _) in enumerate(matchups):
            venue_id = team_by_id[home_id].home_venue_id
            for s in range(n_slots):
                if (venue_id, s) in blocked:
                    model.Add(x[m][s] == 0)

    # ── Broadcaster contractual requirements (HARD) ───────────────────────────
    # Enforce minimum and maximum game counts per contracted timeslot.
    # These represent legally binding inventory commitments to broadcast partners.
    for contract in constraints.broadcast_contracts:
        contract_slot_vars = []
        for m in range(n_matchups):
            for s, (_, slot) in enumerate(date_slots):
                if slot == contract.timeslot:
                    contract_slot_vars.append(x[m][s])
        if contract_slot_vars:
            if contract.required_games > 0:
                model.Add(sum(contract_slot_vars) >= contract.required_games)
            if contract.max_games > 0:
                model.Add(sum(contract_slot_vars) <= contract.max_games)

    # ─────────────────────────────────────────────────────────────────────────

    # Objective: maximize primetime/rivalry placement, penalize long away travel
    # travel_penalty = int(dist * travel_optimization_weight / 100)
    # → 1000 mi trip at weight 1.0 → 10 pt penalty, same order as slot scores (7–15)
    travel_weight = max(0.0, constraints.travel_optimization_weight)
    objective_terms = []
    for m, (home_id, away_id) in enumerate(matchups):
        is_rivalry = (home_id, away_id) in rivalry_set
        dist = travel_miles_per_matchup[m]
        travel_penalty = int(dist * travel_weight / 100) if travel_weight > 0 else 0
        for s, (d, slot) in enumerate(date_slots):
            score = 10
            slot_enum = TimeSlot(slot) if slot in [e.value for e in TimeSlot] else None
            if slot_enum:
                multiplier = SLOT_VIEWERSHIP_MULTIPLIER.get(slot_enum, 1.0)
                score = int(multiplier * 10)
            if is_rivalry and slot in [ts.value for ts in PRIMETIME_SLOTS]:
                score += 20
            score -= travel_penalty
            objective_terms.append(score * x[m][s])

    model.Maximize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30.0
    solver.parameters.num_search_workers = 4

    # Count constraints before solving for audit reporting
    n_hard_constraints = (
        n_matchups  # each matchup assigned exactly once
        + len(slot_venue_games)  # venue exclusivity
        + len(week_team_games)  # weekly per-team game cap
        + len([None for tid in team_ids for _ in range(20)])  # rest windows (approx)
        + len(slot_week_vars)  # slot-per-week caps
        + sum(1 for _ in constraints.venue_blackouts) * n_slots  # blackout blocks (approx)
        + len(constraints.broadcast_contracts) * 2  # contract min/max
        + (len(team_ids) * len(week_slot_indices))  # travel caps
    )

    status = solver.Solve(model)

    decisions_evaluated = solver.NumBranches()
    solve_time = round(solver.WallTime(), 2)
    obj_value = round(solver.ObjectiveValue(), 1) if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None

    games: List[Game] = []
    schedule_id = str(uuid.uuid4())

    infeasibility_reasons: List[str] = []

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for m, (home_id, away_id) in enumerate(matchups):
            for s in range(n_slots):
                if solver.Value(x[m][s]) == 1:
                    d, slot = date_slots[s]
                    venue_id = team_by_id[home_id].home_venue_id
                    is_rivalry = (home_id, away_id) in rivalry_set
                    home_venue = venues.get(venue_id)
                    dist = travel_miles_per_matchup[m]
                    slot_enum = None
                    try:
                        slot_enum = TimeSlot(slot)
                    except Exception:
                        pass
                    mult = SLOT_VIEWERSHIP_MULTIPLIER.get(slot_enum, 1.0) if slot_enum else 1.0
                    rivalry_mult = 1.8 if is_rivalry else 1.0
                    market_mult = {"large": 1.3, "medium": 1.1, "small": 1.0}.get(
                        team_by_id[home_id].market_size, 1.0
                    )
                    base_viewership = home_venue.capacity if home_venue else 15000
                    projected = int(base_viewership * mult * rivalry_mult * market_mult * random.uniform(0.7, 1.0))

                    timeslot_score = int(mult * 10)
                    rivalry_bonus = 20 if (is_rivalry and slot in [ts.value for ts in PRIMETIME_SLOTS]) else 0
                    budget_pct = int(dist / max(max_travel, 1) * 100)
                    t_penalty = int(dist * travel_weight / 100) if travel_weight > 0 else 0

                    reasons = []
                    if slot_enum in PRIMETIME_SLOTS:
                        reasons.append(f"primetime slot ({slot_enum.value if slot_enum else slot})")
                    if is_rivalry:
                        reasons.append("rivalry matchup")
                    if dist < max_travel * 0.5:
                        reasons.append("travel-efficient placement")
                    if travel_weight > 0 and t_penalty > 0:
                        reasons.append(f"travel penalized ({t_penalty} pts for {int(dist)} mi)")
                    summary = (
                        "Placed for: " + ", ".join(reasons)
                        if reasons else "Standard placement"
                    )

                    breakdown = ScoreBreakdown(
                        timeslot_score=timeslot_score,
                        rivalry_bonus=rivalry_bonus,
                        travel_miles=round(dist, 1),
                        travel_budget_pct=budget_pct,
                        travel_penalty=t_penalty,
                        total_objective_score=timeslot_score + rivalry_bonus - t_penalty,
                        summary=summary,
                    )

                    games.append(Game(
                        id=str(uuid.uuid4()),
                        home_team_id=home_id,
                        away_team_id=away_id,
                        venue_id=venue_id,
                        game_date=d,
                        timeslot=slot,
                        is_rivalry=is_rivalry,
                        projected_viewership=projected,
                        travel_miles=round(dist, 1),
                        score_breakdown=breakdown,
                    ))
                    break

        solver_status = "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE"
        if constraints.no_back_to_back_away:
            games = _repair_back_to_back_away(games, team_ids, date_slots, constraints.min_rest_days)
    else:
        if status == cp_model.INFEASIBLE:
            solver_status = "INFEASIBLE"
            infeasibility_reasons = _diagnose_infeasibility(constraints, teams, n_matchups, n_slots, date_slots)
        else:
            solver_status = "TIMEOUT_FALLBACK"
        games = _greedy_fallback(matchups, date_slots, team_by_id, venues, rivalry_set, constraints)

    games.sort(key=lambda g: g.game_date)

    schedule = Schedule(
        id=schedule_id,
        league_id=constraints.league_id,
        season_start=constraints.season_start,
        season_end=constraints.season_end,
        games=games,
        constraints=constraints,
        total_games=len(games),
        generated_at=str(date.today()),
        solver_status=solver_status,
    )

    metrics = {
        "decisions_evaluated": decisions_evaluated,
        "solve_time_seconds": solve_time,
        "total_variables": n_matchups * n_slots,
        "hard_constraints_count": max(0, n_hard_constraints),
        "solver_status": solver_status,
        "objective_value": obj_value,
        "infeasibility_reasons": infeasibility_reasons,
        "n_teams": n_teams,
        "n_matchups": n_matchups,
        "n_slots": n_slots,
    }

    return schedule, metrics


def _repair_back_to_back_away(
    games: List[Game],
    team_ids: List[str],
    date_slots: List[Tuple[date, str]],
    min_rest: int,
) -> List[Game]:
    """Post-solve greedy repair: move a home game into the gap between consecutive away games."""
    slot_set: Set[Tuple[str, date, str]] = {
        (g.venue_id, g.game_date, g.timeslot) for g in games
    }
    for _ in range(8):
        any_fixed = False
        for team_id in team_ids:
            t_games = sorted(
                (g for g in games if g.home_team_id == team_id or g.away_team_id == team_id),
                key=lambda g: g.game_date,
            )
            for i in range(len(t_games) - 1):
                g1, g2 = t_games[i], t_games[i + 1]
                if not (g1.away_team_id == team_id and g2.away_team_id == team_id):
                    continue
                d1, d2 = g1.game_date, g2.game_date
                for hg in games:
                    if hg.home_team_id != team_id or d1 <= hg.game_date <= d2:
                        continue
                    opp = hg.away_team_id
                    t_other = {g.game_date for g in games
                               if g.id != hg.id and (g.home_team_id == team_id or g.away_team_id == team_id)}
                    o_other = {g.game_date for g in games
                               if g.id != hg.id and (g.home_team_id == opp or g.away_team_id == opp)}
                    moved = False
                    for cand_d, cand_s in date_slots:
                        if not (d1 < cand_d < d2):
                            continue
                        if (hg.venue_id, cand_d, cand_s) in slot_set:
                            continue
                        if any(abs((cand_d - d).days) < min_rest for d in t_other):
                            continue
                        if any(abs((cand_d - d).days) < min_rest for d in o_other):
                            continue
                        slot_set.discard((hg.venue_id, hg.game_date, hg.timeslot))
                        hg.game_date = cand_d
                        hg.timeslot = cand_s
                        slot_set.add((hg.venue_id, cand_d, cand_s))
                        moved = any_fixed = True
                        break
                    if moved:
                        break
        if not any_fixed:
            break
    games.sort(key=lambda g: g.game_date)
    return games


def _greedy_fallback(matchups, date_slots, team_by_id, venues, rivalry_set, constraints):
    import random as rnd
    games = []
    used_slots: Dict[Tuple[str, int], bool] = {}
    team_last_game: Dict[str, date] = {}
    slot_list = list(enumerate(date_slots))
    rnd.shuffle(slot_list)

    for home_id, away_id in matchups:
        venue_id = team_by_id[home_id].home_venue_id
        is_rivalry = (home_id, away_id) in rivalry_set
        assigned = False

        candidates = sorted(
            slot_list,
            key=lambda x: (
                -(1.5 if "Saturday" in x[1][1] else 1.0) * (1.8 if is_rivalry else 1.0)
            ),
        )

        for s, (d, slot) in candidates:
            venue_slot_key = (venue_id, s)
            if venue_slot_key in used_slots:
                continue
            rest_ok = True
            for tid in [home_id, away_id]:
                if tid in team_last_game:
                    gap = abs((d - team_last_game[tid]).days)
                    if gap < constraints.min_rest_days:
                        rest_ok = False
                        break
            if not rest_ok:
                continue

            used_slots[venue_slot_key] = True
            for tid in [home_id, away_id]:
                if tid not in team_last_game or abs((d - team_last_game[tid]).days) > 0:
                    team_last_game[tid] = d

            home_venue = venues.get(venue_id)
            slot_enum = None
            try:
                slot_enum = TimeSlot(slot)
            except Exception:
                pass
            mult = SLOT_VIEWERSHIP_MULTIPLIER.get(slot_enum, 1.0) if slot_enum else 1.0
            rivalry_mult = 1.8 if is_rivalry else 1.0
            market_mult = {"large": 1.3, "medium": 1.1, "small": 1.0}.get(
                team_by_id[home_id].market_size, 1.0
            )
            base_viewership = home_venue.capacity if home_venue else 15000
            projected = int(base_viewership * mult * rivalry_mult * market_mult * random.uniform(0.7, 1.0))

            games.append(Game(
                id=str(uuid.uuid4()),
                home_team_id=home_id,
                away_team_id=away_id,
                venue_id=venue_id,
                game_date=d,
                timeslot=slot,
                is_rivalry=is_rivalry,
                projected_viewership=projected,
            ))
            assigned = True
            break

        if not assigned:
            s, (d, slot) = rnd.choice(slot_list)
            home_venue = venues.get(venue_id)
            base_viewership = home_venue.capacity if home_venue else 15000
            games.append(Game(
                id=str(uuid.uuid4()),
                home_team_id=home_id,
                away_team_id=away_id,
                venue_id=venue_id,
                game_date=d,
                timeslot=slot,
                is_rivalry=is_rivalry,
                projected_viewership=int(base_viewership * random.uniform(0.6, 0.9)),
            ))

    return games


def _diagnose_infeasibility(
    constraints: ScheduleConstraints,
    teams: List[Team],
    n_matchups: int,
    n_slots: int,
    date_slots: List[Tuple[date, str]],
) -> List[str]:
    """Identify likely reasons the CP-SAT solver returned INFEASIBLE."""
    reasons = []
    n_teams = len(teams)
    season_days = (constraints.season_end - constraints.season_start).days

    if n_slots < n_matchups:
        reasons.append(
            f"Too few scheduling slots: {n_slots} available date-slots for {n_matchups} required games. "
            f"Extend the season end date or reduce the minimum rest days."
        )

    max_games_per_team = season_days // max(constraints.min_rest_days, 1)
    games_per_team = 2 * (n_teams - 1)
    if max_games_per_team < games_per_team:
        reasons.append(
            f"Rest constraint infeasible: with {constraints.min_rest_days}-day rest, each team can play "
            f"at most {max_games_per_team} games in {season_days} days, but needs {games_per_team}. "
            f"Reduce min_rest_days to ≤{season_days // max(games_per_team, 1)} or extend the season."
        )

    slot_date_count: Dict[str, int] = {}
    for (_, slot) in date_slots:
        slot_date_count[slot] = slot_date_count.get(slot, 0) + 1

    for contract in constraints.broadcast_contracts:
        available = slot_date_count.get(contract.timeslot, 0)
        max_possible = available * (n_teams // 2)
        if contract.required_games > max_possible:
            reasons.append(
                f"Broadcast contract infeasible: {contract.network} requires {contract.required_games} games "
                f"in '{contract.timeslot}', but only {max_possible} are possible in this season window. "
                f"Reduce required_games to ≤{max_possible} or extend the season."
            )

    if constraints.venue_blackouts:
        blacked_by_venue: Dict[str, int] = {}
        for blackout in constraints.venue_blackouts:
            count = sum(1 for (d, _) in date_slots if blackout.start_date <= d <= blackout.end_date)
            blacked_by_venue[blackout.venue_id] = blacked_by_venue.get(blackout.venue_id, 0) + count
        for venue_id, blacked in blacked_by_venue.items():
            home_games = sum(1 for t in teams if t.home_venue_id == venue_id) * (n_teams - 1)
            if n_slots - blacked < home_games:
                reasons.append(
                    f"Venue blackout infeasible: venue '{venue_id}' is blacked out for {blacked} slot(s), "
                    f"leaving too few slots for {home_games} home games. Shorten the blackout window."
                )

    if constraints.even_distribution:
        weeks = season_days / 7
        avg_per_week = n_matchups / max(weeks, 1)
        target_min = constraints.target_games_per_week - constraints.games_per_week_tolerance
        if avg_per_week < target_min * 0.6:
            reasons.append(
                f"Even distribution target too high: the season math allows only ~{avg_per_week:.1f} games/week, "
                f"but the target band requires {target_min}+. Lower target_games_per_week or extend the season."
            )

    if not reasons:
        reasons.append(
            "The combined set of hard constraints (rest days, venue availability, broadcaster commitments, "
            "weekly travel cap, and distribution rules) has no feasible solution in this season window. "
            "Try relaxing one constraint at a time — start with min_rest_days or venue blackouts."
        )

    return reasons
