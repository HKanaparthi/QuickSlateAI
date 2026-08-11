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


def validate_schedule(
    games: List[Game],
    constraints: ScheduleConstraints,
    teams: List[Team],
) -> Dict:
    all_violations = []

    all_violations.extend(check_venue_conflicts(games))

    for team in teams:
        all_violations.extend(check_rest_days(team.id, games, constraints.min_rest_days))
        if constraints.no_back_to_back_away:
            all_violations.extend(check_back_to_back_away(team.id, games))
        if constraints.home_away_balanced:
            all_violations.extend(check_home_away_balance(team.id, games))

    red = [v for v in all_violations if v["severity"] == "RED"]
    yellow = [v for v in all_violations if v["severity"] == "YELLOW"]

    return {
        "violations": all_violations,
        "red_count": len(red),
        "yellow_count": len(yellow),
        "status": "RED" if red else ("YELLOW" if yellow else "GREEN"),
    }
