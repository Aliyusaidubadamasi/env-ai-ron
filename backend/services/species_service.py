from pathlib import Path
import json


class SpeciesService:
    """Loads the site-appropriate native species registry for a chosen region."""

    def __init__(self, species_path: str | None = None) -> None:
        self.species_path = species_path or str(Path(__file__).resolve().parents[2] / "data" / "species" / "lagos_native_species.json")

    def load_species(self) -> list[dict]:
        with open(self.species_path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def recommend_for_site(self, region: str = "lagos", soil_type: str = "loamy", goal: str = "cooling") -> list[dict]:
        species = self.load_species()

        filtered = []
        for item in species:
            if item["native_status"] != "native":
                continue
            if item["invasive_risk"] != "low":
                continue
            if goal == "cooling":
                item = dict(item)
                item["score"] = (item["shade_value"] * 0.5) + (item["carbon_sequestration_score"] * 0.3)
                filtered.append(item)
            else:
                filtered.append(item)

        return sorted(filtered, key=lambda x: x.get("score", 0), reverse=True)[:5]
