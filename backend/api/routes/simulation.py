from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/v1", tags=["simulation"])


@router.get("/sites/{site_id}/simulation")
async def get_simulation(site_id: str) -> dict:
    if not site_id:
        raise HTTPException(status_code=400, detail="site_id is required")

    return {
        "site_id": site_id,
        "scenario": {
            "years": [5, 10, 20],
            "canopy_growth_percent": {"5": 8.2, "10": 16.5, "20": 28.4},
            "temperature_reduction_c": {"5": 0.6, "10": 1.2, "20": 2.1},
            "biodiversity_index_gain": {"5": 12, "10": 24, "20": 41},
        },
    }
