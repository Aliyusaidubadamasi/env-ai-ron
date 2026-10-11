from pathlib import Path

import geopandas as gpd
import rasterio
from rasterio.features import shapes


class GeoProcessing:
    """Utility functions for working with geospatial files."""

    @staticmethod
    def load_geojson(path: str | Path):
        return gpd.read_file(str(path))

    @staticmethod
    def load_raster(path: str | Path):
        return rasterio.open(str(path))

    @staticmethod
    def raster_class_summary(raster_path: str | Path) -> dict:
        with rasterio.open(str(raster_path)) as src:
            data = src.read(1)
            values, counts = __import__("numpy").unique(data, return_counts=True)
            return {str(int(value)): int(count) for value, count in zip(values, counts)}
