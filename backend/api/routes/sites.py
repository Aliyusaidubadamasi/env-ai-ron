from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/v1", tags=["sites"])


@router.get("/sites/{site_id}")
async def get_site(site_id: str) -> dict:
    if not site_id:
        raise HTTPException(status_code=400, detail="site_id is required")

    return {
        "site_id": site_id,
        "name": "Lagos Sample Site",
        "region": "Lagos",
        "center": {"lat": 6.5244, "lng": 3.3792},
        "status": "active",
        "ecological_score": 82.4,
    }
