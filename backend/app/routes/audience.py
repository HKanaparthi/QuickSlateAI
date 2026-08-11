from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List
from ..audience.estimator import compute_audience_analysis
from ..data import LEAGUES_BY_ID
from .schedule import _schedule_store

router = APIRouter(prefix="/api/audience", tags=["audience"])


@router.get("/{schedule_id}")
def get_audience_analysis(schedule_id: str):
    schedule = _schedule_store.get(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    league = LEAGUES_BY_ID.get(schedule.league_id)
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    return compute_audience_analysis(
        schedule.games,
        league.teams,
        schedule.constraints.rivalry_pairs,
    )
