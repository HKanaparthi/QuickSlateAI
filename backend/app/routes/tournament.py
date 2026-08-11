from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from ..tournament.bracket import generate_bracket

router = APIRouter(prefix="/api/tournament", tags=["tournament"])


class TournamentRequest(BaseModel):
    team_names: List[str]
    format: str = "single_elimination"  # single_elimination | round_robin | pool_play_knockout
    num_fields: int = 2
    pools: int = 2
    game_duration_minutes: int = 60
    break_minutes: int = 15


@router.post("/generate")
def generate_tournament(req: TournamentRequest):
    if len(req.team_names) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 teams")
    if len(req.team_names) > 64:
        raise HTTPException(status_code=400, detail="Maximum 64 teams supported")
    bracket = generate_bracket(req.team_names, req.format, req.num_fields, req.pools)
    return bracket
