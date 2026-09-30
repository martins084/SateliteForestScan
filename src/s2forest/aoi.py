"""Loading of vector inputs (AOI, stands, references) and the analysis grid."""

from __future__ import annotations

import hashlib
from pathlib import Path

import geopandas as gpd
import numpy as np
from odc.geo.geobox import GeoBox
from rasterio.features import rasterize
from shapely.geometry.base import BaseGeometry


def read_vector(path: str | Path, crs: str) -> gpd.GeoDataFrame:
    """Read GeoJSON / Shapefile / GeoPackage and reproject to `crs`."""
    gdf = gpd.read_file(path)
    if gdf.crs is None:
        raise ValueError(f"{path} has no CRS defined")
    gdf = gdf.to_crs(crs)
    gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()].copy()
    gdf["geometry"] = gdf.geometry.make_valid()
    return gdf


def aoi_geometry(gdf: gpd.GeoDataFrame) -> BaseGeometry:
    return gdf.geometry.union_all()


def make_geobox(geom: BaseGeometry, crs: str, resolution: float, buffer_m: float = 0.0) -> GeoBox:
    """10 m grid aligned to whole multiples of the resolution (stable across runs)."""
    minx, miny, maxx, maxy = geom.buffer(buffer_m).bounds if buffer_m else geom.bounds
    return GeoBox.from_bbox((minx, miny, maxx, maxy), crs=crs, resolution=resolution, tight=False)


def geobox_key(gbox: GeoBox) -> str:
    """Short hash identifying a grid; used as cache folder name."""
    a = gbox.affine
    s = f"{gbox.crs.epsg}|{gbox.shape}|{a.a:.3f},{a.c:.3f},{a.e:.3f},{a.f:.3f}"
    return hashlib.sha1(s.encode()).hexdigest()[:12]


def geometry_mask(geom: BaseGeometry, gbox: GeoBox) -> np.ndarray:
    """Boolean array (y, x), True inside the geometry (pixel centres)."""
    return rasterize(
        [(geom, 1)], out_shape=gbox.shape, transform=gbox.affine, fill=0, dtype="uint8"
    ).astype(bool)
