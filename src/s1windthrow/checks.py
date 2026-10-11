"""Read-only checks against s2forest outputs.

* `s2_index_check`: S2 index change (pre/post event) inside each S1 candidate, minus the
  same change in the stable forest. Labelled "S2 vizuāla/indeksa pārbaude" - NOT validation.
* `proxy_cut_windows`: per S2 summer cut (PROXY / aizvietotājs), the S1 pre/post windows.
"""

from __future__ import annotations

import warnings
from datetime import date, timedelta
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import geometry_mask


def read_timeseries(path: Path) -> tuple[np.ndarray, pd.DatetimeIndex, object]:
    with rasterio.open(path) as src:
        return src.read().astype("float32"), pd.DatetimeIndex(src.descriptions), src.transform


def polygon_mask(geom, shape, transform) -> np.ndarray:
    return ~geometry_mask([geom], out_shape=shape, transform=transform)


def _median(arr2d: np.ndarray, sel: np.ndarray, min_valid: float) -> float:
    v = arr2d[sel]
    if v.size == 0 or np.isfinite(v).mean() < min_valid:
        return np.nan
    return float(np.nanmedian(v))


def s2_index_check(polys: gpd.GeoDataFrame, run_dir: Path, indices: list[str], stable: np.ndarray,
                   pre: tuple[date, date], post: tuple[date, date], min_valid: float = 0.5
                   ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (per polygon x index summary, per polygon x date long table)."""
    summary, long = [], []
    for name in indices:
        arr, times, tr = read_timeseries(run_dir / "rasters" / "indices" / f"{name}_timeseries.tif")
        d = times.date
        sel_t = np.flatnonzero(((d >= pre[0]) & (d <= pre[1])) | ((d >= post[0]) & (d <= post[1])))
        stable_med = np.array([_median(arr[t], stable, min_valid) for t in range(arr.shape[0])])
        for _, p in polys.iterrows():
            m = polygon_mask(p.geometry, arr.shape[1:], tr)
            vals = {}
            for t in sel_t:
                v = _median(arr[t], m, min_valid)
                win = "pre" if d[t] <= pre[1] else "post"
                long.append({"id": p["id"], "index": name, "date": d[t], "window": win,
                             "polygon": v, "stable": stable_med[t]})
                vals.setdefault(win, []).append((v, stable_med[t]))
            row = {"id": p["id"], "class": p["class"], "index": name}
            for win in ("pre", "post"):
                pv = [a for a, _ in vals.get(win, []) if np.isfinite(a)]
                sv = [b for a, b in vals.get(win, []) if np.isfinite(a) and np.isfinite(b)]
                row[f"n_{win}"] = len(pv)
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", RuntimeWarning)
                    row[f"{win}_poly"] = float(np.median(pv)) if pv else np.nan
                    row[f"{win}_stable"] = float(np.median(sv)) if sv else np.nan
            row["d_poly"] = row["post_poly"] - row["pre_poly"]
            row["d_stable"] = row["post_stable"] - row["pre_stable"]
            row["d_rel"] = row["d_poly"] - row["d_stable"]
            summary.append(row)
    return pd.DataFrame(summary), pd.DataFrame(long)


def proxy_cuts(layers: list, min_area_ha: float, months: tuple[int, int]
               ) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    """S2 summer cuts >= min_area_ha. Winter cuts (onset_before_season) are excluded.
    Returns (cuts, table of exclusions)."""
    keep, dropped, crs = [], [], None
    for ref in layers:
        g = gpd.read_file(ref.path, layer=ref.layer)
        crs = crs or g.crs
        g = g[g["type"] == "cut"].copy()
        g["first_detected"] = pd.to_datetime(g["first_detected"])
        g["source_layer"] = ref.layer
        g["run_dir"] = str(ref.run_dir)
        for _, r in g.iterrows():
            why = None
            if r["area_ha"] < min_area_ha:
                why = f"< {min_area_ha} ha"
            elif not (months[0] <= r["first_detected"].month <= months[1]):
                why = "first_detected ārpus mēnešiem"
            elif bool(r.get("onset_before_season", False)):
                why = "ziemas cirte (onset_before_season)"
            (dropped if why else keep).append(r if not why else
                                              {"layer": ref.layer, "id": r["id"], "reason": why})
    cuts = (gpd.GeoDataFrame(keep, geometry="geometry", crs=crs).reset_index(drop=True)
            if keep else gpd.GeoDataFrame())
    return cuts, pd.DataFrame(dropped)


def proxy_windows(cut, window_days: int, min_valid: float = 0.5) -> dict:
    """pre = `window_days` up to the previous clear S2 date before first_detected;
    post = `window_days` from first_detected. Clear = >= min_valid of the polygon valid."""
    arr, times, tr = read_timeseries(Path(cut["run_dir"]) / "rasters" / "indices" / "ndvi_timeseries.tif")
    m = polygon_mask(cut.geometry, arr.shape[1:], tr)
    fd = cut["first_detected"].date()
    prev = None
    for t in np.argsort(times):
        if times[t].date() < fd and np.isfinite(arr[t][m]).mean() >= min_valid:
            prev = times[t].date()
    out = {"first_detected": fd, "prev_clear": prev,
           "post": (fd, fd + timedelta(days=window_days))}
    out["pre"] = (prev - timedelta(days=window_days), prev) if prev else None
    return out
