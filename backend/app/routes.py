from fastapi import APIRouter
from typing import Optional

router = APIRouter()

@router.get("/health")
async def health():
    return {"status": "ok"}

@router.get("/metadata")
async def metadata():
    # Minimal metadata stub. Replace with DB queries.
    return {
        "repo_id": 1329242146,
        "leagues_count": 0,
        "teams_count": 0,
        "matches_count": 0,
        "date_range": None
    }
