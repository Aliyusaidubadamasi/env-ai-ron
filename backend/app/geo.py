"""Georeferencing helpers: pixel/cell <-> lon/lat, and GeoJSON polygon rasterisation.

Kept dependency-light (numpy + Pillow) so the core engine runs anywhere.
GeoTIFF reading and shapefile export use rasterio / geopandas when available.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np
from PIL import Image, ImageDraw

from . import config


@dataclass(frozen=True)
class GridSpec:
    """Maps a north-up raster tile onto lon/lat and onto coarser planning cells."""

    bbox: tuple[float, float, float, float]  # west, south, east, north
    height_px: int
    width_px: int
    cell_px: int = config.CELL_PX

    @property
    def rows(self) -> int:
        return self.height_px // self.cell_px

    @property
    def cols(self) -> int:
        return self.width_px // self.cell_px

    @property
    def lat_mid(self) -> float:
        return (self.bbox[1] + self.bbox[3]) / 2

    @property
    def px_size_m(self) -> tuple[float, float]:
        """(x metres per pixel, y metres per pixel)."""
        west, south, east, north = self.bbox
        mx = (east - west) * 111_320 * math.cos(math.radians(self.lat_mid)) / self.width_px
        my = (north - south) * 110_540 / self.height_px
        return mx, my

    @property
    def cell_area_m2(self) -> float:
        mx, my = self.px_size_m
        return mx * my * self.cell_px * self.cell_px

    def cell_center_lonlat(self, r: np.ndarray | int, c: np.ndarray | int):
        west, south, east, north = self.bbox
        lon = west + (np.asarray(c) + 0.5) / self.cols * (east - west)
        lat = north - (np.asarray(r) + 0.5) / self.rows * (north - south)
        return lon, lat

    def lonlat_to_cell(self, lon: float, lat: float) -> tuple[int, int] | None:
        west, south, east, north = self.bbox
        if not (west <= lon <= east and south <= lat <= north):
            return None
        c = int((lon - west) / (east - west) * self.cols)
        r = int((north - lat) / (north - south) * self.rows)
        return min(r, self.rows - 1), min(c, self.cols - 1)

    def to_dict(self) -> dict:
        return {
            "bbox": list(self.bbox),
            "height_px": self.height_px,
            "width_px": self.width_px,
            "cell_px": self.cell_px,
            "rows": self.rows,
            "cols": self.cols,
            "cell_area_m2": round(self.cell_area_m2, 1),
        }


def block_reduce_mode(labels: np.ndarray, block: int, n_classes: int) -> np.ndarray:
    """Per-cell class fractions: (rows, cols, n_classes)."""
    h, w = labels.shape
    rows, cols = h // block, w // block
    trimmed = labels[: rows * block, : cols * block]
    out = np.zeros((rows, cols, n_classes), dtype=np.float32)
    blocks = trimmed.reshape(rows, block, cols, block).transpose(0, 2, 1, 3).reshape(rows, cols, -1)
    for k in range(n_classes):
        out[..., k] = (blocks == k).mean(axis=-1)
    return out


# --------------------------------------------------------------------------
# GeoJSON rasterisation (municipal GIS layers -> analysis grid)
# --------------------------------------------------------------------------

def _iter_polygons(geom: dict) -> Iterable[list[list[tuple[float, float]]]]:
    t = geom.get("type")
    coords = geom.get("coordinates", [])
    if t == "Polygon":
        yield coords
    elif t == "MultiPolygon":
        for poly in coords:
            yield poly
    elif t == "GeometryCollection":
        for g in geom.get("geometries", []):
            yield from _iter_polygons(g)


def rasterize_geojson(
    geojson: dict | str | bytes,
    spec: GridSpec,
    attribute: str,
    *,
    categorical: bool = False,
    default: Any = np.nan,
) -> tuple[np.ndarray, list[str]]:
    """Burn polygon features onto the planning-cell grid.

    Returns (grid, categories). For numeric layers grid is float32 with `default`
    where no polygon covers the cell. For categorical layers grid holds category
    indices (-1 where uncovered) and `categories` lists the labels.
    """
    if isinstance(geojson, (str, bytes)):
        geojson = json.loads(geojson)
    feats = geojson.get("features", []) if geojson.get("type") == "FeatureCollection" else [geojson]

    rows, cols = spec.rows, spec.cols
    west, south, east, north = spec.bbox

    def to_xy(lon: float, lat: float) -> tuple[float, float]:
        return (lon - west) / (east - west) * cols, (north - lat) / (north - south) * rows

    categories: list[str] = []
    if categorical:
        canvas = Image.new("I", (cols, rows), -1)
    else:
        canvas = Image.new("F", (cols, rows), float("nan") if default is np.nan else float(default))
    draw = ImageDraw.Draw(canvas)

    for f in feats:
        props = f.get("properties") or {}
        if attribute not in props or props[attribute] is None:
            continue
        val = props[attribute]
        if categorical:
            val = str(val)
            if val not in categories:
                categories.append(val)
            fill: float | int = categories.index(val)
        else:
            try:
                fill = float(val)
            except (TypeError, ValueError):
                continue
        for poly in _iter_polygons(f.get("geometry") or {}):
            if not poly:
                continue
            ring = [to_xy(*pt[:2]) for pt in poly[0]]
            if len(ring) >= 3:
                draw.polygon(ring, fill=fill)
            for hole in poly[1:]:  # cut holes back out
                hring = [to_xy(*pt[:2]) for pt in hole]
                if len(hring) >= 3:
                    draw.polygon(hring, fill=-1 if categorical else float("nan"))

    grid = np.array(canvas)
    return (grid.astype(np.int32) if categorical else grid.astype(np.float32)), categories


# --------------------------------------------------------------------------
# GeoTIFF ingestion (optional rasterio)
# --------------------------------------------------------------------------

def read_geotiff(path: str) -> tuple[np.ndarray, tuple[float, float, float, float]]:
    """Read first three bands as uint8 RGB plus WGS84 bbox. Requires rasterio."""
    import rasterio
    from rasterio.warp import transform_bounds

    with rasterio.open(path) as src:
        count = min(3, src.count)
        arr = src.read(list(range(1, count + 1)))
        if count < 3:
            arr = np.repeat(arr[:1], 3, axis=0)
        bounds = src.bounds
        if src.crs and src.crs.to_epsg() != 4326:
            bounds = rasterio.coords.BoundingBox(*transform_bounds(src.crs, "EPSG:4326", *bounds))
    arr = np.moveaxis(arr, 0, -1)
    if arr.dtype != np.uint8:  # scale 16-bit / float imagery to 8-bit using 2-98 percentile
        lo, hi = np.percentile(arr, (2, 98))
        arr = np.clip((arr.astype(np.float32) - lo) / max(hi - lo, 1e-6) * 255, 0, 255).astype(np.uint8)
    return arr, (bounds.left, bounds.bottom, bounds.right, bounds.top)


def smooth_normalise(a: np.ndarray, lo_pct: float = 2, hi_pct: float = 98) -> np.ndarray:
    """Robust 0-1 normalisation (NaN-safe)."""
    a = np.asarray(a, dtype=np.float32)
    finite = a[np.isfinite(a)]
    if finite.size == 0:
        return np.zeros_like(a)
    lo, hi = np.percentile(finite, (lo_pct, hi_pct))
    if hi - lo < 1e-9:
        return np.zeros_like(a)
    return np.clip(np.nan_to_num((a - lo) / (hi - lo), nan=0.0), 0, 1)


def read_raster_band(path: str, spec: GridSpec) -> tuple[np.ndarray, str | None]:
    """Read band 1 of a raster (e.g. DEM) resampled onto the planning grid. Requires rasterio.

    Returns (grid, warning). The raster is warped onto the tile bbox in EPSG:4326.
    """
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.transform import from_bounds
    from rasterio.warp import reproject

    west, south, east, north = spec.bbox
    dst = np.full((spec.rows, spec.cols), np.nan, np.float32)
    with rasterio.open(path) as src:
        reproject(
            source=rasterio.band(src, 1), destination=dst,
            dst_transform=from_bounds(west, south, east, north, spec.cols, spec.rows),
            dst_crs="EPSG:4326", resampling=Resampling.bilinear, dst_nodata=np.nan,
        )
    cover = float(np.isfinite(dst).mean())
    warn = None if cover > 0.9 else f"Raster covers only {cover:.0%} of the tile; gaps filled with the mean."
    if cover == 0:
        raise ValueError("Raster does not overlap the tile bounding box.")
    dst = np.where(np.isfinite(dst), dst, np.nanmean(dst)).astype(np.float32)
    return dst, warn
