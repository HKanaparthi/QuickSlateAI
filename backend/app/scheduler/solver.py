import uuid
import random
from datetime import date, timedelta
from typing import List, Dict, Tuple, Set
from ortools.sat.python import cp_model

from .models import (
    Game,
    Schedule,
    ScheduleConstraints,
    Team,
    Venue,
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


def solve_schedule(
    constraints: ScheduleConstraints,
    teams: List[Team],
    venues: Dict[str, Venue],
) -> Schedule:
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

    all_dates = sorted(date_to_matchup_slots.keys())

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

    # ─────────────────────────────────────────────────────────────────────────

    # ── No back-to-back away games ────────────────────────────────────────────
    # Two away-game slots s1 < s2 for the same team are "consecutive" when the
    # team has no game between them. The constraint forbids that pattern by
    # requiring sum(between_game_indicators) >= 1 whenever both slots are away.
    # Formulation: away[s1] + away[s2] <= 1 + any_team_game_between(s1, s2)
    if constraints.no_back_to_back_away:
        # Precompute per (team, slot): away-game x-vars and any-game x-vars
        away_s: Dict[Tuple[str, int], List] = {}
        any_s: Dict[Tuple[str, int], List] = {}
        for m, (h, a) in enumerate(matchups):
            for s in range(n_slots):
                any_s.setdefault((h, s), []).append(x[m][s])
                any_s.setdefault((a, s), []).append(x[m][s])
                away_s.setdefault((a, s), []).append(x[m][s])

        # Auxiliary BoolVar: team plays ANY game (home or away) at slot s
        ta: Dict[Tuple[str, int], object] = {}
        for (tid, s), vlist in any_s.items():
            b = model.NewBoolVar(f"ta_{tid[:4]}_{s}")
            model.Add(sum(vlist) >= 1).OnlyEnforceIf(b)
            model.Add(sum(vlist) == 0).OnlyEnforceIf(b.Not())
            ta[(tid, s)] = b

        MAX_AWAY_GAP_DAYS = 70  # covers gaps up to 10 weeks between consecutive games
        for team_id in team_ids:
            a_slots = sorted(s for s in range(n_slots) if away_s.get((team_id, s)))
            for i, s1 in enumerate(a_slots):
                d1 = date_slots[s1][0]
                for s2 in a_slots[i + 1:]:
                    d2 = date_slots[s2][0]
                    if (d2 - d1).days > MAX_AWAY_GAP_DAYS:
                        break
                    between = [
                        ta[(team_id, sb)]
                        for sb in range(s1 + 1, s2)
                        if (team_id, sb) in ta
                    ]
                    model.Add(
                        sum(away_s[(team_id, s1)]) + sum(away_s[(team_id, s2)])
                        <= 1 + sum(between)
                    )

    # ─────────────────────────────────────────────────────────────────────────

    # Objective: maximize primetime placement for rivalry games + minimize travel
    objective_terms = []
    for m, (home_id, away_id) in enumerate(matchups):
        is_rivalry = (home_id, away_id) in rivalry_set
        home_venue = venues.get(team_by_id[home_id].home_venue_id)
        for s, (d, slot) in enumerate(date_slots):
            score = 10
            slot_enum = TimeSlot(slot) if slot in [e.value for e in TimeSlot] else None
            if slot_enum:
                multiplier = SLOT_VIEWERSHIP_MULTIPLIER.get(slot_enum, 1.0)
                score = int(multiplier * 10)
            if is_rivalry and slot in [ts.value for ts in PRIMETIME_SLOTS]:
                score += 20
            objective_terms.append(score * x[m][s])

    model.Maximize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30.0
    solver.parameters.num_search_workers = 4
    status = solver.Solve(model)

    games: List[Game] = []
    schedule_id = str(uuid.uuid4())

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for m, (home_id, away_id) in enumerate(matchups):
            for s in range(n_slots):
                if solver.Value(x[m][s]) == 1:
                    d, slot = date_slots[s]
                    venue_id = team_by_id[home_id].home_venue_id
                    is_rivalry = (home_id, away_id) in rivalry_set
                    home_venue = venues.get(venue_id)
                    away_venue = venues.get(team_by_id[away_id].home_venue_id)
                    dist = 0.0
                    if home_venue and away_venue:
                        dist = haversine_miles(
                            away_venue.latitude, away_venue.longitude,
                            home_venue.latitude, home_venue.longitude,
                        )
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
                    break

        solver_status = "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE"
    else:
        games = _greedy_fallback(matchups, date_slots, team_by_id, venues, rivalry_set, constraints)
        solver_status = "GREEDY_FALLBACK"

    games.sort(key=lambda g: g.game_date)

    return Schedule(
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
            away_venue = venues.get(team_by_id[away_id].home_venue_id)
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
