"""Loading of Sentinel-1 RTC acquisitions onto the analysis grid (cached) and composites."""

from __future__ import annotations

import logging
import warnings
from pathlib import Path

import numpy as np
import odc.stac
import planetary_computer
import xarray as xr
from odc.geo.geobox import GeoBox

from .event import Acquisition

log = logging.getLogger(__name__)


def mask_nodata(arr: np.ndarray, nodata: float) -> np.ndarray:
    """Nodata (odc-stac keeps -32768 as a value) and non-positive gamma0 -> NaN."""
    out = np.asarray(arr, dtype="float32").copy()
    with np.errstate(invalid="ignore"):
        out[(out == nodata) | ~(out > 0)] = np.nan
    return out


def acquisition_key(a: Acquisition) -> str:
    return f"{a.date:%Y%m%d}_{a.platform.replace('sentinel-', 'S')}_o{a.rel_orbit:03d}"


def load_acquisition(a: Acquisition, geobox: GeoBox, pols: list[str], nodata: float,
                     resampling: str, cache_dir: Path) -> dict[str, np.ndarray]:
    """Linear gamma0 per polarization (y, x), NaN outside the footprint. Cached as .npz."""
    path = cache_dir / f"{acquisition_key(a)}.npz"
    if path.exists():
        with np.load(path) as z:
            return {p: z[p] for p in pols}
    items = [planetary_computer.sign(s.item) for s in a.scenes]
    ds = odc.stac.load(items, bands=pols, geobox=geobox, resampling=resampling,
                       groupby="solar_day", nodata=nodata)
    out = {}
    for p in pols:
        v = ds[p].values
        if v.ndim == 3:   # several solar days should not happen within one acquisition
            v = v[0] if v.shape[0] == 1 else np.where(v == nodata, np.nan, v).max(axis=0)
        out[p] = mask_nodata(v, nodata)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **out)
    return out


def composite_db(stack: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Mean in linear scale over acquisitions, then dB. Returns (dB (y, x), count (y, x))."""
    arr = np.stack(stack).astype("float32")
    n = np.isfinite(arr).sum(axis=0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        mean = np.nanmean(arr, axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        db = 10.0 * np.log10(mean)
    db[n == 0] = np.nan
    return db.astype("float32"), n.astype("int16")


def to_db(x: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return (10.0 * np.log10(x)).astype("float32")


def stack_to_dataarray(arrs: list[np.ndarray], times, geobox: GeoBox, name: str) -> xr.DataArray:
    c = geobox.coordinates
    return xr.DataArray(np.stack(arrs), dims=("time", "y", "x"), name=name,
                        coords={"time": times, "y": c["y"].values, "x": c["x"].values})
