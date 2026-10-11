"""Native species database and recommender for the Lagos lowland-forest / coastal mosaic.

IMPORTANT: every numeric trait below is a *provisional planning value* assembled for
the MVP. They must be reviewed by local botanists / forestry staff (e.g. FRIN, Lagos
State forestry, university herbaria) before the platform is used for real planting
decisions. The data model (not the numbers) is the deliverable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

POLLINATOR_POOL = {
    "honey bees (Apis mellifera adansonii)",
    "stingless bees (Meliponini)",
    "carpenter bees (Xylocopa spp.)",
    "halictid sweat bees",
    "butterflies (Lepidoptera)",
    "hawkmoths (Sphingidae)",
    "sunbirds (Nectariniidae)",
    "fruit bats (Pteropodidae)",
    "hoverflies (Syrphidae)",
    "beetles (Scarabaeidae/Nitidulidae)",
    "wasps (fig / Vespidae)",
    "flower flies and blow flies",
}


@dataclass(frozen=True)
class Species:
    key: str
    scientific: str
    common: str  # local / common names
    status: str  # native | exotic | invasive
    water_demand: str  # low | moderate | high
    soils: tuple[str, ...]  # sandy | loam | clay
    flood_tolerance: str  # low | moderate | high
    mature_crown_radius_m: float
    years_to_half_crown: float  # logistic midpoint
    co2_kg_per_yr_mature: float
    cooling_index: float  # 0-1 relative shade / evapotranspiration benefit
    pollinators: tuple[str, ...] = ()
    trees_per_cell: int = 4  # planting-density ceiling per 20 m cell (actual stems also limited by crown size)
    notes: str = ""

    @property
    def eligible(self) -> bool:
        return self.status == "native" and self.water_demand != "high"

    def rejection_reason(self) -> str | None:
        """All reasons a species is refused (a species can fail on several counts)."""
        reasons = []
        if self.status == "invasive":
            reasons.append("Invasive: displaces native flora (do no harm)")
        elif self.status == "exotic":
            reasons.append("Exotic / ornamental: low habitat value for native fauna")
        if self.water_demand == "high":
            reasons.append("High water demand: unsustainable in a water-stressed city")
        return "; ".join(reasons) or None


SPECIES: tuple[Species, ...] = (
    Species("terminalia_superba", "Terminalia superba", "Afara / Idi", "native", "moderate",
            ("loam", "sandy"), "low", 8.0, 7, 38, 0.95,
            ("honey bees (Apis mellifera adansonii)", "stingless bees (Meliponini)", "hoverflies (Syrphidae)",
             "butterflies (Lepidoptera)"), 4,
            "Fast-growing, broad crown; strong shade tree for hot residential plots."),
    Species("terminalia_ivorensis", "Terminalia ivorensis", "Idigbo", "native", "moderate",
            ("loam",), "low", 7.0, 9, 34, 0.85,
            ("honey bees (Apis mellifera adansonii)", "stingless bees (Meliponini)", "halictid sweat bees"), 4,
            "Valuable timber species; good for deeper lateritic soils."),
    Species("milicia_excelsa", "Milicia excelsa", "Iroko", "native", "moderate",
            ("loam",), "low", 9.0, 14, 42, 0.90,
            ("wasps (fig / Vespidae)", "beetles (Scarabaeidae/Nitidulidae)", "flower flies and blow flies"), 2,
            "Long-lived keystone forest tree; slow start, very large canopy."),
    Species("ceiba_pentandra", "Ceiba pentandra", "Araba / Okha", "native", "moderate",
            ("loam", "sandy"), "moderate", 10.0, 10, 45, 0.90,
            ("fruit bats (Pteropodidae)", "honey bees (Apis mellifera adansonii)", "sunbirds (Nectariniidae)",
             "hawkmoths (Sphingidae)"), 2,
            "Emergent species; bat-pollinated. Needs space away from buildings."),
    Species("albizia_zygia", "Albizia zygia", "Ayinre / Okuro", "native", "low",
            ("loam", "sandy", "clay"), "moderate", 6.5, 6, 28, 0.80,
            ("honey bees (Apis mellifera adansonii)", "butterflies (Lepidoptera)", "carpenter bees (Xylocopa spp.)",
             "hoverflies (Syrphidae)"), 5,
            "Nitrogen-fixing legume; spreading crown, tolerates degraded soils."),
    Species("blighia_sapida", "Blighia sapida", "Isin / Ackee", "native", "moderate",
            ("loam", "sandy"), "low", 5.0, 8, 22, 0.75,
            ("honey bees (Apis mellifera adansonii)", "stingless bees (Meliponini)", "butterflies (Lepidoptera)"), 6,
            "Compact evergreen crown; food tree (fruit must be eaten only when naturally ripe)."),
    Species("newbouldia_laevis", "Newbouldia laevis", "Akoko / Ogirisako", "native", "low",
            ("loam", "sandy", "clay"), "moderate", 3.5, 5, 12, 0.55,
            ("sunbirds (Nectariniidae)", "carpenter bees (Xylocopa spp.)", "honey bees (Apis mellifera adansonii)",
             "hawkmoths (Sphingidae)"), 9,
            "Small, tough, showy flowers; excellent for narrow plots and pollinator corridors."),
    Species("pterocarpus_santalinoides", "Pterocarpus santalinoides", "Gbengbe / Nanga", "native", "moderate",
            ("clay", "sandy"), "high", 5.5, 7, 24, 0.75,
            ("honey bees (Apis mellifera adansonii)", "stingless bees (Meliponini)", "butterflies (Lepidoptera)"), 5,
            "Riparian specialist: use in flood-prone / drainage-edge cells."),
    Species("mitragyna_ciliata", "Mitragyna ciliata", "Abura", "native", "moderate",
            ("clay",), "high", 7.0, 10, 30, 0.80,
            ("honey bees (Apis mellifera adansonii)", "flower flies and blow flies", "beetles (Scarabaeidae/Nitidulidae)"), 4,
            "Swamp-forest tree for waterlogged clay."),
    Species("anthocleista_vogelii", "Anthocleista vogelii", "Sapo / Oko-ikoko", "native", "moderate",
            ("clay", "loam"), "moderate", 4.5, 6, 18, 0.65,
            ("fruit bats (Pteropodidae)", "hawkmoths (Sphingidae)", "carpenter bees (Xylocopa spp.)"), 6,
            "Large-leaved forest-edge tree, night-flowering."),
    Species("alstonia_boonei", "Alstonia boonei", "Ahun / Egbu", "native", "moderate",
            ("loam", "sandy"), "low", 7.0, 8, 32, 0.80,
            ("honey bees (Apis mellifera adansonii)", "halictid sweat bees", "butterflies (Lepidoptera)"), 4,
            "Tall, quick-growing; give wide spacing."),
    Species("treculia_africana", "Treculia africana", "Afon / African breadfruit", "native", "moderate",
            ("loam", "clay"), "moderate", 6.0, 9, 26, 0.75,
            ("flower flies and blow flies", "beetles (Scarabaeidae/Nitidulidae)", "wasps (fig / Vespidae)"), 4,
            "Food tree for communities and wildlife."),
    # ---- Species the engine must refuse, kept so rejections are auditable ----
    Species("azadirachta_indica", "Azadirachta indica", "Neem / Dogonyaro", "invasive", "low",
            ("loam", "sandy"), "low", 6.0, 6, 25, 0.80, (), 5,
            "Widely planted exotic; spreads and offers limited native habitat."),
    Species("eucalyptus_camaldulensis", "Eucalyptus camaldulensis", "Eucalyptus", "invasive", "high",
            ("loam", "sandy"), "low", 6.0, 5, 30, 0.60, (), 5, "Very high water use."),
    Species("prosopis_juliflora", "Prosopis juliflora", "Mesquite", "invasive", "low",
            ("sandy", "loam"), "low", 4.0, 4, 15, 0.50, (), 6, "Aggressive invader of arid / coastal land."),
    Species("delonix_regia", "Delonix regia", "Flamboyant / Royal poinciana", "exotic", "moderate",
            ("loam",), "low", 6.0, 8, 20, 0.70, (), 4, "Ornamental; brittle, poor native wildlife value."),
    Species("roystonea_regia", "Roystonea regia", "Royal palm", "exotic", "high",
            ("loam",), "low", 3.0, 8, 8, 0.35, (), 8, "Ornamental avenue palm; thirsty, little shade."),
    Species("casuarina_equisetifolia", "Casuarina equisetifolia", "Beach sheoak", "invasive", "low",
            ("sandy",), "moderate", 4.0, 5, 18, 0.45, (), 6, "Exotic coastal planting that spreads aggressively."),
)

BY_KEY = {s.key: s for s in SPECIES}

# Goal -> which traits matter. Values multiply species suitability.
GOALS = ("shade", "carbon", "pollinator", "balanced")


def eligible_species() -> list[Species]:
    return [s for s in SPECIES if s.eligible]


def rejected_species() -> list[dict]:
    return [
        {"scientific": s.scientific, "common": s.common, "status": s.status,
         "water_demand": s.water_demand, "reason": s.rejection_reason()}
        for s in SPECIES if not s.eligible
    ]


def _goal_score(s: Species, goal: str) -> float:
    pol = min(len(s.pollinators) / 4.0, 1.0)
    carbon = min(s.co2_kg_per_yr_mature / 45.0, 1.0)
    if goal == "shade":
        return 0.7 * s.cooling_index + 0.15 * carbon + 0.15 * pol
    if goal == "carbon":
        return 0.7 * carbon + 0.2 * s.cooling_index + 0.1 * pol
    if goal == "pollinator":
        return 0.7 * pol + 0.15 * s.cooling_index + 0.15 * carbon
    return 0.4 * s.cooling_index + 0.3 * carbon + 0.3 * pol


def suitability(s: Species, soil: str, flood_prone: bool, narrow_plot: bool) -> float:
    """0 = unsuitable (hard exclusion), up to 1 = ideal site match."""
    if not s.eligible:
        return 0.0
    score = 1.0 if soil in s.soils else 0.35  # off-soil is allowed but strongly penalised
    if flood_prone:
        score *= {"low": 0.0, "moderate": 0.6, "high": 1.0}[s.flood_tolerance]
    else:
        # riparian specialists are wasted on dry ground
        score *= 0.7 if s.flood_tolerance == "high" and soil != "clay" else 1.0
    if narrow_plot and s.mature_crown_radius_m > 7:
        score *= 0.4  # large crowns conflict with buildings in tight plots
    return float(score)


def recommend(soil: str, goal: str = "balanced", flood_prone: bool = False,
              narrow_plot: bool = False, exclude: Iterable[str] = ()) -> tuple[Species, float]:
    """Best native species for a site. Never returns an ineligible species."""
    ex = set(exclude)
    best: tuple[float, Species] | None = None
    for s in eligible_species():
        if s.key in ex:
            continue
        fit = suitability(s, soil, flood_prone, narrow_plot)
        if fit <= 0:
            continue
        total = fit * (0.5 + _goal_score(s, goal))
        if best is None or total > best[0]:
            best = (total, s)
    if best is None:  # extremely unusual: fall back to the most tolerant native
        s = BY_KEY["albizia_zygia"]
        return s, 0.2
    return best[1], round(best[0] / 1.5, 3)


def growth_fraction(s: Species, years: float) -> float:
    """Logistic fraction of mature crown reached at `years` since planting (0 -> 1)."""
    import math

    k = 0.55
    raw = 1.0 / (1.0 + math.exp(-k * (years - s.years_to_half_crown)))
    raw0 = 1.0 / (1.0 + math.exp(-k * (0 - s.years_to_half_crown)))
    return max(0.0, min(1.0, (raw - raw0) / (1 - raw0)))


def stems_per_cell(s: Species, cell_area_m2: float, survival: float = 1.0) -> int:
    """Number of stems to plant in one cell so mature crowns fill <= ~65% of it.

    Crowns of large species need space, so a 20 m cell may hold a single Iroko but
    seven Newbouldia. Capped by the species' planting-density ceiling.
    """
    import math

    crown20 = math.pi * s.mature_crown_radius_m ** 2 * growth_fraction(s, 20)
    n = round(0.65 * cell_area_m2 / max(crown20, 1.0))
    return int(max(1, min(s.trees_per_cell, n)))


def recommend_ranked(soil: str, goal: str = "balanced", flood_prone: bool = False,
                     narrow_plot: bool = False, n: int = 3) -> list[tuple[Species, float]]:
    """Top-n eligible species for a site context, best first (used to avoid monocultures)."""
    scored = []
    for s in eligible_species():
        fit = suitability(s, soil, flood_prone, narrow_plot)
        if fit > 0:
            scored.append((fit * (0.5 + _goal_score(s, goal)), s, fit))
    scored.sort(key=lambda t: -t[0])
    out = [(s, round(total / 1.5, 3)) for total, s, _ in scored[:n]]
    return out or [(BY_KEY["albizia_zygia"], 0.2)]
