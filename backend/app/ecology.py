"""Ecological state of the tile: land-cover fractions, heat proxy, ecological voids,
equity weights and plantable candidate cells.

Everything is computed on the planning-cell grid (default 20 m x 20 m).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage as ndi

from . import config
from .geo import GridSpec, block_reduce_mode, smooth_normalise

PLANTABLE_ZONES = {"residential_high", "residential_low", "commercial", "industrial", "institutional", "open_space"}
# road_row and drainage_row are excluded: roads need a separate street-tree workflow, and
# planting inside drainage channels would increase flood risk (do no harm).


@dataclass
class EcoState:
    spec: GridSpec
    frac: np.ndarray            # (rows, cols, 3) concrete / canopy / bare soil fractions
    lst_c: np.ndarray           # surface temperature proxy per cell, deg C
    heat_excess: np.ndarray     # 0-1 how much hotter than the vegetated reference
    void_score: np.ndarray      # 0-1 ecological void intensity
    void_mask: np.ndarray       # bool
    equity: np.ndarray          # 0-1 health-equity priority per cell
    plantable: np.ndarray       # bool candidate cells
    soil: np.ndarray            # object array of soil names
    zoning: np.ndarray          # object array of zone names
    flood_prone: np.ndarray     # bool
    narrow_plot: np.ndarray     # bool: dense built-up neighbourhood (tight plots)
    hvi: np.ndarray
    asthma: np.ndarray
    ward_idx: np.ndarray        # (rows, cols) int ward index, -1 when unknown
    notes: list[str]


def heat_proxy(frac: np.ndarray) -> np.ndarray:
    """Land-surface temperature proxy from cover fractions (no thermal band in RGB imagery).

    NOTE: replace with Landsat / ECOSTRESS LST when thermal data are available.
    """
    s = config.SIM
    imperv = frac[..., 0] + 0.45 * frac[..., 2]  # bare soil is hot-ish but not as hot as concrete
    lst = s["baseline_lst_c"] + s["imperv_lst_gain_c"] * np.clip(imperv, 0, 1) - s["canopy_lst_drop_c"] * frac[..., 1]
    return ndi.gaussian_filter(lst, 0.8).astype(np.float32)  # heat is felt beyond a single cell


def build_eco_state(
    labels: np.ndarray,
    spec: GridSpec,
    *,
    soil: np.ndarray | None = None,        # (rows, cols) of soil names
    zoning: np.ndarray | None = None,      # (rows, cols) of zone names
    elevation: np.ndarray | None = None,   # (rows, cols) metres
    hvi: np.ndarray | None = None,         # (rows, cols) 0-1
    asthma: np.ndarray | None = None,      # (rows, cols) per 1000
    ward_idx: np.ndarray | None = None,    # (rows, cols) int ward / neighbourhood index
) -> EcoState:
    rows, cols = spec.rows, spec.cols
    notes: list[str] = []
    frac = block_reduce_mode(labels, spec.cell_px, 3)
    lst = heat_proxy(frac)
    heat_excess = smooth_normalise(lst)

    # Ecological voids: hot + canopy-poor + concrete-dominated, judged over a ~60 m neighbourhood
    can_loc = ndi.uniform_filter(frac[..., 1], 3)
    con_loc = ndi.uniform_filter(frac[..., 0], 3)
    void_score = np.clip(0.45 * heat_excess + 0.30 * (1 - np.clip(can_loc / 0.30, 0, 1)) + 0.25 * np.clip(con_loc / 0.5, 0, 1), 0, 1)
    void_mask = void_score > np.percentile(void_score, 70)

    # ---- GIS layers (fall back to neutral values and say so) --------------
    if soil is None:
        soil = np.full((rows, cols), "loam", dtype=object)
        notes.append("No soil layer supplied: assumed lateritic loam everywhere.")
    if zoning is None:
        zoning = np.full((rows, cols), "residential_low", dtype=object)
        notes.append("No zoning layer supplied: assumed all cells are plantable residential land.")
    if elevation is None:
        flood = np.zeros((rows, cols), bool)
        notes.append("No elevation layer supplied: flood-prone cells could not be identified.")
    else:
        flood = elevation < np.nanpercentile(elevation, 12)
    if hvi is None:
        hvi = np.full((rows, cols), 0.5, np.float32)
        notes.append("No heat-vulnerability layer supplied: equity weighting uses a neutral value.")
    if asthma is None:
        asthma = np.full((rows, cols), np.nan, np.float32)
        notes.append("No asthma / respiratory layer supplied.")

    hvi = np.nan_to_num(hvi, nan=float(np.nanmean(hvi)) if np.isfinite(hvi).any() else 0.5)
    asthma_n = smooth_normalise(asthma) if np.isfinite(asthma).any() else np.full((rows, cols), 0.5, np.float32)
    canopy_poverty = 1 - np.clip(ndi.uniform_filter(frac[..., 1], 7) / 0.25, 0, 1)
    equity = np.clip(0.50 * np.clip(hvi, 0, 1) + 0.25 * asthma_n + 0.25 * canopy_poverty, 0, 1).astype(np.float32)

    zone_ok = np.isin(zoning, list(PLANTABLE_ZONES))
    plantable = (frac[..., 2] >= 0.35) & zone_ok & (frac[..., 1] < 0.35)  # never displace existing canopy
    narrow = ndi.uniform_filter(frac[..., 0], 3) > 0.30

    return EcoState(spec, frac, lst, heat_excess, void_score, void_mask, equity, plantable,
                    soil, zoning, flood, narrow, np.asarray(hvi, np.float32), np.asarray(asthma, np.float32),
                    ward_idx if ward_idx is not None else np.full((rows, cols), -1, np.int32), notes)


def summarise(state: EcoState) -> dict:
    f = state.frac
    area_ha = state.spec.cell_area_m2 * state.spec.rows * state.spec.cols / 10_000
    return {
        "area_ha": round(area_ha, 1),
        "cover_pct": {"concrete_impervious": round(100 * float(f[..., 0].mean()), 1),
                      "canopy": round(100 * float(f[..., 1].mean()), 1),
                      "bare_soil": round(100 * float(f[..., 2].mean()), 1)},
        "mean_lst_proxy_c": round(float(state.lst_c.mean()), 2),
        "hottest_decile_lst_c": round(float(np.percentile(state.lst_c, 90)), 2),
        "ecological_void_cells": int(state.void_mask.sum()),
        "ecological_void_ha": round(float(state.void_mask.sum()) * state.spec.cell_area_m2 / 10_000, 1),
        "plantable_cells": int(state.plantable.sum()),
        "plantable_ha": round(float(state.plantable.sum()) * state.spec.cell_area_m2 / 10_000, 1),
        "flood_prone_cells": int(state.flood_prone.sum()),
    }
