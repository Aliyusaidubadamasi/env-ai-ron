"""End-to-end analysis: imagery + GIS layers -> optimised, species-specific planting blueprint."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import numpy as np
from scipy import ndimage as ndi

from . import __version__, config, species as sp
from .ecology import EcoState, build_eco_state, summarise
from .geo import GridSpec, rasterize_geojson, read_raster_band
from .optimizer import optimise
from .segmentation import CLASS_NAMES, TreeSegmenter, load_model
from .simulation import Plan, project, pollinator_taxa

SOILS = {"loam", "sandy", "clay"}


@lru_cache(maxsize=1)
def get_model() -> TreeSegmenter:
    return load_model()


@dataclass
class Layers:
    soil: np.ndarray | None = None
    zoning: np.ndarray | None = None
    elevation: np.ndarray | None = None
    hvi: np.ndarray | None = None
    asthma: np.ndarray | None = None
    ward_name: np.ndarray | None = None
    ward_idx: np.ndarray | None = None
    notes: list[str] = field(default_factory=list)


def load_layers(spec: GridSpec, *, soil_geojson=None, zoning_geojson=None, wards_geojson=None,
                elevation_path: str | None = None) -> Layers:
    """Rasterise municipal GIS layers onto the planning grid."""
    L = Layers()
    if soil_geojson is not None:
        g, cats = rasterize_geojson(soil_geojson, spec, "soil_type", categorical=True)
        names = np.array([c.lower() for c in cats] + ["loam"], dtype=object)
        out = names[np.where(g < 0, len(cats), g)]
        unknown = sorted({c for c in cats if c.lower() not in SOILS})
        if unknown:
            L.notes.append(f"Soil classes {unknown} are not in the species database; treated as loam.")
            out = np.where(np.isin(out, list(SOILS)), out, "loam")
        L.soil = out
    if zoning_geojson is not None:
        g, cats = rasterize_geojson(zoning_geojson, spec, "zone", categorical=True)
        names = np.array(cats + ["unzoned"], dtype=object)
        L.zoning = names[np.where(g < 0, len(cats), g)]
        L.notes.append("Cells with no zoning polygon are treated as unplantable ('unzoned').")
    if wards_geojson is not None:
        hv, _ = rasterize_geojson(wards_geojson, spec, "heat_vulnerability_index")
        asth, _ = rasterize_geojson(wards_geojson, spec, "asthma_per_1000")
        wn, cats = rasterize_geojson(wards_geojson, spec, "ward_name", categorical=True)
        L.hvi, L.asthma = hv, asth
        L.ward_idx = wn.astype(np.int32)
        if cats:
            L.ward_name = np.array(cats + [""], dtype=object)[np.where(wn < 0, len(cats), wn)]
    if elevation_path:
        L.elevation, warn = read_raster_band(elevation_path, spec)
        if warn:
            L.notes.append(warn)
    return L


def _clusters(rows: np.ndarray, cols: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    grid = np.zeros(shape, bool)
    grid[rows, cols] = True
    lab, _ = ndi.label(grid, structure=np.ones((3, 3)))
    return lab[rows, cols]


def run_analysis(
    image: np.ndarray,
    spec: GridSpec,
    layers: Layers | None = None,
    *,
    weights: dict[str, float] | None = None,
    preset: str = "balanced",
    budget_sites: int = 180,
    seed: int = 42,
    region_name: str | None = None,
) -> dict[str, Any]:
    t0 = time.time()
    layers = layers or Layers()
    w = dict(weights) if weights else dict(config.PRESETS[preset])
    timings: dict[str, float] = {}

    tt = time.time()
    labels = get_model().predict(image)
    timings["segmentation_s"] = round(time.time() - tt, 2)

    state = build_eco_state(
        labels, spec, soil=layers.soil, zoning=layers.zoning, elevation=layers.elevation,
        hvi=layers.hvi, asthma=layers.asthma, ward_idx=layers.ward_idx,
    )

    tt = time.time()
    opt = optimise(state, w, budget_sites, seed=seed)
    timings["optimisation_s"] = round(time.time() - tt, 2)

    cand = opt["cand"]
    sel = opt["selected"]
    cols = spec.cols
    flat = cand.flat_idx[sel] if len(sel) else np.array([], int)
    rows_i, cols_i = (flat // cols).astype(int), (flat % cols).astype(int)
    chosen = [cand.species[i] for i in sel]
    stems = cand.stems[sel] if len(sel) else np.array([], int)
    plan = Plan(rows_i, cols_i, chosen, stems)

    tt = time.time()
    sim = project(state, plan)
    timings["simulation_s"] = round(time.time() - tt, 2)

    # ------------------------------------------------------------- site records
    cluster_ids = _clusters(rows_i, cols_i, (spec.rows, spec.cols)) if len(sel) else np.array([], int)
    lon, lat = spec.cell_center_lonlat(rows_i, cols_i)
    surv = config.SIM["establishment_survival"]
    from .species import growth_fraction

    sites = []
    for j in range(len(sel)):
        r, c = int(rows_i[j]), int(cols_i[j])
        s = chosen[j]
        hz = {h: {k: v for k, v in sim["horizons"][h]["sites"][j].items()} for h in sim["horizons"]}
        eq = float(state.equity[r, c])
        why = [f"{s.common} ({s.scientific}) is native and suits {state.soil[r, c]} soil"]
        if state.flood_prone[r, c]:
            why.append("tolerates the periodic flooding of this low-lying cell")
        if state.narrow_plot[r, c] and s.mature_crown_radius_m <= 7:
            why.append("has a crown that fits tight plots between buildings")
        if eq > 0.6:
            why.append("serves a heat-vulnerable, canopy-poor neighbourhood")
        if state.heat_excess[r, c] > 0.7:
            why.append("sits in one of the hottest parts of the tile")
        sites.append({
            "site_id": f"S{j + 1:03d}",
            "cluster_id": f"C{int(cluster_ids[j]):02d}",
            "lon": round(float(lon[j]), 6), "lat": round(float(lat[j]), 6),
            "row": r, "col": c,
            "species": s.scientific, "common_name": s.common, "stems": int(stems[j]),
            "soil": str(state.soil[r, c]), "zone": str(state.zoning[r, c]),
            "flood_prone": bool(state.flood_prone[r, c]),
            "equity_priority": round(eq, 3), "heat_excess": round(float(state.heat_excess[r, c]), 3),
            "ward": str(layers.ward_name[r, c]) if layers.ward_name is not None else None,
            "species_fit": round(float(cand.fit[sel[j]]), 3),
            "tco2_20yr": round(float(cand.carbon_kg20[sel[j]]) / 1000, 3),
            "pollinator_taxa": list(s.pollinators),
            "horizons": hz,
            "rationale": "; ".join(why) + ".",
        })

    clusters = []
    for cid in sorted({s["cluster_id"] for s in sites}):
        members = [s for s in sites if s["cluster_id"] == cid]
        sp_count: dict[str, int] = {}
        for m in members:
            sp_count[m["species"]] = sp_count.get(m["species"], 0) + m["stems"]
        trees = sum(m["stems"] for m in members)
        spp = [sp.BY_KEY[next(k for k, v in sp.BY_KEY.items() if v.scientific == n)] for n in sp_count]
        taxa = pollinator_taxa(spp)
        mean_cool = {h: float(np.mean([m["horizons"][h]["cooling_c"] for m in members])) for h in sim["horizons"]}
        top = max(sp_count, key=sp_count.get)
        top_common = next(m["common_name"] for m in members if m["species"] == top)
        clusters.append({
            "cluster_id": cid, "n_sites": len(members), "trees": trees,
            "area_ha": round(len(members) * spec.cell_area_m2 / 10_000, 2),
            "species_mix": dict(sorted(sp_count.items(), key=lambda kv: -kv[1])),
            "dominant_species": top, "dominant_common": top_common,
            "lon": round(float(np.mean([m["lon"] for m in members])), 6),
            "lat": round(float(np.mean([m["lat"] for m in members])), 6),
            "mean_equity": round(float(np.mean([m["equity_priority"] for m in members])), 3),
            "mean_cooling_c": {h: round(v, 2) for h, v in mean_cool.items()},
            "pollinator_taxa": taxa, "n_pollinator_taxa": len(taxa),
            "tco2_20yr": round(sum(m["tco2_20yr"] for m in members), 2),
        })
    clusters.sort(key=lambda c: -(c["trees"] * (0.5 + c["mean_equity"])))
    for c in clusters:
        m20 = c["mean_cooling_c"]["20"]
        lo = m20 * (1 - config.SIM["cooling_uncertainty"])
        hi = min(m20 * (1 + config.SIM["cooling_uncertainty"]), config.SIM["max_local_cooling_c"])
        c["roi_statement"] = (
            f"Planting {c['trees']} native trees here (mostly {c['dominant_common']}, "
            f"{c['dominant_species']}) is projected to cool the planted cells by about {m20:.1f} °C "
            f"by year 20 (range {lo:.1f}–{hi:.1f} °C), store ~{c['tco2_20yr']:.1f} tCO₂ and support "
            f"{c['n_pollinator_taxa']} pollinator groups."
        )

    last = sim["series"][-1]
    total_trees = int(stems.sum()) if len(sel) else 0
    eq_high = float(sum(s["stems"] for s in sites if s["equity_priority"] > 0.6) / max(total_trees, 1))
    cand_eq_high = float((state.equity[state.plantable] > 0.6).mean()) if state.plantable.any() else 0.0
    counts: dict[str, int] = {}
    for st in sites:
        counts[st["species"]] = counts.get(st["species"], 0) + st["stems"]
    shares = np.array(list(counts.values()), float) / max(total_trees, 1)
    shannon = float(-(shares * np.log(shares)).sum()) if len(shares) else 0.0
    summary = {
        "species_diversity": {"n_species": len(counts), "shannon_index": round(shannon, 3),
                              "max_species_share": round(float(shares.max()) if len(shares) else 0.0, 3),
                              "trees_by_species": dict(sorted(counts.items(), key=lambda kv: -kv[1]))},
        "sites": len(sites), "trees": total_trees,
        "planted_area_ha": round(len(sites) * spec.cell_area_m2 / 10_000, 2),
        "species_used": sorted({s["species"] for s in sites}),
        "tco2_by_year": {str(h): sim["series"][int(h)]["tco2_cumulative"] for h in sim["horizons"]},
        "cooling_planted_cells_c": {str(h): sim["series"][int(h)]["mean_cooling_planted_c"] for h in sim["horizons"]},
        "cooling_100m_c": {str(h): sim["series"][int(h)]["mean_cooling_100m_c"] for h in sim["horizons"]},
        "peak_cooling_c": {str(h): sim["series"][int(h)]["peak_cooling_c"] for h in sim["horizons"]},
        "canopy_added_ha": {str(h): sim["series"][int(h)]["canopy_added_ha"] for h in sim["horizons"]},
        "habitat_index": {"baseline": sim["baseline_habitat_index_mean"],
                          **{str(h): sim["series"][int(h)]["habitat_index_mean"] for h in sim["horizons"]}},
        "pollinator_taxa_supported": len(sim["pollinator_taxa"]),
        "pollinator_taxa": sim["pollinator_taxa"],
        "sites_by_ward": dict(sorted(
            {k: v for k, v in __import__("collections").Counter(
                st["ward"] for st in sites if st["ward"]).items()}.items(), key=lambda kv: -kv[1])),
        "equity": {"share_of_trees_in_high_vulnerability_cells": round(eq_high, 3),
                   "share_of_plantable_cells_high_vulnerability": round(cand_eq_high, 3)},
        "canopy_cover_pct_before": round(100 * float(state.frac[..., 1].mean()), 2),
        "canopy_cover_pct_after_20yr": round(
            100 * float(np.clip(state.frac[..., 1] + sim["horizons"]["20"]["gain_grid"], 0, 1).mean()), 2),
    }

    result = {
        "version": __version__,
        "region": region_name or config.REGION["name"],
        "principles": list(config.PRINCIPLES),
        "grid": spec.to_dict(),
        "params": {"weights": opt["weights"], "preset": None if weights else preset,
                   "budget_sites": budget_sites, "seed": seed},
        "baseline": summarise(state),
        "optimiser": {
            "score": round(opt["score"], 4), "breakdown": opt["breakdown"],
            "comparison_scores": {k: round(v, 4) for k, v in opt["baselines"].items()},
            "baseline_breakdowns": opt.get("baseline_breakdowns", {}),
            "history": [round(h, 4) for h in opt["history"]],
            "candidates": opt.get("n_candidates", 0),
        },
        "summary": summary,
        "clusters": clusters,
        "sites": sites,
        "simulation": {"series": sim["series"], "assumptions": sim["assumptions"]},
        "species_rejected": sp.rejected_species(),
        "notes": state.notes + layers.notes,
        "timings": {**timings, "total_s": round(time.time() - t0, 2)},
        "model": {"classes": list(CLASS_NAMES)},
    }
    arrays = {"labels": labels, "state": state, "sim": sim, "plan": plan}
    return {"result": result, "arrays": arrays}


def blueprint_geojson(result: dict, spec: GridSpec) -> dict:
    """GIS-compatible FeatureCollection: one polygon (the 20 m planting cell) per site."""
    west, south, east, north = spec.bbox
    dx, dy = (east - west) / spec.cols, (north - south) / spec.rows
    feats = []
    for s in result["sites"]:
        r, c = s["row"], s["col"]
        x0, x1 = west + c * dx, west + (c + 1) * dx
        y1, y0 = north - r * dy, north - (r + 1) * dy
        props = {k: v for k, v in s.items() if k not in ("horizons", "pollinator_taxa")}
        props["cooling_5yr_c"] = s["horizons"]["5"]["cooling_c"]
        props["cooling_10yr_c"] = s["horizons"]["10"]["cooling_c"]
        props["cooling_20yr_c"] = s["horizons"]["20"]["cooling_c"]
        props["pollinator_taxa"] = "; ".join(s["pollinator_taxa"])
        feats.append({"type": "Feature", "properties": props,
                      "geometry": {"type": "Polygon", "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}})
    return {"type": "FeatureCollection", "name": "env_ai_ron_planting_blueprint",
            "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
            "features": feats}


TRAIN_GSD_M = 2.5  # ground sample distance the segmenter was trained at


def prepare_image(arr: np.ndarray, bbox: tuple[float, float, float, float]) -> tuple[np.ndarray, GridSpec, list[str]]:
    """Resample imagery to the model's working resolution and snap to whole planning cells."""
    from PIL import Image

    notes: list[str] = []
    h, w = arr.shape[:2]
    west, south, east, north = bbox
    lat_mid = (south + north) / 2
    gsd_x = (east - west) * 111_320 * np.cos(np.radians(lat_mid)) / w
    gsd_y = (north - south) * 110_540 / h
    gsd = float((gsd_x + gsd_y) / 2)
    if gsd < TRAIN_GSD_M * 0.8:
        nw, nh = max(config.CELL_PX, round(w * gsd / TRAIN_GSD_M)), max(config.CELL_PX, round(h * gsd / TRAIN_GSD_M))
        arr = np.asarray(Image.fromarray(arr).resize((nw, nh), Image.BOX))
        notes.append(f"Imagery downsampled from {gsd:.2f} m to ~{TRAIN_GSD_M} m per pixel (the model's working resolution).")
    elif gsd > TRAIN_GSD_M * 1.6:
        notes.append(f"Imagery is coarse ({gsd:.1f} m/pixel); the segmenter was trained at {TRAIN_GSD_M} m, so accuracy will drop.")
    h, w = arr.shape[:2]
    h8, w8 = (h // config.CELL_PX) * config.CELL_PX, (w // config.CELL_PX) * config.CELL_PX
    if h8 < 10 * config.CELL_PX or w8 < 10 * config.CELL_PX:
        raise ValueError("Image too small after resampling (need at least 80x80 working pixels).")
    arr = np.ascontiguousarray(arr[:h8, :w8])
    return arr, GridSpec(bbox, h8, w8, config.CELL_PX), notes


def load_demo_inputs():
    """Synthetic Lagos demo tile + GIS layers (generated on first use)."""
    import json as _json

    from PIL import Image

    from .synthetic import export_demo_dataset

    demo = config.DATA_DIR / "demo"
    if not (demo / "lagos_demo_tile.png").exists():
        export_demo_dataset(demo)
    img = np.array(Image.open(demo / "lagos_demo_tile.png").convert("RGB"))
    spec = GridSpec(config.REGION["bbox"], img.shape[0], img.shape[1])
    layers = load_layers(
        spec,
        soil_geojson=_json.loads((demo / "soil.geojson").read_text()),
        zoning_geojson=_json.loads((demo / "zoning.geojson").read_text()),
        wards_geojson=_json.loads((demo / "wards_health.geojson").read_text()),
        elevation_path=str(demo / "lagos_demo_elevation.tif"),
    )
    return img, spec, layers
