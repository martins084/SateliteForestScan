"""Per-pixel time-series helpers shared by the haze test and the anomaly baseline."""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd


def doy_distance(a: np.ndarray, b: int | np.ndarray) -> np.ndarray:
    """Circular day-of-year distance."""
    d = np.abs(np.asarray(a) - b)
    return np.minimum(d, 365 - d)


def window_indices(doy: np.ndarray, ref_sel: np.ndarray, window: int) -> list[np.ndarray]:
    """For every time step, the indices of reference time steps within +-window days."""
    ref_idx = np.flatnonzero(ref_sel)
    return [ref_idx[doy_distance(doy[ref_idx], d) <= window] for d in doy]


def doy_reference_stats(values: np.ndarray, doy: np.ndarray, ref_sel: np.ndarray, window: int,
                        min_obs: int, with_mad: bool = False
                        ) -> tuple[np.ndarray, np.ndarray | None, np.ndarray]:
    """Per time step and pixel: median (and MAD) of reference observations in the
    DOY window around that time step.

    values: (T, ...) with NaN for invalid. ref_sel: bool (T,) - which time steps may
    serve as reference (e.g. baseline years only).
    Returns (median, mad or None, count); median/mad are NaN where count < min_obs.
    """
    T = values.shape[0]
    med = np.full(values.shape, np.nan, dtype="float32")
    mad = np.full(values.shape, np.nan, dtype="float32") if with_mad else None
    cnt = np.zeros(values.shape, dtype="int16")
    cache: dict[bytes, tuple] = {}
    for t, idx in enumerate(window_indices(doy, ref_sel, window)):
        if idx.size == 0:
            continue
        key = idx.tobytes()
        if key not in cache:
            sub = values[idx]
            n = np.sum(~np.isnan(sub), axis=0)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                m = np.nanmedian(sub, axis=0)
                d = np.nanmedian(np.abs(sub - m), axis=0) if with_mad else None
            ok = n >= min_obs
            m = np.where(ok, m, np.nan)
            if d is not None:
                d = np.where(ok, d, np.nan)
            cache[key] = (m, d, n)
        m, d, n = cache[key]
        med[t], cnt[t] = m, n
        if with_mad:
            mad[t] = d
    return med, mad, cnt


def time_info(times) -> tuple[np.ndarray, np.ndarray]:
    t = pd.DatetimeIndex(times)
    return t.dayofyear.values.astype(int), t.year.values.astype(int)
