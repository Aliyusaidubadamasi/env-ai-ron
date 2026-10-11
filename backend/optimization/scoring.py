class WeightedOptimization:
    """Weighted ecological scoring model for planting prioritization."""

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        self.weights = weights or {
            "heat": 0.30,
            "carbon": 0.25,
            "pollinator": 0.20,
            "health_equity": 0.25,
        }

    def score(self, heat: float, carbon: float, pollinator: float, health_equity: float) -> float:
        return (
            heat * self.weights["heat"]
            + carbon * self.weights["carbon"]
            + pollinator * self.weights["pollinator"]
            + health_equity * self.weights["health_equity"]
        )

    def best_site_candidates(self, candidates: list[dict]) -> list[dict]:
        scored = []
        for item in candidates:
            score = self.score(
                item.get("heat_reduction", 0.0),
                item.get("carbon_score", 0.0),
                item.get("pollinator_score", 0.0),
                item.get("health_equity", 0.0),
            )
            scored.append({**item, "ecological_score": round(score, 4)})
        return sorted(scored, key=lambda x: x["ecological_score"], reverse=True)
