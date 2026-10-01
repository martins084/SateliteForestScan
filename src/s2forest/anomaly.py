"""Anomaly detection: baseline, robust z-scores, persistence, disturbance type.

Per pixel and index i, for every observation t:

    x'  = x - offset(t, i)                     regional normalization (see below)
    med, MAD = median / MAD of x' over BASELINE-year observations within +-doy_window
    z   = stress_sign(i) * (x' - med) / max(1.4826 * MAD, mad_floor(i))

so z > 0 always means "towards stress" (NDVI/NDRE/NDMI down, CRSWIR up).

An observation is anomalous if z(primary) >= k and at least `min_confirming`
other indices also have z >= k. A pixel is flagged when anomalous observations
occur in `persistence` consecutive VALID observations of the monitoring year
(cloudy dates are skipped, they do not break the run). The first date of the
first such run is the first detection date.

Regional normalization (enabled by default): offset(t, i) is the median, over
forest pixels of the coarse context layer (AOI + buffer), of each pixel's
deviation from its own baseline reference. It removes signals shared by the
whole region (drought year, phenology shift, residual atmospheric effects).
Computed in two passes: pass 2 excludes context pixels that pass 1 flagged.

Baseline cleanliness: each baseline year is tested with the same rule against
the baseline years before it (the first baseline year against the others), and
checked for the cut signature. Pixels disturbed during the baseline period are
excluded from the analysis (reported separately), because their baseline does
not describe a healthy stand.

Disturbance type of a flagged pixel: "cut" (stand-replacing change: clear-cut,
sanitary felling, or a completely dead stand) if, in at least half of the
detection-run observations, NDVI falls to <= cut_ndvi_max and >= cut_ndvi_drop
below the baseline median, OR NDMI is >= cut_ndmi_drop below it; otherwise
"stress".
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import dask.array as da
import numpy as np
import pandas as pd
import xarray as xr

from .config import AnomalyConfig
from .indices import INDICES
from .temporal import doy_reference_stats, harmonic_reference, time_info

MAD_SCALE = 1.4826

# Per-pixel feature planes returned by the block detector.
FEATURES = [
    "flag",              # 1 flagged (monitoring year), 0 not, NaN not analysed
    "first_idx",         # index (into time) of first detection
    "run_len",           # length of the longest anomalous run (valid obs)
    "n_agree",           # median number of confirming indices in the run
    "z_primary",         # median primary z in the run
    "is_cut",            # 1 cut, 0 stress
    "baseline_obs",      # number of baseline observations (primary index, all DOY)
    "baseline_disturbed",  # 1 if disturbed during the baseline period
    "max_z_primary",     # max primary z in the monitoring year
    "baseline_cut_year",  # latest baseline year with a persistent cut signature (NaN: none)
    "pending",           # 1: run reached N observations but not yet the minimum span (season end)
    "prev_autumn_z",     # median primary z in the previous year's late season (NaN: no data)
]


@dataclass
class DetectParams:
    names: list[str]
    signs: np.ndarray
    floors: np.ndarray
    primary: int
    k: float
    persistence: int
    min_confirming: int
    window: int
    min_obs: int
    cut_ndvi_max: float
    cut_ndvi_drop: float
    cut_ndmi_drop: float
    ndmi_i: int | None
    ndvi_i: int | None
    baseline_years: list[int]
    monitor_year: int
    min_days: int = 0
    prev_autumn_doy: int = 227
    baseline_method: str = "harmonic"
    harmonics: int = 1
    robust_iterations: int = 5
    huber_k: float = 1.345


def params_from_config(cfg: AnomalyConfig, names: list[str], baseline_years: list[int],
                       monitor_year: int) -> DetectParams:
    return DetectParams(
        names=names,
        signs=np.array([INDICES[n].stress_sign for n in names], dtype="float32"),
        floors=np.array([cfg.mad_floor.get(n, 0.02) for n in names], dtype="float32"),
        primary=names.index(cfg.primary_index),
        k=cfg.z_threshold, persistence=cfg.persistence, min_confirming=cfg.min_confirming,
        window=cfg.doy_window, min_obs=cfg.min_baseline_obs,
        cut_ndvi_max=cfg.cut_ndvi_max, cut_ndvi_drop=cfg.cut_ndvi_drop,
        cut_ndmi_drop=cfg.cut_ndmi_drop, ndmi_i=names.index("ndmi") if "ndmi" in names else None,
        ndvi_i=names.index("ndvi") if "ndvi" in names else None,
        baseline_years=baseline_years, monitor_year=monitor_year,
        min_days=cfg.persistence_min_days,
        prev_autumn_doy=int(pd.Timestamp(f"2001-{cfg.prev_autumn_start}").dayofyear),
        baseline_method=cfg.baseline_method, harmonics=cfg.harmonics,
        robust_iterations=cfg.robust_iterations, huber_k=cfg.huber_k,
    )


def cut_signature(values: np.ndarray, med: np.ndarray, p: DetectParams) -> np.ndarray | None:
    """Per observation: stand-replacing change signature. values/med: (I, T, ...)."""
    out = None
    with np.errstate(invalid="ignore"):
        if p.ndvi_i is not None:
            nd = values[p.ndvi_i]
            out = (nd <= p.cut_ndvi_max) & ((nd - med[p.ndvi_i]) <= -p.cut_ndvi_drop)
        if p.ndmi_i is not None:
            m = (values[p.ndmi_i] - med[p.ndmi_i]) <= -p.cut_ndmi_drop
            out = m if out is None else (out | m)
    return out


def baseline_reference(values: np.ndarray, doy: np.ndarray, ref_sel: np.ndarray, p: DetectParams
                       ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """One index, values (T, ...): expected value (T, ...), MAD (T, ...), count (T, ...)
    from the reference observations, with the configured baseline method."""
    if p.baseline_method == "harmonic":
        return harmonic_reference(values, doy, ref_sel, p.min_obs, p.harmonics,
                                  p.robust_iterations, p.huber_k)
    return doy_reference_stats(values, doy, ref_sel, p.window, p.min_obs, with_mad=True)


def zscores(values: np.ndarray, doy: np.ndarray, ref_sel: np.ndarray, p: DetectParams
            ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """values (I, T, ...) -> z (I, T, ...), expected value (I, T, ...), count (T, ...)."""
    z = np.full(values.shape, np.nan, dtype="float32")
    med_all = np.full(values.shape, np.nan, dtype="float32")
    cnt0 = None
    for i in range(values.shape[0]):
        med, mad, cnt = baseline_reference(values[i], doy, ref_sel, p)
        scale = np.maximum(MAD_SCALE * mad, p.floors[i])
        z[i] = p.signs[i] * (values[i] - med) / scale
        med_all[i] = med
        if i == p.primary:
            cnt0 = cnt
    return z, med_all, cnt0


def anomalous_obs(z: np.ndarray, p: DetectParams) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(anomalous, valid, n_agree) per observation; valid = primary z is finite."""
    zp = z[p.primary]
    valid = np.isfinite(zp)
    others = np.delete(z, p.primary, axis=0)
    with np.errstate(invalid="ignore"):
        n_agree = np.sum(others >= p.k, axis=0)
        anom = valid & (zp >= p.k) & (n_agree >= p.min_confirming)
    return anom, valid, n_agree


