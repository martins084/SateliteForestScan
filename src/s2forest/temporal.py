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


def harmonic_design(doy: np.ndarray, n_harmonics: int) -> np.ndarray:
    """Design matrix: intercept + cos/sin pairs of the annual cycle, (T, 1 + 2 * n)."""
    w = 2 * np.pi * np.asarray(doy, dtype="float64") / 365.25
    cols = [np.ones_like(w)]
    for k in range(1, n_harmonics + 1):
        cols += [np.cos(k * w), np.sin(k * w)]
    return np.stack(cols, axis=1)


def harmonic_fit(values: np.ndarray, doy: np.ndarray, n_harmonics: int = 1,
                 iterations: int = 5, huber_k: float = 1.345
                 ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Robust per-pixel harmonic fit (IRLS with Huber weights), vectorized.

    values: (T, ...) reference observations, NaN = missing; doy: (T,).
    Returns (coefficients (p, ...), robust residual scale 1.4826*MAD (...), n valid (...)).
    Pixels with fewer than p + 2 observations get NaN coefficients.
    """
    shape = values.shape[1:]
    y = values.reshape(values.shape[0], -1).astype("float64")
    X = harmonic_design(doy, n_harmonics)
    p = X.shape[1]
    valid = np.isfinite(y)
    n = valid.sum(axis=0)
    y0 = np.where(valid, y, 0.0)
    w = valid.astype("float64")
    ridge = 1e-8 * np.eye(p)
    beta = np.zeros((y.shape[1], p))
    scale = np.full(y.shape[1], np.nan)
    ok = n >= p + 2
    for _ in range(max(iterations, 1)):
        A = np.einsum("tn,tp,tq->npq", w, X, X) + ridge
        b = np.einsum("tn,tp,tn->np", w, X, y0)
        A[~ok] = np.eye(p)
        b[~ok] = 0.0
        beta = np.linalg.solve(A, b[..., None])[..., 0]
        resid = np.where(valid, y0 - X @ beta.T, np.nan)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            scale = 1.4826 * np.nanmedian(np.abs(resid), axis=0)
        s = np.maximum(np.nan_to_num(scale, nan=1.0), 1e-6)
        u = np.abs(np.nan_to_num(resid)) / (huber_k * s)
        w = valid * np.where(u <= 1, 1.0, 1.0 / np.maximum(u, 1e-12))
    beta[~ok] = np.nan
    scale = np.where(ok, scale, np.nan)
    return (beta.T.reshape((p,) + shape).astype("float32"),
            scale.reshape(shape).astype("float32"), n.reshape(shape))


def harmonic_predict(coef: np.ndarray, doy: np.ndarray, n_harmonics: int) -> np.ndarray:
    """coef (p, ...) -> predictions (T, ...) at the given days of year."""
    X = harmonic_design(doy, n_harmonics).astype("float32")
    return np.tensordot(X, coef, axes=(1, 0))


def harmonic_reference(values: np.ndarray, doy: np.ndarray, ref_sel: np.ndarray, min_obs: int,
                       n_harmonics: int = 1, iterations: int = 5, huber_k: float = 1.345
                       ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Same contract as doy_reference_stats(with_mad=True), for the harmonic model:
    returns (prediction (T, ...), residual scale / 1.4826 i.e. MAD (T, ...), count (T, ...)).
    Pixels with fewer than `min_obs` reference observations get NaN."""
    coef, scale, n = harmonic_fit(values[ref_sel], doy[ref_sel], n_harmonics, iterations, huber_k)
    pred = harmonic_predict(coef, doy, n_harmonics)
    enough = n >= min_obs
    pred = np.where(enough[None], pred, np.nan).astype("float32")
    mad = np.where(enough, scale / 1.4826, np.nan).astype("float32")
    T = values.shape[0]
    return pred, np.broadcast_to(mad, (T,) + mad.shape).copy(), np.broadcast_to(
        n.astype("int16"), (T,) + n.shape).copy()
