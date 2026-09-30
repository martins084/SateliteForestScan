"""Writing of raster outputs (GeoTIFF). Vector/CSV writers are added in later stages."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import xarray as xr
from rasterio.transform import from_origin


def _transform(da: xr.DataArray):
    x, y = da.x.values, da.y.values
    res_x = float(x[1] - x[0])
    res_y = float(y[0] - y[1])
    return from_origin(float(x[0]) - res_x / 2, float(y[0]) + res_y / 2, res_x, res_y)


def write_geotiff(da: xr.DataArray, path: Path, crs: str, band_names: list[str] | None = None,
                  nodata: float | int | None = None, dtype: str | None = None) -> Path:
    """Write a (y, x) or (band, y, x) DataArray as a tiled, compressed GeoTIFF."""
    arr = np.asarray(da.values)
    if arr.ndim == 2:
        arr = arr[None]
    dtype = dtype or str(arr.dtype)
    if dtype == "bool":
        dtype = "uint8"
    if nodata is None and np.issubdtype(np.dtype(dtype), np.floating):
        nodata = np.nan
    path.parent.mkdir(parents=True, exist_ok=True)
    profile = dict(driver="GTiff", width=arr.shape[2], height=arr.shape[1], count=arr.shape[0],
                   dtype=dtype, crs=crs, transform=_transform(da), nodata=nodata,
                   compress="deflate", tiled=True, blockxsize=256, blockysize=256)
    if np.issubdtype(np.dtype(dtype), np.floating):
        profile["predictor"] = 3
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(arr.astype(dtype))
        if band_names:
            for i, name in enumerate(band_names, start=1):
                dst.set_band_description(i, name)
    return path


def write_timeseries_geotiff(da: xr.DataArray, path: Path, crs: str) -> Path:
    """(time, y, x) -> one band per date; band descriptions are ISO dates."""
    names = pd.DatetimeIndex(da.time.values).strftime("%Y-%m-%d").tolist()
    return write_geotiff(da.transpose("time", "y", "x"), path, crs, band_names=names,
                         dtype="float32")
