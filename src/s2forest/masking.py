"""Cloud / shadow / snow / defect masking from the Sen2Cor SCL band."""

from __future__ import annotations

import dask.array as da
import numpy as np
import xarray as xr
from scipy.ndimage import binary_dilation

# Classes whose masks are grown by the cloud buffer (SCL edges are usually too tight).
BUFFERED_CLASSES = (3, 8, 9, 10)


def _disk(radius: int) -> np.ndarray:
    y, x = np.ogrid[-radius:radius + 1, -radius:radius + 1]
    return x * x + y * y <= radius * radius


def _dilate2d(block: np.ndarray, radius: int) -> np.ndarray:
    if radius <= 0:
        return block
    out = np.empty_like(block)
    for idx in np.ndindex(block.shape[:-2]):
        out[idx] = binary_dilation(block[idx], structure=_disk(radius))
    return out


def valid_mask(scl: xr.DataArray, invalid_classes: list[int], buffer_px: int = 0) -> xr.DataArray:
    """True where the observation is usable (clear land/vegetation)."""
    invalid = scl.isin(invalid_classes)
    if buffer_px > 0:
        grow = scl.isin([c for c in BUFFERED_CLASSES if c in invalid_classes])
        data = grow.data
        if isinstance(data, da.Array):
            depth = {i: 0 for i in range(data.ndim)}
            depth[data.ndim - 1] = depth[data.ndim - 2] = buffer_px
            grown = data.map_overlap(_dilate2d, depth=depth, boundary=False,
                                     radius=buffer_px, dtype=bool)
        else:
            grown = _dilate2d(np.asarray(data), buffer_px)
        invalid = invalid | grow.copy(data=grown)
    return ~invalid


def valid_fraction(mask: xr.DataArray, region: np.ndarray) -> xr.DataArray | float:
    """Share of `region` pixels (bool y,x array) that are valid. Per time step if 3-D."""
    region_da = xr.DataArray(region, dims=("y", "x"))
    n = int(region.sum())
    if n == 0:
        raise ValueError("Region mask is empty - AOI does not overlap the grid")
    return mask.where(region_da, False).sum(dim=("y", "x")) / n
