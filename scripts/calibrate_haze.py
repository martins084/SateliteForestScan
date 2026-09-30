"""Calibrate the haze test threshold (B02 excess over the pixel's baseline reference).

Shows, for a hazy scene and a clear control scene: RGB, B02 excess, and the
resulting masks for several thresholds. Uses the cached AOI cube with the haze
test switched off, then applies it here with each candidate threshold.

Usage: python scripts/calibrate_haze.py configs/test_kalsnava.yaml 2026-09-15 2026-07-17
"""

from __future__ import annotations

import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from s2forest.config import load_config
from s2forest.fetch import build_grid, open_cube
from s2forest.forestmask import forest_mask
from s2forest.haze import haze_mask_numpy
from s2forest.temporal import doy_reference_stats, time_info
from s2forest.viz import rgb_image

THRESHOLDS = [0.01, 0.015, 0.02, 0.03]


def main(config: str, hazy: str, clear: str) -> None:
    cfg = load_config(config)
    cfg.masking.haze.enabled = False
    cfg.data.min_valid_fraction = 0.0
    cube = open_cube(cfg).load()
    grid = build_grid(cfg)
    fmask = forest_mask(grid.geobox, cfg.cache_dir / grid.key, "hrl_dlt_2018", [1, 2])

    doy, year = time_info(cube.time.values)
    b02 = cube.B02.values
    valid = cube.valid.values
    base = cfg.time.baseline_year_list
    ref, _, _ = doy_reference_stats(np.where(valid, b02, np.nan), doy, np.isin(year, base),
                                    cfg.masking.haze.doy_window, cfg.masking.haze.min_ref_obs)
    excess = b02 - ref

    times = pd.DatetimeIndex(cube.time.values).strftime("%Y-%m-%d")
    rows = []
    masks = {}
    for thr in THRESHOLDS:
        m, u = haze_mask_numpy(b02, valid, doy, year, base, thr, cfg.masking.haze.doy_window,
                               cfg.masking.haze.min_ref_obs)
        masks[thr] = (m, u)
        n_valid = valid.sum(axis=(1, 2))
        rows.append(pd.DataFrame({"date": cube.acq_key.values, "thr": thr,
                                  "masked_frac": m.sum(axis=(1, 2)) / np.maximum(n_valid, 1),
                                  "unresolved_frac": u.sum(axis=(1, 2)) / np.maximum(n_valid, 1)}))
    table = pd.concat(rows)
    wide = table.pivot(index="date", columns="thr", values="masked_frac")
    out = cfg.run_dir / "diagnostics"
    out.mkdir(parents=True, exist_ok=True)
    wide.to_csv(out / "haze_calibration_by_date.csv")
    print("Masked share of valid AOI pixels per threshold (monitoring year shown):")
    print(wide[wide.index.str.startswith(str(cfg.time.monitor_year))].round(3).to_string())

    # Excess distribution over forest pixels on clear dates (defines the noise floor).
    vf = cube.valid_fraction.values
    clear_idx = np.flatnonzero(vf > 0.98)
    ex_clear = excess[clear_idx][:, fmask][~np.isnan(excess[clear_idx][:, fmask])]
    print(f"\nClear dates (vf>0.98, n={clear_idx.size}), forest pixels: B02 excess percentiles "
          f"p50={np.percentile(ex_clear, 50):.4f} p95={np.percentile(ex_clear, 95):.4f} "
          f"p99={np.percentile(ex_clear, 99):.4f} p99.9={np.percentile(ex_clear, 99.9):.4f}")

    fig, axes = plt.subplots(2, 2 + len(THRESHOLDS), figsize=(3.1 * (2 + len(THRESHOLDS)), 6.6))
    for row, day in enumerate([hazy, clear]):
        t = int(np.flatnonzero(times == day)[0])
        ax = axes[row]
        ax[0].imshow(rgb_image(cube, t, gain=3.5))
        ax[0].set_title(f"{day} RGB (SCL masked grey)", fontsize=8)
        im = ax[1].imshow(np.where(valid[t], excess[t], np.nan), cmap="Blues", vmin=0, vmax=0.04)
        ax[1].set_title("B02 excess over reference", fontsize=8)
        for k, thr in enumerate(THRESHOLDS):
            m, u = masks[thr]
            show = np.zeros(valid[t].shape + (3,)) + 0.85
            show[valid[t]] = [0.3, 0.45, 0.3]
            show[m[t]] = [0.92, 0.41, 0.2]
            show[u[t]] = [0.93, 0.63, 0.0]
            ax[2 + k].imshow(show)
            ax[2 + k].set_title(f"thr {thr}: masked {m[t].sum() / max(valid[t].sum(), 1):.0%}"
                                f", unresolved {u[t].sum() / max(valid[t].sum(), 1):.0%}", fontsize=8)
        for a in ax:
            a.axis("off")
    fig.colorbar(im, ax=axes[:, 1], fraction=0.04, shrink=0.8)
    fig.suptitle("Haze threshold calibration (orange = masked, yellow = unresolved/kept, "
                 "green = valid)", fontsize=10, x=0.01, ha="left")
    fig.savefig(out / "haze_calibration.png", dpi=130, bbox_inches="tight")
    print(f"\nFigure: {out / 'haze_calibration.png'}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
