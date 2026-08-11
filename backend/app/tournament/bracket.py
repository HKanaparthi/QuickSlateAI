import uuid
import math
from typing import List, Dict, Optional, Any


def generate_single_elimination(teams: List[str], num_fields: int = 2) -> Dict:
    n = len(teams)
    # Pad to next power of 2
    size = 1
    while size < n:
        size *= 2
    padded = teams + [None] * (size - n)

    rounds = []
    current_round = padded
    round_num = 1
    field_counter = 0

    while len(current_round) > 1:
        matchups = []
        next_round_size = len(current_round) // 2
        for i in range(0, len(current_round), 2):
            t1 = current_round[i]
            t2 = current_round[i + 1] if i + 1 < len(current_round) else None
            field_counter = (field_counter % num_fields) + 1
            matchup = {
                "id": str(uuid.uuid4()),
                "team1": t1,
                "team2": t2,
                "winner": t1 if t2 is None else None,
                "field": f"Field {field_counter}",
                "is_bye": t2 is None,
                "round": round_num,
            }
            matchups.append(matchup)
        rounds.append({"round": round_num, "name": _round_name(round_num, size), "matchups": matchups})
        current_round = [m["team1"] if m["is_bye"] else None for m in matchups]
        round_num += 1

    return {
        "format": "single_elimination",
        "teams": teams,
        "total_rounds": len(rounds),
        "rounds": rounds,
        "champion": None,
    }


def generate_round_robin(teams: List[str], num_fields: int = 2) -> Dict:
    n = len(teams)
    schedule = []
    # Circle algorithm for round-robin scheduling
    team_list = list(teams)
    if n % 2 == 1:
        team_list.append("BYE")
    n2 = len(team_list)
    rounds = n2 - 1

    field_counter = 0
    game_num = 1
    round_schedule = []

    for r in range(rounds):
        round_games = []
        for i in range(n2 // 2):
            t1 = team_list[i]
            t2 = team_list[n2 - 1 - i]
            if t1 != "BYE" and t2 != "BYE":
                field_counter = (field_counter % num_fields) + 1
                round_games.append({
                    "id": str(uuid.uuid4()),
                    "team1": t1,
                    "team2": t2,
                    "field": f"Field {field_counter}",
                    "game_number": game_num,
                    "round": r + 1,
                })
                game_num += 1
        round_schedule.append({"round": r + 1, "name": f"Round {r + 1}", "matchups": round_games})
        # Rotate (keep first element fixed)
        team_list = [team_list[0]] + [team_list[-1]] + team_list[1:-1]

    return {
        "format": "round_robin",
        "teams": teams,
        "total_rounds": rounds,
        "rounds": round_schedule,
        "total_games": game_num - 1,
    }


def generate_pool_play_knockout(teams: List[str], num_fields: int = 2, pools: int = 2) -> Dict:
    pool_size = len(teams) // pools
    team_pools = [teams[i * pool_size: (i + 1) * pool_size] for i in range(pools)]
    remainder = teams[pools * pool_size:]
    for i, t in enumerate(remainder):
        team_pools[i % pools].append(t)

    pool_stages = []
    for i, pool_teams in enumerate(team_pools):
        rr = generate_round_robin(pool_teams, num_fields)
        pool_stages.append({"pool": f"Pool {chr(65 + i)}", "schedule": rr})

    top_per_pool = max(1, 2)
    advancing = [f"Pool {chr(65+i)} 1st" for i in range(pools)] + \
                [f"Pool {chr(65+i)} 2nd" for i in range(pools)]

    knockout = generate_single_elimination(advancing, num_fields)

    return {
        "format": "pool_play_knockout",
        "pool_stages": pool_stages,
        "knockout_stage": knockout,
        "teams": teams,
    }


def generate_bracket(
    team_names: List[str],
    format: str = "single_elimination",
    num_fields: int = 2,
    pools: int = 2,
) -> Dict:
    if format == "single_elimination":
        return generate_single_elimination(team_names, num_fields)
    elif format == "round_robin":
        return generate_round_robin(team_names, num_fields)
    elif format == "pool_play_knockout":
        return generate_pool_play_knockout(team_names, num_fields, pools)
    else:
        return generate_single_elimination(team_names, num_fields)


def _round_name(round_num: int, bracket_size: int) -> str:
    total_rounds = int(math.log2(bracket_size))
    from_end = total_rounds - round_num + 1
    names = {1: "Final", 2: "Semifinals", 3: "Quarterfinals", 4: "Round of 16", 5: "Round of 32"}
    return names.get(from_end, f"Round {round_num}")
