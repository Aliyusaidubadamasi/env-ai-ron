class DigitalTwinSimulation:
    """Simple 5/10/20-year orange-green canopy growth and cooling model."""

    def __init__(self, baseline_canopy: float = 18.0, baseline_heat: float = 29.5) -> None:
        self.baseline_canopy = baseline_canopy
        self.baseline_heat = baseline_heat

    def project(self, tree_count: int = 50) -> dict:
        canopy_gain = {
            5: round((tree_count / 50) * 8.2 + 2.0, 2),
            10: round((tree_count / 50) * 16.5 + 4.0, 2),
            20: round((tree_count / 50) * 28.4 + 7.0, 2),
        }
        temperature_reduction = {
            5: round(0.6 + (tree_count / 100), 2),
            10: round(1.2 + (tree_count / 80), 2),
            20: round(2.1 + (tree_count / 60), 2),
        }
        biodiversity_gain = {
            5: 12,
            10: 24,
            20: 41,
        }

        return {
            "baseline_canopy_percent": self.baseline_canopy,
            "baseline_temperature_c": self.baseline_heat,
            "canopy_growth_percent": canopy_gain,
            "temperature_reduction_c": temperature_reduction,
            "biodiversity_index_gain": biodiversity_gain,
        }
