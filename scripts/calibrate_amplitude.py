"""Calibrate the seasonal-amplitude threshold of the forest mask.

Per pixel: robust seasonal range = p90 - p10 of the baseline-period observations
(CRSWIR and NDVI), for pixels currently in the analysis mask. Closed conifer
stands have a small, stable seasonal cycle; mixed / deciduous / wet or sparse
stands have a large one. Shows the histogram, the value of chosen example
polygons, and an RGB with the pixels a candidate threshold would exclude.

Usage: python scripts/calibrate_amplitude.py configs/test_kalsnava_2025.yaml 65
       (optional polygon ids from the run's suspects layer to mark)
"""

from __future__ import annotations

import sys
import warnings

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from rasterio.features import geometry_mask

from s2forest.config import load_config
from s2forest.forestmask import seasonal_range
from s2forest.pipeline import index_stage
from s2forest.viz import INK_2, SERIES, rgb_image


def main(config: str, ids: list[int]) -> None:
    cfg = load_config(config)
    cfg.forest_mask.max_seasonal_range = None      # measure before applying
    st = index_stage(cfg)
    m = st.analysis_mask
    year = cfg.time.monitor_year
    polys = gpd.read_file(cfg.run_dir / "vectors" / "suspects.gpkg", layer=f"suspects_{year}")
    out = {}
    for name in ("crswir", "ndvi"):
        r = seasonal_range(st.indices[name], cfg.time.baseline_year_list)
        v = r[m & np.isfinite(r)]
        q = np.percentile(v, [50, 75, 90, 95, 97.5, 99])
        mad = np.median(np.abs(v - q[0])) * 1.4826
        print(f"{name}: range p50 {q[0]:.3f} p75 {q[1]:.3f} p90 {q[2]:.3f} p95 {q[3]:.3f} "
              f"p97.5 {q[4]:.3f} p99 {q[5]:.3f}; median + 3*robust sd = {q[0] + 3 * mad:.3f}")
        out[name] = (r, v, q[0] + 3 * mad)
        x, y = st.cube.x.values, st.cube.y.values
        from rasterio.transform import from_origin
        tr = from_origin(float(x[0]) - 5, float(y[0]) + 5, 10, 10)
        for pid in ids:
            g = polys[polys["id"] == pid]
            if len(g):
                inside = ~geometry_mask(list(g.geometry), out_shape=r.shape, transform=tr)
                print(f"   polygon #{pid}: median range {np.nanmedian(r[inside]):.3f}")

    plot_idx = cfg.forest_mask.seasonal_range_index
    r, v, thr = out[plot_idx]
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.8))
    axes[0].hist(v, bins=np.linspace(0, np.percentile(v, 99.8), 80), color=SERIES[0])
    axes[0].axvline(thr, color=INK_2, ls="--", lw=1)
    axes[0].text(thr, axes[0].get_ylim()[1] * 0.9, f" {thr:.2f}", color=INK_2, fontsize=8)
    axes[0].set_title(f"{plot_idx.upper()} sezonālais diapazons (p90−p10), analizētais mežs",
                      loc="left")
    t = np.flatnonzero(st.cube.valid_fraction.values > 0.98)
    t = int(t[np.argmax(st.cube.time.values[t])])
    rgb = rgb_image(st.cube, t, gain=3.2)
    axes[1].imshow(rgb)
    axes[1].set_title(f"RGB {str(st.cube.time.values[t])[:10]}", loc="left")
    ov = rgb.copy()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        ex = m & (r > thr)
    ov[ex] = [0.93, 0.63, 0.0]
    axes[2].imshow(ov)
    axes[2].set_title(f"izslēgts ar slieksni {thr:.2f}: {ex.sum() / m.sum():.1%} (dzeltens)", loc="left")
    for a in axes[1:]:
        a.axis("off")
    path = cfg.run_dir / "diagnostics" / "amplitude_calibration.png"
    fig.savefig(path, dpi=130, bbox_inches="tight")
    print(f"Figure: {path}")


if __name__ == "__main__":
    main(sys.argv[1], [int(a) for a in sys.argv[2:]])
