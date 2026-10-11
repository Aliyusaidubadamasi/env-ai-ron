from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/v1", tags=["analysis"])


@router.post("/sites/{site_id}/analyze")
async def analyze_site(site_id: str) -> dict:
    if not site_id:
        raise HTTPException(status_code=400, detail="site_id is required")

    return {
        "site_id": site_id,
        "message": "Analysis queued successfully",
        "land_cover_classes": ["concrete", "existing_canopy", "bare_soil"],
        "status": "processing",
    }
