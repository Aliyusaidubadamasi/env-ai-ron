from fastapi import APIRouter

router = APIRouter(prefix="/api/v1", tags=["recommendations"])


@router.get("/sites/{site_id}/recommendations")
async def get_recommendations(site_id: str) -> dict:
    return {
        "site_id": site_id,
        "recommendations": [
            {
                "species": "Terminalia catappa",
                "native_status": "native",
                "reason": "High shade value and strong performance in warm coastal conditions",
                "estimated_temperature_reduction_c": 1.5,
                "pollinator_support": 12,
            },
            {
                "species": "Milicia excelsa",
                "native_status": "native",
                "reason": "Supports biodiversity and improves urban cooling",
                "estimated_temperature_reduction_c": 1.2,
                "pollinator_support": 9,
            },
        ],
    }
