from typing import Any


class OptimizationService:
    """Simple weighted objective function for planting prioritization."""

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        self.weights = weights or {
            "heat": 0.30,
            "carbon": 0.25,
            "pollinator": 0.20,
            "health_equity": 0.25,
        }

    def score(self, heat_reduction: float, carbon_score: float, pollinator_score: float, health_equity: float) -> float:
        return (
            heat_reduction * self.weights["heat"]
            + carbon_score * self.weights["carbon"]
            + pollinator_score * self.weights["pollinator"]
            + health_equity * self.weights["health_equity"]
        )

    def recommend_plan(self, site_metrics: dict[str, Any]) -> dict[str, Any]:
        overall = self.score(
            site_metrics.get("heat_reduction", 0.7),
            site_metrics.get("carbon_score", 0.8),
            site_metrics.get("pollinator_score", 0.6),
            site_metrics.get("health_equity", 0.9),
        )

        return {
            "overall_score": round(overall, 3),
            "recommended_tree_count": site_metrics.get("recommended_tree_count", 50),
            "weights": self.weights,
            "priority_zone": site_metrics.get("priority_zone", "ecological_void_cluster_a"),
        }
