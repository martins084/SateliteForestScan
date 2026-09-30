"""Flagged pixels -> polygons with attributes."""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr
from rasterio.features import shapes
from scipy import ndimage
from shapely.geometry import shape

from .anomaly import FEATURES


def confidence_score(z_primary: float, n_agree: float, n_other: int, run_len: float,
                     persistence: int, baseline_obs: float, min_obs: int, k: float) -> float:
    """Heuristic 0..1 (NOT a probability). Weighted sum of:

    * 0.35 strength: median primary z in the run, saturating at 2k;
    * 0.25 agreement: median share of other indices that also exceed k;
    * 0.25 persistence: run length, saturating at 2 x required persistence;
    * 0.15 baseline support: baseline observation count, saturating at 3 x minimum.
    """
    s_z = np.clip(z_primary / (2 * k), 0, 1)
    s_a = np.clip(n_agree / max(n_other, 1), 0, 1)
    s_p = np.clip(run_len / (2 * persistence), 0, 1)
    s_b = np.clip(baseline_obs / (3 * min_obs), 0, 1)
    return float(np.round(0.35 * s_z + 0.25 * s_a + 0.25 * s_p + 0.15 * s_b, 3))


def polygonize(feats: xr.Dataset, zm: xr.DataArray, index_delta: xr.DataArray, crs: str,
               min_area_ha: float, k: float, persistence: int, min_obs: int,
               stand_codes: np.ndarray | None = None) -> gpd.GeoDataFrame:
    """Connected (8-neighbour) groups of flagged pixels -> polygons.

    index_delta: (index, time_mon, y, x) change x' - baseline median (index units),
    used for per-polygon `delta_<index>` after the first detection.
    """
    flag = np.nan_to_num(feats["flag"].values, nan=0).astype(bool)
    labels, n = ndimage.label(flag, structure=np.ones((3, 3), dtype=int))
    if n == 0:
        return gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs=crs)

    x, y = feats.x.values, feats.y.values
    res = float(abs(x[1] - x[0]))
    from rasterio.transform import from_origin
    transform = from_origin(float(x[0]) - res / 2, float(y[0]) + res / 2, res, res)
    px_ha = res * res / 1e4

    geoms: dict[int, list] = {}
    for geom, val in shapes(labels.astype("int32"), mask=labels > 0, transform=transform,
                            connectivity=8):
        geoms.setdefault(int(val), []).append(shape(geom))

    times = pd.DatetimeIndex(zm.time.values)
    names = list(zm["index"].values)
    F = {f: feats[f].values for f in FEATURES}
    first_idx = F["first_idx"]
    tm = np.arange(len(times))[:, None]
    # First monitoring-season date with valid data anywhere; detections starting
    # there mean the change happened before the season (e.g. winter felling).
    first_valid_t = int(np.argmax(np.isfinite(zm.values).any(axis=(0, 2, 3))))
    rows = []
    for lab in range(1, n + 1):
        sel = labels == lab
        npx = int(sel.sum())
        area = npx * px_ha
        if area < min_area_ha:
            continue
        fi = first_idx[sel].astype(int)
        first = times[fi.min()]
        row = {
            "first_detected": first.strftime("%Y-%m-%d"),
            "first_detected_median": times[int(np.median(fi))].strftime("%Y-%m-%d"),
            "onset_before_season": bool(np.median(fi) <= first_valid_t),
            "area_ha": round(area, 3),
            "n_pixels": npx,
            "type": "cut" if np.nanmean(F["is_cut"][sel]) >= 0.5 else "stress",
            "cut_share": round(float(np.nanmean(F["is_cut"][sel])), 2),
            "persistence_len": float(np.nanmedian(F["run_len"][sel])),
            "n_indices_agree": float(np.nanmedian(F["n_agree"][sel])),
            "baseline_obs": float(np.nanmedian(F["baseline_obs"][sel])),
        }
        # per-index change and z after first detection (per pixel: from its own first date)
        after = tm >= fi[None, :]
        for i, name in enumerate(names):
            d = index_delta.values[i][:, sel]
            z = zm.values[i][:, sel]
            with np.errstate(invalid="ignore"):
                row[f"delta_{name}"] = round(float(np.nanmedian(np.where(after, d, np.nan))), 4)
                row[f"z_{name}"] = round(float(np.nanmedian(np.where(after, z, np.nan))), 2)
        row["confidence"] = confidence_score(
            float(np.nanmedian(F["z_primary"][sel])), row["n_indices_agree"], len(names) - 1,
            row["persistence_len"], persistence, row["baseline_obs"], min_obs, k)
        g = gpd.GeoSeries(geoms[lab]).union_all()
        rows.append({**row, "geometry": g})

    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs=crs)
    if gdf.empty:
        return gdf
    gdf = gdf.sort_values(["confidence", "area_ha"], ascending=False).reset_index(drop=True)
    gdf.insert(0, "id", np.arange(1, len(gdf) + 1))
    return gdf
