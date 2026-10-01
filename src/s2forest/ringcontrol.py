"""Control-ring diagnostic: each suspect polygon against the healthy forest around it.

For a polygon, the primary index (median per date) inside the polygon is
compared with a ring of analysed forest around it (default 100 m, polygon
excluded). The ring sees the same weather, phenology and atmosphere, so the
difference isolates what is specific to the polygon. Summaries per year:

* late season (15.08 - 30.09): was the polygon already different last autumn?
* summer (15.06 - 14.08) and early season (<= 31.05);
* both as a difference (polygon - ring) and as a ratio (polygon / ring). The
  ratio is less sensitive to the high spring level of CRSWIR, which inflates
  absolute differences early in the season.

Note: when `first_detected` equals the first valid observation of the season,
it is not the onset date: the change existed already, and the early-season
level amplifies the difference. Look at the late-season values of the previous
year (and `onset_prev_autumn`) for the onset.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from rasterio.features import geometry_mask
from rasterio.transform import from_origin

PARTS = {"early": ("01-01", "05-31"), "summer": ("06-15", "08-14"), "late": ("08-15", "12-31")}


def _median_series(arr: np.ndarray, sel: np.ndarray, min_valid: float = 0.5) -> np.ndarray:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        v = arr[:, sel]
        ok = np.isfinite(v).mean(axis=1) >= min_valid if v.size else np.zeros(arr.shape[0], bool)
        out = np.nanmedian(v, axis=1) if v.size else np.full(arr.shape[0], np.nan)
    return np.where(ok, out, np.nan)


def ring_series(arr: np.ndarray, times, x: np.ndarray, y: np.ndarray, polygons: gpd.GeoDataFrame,
                analysis_mask: np.ndarray, ring_m: float = 100.0) -> pd.DataFrame:
    """Long table: one row per polygon and date (value inside, ring, diff, ratio)."""
    res = float(abs(x[1] - x[0]))
    tr = from_origin(float(x[0]) - res / 2, float(y[0]) + res / 2, res, res)
    shape = (len(y), len(x))
    t = pd.DatetimeIndex(times)
    rows = []
    for _, p in polygons.iterrows():
        inside = ~geometry_mask([p.geometry], out_shape=shape, transform=tr)
        ring = ~geometry_mask([p.geometry.buffer(ring_m)], out_shape=shape, transform=tr)
        ring &= ~inside & analysis_mask
        s_in = _median_series(arr, inside)
        s_ring = _median_series(arr, ring, min_valid=0.3)
        rows.append(pd.DataFrame({"id": int(p["id"]), "date": t, "inside": s_in, "ring": s_ring,
                                  "ring_pixels": int(ring.sum())}))
    df = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(
        columns=["id", "date", "inside", "ring", "ring_pixels"])
    df["diff"] = df["inside"] - df["ring"]
    df["ratio"] = df["inside"] / df["ring"]
    return df


def summarize_ring(series: pd.DataFrame) -> pd.DataFrame:
    """Per polygon and year: median diff / ratio for early, summer and late season."""
    if series.empty:
        return pd.DataFrame()
    s = series.dropna(subset=["diff"]).copy()
    s["year"] = pd.DatetimeIndex(s["date"]).year
    s["mmdd"] = pd.DatetimeIndex(s["date"]).strftime("%m-%d")
    out = []
    for (pid, yr), d in s.groupby(["id", "year"]):
        row = {"id": pid, "year": yr}
        for part, (a, b) in PARTS.items():
            sel = ((d["mmdd"] >= a) & (d["mmdd"] <= b)).values
            row[f"{part}_n"] = int(sel.sum())
            row[f"{part}_diff"] = round(float(d["diff"][sel].median()), 3) if sel.any() else np.nan
            row[f"{part}_ratio"] = round(float(d["ratio"][sel].median()), 3) if sel.any() else np.nan
        out.append(row)
    return pd.DataFrame(out)


def plot_ring(series: pd.DataFrame, polygons: gpd.GeoDataFrame, index: str, path: Path,
              max_panels: int = 6) -> Path | None:
    from . import viz

    plt = viz.plt
    ids = list(polygons["id"])[:max_panels]
    if not ids:
        return None
    fig, axes = plt.subplots(len(ids), 1, figsize=(10, 2.4 * len(ids)), squeeze=False)
    for ax, pid in zip(axes[:, 0], ids):
        d = series[series["id"] == pid]
        p = polygons[polygons["id"] == pid].iloc[0]
        for col, color, lab in (("inside", viz.SERIES[1], "poligonā"),
                                ("ring", viz.SERIES[0], "apkārtējais mežs (gredzens)")):
            ok = d[col].notna()
            ax.plot(pd.DatetimeIndex(d["date"][ok]), d[col][ok], "-o", ms=3, lw=1, color=color,
                    label=lab)
        ax.axvline(pd.Timestamp(p["first_detected"]), color=viz.INK_2, ls="--", lw=1)
        extra = []
        if "onset_prev_autumn" in p and bool(p["onset_prev_autumn"]):
            extra.append("sācies iepr. rudenī")
        if "onset_before_season" in p and bool(p["onset_before_season"]):
            extra.append("1. noteikšana = sezonas sākums, nav sākuma datums")
        ax.set_title(f"#{pid}: {index.upper()}, {p.get('status', '')}, {p['area_ha']:.2f} ha"
                     + (f" ({'; '.join(extra)})" if extra else ""), loc="left", fontsize=8.5)
        viz._concise_dates(ax)
        if pid == ids[0]:
            ax.legend(loc="upper left", fontsize=7.5)
    fig.suptitle("Kontroles gredzens: poligons pret apkārtējo mežu (100 m); svītra = pirmā noteikšana",
                 x=0.01, ha="left", fontsize=10.5, color=viz.INK)
    fig.tight_layout()
    return viz._save(fig, path)
