"""Forest-edge attributes (informative diagnostic; detection is not changed).

"Open" ground = everything that is not tree cover (HRL Dominant Leaf Type classes
`tree_classes`, default 1 broadleaved + 2 coniferous), plus the OSM road buffer, cuts found in
the baseline years and cuts of the monitoring year. For every polygon / drone target:
  * `edge_dist_m`    — distance between pixel centres from the polygon to the nearest open pixel
                       outside the polygon (10 m = adjacent at 10 m resolution);
  * `edge_share_20m` — share of the polygon's pixels within `near_m` of such open ground.
A summary table compares polygon types with all analysed forest pixels (S1 early-signal test:
S2 stress targets were ~2x closer to the forest edge than controls).
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
from rasterio.features import geometry_mask
from scipy import ndimage


def open_mask(tree: np.ndarray, roads: np.ndarray, cut_baseline: np.ndarray,
              cut_monitor: np.ndarray) -> np.ndarray:
    return ~tree | roads | cut_baseline | cut_monitor


def distance_to_open(open_px: np.ndarray, resolution: float) -> np.ndarray:
    """Euclidean distance (m) from every pixel centre to the nearest open pixel centre."""
    if not open_px.any():
        return np.full(open_px.shape, np.inf, dtype="float32")
    return (ndimage.distance_transform_edt(~open_px) * resolution).astype("float32")


def polygon_edge_attributes(gdf: gpd.GeoDataFrame, open_px: np.ndarray, transform,
                            resolution: float, near_m: float = 20.0,
                            margin_m: float = 1000.0) -> pd.DataFrame:
    """Per polygon: distance to open ground OUTSIDE the polygon (its own pixels - e.g. the cut
    itself - do not count), computed in a window of `margin_m` around it. NaN if there is no
    open pixel within the window (edge farther than `margin_m`)."""
    pad = int(np.ceil(margin_m / resolution))
    rows = []
    for geom in gdf.geometry:
        m = ~geometry_mask([geom], out_shape=open_px.shape, transform=transform)
        if not m.any():
            rows.append({"edge_dist_m": np.nan, "edge_share_20m": np.nan})
            continue
        r, c = np.nonzero(m)
        r0, r1 = max(r.min() - pad, 0), min(r.max() + pad + 1, m.shape[0])
        c0, c1 = max(c.min() - pad, 0), min(c.max() + pad + 1, m.shape[1])
        win = m[r0:r1, c0:c1]
        d = distance_to_open(open_px[r0:r1, c0:c1] & ~win, resolution)[win]
        d = d[np.isfinite(d) & (d <= margin_m)]
        if d.size == 0:
            rows.append({"edge_dist_m": np.nan, "edge_share_20m": 0.0})
            continue
        rows.append({"edge_dist_m": round(float(d.min()), 1),
                     "edge_share_20m": round(float((d <= near_m).sum() / win.sum()), 3)})
    return pd.DataFrame(rows, index=gdf.index)


def edge_summary(gdf: gpd.GeoDataFrame, dist: np.ndarray, analysed: np.ndarray,
                 near_m: float = 20.0) -> pd.DataFrame:
    """Polygon types vs. all analysed forest pixels (reference)."""
    d = dist[analysed]
    rows = [{"group": "analysed forest pixels", "n": int(d.size),
             "median_dist_m": float(np.median(d)) if d.size else np.nan,
             f"share_within_{near_m:g}m": float((d <= near_m).mean()) if d.size else np.nan}]
    if len(gdf) and "type" in gdf:
        for t, g in gdf.groupby("type"):
            rows.append({"group": f"{t} polygons", "n": len(g),
                         "median_dist_m": float(g["edge_dist_m"].median()),
                         "n_no_edge_within_margin": int(g["edge_dist_m"].isna().sum()),
                         f"share_within_{near_m:g}m": float((g["edge_dist_m"] <= near_m).mean())})
    return pd.DataFrame(rows)
