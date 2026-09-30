"""Forest mask from Copernicus HRL Dominant Leaf Type 2018 (10 m).

Fetched from the public EEA ArcGIS ImageServer (no authentication), clipped to
the grid and cached as GeoTIFF.

Classes: 0 all non-tree areas, 1 broadleaved, 2 coniferous, 254 unclassifiable,
255 outside area.

Limitations (also stated in the README):
* Reference year 2018 - stands clear-cut since then are still marked forest.
* "Coniferous" includes Scots pine; spruce cannot be separated from pine with
  this layer. Use stand polygons (species attribute) where available.
"""

from __future__ import annotations

import io
import math
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import requests
import xarray as xr
from odc.geo.geobox import GeoBox
from rasterio.transform import from_bounds
from rasterio.warp import Resampling, reproject, transform_bounds

DLT_URL = ("https://image.discomap.eea.europa.eu/arcgis/rest/services/GioLandPublic/"
           "HRL_DominantLeafType2018/ImageServer/exportImage")
DLT_CRS = "EPSG:3035"
MAX_PX = 4000  # server limit is 15000 x 4100


def _download_dlt(bounds_3035: tuple[float, float, float, float], res: float = 10.0) -> tuple[np.ndarray, object]:
    minx, miny, maxx, maxy = bounds_3035
    minx, miny = math.floor(minx / res) * res, math.floor(miny / res) * res
    maxx, maxy = math.ceil(maxx / res) * res, math.ceil(maxy / res) * res
    width, height = int((maxx - minx) / res), int((maxy - miny) / res)
    out = np.full((height, width), 255, dtype="uint8")
    for r0 in range(0, height, MAX_PX):
        for c0 in range(0, width, MAX_PX):
            h, w = min(MAX_PX, height - r0), min(MAX_PX, width - c0)
            bx0, by1 = minx + c0 * res, maxy - r0 * res
            params = {
                "bbox": f"{bx0},{by1 - h * res},{bx0 + w * res},{by1}",
                "bboxSR": 3035, "imageSR": 3035, "size": f"{w},{h}",
                "format": "tiff", "pixelType": "U8",
                "interpolation": "RSP_NearestNeighbor", "f": "image",
            }
            resp = requests.get(DLT_URL, params=params, timeout=120)
            resp.raise_for_status()
            with rasterio.MemoryFile(io.BytesIO(resp.content)) as mf, mf.open() as src:
                out[r0:r0 + h, c0:c0 + w] = src.read(1)
    return out, from_bounds(minx, miny, maxx, maxy, width, height)


def dlt_on_grid(geobox: GeoBox, cache_file: Path) -> np.ndarray:
    """DLT class array (y, x) on the analysis grid, cached."""
    if cache_file.exists():
        with rasterio.open(cache_file) as src:
            return src.read(1)
    b = geobox.boundingbox
    bounds = transform_bounds(str(geobox.crs), DLT_CRS, b.left, b.bottom, b.right, b.top)
    pad = 50.0
    src_arr, src_tr = _download_dlt((bounds[0] - pad, bounds[1] - pad, bounds[2] + pad, bounds[3] + pad))
    dst = np.full(geobox.shape, 255, dtype="uint8")
    reproject(src_arr, dst, src_transform=src_tr, src_crs=DLT_CRS,
              dst_transform=geobox.affine, dst_crs=str(geobox.crs),
              resampling=Resampling.nearest, src_nodata=None, dst_nodata=255)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(cache_file, "w", driver="GTiff", width=dst.shape[1], height=dst.shape[0],
                       count=1, dtype="uint8", crs=str(geobox.crs), transform=geobox.affine,
                       nodata=255, compress="deflate") as f:
        f.write(dst, 1)
    return dst


# Codes of the forest mask raster written to the outputs.
FOREST_NOT_IN_HRL = 0
FOREST_ANALYSED = 1
FOREST_LOW_NDVI = 2      # in HRL class, but low baseline summer NDVI (felled / young)
FOREST_NO_DATA = 3       # in HRL class, but no clear summer observation in the baseline
FOREST_LINEAR = 4        # in HRL class, but within the buffer of a road (OSM)


def summer_median(da: xr.DataArray, years: list[int], start: str, end: str) -> xr.DataArray:
    """Per-pixel median of `da` over the summer window of the given years."""
    t = pd.DatetimeIndex(da.time.values)
    mmdd = t.strftime("%m-%d")
    sel = np.isin(t.year, years) & (mmdd >= start) & (mmdd <= end)
    if not sel.any():
        return xr.full_like(da.isel(time=0, drop=True), np.nan)
    return da.isel(time=np.flatnonzero(sel)).median("time", skipna=True)


def refine_forest_mask(hrl: np.ndarray, ndvi_summer: np.ndarray,
                       min_ndvi: float | None) -> np.ndarray:
    """Coded mask (see FOREST_* constants) from the HRL mask and baseline summer NDVI."""
    codes = np.full(hrl.shape, FOREST_NOT_IN_HRL, dtype="uint8")
    codes[hrl] = FOREST_ANALYSED
    if min_ndvi is not None:
        nodata = hrl & np.isnan(ndvi_summer)
        with np.errstate(invalid="ignore"):
            low = hrl & (ndvi_summer < min_ndvi)
        codes[low] = FOREST_LOW_NDVI
        codes[nodata] = FOREST_NO_DATA
    return codes


def forest_fraction(geobox: GeoBox, fine_geobox: GeoBox, cache_dir: Path,
                    classes: list[int]) -> np.ndarray:
    """Share of each (coarse) pixel of `geobox` covered by the HRL classes.

    The 10 m HRL layer is fetched on `fine_geobox` (same extent as `geobox`,
    10 m) and aggregated by averaging.
    """
    dlt = dlt_on_grid(fine_geobox, cache_dir / "forest_hrl_dlt_2018_context10m.tif")
    frac = np.isin(dlt, classes).astype("float32")
    dst = np.zeros(geobox.shape, dtype="float32")
    reproject(frac, dst, src_transform=fine_geobox.affine, src_crs=str(fine_geobox.crs),
              dst_transform=geobox.affine, dst_crs=str(geobox.crs),
              resampling=Resampling.average)
    return dst


def forest_mask(geobox: GeoBox, cache_dir: Path, source: str, classes: list[int]) -> np.ndarray | None:
    """Boolean forest mask on the grid, or None if disabled."""
    if source == "none":
        return None
    if source == "hrl_dlt_2018":
        dlt = dlt_on_grid(geobox, cache_dir / "forest_hrl_dlt_2018.tif")
        return np.isin(dlt, classes)
    raise ValueError(f"Unknown forest mask source: {source}")