def persistent_runs(anom: np.ndarray, valid: np.ndarray, n: int, days: np.ndarray | None = None,
                    min_days: int = 0
                    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Scan time (axis 0). Returns (flag, first_idx, longest_run, pending, pending_start).

    A run counts consecutive VALID observations that are anomalous; invalid
    observations are skipped. A pixel is flagged when a run reaches `n`
    observations AND spans at least `min_days` (days: (T,) day numbers);
    first_idx = start of the first such run. `pending`: not flagged, but the
    run active at the end of the series already has >= n observations and is
    still shorter than `min_days` (to be confirmed later -> status "new").
    """
    shape = anom.shape[1:]
    if days is None:
        days = np.arange(anom.shape[0])
    run = np.zeros(shape, dtype="int16")
    start = np.full(shape, -1, dtype="int32")
    start_day = np.zeros(shape, dtype="float64")
    longest = np.zeros(shape, dtype="int16")
    first = np.full(shape, -1, dtype="int32")
    for t in range(anom.shape[0]):
        a, v = anom[t], valid[t]
        new_run = v & a & (run == 0)
        start = np.where(new_run, t, start)
        start_day = np.where(new_run, days[t], start_day)
        run = np.where(v, np.where(a, run + 1, 0), run)
        longest = np.maximum(longest, run)
        hit = (run >= n) & (first < 0) & ((days[t] - start_day) >= min_days)
        first = np.where(hit, start, first)
    flag = first >= 0
    pending = ~flag & (run >= n)
    return flag, first, longest, pending, np.where(pending, start, -1)


def detect_block(values: np.ndarray, doy: np.ndarray, year: np.ndarray, p: DetectParams
                 ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """values (I, T, y, x), already normalized. Returns (features (F, y, x),
    z of the monitoring year (I, Tm, y, x), change x' - baseline median (I, Tm, y, x))."""
    base_sel = np.isin(year, p.baseline_years)
    mon_sel = year == p.monitor_year
    z, med, cnt = zscores(values, doy, base_sel, p)
    shape = values.shape[2:]

    # --- baseline cleanliness (leave-one-year-out) ---------------------------------
    disturbed = np.zeros(shape, dtype=bool)
    cut_year = np.full(shape, np.nan, dtype="float32")
    for by in p.baseline_years:
        # Reference = the baseline years BEFORE `by` (catches the onset of a disturbance
        # that continues into later years); the first year is tested against the others.
        ref_sel = base_sel & (year < by)
        if not ref_sel.any():
            ref_sel = base_sel & (year != by)
        sel = np.flatnonzero(year == by)
        if sel.size == 0 or not ref_sel.any():
            continue
        # z for year `by` against the other baseline years
        sub = values[:, np.concatenate([np.flatnonzero(ref_sel), sel])]
        sub_doy = np.concatenate([doy[ref_sel], doy[sel]])
        sub_ref = np.concatenate([np.ones(ref_sel.sum(), bool), np.zeros(sel.size, bool)])
        zb, medb, _ = zscores(sub, sub_doy, sub_ref, p)
        zb, medb = zb[:, ref_sel.sum():], medb[:, ref_sel.sum():]
        anom, valid, _ = anomalous_obs(zb, p)
        flag, *_ = persistent_runs(anom, valid, p.persistence, doy[sel], p.min_days)
        disturbed |= flag
        cut = cut_signature(sub[:, ref_sel.sum():], medb, p)
        if cut is not None:
            cflag, *_ = persistent_runs(cut, np.isfinite(sub[p.primary, ref_sel.sum():]),
                                        p.persistence, doy[sel], p.min_days)
            disturbed |= cflag
            cut_year = np.where(cflag, np.float32(by), cut_year)

    # --- monitoring year ------------------------------------------------------------
    zm = z[:, mon_sel]
    anom, valid, n_agree = anomalous_obs(zm, p)
    confirmed, first_c, longest, pending, pstart = persistent_runs(
        anom, valid, p.persistence, doy[mon_sel], p.min_days)
    # pending runs (season end, span not yet reached) are kept and get status "new"
    flag = confirmed | pending
    first = np.where(confirmed, first_c, pstart)

    feats = np.full((len(FEATURES),) + shape, np.nan, dtype="float32")
    analysable = (cnt[mon_sel] > 0).any(axis=0) if mon_sel.any() else np.zeros(shape, bool)
    base_count = np.sum(np.isfinite(values[p.primary][base_sel]), axis=0)
    feats[FEATURES.index("baseline_obs")] = base_count
    feats[FEATURES.index("baseline_disturbed")] = disturbed
    feats[FEATURES.index("baseline_cut_year")] = cut_year
    prev_sel = (year == p.monitor_year - 1) & (doy >= p.prev_autumn_doy)
    if prev_sel.any():
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            feats[FEATURES.index("prev_autumn_z")] = np.nanmedian(z[p.primary][prev_sel], axis=0)
    with np.errstate(invalid="ignore"):
        feats[FEATURES.index("max_z_primary")] = np.nanmax(
            np.where(valid, zm[p.primary], -np.inf), axis=0) if zm.shape[1] else np.nan
    mz = feats[FEATURES.index("max_z_primary")]
    mz[~np.isfinite(mz)] = np.nan

    # Baseline disturbance is only recorded here; the exclusion is applied after a
    # spatial (minimum patch area) filter in `apply_baseline_exclusion`.
    ok = analysable
    feats[FEATURES.index("flag")] = np.where(ok, flag, np.nan)
    feats[FEATURES.index("first_idx")] = np.where(ok & flag, first, np.nan)
    feats[FEATURES.index("run_len")] = np.where(ok & flag, longest, np.nan)
    feats[FEATURES.index("pending")] = np.where(ok & flag, pending, np.nan)

    # Run statistics for flagged pixels: observations from first detection on.
    tm = np.arange(zm.shape[1])[:, None, None]
    in_run = (tm >= first[None]) & anom & (ok & flag)[None]
    with np.errstate(invalid="ignore"):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            feats[FEATURES.index("n_agree")] = np.nanmedian(np.where(in_run, n_agree, np.nan), axis=0)
            feats[FEATURES.index("z_primary")] = np.nanmedian(np.where(in_run, zm[p.primary], np.nan), axis=0)
            cut_obs = cut_signature(values[:, mon_sel], med[:, mon_sel], p)
            if cut_obs is not None:
                share = np.nansum(np.where(in_run, cut_obs, np.nan), axis=0) / np.maximum(in_run.sum(0), 1)
                feats[FEATURES.index("is_cut")] = np.where(ok & flag, share >= 0.5, np.nan)
            else:
                feats[FEATURES.index("is_cut")] = np.where(ok & flag, 0, np.nan)
    delta = (values - med)[:, mon_sel]
    return feats, zm.astype("float32"), delta.astype("float32")


def apply_baseline_exclusion(feats: xr.Dataset, min_pixels: int) -> xr.Dataset:
    """Exclude pixels disturbed during the baseline period, but only coherent
    patches of at least `min_pixels` (8-connected); isolated noisy pixels are
    not treated as disturbed. Returns a copy with flag/run features set to NaN
    for excluded pixels and `baseline_disturbed` holding the filtered mask."""
    from scipy import ndimage

    raw = np.nan_to_num(feats["baseline_disturbed"].values) > 0
    lab, n = ndimage.label(raw, structure=np.ones((3, 3), dtype=int))
    sizes = np.bincount(lab.ravel())
    keep = sizes >= min_pixels
    keep[0] = False
    excl = keep[lab]
    out = feats.copy(deep=True)
    for f in ("flag", "first_idx", "run_len", "n_agree", "z_primary", "is_cut"):
        out[f] = out[f].where(~excl)
    out["baseline_disturbed"] = (("y", "x"), excl.astype("float32"))
    out["baseline_disturbed_raw"] = (("y", "x"), raw.astype("float32"))
    return out


def regional_offsets(values: np.ndarray, doy: np.ndarray, year: np.ndarray, forest: np.ndarray,
                     p: DetectParams, exclude: np.ndarray | None = None,
                     min_pixels: int = 50) -> tuple[np.ndarray, np.ndarray]:
    """values (I, T, y, x) on the context grid -> offsets (I, T) and pixel counts (T,).

    offset = median over context forest pixels of (x - own baseline expectation).
    Dates with fewer than `min_pixels` usable pixels get offset 0 (no normalization).
    """
    base_sel = np.isin(year, p.baseline_years)
    region = forest if exclude is None else (forest & ~exclude)
    offsets = np.zeros(values.shape[:2], dtype="float32")
    counts = np.zeros(values.shape[1], dtype="int32")
    for i in range(values.shape[0]):
        med, _, _ = baseline_reference(values[i], doy, base_sel, p)
        dev = values[i] - med
        for t in range(values.shape[1]):
            d = dev[t][region]
            d = d[np.isfinite(d)]
            if i == p.primary:
                counts[t] = d.size
            if d.size >= min_pixels:
                offsets[i, t] = np.median(d)
    return offsets, counts


def run_detection(values: xr.DataArray, p: DetectParams, chunk: int = 256
                  ) -> tuple[xr.Dataset, xr.DataArray, xr.DataArray]:
    """values: (index, time, y, x), normalized. Dask-parallel over spatial blocks."""
    doy, year = time_info(values.time.values)
    mon_times = values.time.values[year == p.monitor_year]
    arr = values.data
    if not isinstance(arr, da.Array):
        arr = da.from_array(arr)
    arr = arr.rechunk((-1, -1, chunk, chunk))
    nF, nI, nTm = len(FEATURES), values.sizes["index"], len(mon_times)

    def _blk(b):
        f, z, d = detect_block(b, doy, year, p)
        return np.concatenate([f, z.reshape((nI * nTm,) + z.shape[2:]),
                               d.reshape((nI * nTm,) + d.shape[2:])], axis=0)

    out = arr.map_blocks(_blk, dtype="float32", chunks=((nF + 2 * nI * nTm,),) + arr.chunks[2:],
                         drop_axis=1, new_axis=None)
    out = out.compute()
    feats = xr.Dataset({name: (("y", "x"), out[k]) for k, name in enumerate(FEATURES)},
                       coords={"y": values.y, "x": values.x})
    coords = {"index": values["index"].values, "time": mon_times, "y": values.y, "x": values.x}
    dims = ("index", "time", "y", "x")
    z = xr.DataArray(out[nF:nF + nI * nTm].reshape((nI, nTm) + out.shape[1:]), dims=dims,
                     coords=coords, name="z")
    delta = xr.DataArray(out[nF + nI * nTm:].reshape((nI, nTm) + out.shape[1:]), dims=dims,
                         coords=coords, name="delta")
    return feats, z, delta
