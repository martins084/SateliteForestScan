"""Vegetation indices with a small registry.

Adding an index:

    @register_index("myidx", bands=("B08", "B04"), stress_sign=-1,
                    description="...")
    def myidx(ds):
        return ...

`stress_sign` tells the anomaly step which direction means "more stress":
-1 = the index decreases under stress (NDVI, NDRE, NDMI), +1 = it increases (CRSWIR).

Resolution note: B04/B08 are native 10 m; B05, B8A, B11, B12 are 20 m and are
bilinearly resampled to the 10 m grid when loaded. NDRE, NDMI and CRSWIR are
therefore effectively 20 m products on a 10 m grid.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import xarray as xr

# Central wavelengths (micrometres), Sentinel-2 MSI (mean of S2A/S2B).
WAVELENGTH = {"B8A": 0.865, "B11": 1.610, "B12": 2.190}


@dataclass(frozen=True)
class IndexSpec:
    name: str
    bands: tuple[str, ...]
    stress_sign: int
    func: Callable[[xr.Dataset], xr.DataArray]
    description: str


INDICES: dict[str, IndexSpec] = {}


def register_index(name: str, bands: tuple[str, ...], stress_sign: int, description: str = ""):
    def deco(func):
        INDICES[name] = IndexSpec(name, bands, stress_sign, func, description)
        return func
    return deco


def _nd(a: xr.DataArray, b: xr.DataArray) -> xr.DataArray:
    s = a + b
    return ((a - b) / s.where(s > 0)).astype("float32")


@register_index("ndvi", ("B08", "B04"), -1, "Normalized Difference Vegetation Index (B08, B04)")
def ndvi(ds: xr.Dataset) -> xr.DataArray:
    return _nd(ds.B08, ds.B04)


@register_index("ndre", ("B8A", "B05"), -1, "Normalized Difference Red Edge (B8A, B05)")
def ndre(ds: xr.Dataset) -> xr.DataArray:
    return _nd(ds.B8A, ds.B05)


@register_index("ndmi", ("B8A", "B11"), -1, "Normalized Difference Moisture Index (B8A, B11)")
def ndmi(ds: xr.Dataset) -> xr.DataArray:
    return _nd(ds.B8A, ds.B11)


@register_index("crswir", ("B8A", "B11", "B12"), +1,
                "Continuum-removed SWIR: B11 / linear continuum between B8A and B12 at 1610 nm")
def crswir(ds: xr.Dataset) -> xr.DataArray:
    w8a, w11, w12 = WAVELENGTH["B8A"], WAVELENGTH["B11"], WAVELENGTH["B12"]
    continuum = ds.B8A + (ds.B12 - ds.B8A) * ((w11 - w8a) / (w12 - w8a))
    return (ds.B11 / continuum.where(continuum > 0)).astype("float32")


def compute_indices(ds: xr.Dataset, names: list[str]) -> xr.Dataset:
    """Lazily compute the requested indices; keeps time/coords of `ds`."""
    unknown = [n for n in names if n not in INDICES]
    if unknown:
        raise KeyError(f"Unknown indices {unknown}; available: {sorted(INDICES)}")
    out = xr.Dataset(coords={k: v for k, v in ds.coords.items()})
    for n in names:
        spec = INDICES[n]
        da = spec.func(ds)
        da = da.where(np.isfinite(da))
        da.attrs = {"long_name": spec.description, "stress_sign": spec.stress_sign}
        out[n] = da
    return out
