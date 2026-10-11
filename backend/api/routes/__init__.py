from .upload import router as upload_router
from .sites import router as sites_router
from .analyze import router as analyze_router
from .recommendations import router as recommendations_router
from .optimize import router as optimize_router
from .simulation import router as simulation_router
from .observations import router as observations_router
from .species import router as species_router

__all__ = [
    "upload_router",
    "sites_router",
    "analyze_router",
    "recommendations_router",
    "optimize_router",
    "simulation_router",
    "observations_router",
    "species_router",
]
