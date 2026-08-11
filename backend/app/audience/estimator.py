from typing import List, Dict, Set, Tuple
from ..scheduler.models import Game, Team, TimeSlot, SLOT_VIEWERSHIP_MULTIPLIER
from ..data import VENUES_BY_ID, TEAMS_BY_ID


MARKET_SIZE_MULTIPLIER = {"large": 1.3, "medium": 1.1, "small": 1.0}


def estimate_viewership(game: Game, teams_by_id: Dict[str, Team], rivalry_pairs: Set[Tuple[str, str]]) -> Dict:
    home = teams_by_id.get(game.home_team_id)
    away = teams_by_id.get(game.away_team_id)
    venue = VENUES_BY_ID.get(game.venue_id)

    base = venue.capacity if venue else 15000

    slot_enum = None
    try:
        slot_enum = TimeSlot(game.timeslot)
    except Exception:
        pass
    slot_mult = SLOT_VIEWERSHIP_MULTIPLIER.get(slot_enum, 1.0) if slot_enum else 1.0

    is_rivalry = game.is_rivalry or (game.home_team_id, game.away_team_id) in rivalry_pairs
    rivalry_mult = 1.8 if is_rivalry else 1.0

    home_market = MARKET_SIZE_MULTIPLIER.get(home.market_size if home else "medium", 1.1)
    away_market = MARKET_SIZE_MULTIPLIER.get(away.market_size if away else "medium", 1.1)
    market_mult = (home_market + away_market) / 2

    projected = int(base * slot_mult * rivalry_mult * market_mult)

    return {
        "game_id": game.id,
        "projected_viewership": projected,
        "base_viewership": base,
        "factors": {
            "slot": game.timeslot,
            "slot_multiplier": slot_mult,
            "is_rivalry": is_rivalry,
            "rivalry_multiplier": rivalry_mult,
            "home_market": home.market_size if home else "medium",
            "away_market": away.market_size if away else "medium",
            "market_multiplier": round(market_mult, 2),
        },
        "factor_contributions": {
            "timeslot": f"+{int((slot_mult - 1) * 100)}%" if slot_mult > 1 else f"{int((slot_mult - 1) * 100)}%",
            "rivalry": f"+{int((rivalry_mult - 1) * 100)}%" if is_rivalry else "0%",
            "market_size": f"+{int((market_mult - 1) * 100)}%",
        },
    }


def compute_audience_analysis(games: List[Game], teams: List[Team], rivalry_pairs: List[List[str]]) -> Dict:
    teams_by_id = {t.id: t for t in teams}
    rivalry_set: Set[Tuple[str, str]] = set()
    for pair in rivalry_pairs:
        if len(pair) == 2:
            rivalry_set.add((pair[0], pair[1]))
            rivalry_set.add((pair[1], pair[0]))

    game_estimates = []
    total_viewership = 0
    peak_games = []
    low_games = []

    for g in sorted(games, key=lambda x: x.game_date):
        est = estimate_viewership(g, teams_by_id, rivalry_set)
        home = teams_by_id.get(g.home_team_id)
        away = teams_by_id.get(g.away_team_id)
        game_estimates.append({
            **est,
            "game_date": str(g.game_date),
            "timeslot": g.timeslot,
            "home_team": home.name if home else g.home_team_id,
            "away_team": away.name if away else g.away_team_id,
            "is_rivalry": g.is_rivalry,
        })
        total_viewership += est["projected_viewership"]

    sorted_est = sorted(game_estimates, key=lambda x: x["projected_viewership"], reverse=True)
    peak_games = sorted_est[:3]
    low_games = sorted_est[-3:]

    avg_viewership = total_viewership // len(game_estimates) if game_estimates else 0

    timeslot_analysis: Dict[str, Dict] = {}
    for est in game_estimates:
        slot = est["timeslot"]
        if slot not in timeslot_analysis:
            timeslot_analysis[slot] = {"count": 0, "total": 0, "avg": 0}
        timeslot_analysis[slot]["count"] += 1
        timeslot_analysis[slot]["total"] += est["projected_viewership"]
    for slot in timeslot_analysis:
        cnt = timeslot_analysis[slot]["count"]
        timeslot_analysis[slot]["avg"] = timeslot_analysis[slot]["total"] // cnt if cnt else 0

    return {
        "game_estimates": game_estimates,
        "total_projected_viewership": total_viewership,
        "avg_viewership_per_game": avg_viewership,
        "peak_games": peak_games,
        "low_games": low_games,
        "timeslot_analysis": timeslot_analysis,
        "rivalry_premium": "Rivalry games generate on average 80% more viewership than non-rivalry games in the same timeslot.",
    }
