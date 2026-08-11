import math
from typing import List, Dict, Tuple
from datetime import date, timedelta
from ..scheduler.models import Game, Team, Venue
from ..data import VENUES_BY_ID, TEAMS_BY_ID


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 3958.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def compute_travel_analysis(games: List[Game], teams: List[Team]) -> Dict:
    team_stats: Dict[str, Dict] = {}

    for team in teams:
        team_games = sorted(
            [g for g in games if g.home_team_id == team.id or g.away_team_id == team.id],
            key=lambda g: g.game_date,
        )

        home_venue = VENUES_BY_ID.get(team.home_venue_id)
        if not home_venue:
            continue

        total_miles = 0.0
        longest_trip = 0.0
        travel_legs: List[Dict] = []
        current_location = home_venue

        weekly_miles: Dict[str, float] = {}

        for g in team_games:
            game_venue = VENUES_BY_ID.get(g.venue_id)
            if not game_venue:
                continue

            if current_location.id != game_venue.id:
                dist = haversine_miles(
                    current_location.latitude, current_location.longitude,
                    game_venue.latitude, game_venue.longitude,
                )
                total_miles += dist
                longest_trip = max(longest_trip, dist)

                iso_week = f"{g.game_date.isocalendar()[0]}-W{g.game_date.isocalendar()[1]:02d}"
                weekly_miles[iso_week] = weekly_miles.get(iso_week, 0) + dist

                travel_legs.append({
                    "from_city": current_location.city,
                    "to_city": game_venue.city,
                    "from_lat": current_location.latitude,
                    "from_lng": current_location.longitude,
                    "to_lat": game_venue.latitude,
                    "to_lng": game_venue.longitude,
                    "distance_miles": round(dist, 1),
                    "game_date": str(g.game_date),
                    "game_id": g.id,
                })
                current_location = game_venue

        # Return home after last away game
        if current_location.id != home_venue.id:
            dist = haversine_miles(
                current_location.latitude, current_location.longitude,
                home_venue.latitude, home_venue.longitude,
            )
            total_miles += dist

        n_weeks = max(len(weekly_miles), 1)
        team_stats[team.id] = {
            "team_id": team.id,
            "team_name": team.name,
            "total_miles": round(total_miles, 1),
            "avg_miles_per_week": round(total_miles / n_weeks, 1),
            "longest_trip_miles": round(longest_trip, 1),
            "travel_legs": travel_legs,
            "weekly_miles": weekly_miles,
            "home_venue": {
                "id": home_venue.id,
                "name": home_venue.name,
                "city": home_venue.city,
                "lat": home_venue.latitude,
                "lng": home_venue.longitude,
            },
        }

    all_totals = [s["total_miles"] for s in team_stats.values()]
    league_avg = sum(all_totals) / len(all_totals) if all_totals else 0

    fairness_analysis = []
    for tid, stats in team_stats.items():
        pct_diff = ((stats["total_miles"] - league_avg) / league_avg * 100) if league_avg else 0
        fairness_analysis.append({
            "team_id": tid,
            "team_name": stats["team_name"],
            "total_miles": stats["total_miles"],
            "pct_vs_avg": round(pct_diff, 1),
            "flagged": abs(pct_diff) > 20,
        })

    hotel_suggestions = _compute_hotel_suggestions(games, teams)

    return {
        "team_stats": team_stats,
        "league_avg_miles": round(league_avg, 1),
        "fairness_analysis": fairness_analysis,
        "hotel_suggestions": hotel_suggestions,
        "venues": [
            {
                "id": v.id,
                "name": v.name,
                "city": v.city,
                "lat": v.latitude,
                "lng": v.longitude,
                "capacity": v.capacity,
            }
            for v in VENUES_BY_ID.values()
            if any(g.venue_id == v.id for g in games)
        ],
    }


def _compute_hotel_suggestions(games: List[Game], teams: List[Team]) -> List[Dict]:
    suggestions = []
    for team in teams:
        away_games = sorted(
            [g for g in games if g.away_team_id == team.id],
            key=lambda g: g.game_date,
        )
        i = 0
        while i < len(away_games) - 1:
            g1 = away_games[i]
            g2 = away_games[i + 1]
            gap = (g2.game_date - g1.game_date).days
            if 1 <= gap <= 4:
                v1 = VENUES_BY_ID.get(g1.venue_id)
                v2 = VENUES_BY_ID.get(g2.venue_id)
                if v1 and v2:
                    dist = haversine_miles(v1.latitude, v1.longitude, v2.latitude, v2.longitude)
                    home_v = VENUES_BY_ID.get(team.home_venue_id)
                    home_dist = haversine_miles(
                        v1.latitude, v1.longitude,
                        home_v.latitude, home_v.longitude,
                    ) if home_v else 999
                    if dist < home_dist * 0.6:
                        suggestions.append({
                            "team_id": team.id,
                            "team_name": team.name,
                            "game1_date": str(g1.game_date),
                            "game1_city": v1.city,
                            "game2_date": str(g2.game_date),
                            "game2_city": v2.city,
                            "stay_city": v1.city,
                            "distance_between_games": round(dist, 1),
                            "savings_miles": round(home_dist * 2 - dist, 1),
                            "message": (
                                f"{team.name} plays at {v1.city} ({g1.game_date}) and "
                                f"{v2.city} ({g2.game_date}) — recommend staying in {v1.city} "
                                f"to save ~{round(home_dist * 2 - dist):.0f} miles of travel."
                            ),
                        })
            i += 1
    return suggestions
