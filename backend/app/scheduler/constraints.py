from datetime import date, timedelta
from typing import List, Dict, Set, Tuple
from .models import Game, ScheduleConstraints, Team, Venue, SLOT_VIEWERSHIP_MULTIPLIER, TimeSlot


def get_team_games(team_id: str, games: List[Game]) -> List[Game]:
    return [g for g in games if g.home_team_id == team_id or g.away_team_id == team_id]


def check_rest_days(team_id: str, games: List[Game], min_rest: int) -> List[Dict]:
    violations = []
    team_games = sorted(get_team_games(team_id, games), key=lambda g: g.game_date)
    for i in range(len(team_games) - 1):
        gap = (team_games[i + 1].game_date - team_games[i].game_date).days
        if gap < min_rest:
            violations.append({
                "type": "rest_days",
                "severity": "RED",
                "team_id": team_id,
                "game1_id": team_games[i].id,
                "game2_id": team_games[i + 1].id,
                "message": f"Only {gap} rest days between games (minimum {min_rest})",
            })
    return violations


def check_venue_conflicts(games: List[Game]) -> List[Dict]:
    violations = []
    by_venue_slot: Dict[Tuple, List[Game]] = {}
    for g in games:
        key = (g.venue_id, g.game_date, g.timeslot)
        by_venue_slot.setdefault(key, []).append(g)
    for key, slot_games in by_venue_slot.items():
        if len(slot_games) > 1:
            violations.append({
                "type": "venue_conflict",
                "severity": "RED",
                "venue_id": key[0],
                "date": str(key[1]),
                "timeslot": key[2],
                "game_ids": [g.id for g in slot_games],
                "message": f"Venue double-booked: {len(slot_games)} games at same venue/time",
            })
    return violations


def check_back_to_back_away(team_id: str, games: List[Game]) -> List[Dict]:
    violations = []
    team_games = sorted(
        [g for g in games if g.home_team_id == team_id or g.away_team_id == team_id],
        key=lambda g: g.game_date,
    )
    for i in range(len(team_games) - 1):
        g1, g2 = team_games[i], team_games[i + 1]
        if g1.away_team_id == team_id and g2.away_team_id == team_id:
            violations.append({
                "type": "back_to_back_away",
                "severity": "YELLOW",
                "team_id": team_id,
                "game1_id": g1.id,
                "game2_id": g2.id,
                "message": "Back-to-back away games",
            })
    return violations


def check_home_away_balance(team_id: str, games: List[Game]) -> List[Dict]:
    violations = []
    home = sum(1 for g in games if g.home_team_id == team_id)
    away = sum(1 for g in games if g.away_team_id == team_id)
    total = home + away
    if total == 0:
        return []
    ratio = home / total if total > 0 else 0.5
    if abs(ratio - 0.5) > 0.15:
        violations.append({
            "type": "home_away_imbalance",
            "severity": "YELLOW",
            "team_id": team_id,
            "home_count": home,
            "away_count": away,
            "message": f"Home/away imbalance: {home} home, {away} away games",
        })
    return violations


MAX_GAMES_PER_TEAM_PER_WEEK = 3  # mirrors the solver hard constraint at solver.py:257


def check_weekly_game_cap(games: List[Game], team_ids: List[str]) -> List[Dict]:
    violations = []
    for team_id in team_ids:
        week_counts: Dict[Tuple[int, int], int] = {}
        for g in games:
            if g.home_team_id != team_id and g.away_team_id != team_id:
                continue
            iso = g.game_date.isocalendar()
            wk = (iso[0], iso[1])
            week_counts[wk] = week_counts.get(wk, 0) + 1
        for (yr, wk), count in week_counts.items():
            if count > MAX_GAMES_PER_TEAM_PER_WEEK:
                violations.append({
                    "type": "weekly_game_cap",
                    "severity": "RED",
                    "team_id": team_id,
                    "iso_year": yr,
                    "iso_week": wk,
                    "count": count,
                    "max": MAX_GAMES_PER_TEAM_PER_WEEK,
                    "message": (
                        f"Team '{team_id}' has {count} games in week {yr}-W{wk:02d} "
                        f"(max {MAX_GAMES_PER_TEAM_PER_WEEK})"
                    ),
                })
    return violations


def check_weekly_travel_cap(games: List[Game], team_ids: List[str], constraints: ScheduleConstraints) -> List[Dict]:
    if constraints.max_travel_miles_per_week <= 0:
        return []
    violations = []
    max_miles = constraints.max_travel_miles_per_week
    for team_id in team_ids:
        week_miles: Dict[Tuple[int, int], float] = {}
        for g in games:
            if g.away_team_id != team_id:
                continue
            if g.travel_miles is None:
                continue
            iso = g.game_date.isocalendar()
            wk = (iso[0], iso[1])
            week_miles[wk] = week_miles.get(wk, 0.0) + g.travel_miles
        for (yr, wk), miles in week_miles.items():
            if miles > max_miles:
                violations.append({
                    "type": "weekly_travel_cap",
                    "severity": "RED",
                    "team_id": team_id,
                    "iso_year": yr,
                    "iso_week": wk,
                    "miles": round(miles, 1),
                    "max": max_miles,
                    "message": (
                        f"Team '{team_id}' travels {miles:.0f} mi in week {yr}-W{wk:02d} "
                        f"(cap {max_miles} mi)"
                    ),
                })
    return violations


