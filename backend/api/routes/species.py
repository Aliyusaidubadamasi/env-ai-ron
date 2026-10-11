from fastapi import APIRouter

router = APIRouter(prefix="/api/v1", tags=["species"])


@router.get("/species")
async def get_species(region: str | None = None, soil: str | None = None) -> dict:
    species = [
        {
            "name": "Terminalia catappa",
            "native_status": "native",
            "water_need": "moderate",
            "pollinator_value": 9,
            "carbon_sequestration_score": 8.8,
            "shade_value": 9,
            "climate_zone_match": "coastal_warm",
            "invasive_risk": "low",
        },
        {
            "name": "Milicia excelsa",
            "native_status": "native",
            "water_need": "moderate",
            "pollinator_value": 8,
            "carbon_sequestration_score": 9.1,
            "shade_value": 8,
            "climate_zone_match": "coastal_warm",
            "invasive_risk": "low",
        },
    ]

    return {
        "region": region or "lagos",
        "soil": soil or "loamy",
        "species": species,
    }
