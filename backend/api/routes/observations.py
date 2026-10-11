from fastapi import APIRouter

router = APIRouter(prefix="/api/v1", tags=["observations"])


@router.post("/observations")
async def create_observation() -> dict:
    return {
        "message": "Citizen observation recorded successfully",
        "status": "accepted",
        "health_score": 88,
    }