def check_matchup_preservation(original_games: List[Game], repaired_games: List[Game]) -> List[Dict]:
    """Verify the repaired schedule contains exactly the same (home, away) matchups as the original."""
    orig_matchups: Dict[Tuple[str, str], int] = {}
    for g in original_games:
        key = (g.home_team_id, g.away_team_id)
        orig_matchups[key] = orig_matchups.get(key, 0) + 1

    rep_matchups: Dict[Tuple[str, str], int] = {}
    for g in repaired_games:
        key = (g.home_team_id, g.away_team_id)
        rep_matchups[key] = rep_matchups.get(key, 0) + 1

    violations = []
    all_keys = set(orig_matchups) | set(rep_matchups)
    for key in all_keys:
        orig_count = orig_matchups.get(key, 0)
        rep_count = rep_matchups.get(key, 0)
        if orig_count != rep_count:
            violations.append({
                "type": "matchup_preservation",
                "severity": "RED",
                "home_team_id": key[0],
                "away_team_id": key[1],
                "original_count": orig_count,
                "repaired_count": rep_count,
                "message": (
                    f"Matchup ({key[0]} vs {key[1]}) appears {rep_count}× in repaired "
                    f"schedule but {orig_count}× in original"
                ),
            })
    return violations


def check_venue_blackout_compliance(games: List[Game], constraints: ScheduleConstraints) -> List[Dict]:
    if not constraints.venue_blackouts:
        return []
    violations = []
    for g in games:
        for blackout in constraints.venue_blackouts:
            if (
                g.venue_id == blackout.venue_id
                and blackout.start_date <= g.game_date <= blackout.end_date
            ):
                reason_suffix = f" ({blackout.reason})" if blackout.reason else ""
                violations.append({
                    "type": "venue_blackout",
                    "severity": "RED",
                    "game_id": g.id,
                    "venue_id": g.venue_id,
                    "date": str(g.game_date),
                    "blackout_start": str(blackout.start_date),
                    "blackout_end": str(blackout.end_date),
                    "reason": blackout.reason,
                    "message": (
                        f"Game at venue '{g.venue_id}' on {g.game_date} falls within "
                        f"blackout window {blackout.start_date}–{blackout.end_date}"
                        f"{reason_suffix}"
                    ),
                })
    return violations


def check_broadcast_compliance(games: List[Game], constraints: ScheduleConstraints) -> List[Dict]:
    """Verify broadcaster contractual commitments are met (hard constraints)."""
    compliance = []
    for contract in constraints.broadcast_contracts:
        actual = sum(1 for g in games if g.timeslot == contract.timeslot)
        if actual < contract.required_games:
            status = "UNDER"
        elif contract.max_games > 0 and actual > contract.max_games:
            status = "OVER"
        else:
            status = "OK"
        compliance.append({
            "network": contract.network,
            "timeslot": contract.timeslot,
            "required": contract.required_games,
            "max": contract.max_games,
            "actual": actual,
            "status": status,
        })
    return compliance


def validate_schedule(
    games: List[Game],
    constraints: ScheduleConstraints,
    teams: List[Team],
) -> Dict:
    all_violations = []

    # Derive full team-id set from games (covers cases where teams list is incomplete)
    game_team_ids = list({g.home_team_id for g in games} | {g.away_team_id for g in games})
    team_ids_from_roster = [t.id for t in teams]
    all_team_ids = list(set(game_team_ids + team_ids_from_roster))

    all_violations.extend(check_venue_conflicts(games))
    all_violations.extend(check_venue_blackout_compliance(games, constraints))
    all_violations.extend(check_weekly_game_cap(games, all_team_ids))
    all_violations.extend(check_weekly_travel_cap(games, all_team_ids, constraints))

    for team in teams:
        all_violations.extend(check_rest_days(team.id, games, constraints.min_rest_days))
        if constraints.no_back_to_back_away:
            b2b_viols = check_back_to_back_away(team.id, games)
            for v in b2b_viols:
                v["severity"] = "RED"
            all_violations.extend(b2b_viols)
        if constraints.home_away_balanced:
            all_violations.extend(check_home_away_balance(team.id, games))

    broadcast_compliance = check_broadcast_compliance(games, constraints)
    for item in broadcast_compliance:
        if item["status"] == "UNDER":
            all_violations.append({
                "type": "broadcast_undercount",
                "severity": "RED",
                "message": (
                    f"{item['network']} requires {item['required']} games in "
                    f"'{item['timeslot']}' — only {item['actual']} scheduled"
                ),
            })
        elif item["status"] == "OVER":
            all_violations.append({
                "type": "broadcast_overcount",
                "severity": "RED",
                "message": (
                    f"{item['network']} max {item['max']} games in "
                    f"'{item['timeslot']}' — {item['actual']} scheduled"
                ),
            })

    red = [v for v in all_violations if v["severity"] == "RED"]
    yellow = [v for v in all_violations if v["severity"] == "YELLOW"]

    return {
        "violations": all_violations,
        "red_count": len(red),
        "yellow_count": len(yellow),
        "status": "RED" if red else ("YELLOW" if yellow else "GREEN"),
        "broadcast_compliance": broadcast_compliance,
    }
