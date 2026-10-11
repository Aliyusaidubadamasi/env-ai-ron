from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/v1", tags=["optimization"])


@router.post("/sites/{site_id}/optimize")
async def optimize_site(site_id: str) -> dict:
    if not site_id:
        raise HTTPException(status_code=400, detail="site_id is required")

    return {
        "site_id": site_id,
        "optimized_planting_plan": {
            "recommended_tree_count": 50,
            "priority_zone": "ecological_void_cluster_a",
            "weights": {
                "heat": 0.30,
                "carbon": 0.25,
                "pollinator": 0.20,
                "health_equity": 0.25,
            },
        },
        "status": "ready",
    }
