"""Inspect selected suspect polygons: did the change start in the previous autumn?

For each polygon: median raw CRSWIR (and NDMI) inside the polygon per date, and the
same for a ring of healthy forest around it (100 m, analysed forest only) as a local
control. Prints late-season (15.08-30.09) levels per year and early monitoring-season
levels, and draws one panel per polygon.

Usage: python scripts/inspect_polygons.py configs/test_kalsnava.yaml 23 24 34
"""

from __future__ import annotations

import sys
import warnings

import geopandas as gpd
import numpy as np
import pandas as pd
from rasterio.features import geometry_mask
from rasterio.transform import from_origin

from s2forest import viz
from s2forest.config import load_config
from s2forest.pipeline import index_stage

INDEX = "crswir"


def series(arr: np.ndarray, sel: np.ndarray) -> np.ndarray:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        v = arr[:, sel]
        ok = np.isfinite(v).mean(axis=1) >= 0.5
        out = np.nanmedian(v, axis=1)
    return np.where(ok, out, np.nan)


def main(config: str, ids: list[int]) -> None:
    cfg = load_config(config)
    year = cfg.time.monitor_year
    st = index_stage(cfg)
    g = gpd.read_file(cfg.run_dir / "vectors" / "suspects.gpkg", layer=f"suspects_{year}")
    x, y = st.cube.x.values, st.cube.y.values
    tr = from_origin(float(x[0]) - 5, float(y[0]) + 5, 10, 10)
    t = pd.DatetimeIndex(st.cube.time.values)
    arr = st.indices[INDEX].transpose("time", "y", "x").values
    rows = []
    plt = viz.plt
    fig, axes = plt.subplots(len(ids), 1, figsize=(10, 2.6 * len(ids)), squeeze=False)
    for ax, pid in zip(axes[:, 0], ids):
        p = g[g["id"] == pid].iloc[0]
        inside = ~geometry_mask([p.geometry], out_shape=(len(y), len(x)), transform=tr)
        ring = ~geometry_mask([p.geometry.buffer(100)], out_shape=(len(y), len(x)), transform=tr)
        ring &= ~inside & st.analysis_mask
        s_in, s_ring = series(arr, inside), series(arr, ring)
        diff = s_in - s_ring
        for yr in sorted(set(t.year)):
            late = (t.year == yr) & (t.strftime("%m-%d") >= "08-15")
            early = (t.year == yr) & (t.strftime("%m-%d") <= "05-31")
            rows.append({"id": pid, "year": yr,
                         "late_n": int(np.isfinite(diff[late]).sum()),
                         "late_in": np.nanmedian(s_in[late]) if late.any() else np.nan,
                         "late_in_minus_ring": np.nanmedian(diff[late]) if late.any() else np.nan,
                         "early_in_minus_ring": np.nanmedian(diff[early]) if early.any() else np.nan})
        ok = np.isfinite(s_in)
        ax.plot(t[ok], s_in[ok], "-o", ms=3, lw=1, color=viz.SERIES[1], label="poligonā")
        ok = np.isfinite(s_ring)
        ax.plot(t[ok], s_ring[ok], "-o", ms=3, lw=1, color=viz.SERIES[0], label="apkārtējais mežs (100 m)")
        ax.axvline(pd.Timestamp(p["first_detected"]), color=viz.INK_2, ls="--", lw=1)
        ax.set_title(f"#{pid}: {INDEX.upper()}, pirmoreiz {p['first_detected']}, {p['area_ha']:.2f} ha, "
                     f"statuss {p['status']}", loc="left", fontsize=9)
        viz._concise_dates(ax)
        if pid == ids[0]:
            ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    out = viz._save(fig, cfg.run_dir / "diagnostics" / f"inspect_{'_'.join(map(str, ids))}.png")
    df = pd.DataFrame(rows).round(3)
    df.to_csv(cfg.run_dir / "diagnostics" / f"inspect_{'_'.join(map(str, ids))}.csv", index=False)
    print(df.to_string(index=False))
    print(f"\nFigure: {out}")


if __name__ == "__main__":
    main(sys.argv[1], [int(a) for a in sys.argv[2:]])
