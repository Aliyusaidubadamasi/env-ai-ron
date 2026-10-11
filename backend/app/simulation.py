"""Digital-twin projection: canopy growth, cooling, carbon and habitat at 5 / 10 / 20 years.

All coefficients live in config.SIM and are echoed in every report, because a projection is
only as honest as its stated assumptions. Cooling is reported with a low/high range.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import ndimage as ndi

from . import config, species as sp
from .ecology import EcoState

NEIGH = np.array([[1, 1, 1], [1, 0, 1], [1, 1, 1]], np.float32) / 8.0


@dataclass
class Plan:
    rows: np.ndarray
    cols: np.ndarray
    species: list[sp.Species]
    stems: np.ndarray


def _gain_map(state: EcoState, plan: Plan, year: float) -> np.ndarray:
    surv = config.SIM["establishment_survival"]
    area = state.spec.cell_area_m2
    g = np.zeros((state.spec.rows, state.spec.cols), np.float32)
    for r, c, s, n in zip(plan.rows, plan.cols, plan.species, plan.stems):
        crown = n * surv * math.pi * s.mature_crown_radius_m ** 2 * sp.growth_fraction(s, year)
        g[r, c] += min(0.65, crown / area)
    return g


def cooling_map(state: EcoState, gain: np.ndarray) -> np.ndarray:
    """Air-temperature reduction (deg C, positive = cooler) from added canopy fraction.

    Air mixes laterally, so cooling follows canopy averaged over a ~60 m window rather than
    the single 20 m cell a tree stands in.
    """
    s = config.SIM
    window = ndi.uniform_filter(gain, s["cooling_window_cells"], mode="constant")
    cool = s["cooling_c_per_10pct_canopy"] * (window * 100.0 / 10.0)
    return np.minimum(cool, s["max_local_cooling_c"]).astype(np.float32)


def habitat_index(state: EcoState, gain: np.ndarray) -> np.ndarray:
    """0-100 habitat-quality proxy: canopy share + connectivity of habitat within ~100 m."""
    canopy = np.clip(state.frac[..., 1] + gain, 0, 1)
    local = ndi.uniform_filter(canopy, 3)
    hab = (canopy > 0.30).astype(np.float32)
    rr = np.arange(-5, 6)
    disc = ((rr[:, None] ** 2 + rr[None, :] ** 2) <= 25).astype(np.float32)
    conn = np.clip(ndi.convolve(hab, disc, mode="constant") / disc.sum() / 0.25, 0, 1)
    return 100.0 * np.clip(0.55 * np.clip(local / 0.35, 0, 1) + 0.45 * conn, 0, 1)


def pollinator_taxa(species_list: list[sp.Species]) -> list[str]:
    out: set[str] = set()
    for s in species_list:
        out.update(s.pollinators)
    return sorted(out)


def project(state: EcoState, plan: Plan, horizons=config.SIM["horizons_years"]) -> dict:
    """Run the simulation. Returns annual series (0-20) and per-horizon site-level detail."""
    s = config.SIM
    lo, hi = 1 - s["cooling_uncertainty"], 1 + s["cooling_uncertainty"]
    surv = s["establishment_survival"]
    area = state.spec.cell_area_m2
    planted = np.zeros((state.spec.rows, state.spec.cols), bool)
    planted[plan.rows, plan.cols] = True
    ring = ndi.binary_dilation(planted, structure=np.ones((3, 3), bool))  # planted cells + 1-cell neighbourhood

    bi0 = habitat_index(state, np.zeros_like(planted, np.float32))
    series = []
    cumulative_co2 = 0.0
    for year in range(0, 21):
        gain = _gain_map(state, plan, year)
        cool = cooling_map(state, gain)
        bi = habitat_index(state, gain)
        annual_co2 = sum(n * surv * x.co2_kg_per_yr_mature * sp.growth_fraction(x, year)
                         for x, n in zip(plan.species, plan.stems)) / 1000.0 if year > 0 else 0.0
        cumulative_co2 += float(annual_co2)
        series.append({
            "year": year,
            "canopy_added_ha": round(float(gain.sum()) * area / 10_000, 3),
            "mean_cooling_planted_c": round(float(cool[planted].mean()) if planted.any() else 0.0, 3),
            "peak_cooling_c": round(float(cool.max()), 3),
            "mean_cooling_100m_c": round(float(cool[ring].mean()) if ring.any() else 0.0, 3),
            "tco2_cumulative": round(float(cumulative_co2), 2),
            "habitat_index_mean": round(float(bi.mean()), 3),
            "habitat_index_gain_in_ring": round(float((bi - bi0)[ring].mean()) if ring.any() else 0.0, 3),
        })

    horizon_detail = {}
    for h in horizons:
        gain = _gain_map(state, plan, h)
        cool = cooling_map(state, gain)
        bi = habitat_index(state, gain)
        sites = []
        for r, c, x, n in zip(plan.rows, plan.cols, plan.species, plan.stems):
            crown_r = math.sqrt(max(sp.growth_fraction(x, h), 0) * x.mature_crown_radius_m ** 2)
            sites.append({
                "crown_radius_m": round(crown_r * 1.0, 2),
                "canopy_gain_pct": round(float(gain[r, c]) * 100, 1),
                "cooling_c": round(float(cool[r, c]), 3),
                "cooling_range_c": [round(float(cool[r, c]) * lo, 3), round(float(min(cool[r, c] * hi, s["max_local_cooling_c"])), 3)],
                "habitat_index": round(float(bi[r, c]), 1),
            })
        horizon_detail[str(h)] = {
            "sites": sites,
            "cooling_grid": np.round(cool, 3),
            "gain_grid": gain,
            "bi_grid": bi,
        }
    return {
        "series": series,
        "horizons": horizon_detail,
        "assumptions": {
            "establishment_survival": surv,
            "cooling_c_per_10pct_canopy": s["cooling_c_per_10pct_canopy"],
            "cooling_uncertainty_pct": int(s["cooling_uncertainty"] * 100),
            "max_local_cooling_c": s["max_local_cooling_c"],
            "cooling_window_m": round(s["cooling_window_cells"] * math.sqrt(area)),
            "cell_size_m": round(math.sqrt(area), 1),
            "note": "Coefficients are literature-informed planning assumptions to be calibrated against "
                    "local temperature loggers before decisions rely on the absolute numbers.",
        },
        "pollinator_taxa": pollinator_taxa(plan.species),
        "baseline_habitat_index_mean": round(float(bi0.mean()), 3),
    }
