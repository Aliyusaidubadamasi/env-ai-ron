"""Synthetic Lagos-like aerial tiles + municipal GIS layers.

WHY THIS EXISTS: the MVP must run end-to-end without private municipal data or licensed
imagery. This generator draws a plausible dense West-African neighbourhood (corrugated
roofs, laterite soil, unpaved lanes, drainage channel, scattered compound trees) together
with ground-truth labels, so the segmentation model can be trained and evaluated and the
whole pipeline can be exercised.

EVERYTHING produced here is SYNTHETIC. It is not a measurement of real Lagos.
Ward names are fictional on purpose. Swap in real GeoTIFF / GeoJSON for real use.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy import ndimage as ndi

from . import config
from .geo import GridSpec

CONCRETE, CANOPY, SOIL = 0, 1, 2
CLASS_NAMES = ("concrete", "canopy", "bare_soil")

SOIL_NAMES = ("loam", "sandy", "clay")
ZONING_NAMES = (
    "residential_high", "residential_low", "commercial", "industrial",
    "institutional", "open_space", "road_row", "drainage_row",
)
SOIL_RGB = {"loam": (172, 118, 84), "sandy": (205, 184, 146), "clay": (118, 92, 70)}


@dataclass
class Tile:
    image: np.ndarray               # (H, W, 3) uint8
    labels: np.ndarray              # (H, W) uint8 truth: 0 concrete, 1 canopy, 2 soil
    spec: GridSpec
    elevation: np.ndarray           # (rows, cols) metres
    soil: np.ndarray                # (rows, cols) index into SOIL_NAMES
    zoning: np.ndarray              # (rows, cols) index into ZONING_NAMES
    ward: np.ndarray                # (rows, cols) ward id
    ward_attrs: list[dict] = field(default_factory=list)
    seed: int = 0


def _noise(rng: np.random.Generator, shape: tuple[int, int], sigma: float) -> np.ndarray:
    n = ndi.gaussian_filter(rng.standard_normal(shape), sigma)
    n -= n.mean()
    return n / (n.std() + 1e-9)


def _seg_distance(xx: np.ndarray, yy: np.ndarray, p0, p1) -> np.ndarray:
    (x0, y0), (x1, y1) = p0, p1
    dx, dy = x1 - x0, y1 - y0
    t = np.clip(((xx - x0) * dx + (yy - y0) * dy) / (dx * dx + dy * dy + 1e-9), 0, 1)
    return np.hypot(xx - (x0 + t * dx), yy - (y0 + t * dy))


def generate_tile(seed: int = 2026, size: int = config.IMG_SIZE,
                  bbox: tuple[float, float, float, float] = config.REGION["bbox"]) -> Tile:
    rng = np.random.default_rng(seed)
    H = W = size
    spec = GridSpec(bbox, H, W, config.CELL_PX)
    rows, cols = spec.rows, spec.cols
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)

    # ---------------------------------------------------------- terrain / soil
    gy = np.linspace(0, 1, rows)[:, None]
    gx = np.linspace(0, 1, cols)[None, :]
    elev = 17 - 14 * gy + 2.2 * _noise(rng, (rows, cols), 7) + 1.0 * _noise(rng, (rows, cols), 3)
    # a low-lying, wetter depression in a random quadrant
    dcx, dcy = rng.uniform(0.15, 0.4), rng.uniform(0.15, 0.4)
    elev -= 5.5 * np.exp(-(((gx - dcx) ** 2 + (gy - dcy) ** 2) / 0.012))
    elev = elev.astype(np.float32)

    soil = np.zeros((rows, cols), dtype=np.int32)  # loam
    coast = gy + 0.05 * _noise(rng, (rows, cols), 5) > 0.80
    soil[coast] = 1  # sandy coastal band
    wet = (elev < np.percentile(elev, 11)) & ~coast
    soil[wet] = 2  # clay in the depressions

    # -------------------------------------------------------------- road net
    road_paved = np.zeros((H, W), bool)
    road_unpaved = np.zeros((H, W), bool)
    arterials = []
    for _ in range(2):  # roughly E-W
        y = rng.uniform(0.25, 0.75) * H
        arterials.append(((0, y + rng.uniform(-60, 60)), (W * 0.5, y + rng.uniform(-40, 40))))
        arterials.append(((W * 0.5, arterials[-1][1][1]), (W, y + rng.uniform(-60, 60))))
    x = rng.uniform(0.3, 0.7) * W
    arterials.append(((x + rng.uniform(-40, 40), 0), (x + rng.uniform(-60, 60), H)))
    arterials.append(((0, rng.uniform(0, 0.3) * H), (W, rng.uniform(0.7, 1.0) * H)))
    art_dist = np.full((H, W), 1e9, np.float32)
    for p0, p1 in arterials:
        art_dist = np.minimum(art_dist, _seg_distance(xx, yy, p0, p1))
    road_paved |= art_dist < 3.2

    for coord in list(np.arange(60, H - 30, rng.uniform(85, 125))):
        paved = rng.random() > 0.35
        w = 1.6 if paved else 1.4
        d1 = _seg_distance(xx, yy, (0, coord + rng.uniform(-8, 8)), (W, coord + rng.uniform(-8, 8)))
        (road_paved if paved else road_unpaved).__ior__(d1 < w)
    for coord in list(np.arange(60, W - 30, rng.uniform(85, 125))):
        paved = rng.random() > 0.35
        w = 1.6 if paved else 1.4
        d1 = _seg_distance(xx, yy, (coord + rng.uniform(-8, 8), 0), (coord + rng.uniform(-8, 8), H))
        (road_paved if paved else road_unpaved).__ior__(d1 < w)

    # drainage channel (concrete lined) along a wobbling line through the low ground
    ch_y = (rng.uniform(0.55, 0.8) * H) + 28 * np.sin(np.linspace(0, 2 * np.pi * rng.uniform(0.7, 1.3), W))
    channel = np.abs(yy - ch_y[None, :]) < 2.4

    # ----------------------------------------------- special areas (cell space)
    zoning_px = np.zeros((H, W), np.int32)  # zoning index at pixel level for painting rules
    park = np.zeros((H, W), bool)
    pcx, pcy = rng.uniform(0.62, 0.85) * W, rng.uniform(0.1, 0.35) * H
    park |= (((xx - pcx) / 90) ** 2 + ((yy - pcy) / 70) ** 2) < 1

    def rect_mask(x0, y0, w, h):
        m = np.zeros((H, W), bool)
        m[int(y0):int(y0 + h), int(x0):int(x0 + w)] = True
        return m

    school_rects = []
    for _ in range(3):
        for _try in range(30):
            sx, sy = rng.uniform(40, W - 200), rng.uniform(40, H - 160)
            sw, sh = rng.uniform(90, 150), rng.uniform(70, 110)
            m = rect_mask(sx, sy, sw, sh)
            if not (m & (park | channel)).any():
                school_rects.append(m)
                break
    ind_x, ind_y = rng.uniform(0.55, 0.75) * W, rng.uniform(0.55, 0.7) * H
    industrial = rect_mask(ind_x, ind_y, 130, 90) & ~channel
    school = np.zeros((H, W), bool)
    for m in school_rects:
        school |= m
    school &= ~industrial

    # --------------------------------------------------------------- buildings
    density = np.clip(0.40 + 0.55 * (1 - xx[0] / W)[None, :] ** 1.3 + 0.25 * _noise(rng, (H, W), 40), 0.04, 1.0)
    density = np.broadcast_to(density, (H, W)).copy()
    density[park] *= 0.1
    density[school] *= 0.05
    density[industrial] = 0.0
    building = np.zeros((H, W), bool)
    roof_kind = np.zeros((H, W), np.uint8)
    blocked = road_paved | road_unpaved | channel
    for _ in range(60000):
        bx, by = int(rng.integers(2, W - 12)), int(rng.integers(2, H - 12))
        if rng.random() > density[by, bx]:
            continue
        bw, bh = int(rng.integers(4, 11)), int(rng.integers(4, 9))
        sl = (slice(by - 1, by + bh + 1), slice(bx - 1, bx + bw + 1))
        if blocked[sl].any() or building[sl].any():
            continue
        building[by:by + bh, bx:bx + bw] = True
        roof_kind[by:by + bh, bx:bx + bw] = rng.choice([1, 2, 3, 4], p=[0.45, 0.30, 0.10, 0.15])
    # industrial sheds and school blocks
    for (x0, y0, w, h, n) in [(ind_x, ind_y, 130, 90, 5)]:
        for _ in range(n):
            bw, bh = int(rng.integers(22, 40)), int(rng.integers(12, 20))
            bx, by = int(x0 + rng.integers(2, max(3, 130 - bw))), int(y0 + rng.integers(2, max(3, 90 - bh)))
            if not building[by:by + bh, bx:bx + bw].any():
                building[by:by + bh, bx:bx + bw] = True
                roof_kind[by:by + bh, bx:bx + bw] = 1
    for m in school_rects:
        ys, xs = np.where(m)
        if ys.size:
            bx, by = int(xs.min() + 8), int(ys.min() + 6)
            for k in range(2):
                building[by + k * 24:by + k * 24 + 9, bx:bx + 34] = True
                roof_kind[by + k * 24:by + k * 24 + 9, bx:bx + 34] = 4
    building &= ~channel

    # ------------------------------------------------------------------ canopy
    canopy = np.zeros((H, W), bool)
    tree_p = np.clip(0.55 * (1 - density) + 0.25 * _noise(rng, (H, W), 25) + 0.15, 0.02, 0.95)
    for _ in range(5500):
        tx, ty = int(rng.integers(4, W - 4)), int(rng.integers(4, H - 4))
        if building[ty, tx] or channel[ty, tx] or industrial[ty, tx] and rng.random() < 0.9:
            continue
        if rng.random() > tree_p[ty, tx]:
            continue
        r = rng.uniform(1.8, 5.0)
        y0, y1, x0, x1 = max(0, int(ty - r - 2)), min(H, int(ty + r + 3)), max(0, int(tx - r - 2)), min(W, int(tx + r + 3))
        sub_y, sub_x = yy[y0:y1, x0:x1], xx[y0:y1, x0:x1]
        wob = 1 + 0.18 * np.sin(np.arctan2(sub_y - ty, sub_x - tx) * rng.integers(3, 6) + rng.uniform(0, 6))
        canopy[y0:y1, x0:x1] |= np.hypot(sub_y - ty, sub_x - tx) < r * wob
    # avenue trees along some arterials
    for (p0, p1) in arterials:
        n = int(np.hypot(p1[0] - p0[0], p1[1] - p0[1]) // 13)
        if rng.random() < 0.55:
            continue
        for i in range(n):
            t = i / max(n, 1)
            cx, cy = p0[0] + t * (p1[0] - p0[0]), p0[1] + t * (p1[1] - p0[1])
            side = rng.choice([-1, 1]) * 5.5
            nx, ny = (p1[1] - p0[1]), -(p1[0] - p0[0])
            norm = np.hypot(nx, ny) + 1e-9
            tx, ty = cx + side * nx / norm, cy + side * ny / norm
            if 3 < tx < W - 3 and 3 < ty < H - 3 and rng.random() < 0.8:
                r = rng.uniform(2.2, 3.8)
                canopy |= np.hypot(yy - ty, xx - tx) < r
    # park: dense canopy with clearings
    pn = _noise(rng, (H, W), 9)
    canopy |= park & (pn > -0.35)
    # a couple of groves
    for _ in range(3):
        gx0, gy0 = rng.uniform(40, W - 40), rng.uniform(40, H - 40)
        gn = _noise(rng, (H, W), 6)
        canopy |= ((np.hypot(xx - gx0, yy - gy0) < rng.uniform(22, 38)) & (gn > -0.2) & ~building & ~road_paved)
    canopy &= ~(channel & (rng.random((H, W)) < 0.97))

    # ---------------------------------------------------------------- labels
    labels = np.full((H, W), SOIL, np.uint8)
    labels[road_paved | building | channel] = CONCRETE
    labels[canopy] = CANOPY

    # ---------------------------------------------------------- render image
    soil_px = np.kron(soil, np.ones((config.CELL_PX, config.CELL_PX), np.int32))
    img = np.zeros((H, W, 3), np.float32)
    for i, name in enumerate(SOIL_NAMES):
        img[soil_px == i] = SOIL_RGB[name]
    patch = _noise(rng, (H, W), 14)
    dry_grass = np.clip((patch - 0.6) * 1.5, 0, 0.55)[..., None]
    img = img * (1 - dry_grass) + np.array([142, 142, 88], np.float32) * dry_grass
    img[road_unpaved & ~building] = img[road_unpaved & ~building] * 0.7 + np.array([205, 170, 130]) * 0.3
    # paved surfaces
    asphalt = np.array([72, 74, 78], np.float32) + 10 * _noise(rng, (H, W), 2)[..., None]
    img[road_paved] = asphalt[road_paved]
    img[channel] = np.array([150, 150, 146], np.float32)
    roof_colors = {1: (165, 168, 172), 2: (148, 88, 62), 3: (176, 74, 52), 4: (205, 202, 194)}
    for k, col in roof_colors.items():
        m = building & (roof_kind == k)
        base = np.array(col, np.float32) + rng.normal(0, 7)  # per-roof-type jitter
        img[m] = base
    # per-building tone variation (so identical colours are not a free signal)
    lab_b, nb = ndi.label(building)
    tone = rng.normal(0, 14, nb + 1).astype(np.float32)
    img[building] += tone[lab_b[building]][:, None]
    # shadows cast SE of buildings / trees onto non-canopy ground
    cast = ndi.shift((building | canopy).astype(np.float32), (2, 2), order=0) > 0.5
    shade = cast & ~building & ~canopy
    img[shade] *= 0.72
    # canopy last (it overhangs everything)
    mott = _noise(rng, (H, W), 1.4)
    canopy_rgb = np.stack([46 + 9 * mott, 96 + 16 * mott, 44 + 8 * mott], -1)
    light = _noise(rng, (H, W), 6) > 0.9
    canopy_rgb[light] += np.array([18, 28, 6])
    img[canopy] = canopy_rgb[canopy]
    # global illumination + sensor noise
    img *= (1 + 0.06 * _noise(rng, (H, W), 60))[..., None]
    img += rng.normal(0, 6.5, img.shape)
    img = ndi.gaussian_filter(img, (0.6, 0.6, 0))  # slight optical blur
    img = np.clip(img, 0, 255).astype(np.uint8)

    # ---------------------------------------------- cell-level GIS layers
    def frac(mask):
        return mask.reshape(rows, config.CELL_PX, cols, config.CELL_PX).mean(axis=(1, 3))

    bld_f, road_f = frac(building), frac(road_paved | channel)
    chan_f = frac(channel)
    dens_f = ndi.uniform_filter(bld_f, 3)

    zoning = np.where(dens_f > 0.27, 0, 1).astype(np.int32)                     # residential
    near_artery = (art_dist < 14)[:: config.CELL_PX, :: config.CELL_PX][:rows, :cols]
    zoning[near_artery & (dens_f > 0.12)] = 2                                   # commercial frontage
    zoning[frac(industrial) > 0.4] = 3
    zoning[frac(school) > 0.4] = 4
    zoning[frac(park) > 0.4] = 5
    zoning[road_f > 0.5] = 6
    zoning[ndi.maximum_filter(chan_f, 3) > 0.15] = 7

    # wards: nearest of N seeds, values correlated with built density but with real-world scatter
    n_ward = 12
    seeds_rc = np.stack([rng.uniform(0, rows, n_ward), rng.uniform(0, cols, n_ward)], 1)
    rr, cc = np.mgrid[0:rows, 0:cols]
    d2 = (rr[..., None] - seeds_rc[:, 0]) ** 2 + (cc[..., None] - seeds_rc[:, 1]) ** 2
    ward = d2.argmin(-1).astype(np.int32)
    ward_attrs = []
    can_f = frac(canopy)
    for w in range(n_ward):
        m = ward == w
        d_mean = float(dens_f[m].mean()) if m.any() else 0.0
        c_mean = float(can_f[m].mean()) if m.any() else 0.0
        hvi = float(np.clip(0.25 + 1.1 * d_mean - 0.8 * c_mean + rng.normal(0, 0.12), 0.05, 0.98))
        asthma = float(np.clip(35 + 95 * (0.6 * hvi + 0.4 * rng.random()), 20, 140))
        pop = float(np.clip(4000 + 21000 * d_mean + rng.normal(0, 2500), 1500, 30000))
        ward_attrs.append({
            "ward_id": w, "ward_name": f"Demo Ward {w + 1}",
            "heat_vulnerability_index": round(hvi, 3),
            "asthma_per_1000": round(asthma, 1),
            "pop_per_km2": round(pop, 0),
        })

    return Tile(img, labels, spec, elev, soil, zoning, ward, ward_attrs, seed)


# --------------------------------------------------------------------------
# Export to the same formats a municipality would hand over
# --------------------------------------------------------------------------

def _raster_to_geojson(grid: np.ndarray, spec: GridSpec, names: list[str] | None,
                       prop: str, extra: dict[int, dict] | None = None) -> dict:
    """Dissolve integer cell grid into one (Multi)Polygon per value."""
    from shapely.geometry import box, mapping
    from shapely import union_all

    west, south, east, north = spec.bbox
    dx, dy = (east - west) / spec.cols, (north - south) / spec.rows
    feats = []
    for v in np.unique(grid):
        rs, cs = np.where(grid == v)
        geoms = [box(west + c * dx, north - (r + 1) * dy, west + (c + 1) * dx, north - r * dy)
                 for r, c in zip(rs, cs)]
        geom = union_all(geoms)
        props = {prop: names[int(v)] if names else int(v)}
        if extra and int(v) in extra:
            props.update(extra[int(v)])
        feats.append({"type": "Feature", "properties": props, "geometry": mapping(geom)})
    return {"type": "FeatureCollection", "features": feats}


def export_demo_dataset(out_dir: Path, seed: int = 2026) -> dict:
    """Write imagery + GIS layers (GeoTIFF/PNG/GeoJSON) a planner would normally upload."""
    import rasterio
    from PIL import Image
    from rasterio.transform import from_bounds

    out_dir.mkdir(parents=True, exist_ok=True)
    t = generate_tile(seed)
    west, south, east, north = t.spec.bbox

    Image.fromarray(t.image).save(out_dir / "lagos_demo_tile.png")
    Image.fromarray(t.image).save(out_dir / "lagos_demo_tile.jpg", quality=88)
    with rasterio.open(
        out_dir / "lagos_demo_tile.tif", "w", driver="GTiff", height=t.spec.height_px, width=t.spec.width_px,
        count=3, dtype="uint8", crs="EPSG:4326",
        transform=from_bounds(west, south, east, north, t.spec.width_px, t.spec.height_px),
        compress="deflate",
    ) as dst:
        dst.write(np.moveaxis(t.image, -1, 0))
    with rasterio.open(
        out_dir / "lagos_demo_elevation.tif", "w", driver="GTiff", height=t.spec.rows, width=t.spec.cols,
        count=1, dtype="float32", crs="EPSG:4326",
        transform=from_bounds(west, south, east, north, t.spec.cols, t.spec.rows),
    ) as dst:
        dst.write(t.elevation[None])

    ward_extra = {a["ward_id"]: a for a in t.ward_attrs}
    layers = {
        "wards_health.geojson": _raster_to_geojson(t.ward, t.spec, None, "ward_id", ward_extra),
        "soil.geojson": _raster_to_geojson(t.soil, t.spec, list(SOIL_NAMES), "soil_type"),
        "zoning.geojson": _raster_to_geojson(t.zoning, t.spec, list(ZONING_NAMES), "zone"),
    }
    for name, gj in layers.items():
        (out_dir / name).write_text(json.dumps(gj))
    np.save(out_dir / "truth_labels.npy", t.labels)
    meta = {
        "synthetic": True,
        "disclaimer": "Synthetic demonstration data. Not a measurement of real Lagos.",
        "seed": seed, "spec": t.spec.to_dict(), "files": sorted(p.name for p in out_dir.iterdir()),
    }
    (out_dir / "README.json").write_text(json.dumps(meta, indent=2))
    return meta
