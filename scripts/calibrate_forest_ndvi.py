"""Choose the baseline summer NDVI threshold for the forest mask.

Histogram of the per-pixel summer (Jun-Aug) NDVI median over the baseline years,
for pixels in the HRL forest classes, next to an RGB with the pixels that a
candidate threshold would exclude.

Usage: python scripts/calibrate_forest_ndvi.py configs/test_kalsnava.yaml
"""

from __future__ import annotations

import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from s2forest.config import load_config
from s2forest.fetch import build_grid, open_cube
from s2forest.forestmask import forest_mask, summer_median
from s2forest.indices import compute_indices
from s2forest.viz import INK_2, SERIES, rgb_image

CANDIDATES = [0.70, 0.75, 0.80, 0.85]


def main(config: str) -> None:
    cfg = load_config(config)
    cube = open_cube(cfg)
    grid = build_grid(cfg)
    fm = cfg.forest_mask
    hrl = forest_mask(grid.geobox, cfg.cache_dir / grid.key, fm.source, fm.classes) & grid.aoi_mask
    ndvi = compute_indices(cube, ["ndvi"]).ndvi
    med = summer_median(ndvi, cfg.time.baseline_year_list, fm.summer_start, fm.summer_end).values
    v = med[hrl & np.isfinite(med)]
    print(f"HRL class pixels in AOI: {hrl.sum()}, with summer data: {v.size}")
    print("percentiles:", {p: round(float(np.percentile(v, p)), 3) for p in (1, 5, 10, 25, 50, 75, 95)})
    for c in CANDIDATES:
        print(f"  threshold {c:.2f}: excludes {np.mean(v < c):.1%} of HRL pixels")

    hist, edges = np.histogram(v, bins=np.arange(0.2, 1.0, 0.01))
    t = np.flatnonzero(cube.valid_fraction.values > 0.98)
    t = int(t[np.argmax(cube.time.values[t])])
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.8))
    axes[0].bar(edges[:-1], hist, width=0.009, color=SERIES[0], align="edge")
    for c in CANDIDATES:
        axes[0].axvline(c, color=INK_2, lw=0.8, ls="--")
        axes[0].text(c, hist.max() * 0.95, f"{c:.2f}", fontsize=7, ha="right", color=INK_2)
    axes[0].set_title("Bāzes vasaras NDVI mediāna, HRL skujkoku pikseļi", loc="left")
    axes[0].set_xlabel("NDVI")
    rgb = rgb_image(cube, t, gain=3.2)
    axes[1].imshow(rgb)
    axes[1].set_title(f"RGB {str(cube.time.values[t])[:10]}", loc="left")
    thr = cfg.forest_mask.min_summer_ndvi or 0.8
    ov = rgb.copy()
    ex = hrl & (med < thr)
    ov[ex] = [0.93, 0.63, 0.0]
    axes[2].imshow(ov)
    axes[2].set_title(f"izslēgts ar slieksni {thr:.2f} (dzeltens)", loc="left")
    for a in axes[1:]:
        a.axis("off")
    out = cfg.run_dir / "diagnostics" / "forest_ndvi_calibration.png"
    fig.savefig(out, dpi=130, bbox_inches="tight")
    print(f"Figure: {out}")


if __name__ == "__main__":
    main(sys.argv[1])
