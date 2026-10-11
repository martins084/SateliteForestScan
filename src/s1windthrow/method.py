"""v2 building blocks: per-acquisition normalization, masked spatial averaging, per-class z.

All defaults reproduce v1 (no normalization, window 1, one z statistic for all forest).
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
from scipy.ndimage import uniform_filter

from .detect import MAD_SCALE, OrbitDelta


def linear_mean(stack: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Mean of linear gamma0 over acquisitions (NaN-aware) and the count per pixel."""
    arr = np.stack(stack).astype("float32")
    n = np.isfinite(arr).sum(axis=0).astype("int16")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmean(arr, axis=0).astype("float32"), n


def normalize_acquisition(lin: np.ndarray, stable: np.ndarray) -> tuple[np.ndarray, float]:
    """Divide by the stable-forest median (== subtracting the median in dB)."""
    v = lin[stable]
    med = float(np.nanmedian(v)) if np.isfinite(v).any() else np.nan
    return (lin / med).astype("float32"), med


def masked_mean_filter(lin: np.ndarray, mask: np.ndarray, window: int) -> np.ndarray:
    """Normalized convolution: box mean over `window` x `window` using only pixels inside
    `mask` with finite values (pixels outside the mask do not contribute). NaN outside mask."""
    ok = mask & np.isfinite(lin)
    if window <= 1:
        return np.where(ok, lin, np.nan).astype("float32")
    num = uniform_filter(np.where(ok, lin, 0.0).astype("float64"), size=window, mode="constant")
    den = uniform_filter(ok.astype("float64"), size=window, mode="constant")
    with np.errstate(invalid="ignore", divide="ignore"):
        out = num / den
    out[~mask | (den <= 0)] = np.nan
    return out.astype("float32")


def to_db(x: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return (10.0 * np.log10(x)).astype("float32")


@dataclass
class OrbitComposite:
    rel_orbit: int
    direction: str
    pre: dict[str, np.ndarray]     # linear mean per polarization
    post: dict[str, np.ndarray]
    n_pre: np.ndarray
    n_post: np.ndarray
    pre_dates: list[str]
    post_dates: list[str]


def deltas_from_composites(comps: list[OrbitComposite], mask: np.ndarray, window: int,
                           post_factor: dict[str, np.ndarray] | None = None) -> list[OrbitDelta]:
    """Optionally multiply the post composite (injection), smooth both in linear scale inside
    `mask`, convert to dB and difference (post - pre)."""
    out = []
    for c in comps:
        d = {}
        for pol in ("vv", "vh"):
            post = c.post[pol] if post_factor is None else c.post[pol] * post_factor[pol]
            d[pol] = (to_db(masked_mean_filter(post, mask, window))
                      - to_db(masked_mean_filter(c.pre[pol], mask, window)))
        out.append(OrbitDelta(c.rel_orbit, c.direction, d["vv"], d["vh"], c.n_pre, c.n_post,
                              c.pre_dates, c.post_dates))
    return out


def z_by_class(index: np.ndarray, stable: np.ndarray, analysis: np.ndarray, dlt: np.ndarray,
               classes: list[int] | None) -> tuple[np.ndarray, dict]:
    """Robust z with median / MAD from the stable forest. `classes` None -> one statistic for
    all analysed pixels; otherwise one statistic per HRL class, applied to that class only."""
    z = np.full(index.shape, np.nan, dtype="float32")
    stats = {}
    groups = {"all": np.ones(index.shape, bool)} if not classes else {int(c): dlt == c for c in classes}
    for key, sel in groups.items():
        v = index[stable & sel & np.isfinite(index)]
        if v.size == 0:
            stats[key] = {"median": np.nan, "mad": np.nan, "n": 0}
            continue
        med = float(np.median(v))
        mad = float(np.median(np.abs(v - med)))
        stats[key] = {"median": med, "mad": mad, "n": int(v.size)}
        tgt = analysis & sel
        if mad > 0:
            z[tgt] = (index[tgt] - med) / (MAD_SCALE * mad)
    return z, stats
