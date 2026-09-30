"""Temporal haze / thin-cloud test (complements SCL, which misses thin cloud).

For each pixel and observation:

1. reference = median B02 of the pixel's valid observations from the BASELINE
   years within +-doy_window days (the monitoring year is excluded, so real
   changes in it do not contaminate the reference);
2. candidate = B02 - reference > b02_threshold;
3. the candidate is MASKED only if it is transient: the pixel's next valid
   observation in the same season is not a candidate. If the elevation persists
   (e.g. a clear-cut or dead trees brightening the canopy), it is kept;
4. the last valid observation of a season has no successor. It is KEPT
   (conservative for a screening tool: masking could hide the onset of real
   damage, and a single observation cannot trigger a detection anyway because
   the anomaly step requires persistence). Such cases are reported as
   `haze_unresolved` in the diagnostics.
"""

from __future__ import annotations

import numpy as np
import xarray as xr

from .config import HazeConfig
from .temporal import doy_reference_stats, time_info


def haze_mask_numpy(b02: np.ndarray, valid: np.ndarray, doy: np.ndarray, year: np.ndarray,
                    baseline_years: list[int], threshold: float, window: int,
                    min_ref_obs: int) -> tuple[np.ndarray, np.ndarray]:
    """b02, valid: (T, ...) sorted by time. Returns (masked, unresolved) bool arrays."""
    vals = np.where(valid, b02, np.nan).astype("float32")
    ref, _, _ = doy_reference_stats(vals, doy, np.isin(year, baseline_years), window, min_ref_obs)
    with np.errstate(invalid="ignore"):
        cand = valid & ((vals - ref) > threshold)

    masked = np.zeros(cand.shape, dtype=bool)
    unresolved = np.zeros(cand.shape, dtype=bool)
    # Backward scan: state = candidate flag of the next valid obs in the same season
    # (-1 = none yet).
    state = np.full(cand.shape[1:], -1, dtype="int8")
    cur_year = None
    for t in range(cand.shape[0] - 1, -1, -1):
        if year[t] != cur_year:
            state[...] = -1
            cur_year = year[t]
        masked[t] = cand[t] & (state == 0)
        unresolved[t] = cand[t] & (state == -1)
        state = np.where(valid[t], cand[t].astype("int8"), state)
    return masked, unresolved


def haze_mask(b02: xr.DataArray, valid: xr.DataArray, baseline_years: list[int],
              cfg: HazeConfig) -> tuple[xr.DataArray, xr.DataArray]:
    """Dask-friendly wrapper: the full time axis is needed, space is chunked."""
    doy, year = time_info(b02.time.values)
    order = np.argsort(b02.time.values)
    if not np.array_equal(order, np.arange(order.size)):
        raise ValueError("time axis must be sorted")

    def _run(b, v):
        # apply_ufunc moves the core dim last: (..., time) -> (time, ...)
        m, u = haze_mask_numpy(np.moveaxis(b, -1, 0), np.moveaxis(v, -1, 0), doy, year,
                               baseline_years, cfg.b02_threshold, cfg.doy_window,
                               cfg.min_ref_obs)
        return np.moveaxis(m, 0, -1), np.moveaxis(u, 0, -1)

    chunks = {"time": -1}
    if b02.chunks is not None:
        chunks.update({"y": 256, "x": 256})
    b = b02.chunk(chunks) if b02.chunks is not None else b02
    v = valid.chunk(chunks) if valid.chunks is not None else valid
    masked, unresolved = xr.apply_ufunc(
        _run, b, v,
        input_core_dims=[["time"], ["time"]],
        output_core_dims=[["time"], ["time"]],
        dask="parallelized",
        output_dtypes=[bool, bool],
    )
    return masked.transpose(*b02.dims), unresolved.transpose(*b02.dims)
