"""Diagnostics of the baseline model: seasonal bias of z-scores in healthy forest.

In healthy, undisturbed forest the primary-index z should be centred on 0 at
every time of the season. For each year we compute z of every observation
against a baseline that does NOT contain that year: the monitoring year
against all baseline years, each baseline year against the other baseline
years (leave-one-year-out). Per date: median and 10th / 90th percentile of z
over healthy forest pixels (analysed forest minus pixels flagged by the last
detection run).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import xarray as xr

from .anomaly import params_from_config, zscores
from .config import Config
from .pipeline import IndexStage, _stack, context_offsets
from .temporal import time_info


def healthy_mask(cfg: Config, st: IndexStage) -> np.ndarray:
    m = st.analysis_mask.copy()
    status = cfg.run_dir / "rasters" / "anomaly" / f"status_{cfg.time.monitor_year}.tif"
    if status.exists():
        with rasterio.open(status) as src:
            s = src.read(1)
        if s.shape == m.shape:
            m &= s == 0
    return m


def z_by_date(cfg: Config, st: IndexStage, method: str, harmonics: int = 1,
              subsample: int = 2, normalize: bool = True) -> pd.DataFrame:
    names = list(cfg.indices)
    acfg = cfg.anomaly.model_copy(update={"baseline_method": method, "harmonics": harmonics})
    p = params_from_config(acfg, names, cfg.time.baseline_year_list, cfg.time.monitor_year)
    values = _stack(st.indices, names)
    if normalize and cfg.anomaly.normalization.enabled:
        _, off = context_offsets(cfg, st, p)
        values = values - xr.DataArray(off, dims=("index", "time"))
    m = healthy_mask(cfg, st)[::subsample, ::subsample]
    v = values.values[:, :, ::subsample, ::subsample]
    v = np.where(m[None, None], v, np.nan).astype("float32")
    doy, year = time_info(st.cube.time.values)
    base = np.isin(year, p.baseline_years)
    times = pd.DatetimeIndex(st.cube.time.values)
    rows = []
    for y in sorted(set(year)):
        test = np.flatnonzero(year == y)
        ref = base & (year != y)
        if not ref.any() or test.size == 0:
            continue
        idx = np.concatenate([np.flatnonzero(ref), test])
        sref = np.concatenate([np.ones(ref.sum(), bool), np.zeros(test.size, bool)])
        z, _, _ = zscores(v[:, idx], doy[idx], sref, p)
        zp = z[p.primary, ref.sum():]
        for k, t in enumerate(test):
            vals = zp[k][np.isfinite(zp[k])]
            if vals.size < 50:
                continue
            rows.append({"method": method if method == "window" else f"harmonic{harmonics}",
                         "year": int(y), "role": "monitor" if y == cfg.time.monitor_year else "baseline (LOYO)",
                         "date": times[t].date(), "doy": int(doy[t]),
                         "z_p10": float(np.percentile(vals, 10)),
                         "z_median": float(np.median(vals)),
                         "z_p90": float(np.percentile(vals, 90)),
                         "share_z_ge_k": float(np.mean(vals >= cfg.anomaly.z_threshold)),
                         "n_pixels": int(vals.size)})
    return pd.DataFrame(rows)


def summarize(df: pd.DataFrame, early_doy: int = 150) -> pd.DataFrame:
    """Per method: mean |median z|, early-season median z, share of z >= k."""
    out = []
    for m, d in df.groupby("method"):
        early = d[d["doy"] <= early_doy]
        out.append({"method": m,
                    "mean_abs_median_z": round(float(d["z_median"].abs().mean()), 2),
                    f"median_z_doy_le_{early_doy}": round(float(early["z_median"].median()), 2)
                    if len(early) else None,
                    "mean_share_z_ge_k": round(float(d["share_z_ge_k"].mean()), 4),
                    f"share_z_ge_k_doy_le_{early_doy}": round(float(early["share_z_ge_k"].mean()), 4)
                    if len(early) else None})
    return pd.DataFrame(out)


def plot_z_by_doy(df: pd.DataFrame, k: float, path: Path) -> Path:
    from . import viz

    plt = viz.plt
    years = sorted(df["year"].unique())
    methods = list(dict.fromkeys(df["method"]))
    fig, axes = plt.subplots(1, len(years), figsize=(3.3 * len(years), 3.4), sharey=True,
                             squeeze=False)
    colors = {m: viz.SERIES[i] for i, m in enumerate(methods)}
    labels = {"window": "loga mediāna (±30 d)", "harmonic1": "harmonisks, 1 harmonika",
              "harmonic2": "harmonisks, 2 harmonikas"}
    for ax, y in zip(axes[0], years):
        for m in methods:
            d = df[(df["year"] == y) & (df["method"] == m)].sort_values("doy")
            dt = pd.to_datetime("2001-01-01") + pd.to_timedelta(d["doy"] - 1, unit="D")
            ax.fill_between(dt, d["z_p10"], d["z_p90"], color=colors[m], alpha=0.12, lw=0)
            ax.plot(dt, d["z_median"], "-o", ms=3, lw=1.4, color=colors[m], label=labels.get(m, m))
        ax.axhline(0, color=viz.INK_2, lw=0.8)
        ax.axhline(k, color=viz.INK_2, lw=0.8, ls="--")
        role = "monitorings" if d["role"].iloc[0] == "monitor" else "bāze, LOYO" if len(d) else ""
        ax.set_title(f"{y} ({role})", loc="left", fontsize=9)
        viz._concise_dates(ax)
    axes[0, 0].set_ylabel("z (primārais indekss), veselā mežā")
    axes[0, 0].legend(loc="upper right", fontsize=7.5)
    fig.suptitle("Sezonālā nobīde: z mediāna un p10–p90 pa sezonas dienām (svītra = slieksnis k)",
                 x=0.01, ha="left", fontsize=10.5, color=viz.INK)
    fig.tight_layout()
    return viz._save(fig, path)
