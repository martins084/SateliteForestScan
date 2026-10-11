"""Diagnostics of the S1 injection test (stage 3b): why does detection drop with area?

Reproduces the injection sites of `s1windthrow inject` (same seed and order) and reports:
 a) whether injected pixels can reach the normalization / z statistics, simultaneity,
    injected area share per HRL class and the shift of the class statistics;
 b) the background index (no injection) at each site against the detection result;
 c) the spatial correlation of the stable-forest index for smoothing windows 1/3/5/7.
Nothing is changed in the method.

    python scripts/s1_injection_diagnostics.py configs/s1_kalsnava_2026-08_v2.yaml
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from s1windthrow.config import load_config  # noqa: E402
from s1windthrow.detect import CLASS_WINDTHROW, apply_mmu, classify, combine_orbits  # noqa: E402
from s1windthrow.injection import eligible_masks, sample_sites  # noqa: E402
from s1windthrow.method import deltas_from_composites, z_by_class  # noqa: E402
from s1windthrow.pipeline import orbit_composites, prepare  # noqa: E402

COMBOS = [(3, 2.5), (5, 3.0)]   # (window, k) discussed by the user
CLASS_NAME = {1: "lapu koki", 2: "skujkoki"}


def index_for(comps, masks, window, factor=None):
    comb = combine_orbits(deltas_from_composites(comps, masks.analysis, window, factor))
    return comb["index"]


def correlation(field: np.ndarray, mask: np.ndarray, max_lag_px: int) -> pd.DataFrame:
    """Isotropic autocorrelation of a masked field (FFT, normalized by pair counts)."""
    f = np.where(mask & np.isfinite(field), field, 0.0)
    m = (mask & np.isfinite(field)).astype(float)
    f = np.where(m > 0, f - f[m > 0].mean(), 0.0)
    sh = [2 * s for s in f.shape]
    F, M = np.fft.rfft2(f, sh), np.fft.rfft2(m, sh)
    num = np.fft.irfft2(F * np.conj(F), sh)
    den = np.fft.irfft2(M * np.conj(M), sh)
    with np.errstate(invalid="ignore", divide="ignore"):
        c = num / np.maximum(den, 1)
    c = np.fft.fftshift(c)
    cy, cx = sh[0] // 2, sh[1] // 2
    yy, xx = np.mgrid[-max_lag_px:max_lag_px + 1, -max_lag_px:max_lag_px + 1]
    r = np.hypot(yy, xx).round().astype(int)
    sub = c[cy - max_lag_px:cy + max_lag_px + 1, cx - max_lag_px:cx + max_lag_px + 1]
    out = pd.DataFrame({"lag_px": r.ravel(), "c": sub.ravel()}).groupby("lag_px").c.mean()
    return (out / out.loc[0]).rename("corr").reset_index()


def main(config: str) -> None:
    cfg = load_config(config)
    out = cfg.run_dir / "injection" / "diagnostics"
    out.mkdir(parents=True, exist_ok=True)
    pr = prepare(cfg, progress=lambda m: None)
    masks, grid = pr.masks, pr.grid
    comps, _ = orbit_composites(cfg, pr.table, "used_A", pr.data, masks.stable)
    sus = pd.concat([gpd.read_file(r.path, layer=r.layer).to_crs(cfg.grid.crs)
                     for r in cfg.checks.s2_exclude], ignore_index=True)
    inj = cfg.injection
    elig = eligible_masks(masks, grid, cfg, sus)
    rng = np.random.default_rng(inj.seed)
    gap_px = int(round(inj.min_gap_m / cfg.grid.resolution))
    min_px = math.ceil(cfg.detection.min_area_ha / grid.pixel_ha - 1e-9)
    classes = cfg.forest_mask.hrl_dlt_classes
    stable_ha = {c: float((masks.stable & (masks.dlt == c)).sum() * grid.pixel_ha) for c in classes}
    eligible_ha = {c: float(elig[c].sum() * grid.pixel_ha) for c in classes}

    # background index (no injection) per window, class statistics without injection
    base_idx = {w: index_for(comps, masks, w) for w in inj.windows}
    base_stats = {w: z_by_class(base_idx[w], masks.stable, masks.analysis, masks.dlt, classes)[1]
                  for w in inj.windows}

    area_rows, stat_rows, site_rows = [], [], []
    for size in inj.sizes_ha:
        n_px = int(round(size / grid.pixel_ha))
        sites = sample_sites(elig, masks.dlt, n_px, inj.n_per_combo, inj.class_purity, gap_px, rng)
        injm = np.zeros(masks.stable.shape, bool)
        for s in sites:
            injm[s.rows, s.cols] = True
        for c in classes:
            n = sum(s.cls == c for s in sites)
            area_rows.append({"size_ha": size, "class": c, "n_sites": n,
                              "injected_ha": round(n * size, 1), "stable_class_ha": round(stable_ha[c], 1),
                              "share_of_stable_class_pct": round(100 * n * size / stable_ha[c], 2),
                              "eligible_class_ha": round(eligible_ha[c], 1)})
        factor = {p: np.ones(injm.shape, "float32") for p in ("vv", "vh")}
        for p in ("vv", "vh"):
            factor[p][injm] = 10 ** (inj.base_db[p] / 10)        # strength 1x
        for w, k in COMBOS:
            idx = index_for(comps, masks, w, factor)
            # statistics as in the test (injected pixels excluded) and the spill-over ring
            r = (w - 1) // 2
            from scipy.ndimage import binary_dilation
            ring = binary_dilation(injm, iterations=r) & ~injm if r else np.zeros_like(injm)
            z, st = z_by_class(idx, masks.stable & ~injm, masks.analysis, masks.dlt, classes)
            _, st_ring = z_by_class(idx, masks.stable & ~injm & ~ring, masks.analysis, masks.dlt, classes)
            for c in classes:
                b = base_stats[w][c]
                stat_rows.append({"size_ha": size, "window": w, "class": c,
                                  "median_no_inj": round(b["median"], 4), "mad_no_inj": round(b["mad"], 4),
                                  "median_test": round(st[c]["median"], 4), "mad_test": round(st[c]["mad"], 4),
                                  "median_excl_ring": round(st_ring[c]["median"], 4),
                                  "mad_excl_ring": round(st_ring[c]["mad"], 4),
                                  "ring_px_in_stats": int((ring & masks.stable & (masks.dlt == c)).sum())})
            ana = masks.analysis & np.isfinite(z)
            cls, _ = apply_mmu(classify(z, ana, k), min_px)
            wt = cls == CLASS_WINDTHROW
            for i, s in enumerate(sites):
                bst = base_stats[w][s.cls]
                bg = float(np.nanmean(base_idx[w][s.rows, s.cols]))
                pix_exceed = float(np.nanmean((z[s.rows, s.cols] >= k)))
                site_rows.append({"size_ha": size, "window": w, "k": k, "site": i, "class": s.cls,
                                  "background_db": bg,
                                  "background_z": (bg - bst["median"]) / (1.4826 * bst["mad"]),
                                  "pixel_exceed_share": pix_exceed,
                                  "detected_share": float(wt[s.rows, s.cols].mean())})

    area = pd.DataFrame(area_rows)
    stats = pd.DataFrame(stat_rows)
    sites = pd.DataFrame(site_rows)
    sites["detected"] = sites.detected_share >= inj.detected_fraction
    area.to_csv(out / "a_injected_area.csv", index=False)
    stats.to_csv(out / "a_class_statistics.csv", index=False)
    sites.to_csv(out / "b_site_background.csv", index=False)

    summ = (sites.groupby(["window", "k", "class", "size_ha"])
            .agg(n=("site", "size"), rate=("detected", "mean"),
                 mean_detected_share=("detected_share", "mean"),
                 mean_pixel_exceed=("pixel_exceed_share", "mean"),
                 sd_pixel_exceed=("pixel_exceed_share", "std"),
                 mean_background_z=("background_z", "mean"),
                 sd_background_z=("background_z", "std")).round(3).reset_index())
    summ.to_csv(out / "b_summary.csv", index=False)

    # b) plot: background z vs detected share, per size (rows: combos)
    fig, axes = plt.subplots(len(COMBOS), len(inj.sizes_ha), figsize=(3.3 * len(inj.sizes_ha), 3.1 * len(COMBOS)),
                             dpi=150, sharey=True, sharex=True)
    for i, (w, k) in enumerate(COMBOS):
        for j, size in enumerate(inj.sizes_ha):
            ax = axes[i, j]
            g = sites[(sites.window == w) & (sites.size_ha == size)]
            for c, mk in ((1, "^"), (2, "o")):
                gc = g[g["class"] == c]
                ax.scatter(gc.background_z, gc.detected_share, marker=mk, s=16,
                           c=np.where(gc.detected, "#d62728", "#4c72b0"), alpha=0.8,
                           label=CLASS_NAME[c])
            ax.axhline(inj.detected_fraction, color="grey", lw=0.7, ls=":")
            ax.axvline(0, color="grey", lw=0.5)
            ax.grid(alpha=0.3)
            if i == 0:
                ax.set_title(f"{size:g} ha", fontsize=9)
            if j == 0:
                ax.set_ylabel(f"{w}×{w}, k = {k:g}\natklātā daļa vietā", fontsize=9)
            if i == len(COMBOS) - 1:
                ax.set_xlabel("fona z vietā (bez injekcijas)", fontsize=9)
    axes[0, 0].legend(fontsize=7, title="▲ lapu, ● skuju; sarkans = atklāts", title_fontsize=7)
    fig.suptitle("Fons vietā pret atklāšanu (stiprums 1×)", fontsize=11)
    fig.tight_layout()
    fig.savefig(out / "b_background_vs_detection.png")
    plt.close(fig)

    # c) spatial correlation of the stable-forest index (no injection)
    max_lag = 50   # 500 m
    corr_rows = []
    for w in inj.windows:
        for c in classes:
            cr = correlation(base_idx[w], masks.stable & (masks.dlt == c), max_lag)
            cr["window"], cr["class"] = w, c
            corr_rows.append(cr)
    corr = pd.concat(corr_rows, ignore_index=True)
    corr["lag_m"] = corr.lag_px * cfg.grid.resolution
    corr.to_csv(out / "c_correlation.csv", index=False)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), dpi=150, sharey=True)
    for ax, c in zip(axes, classes):
        for w in inj.windows:
            g = corr[(corr.window == w) & (corr["class"] == c)]
            ax.plot(g.lag_m, g["corr"], label=f"{w}×{w}")
        ax.axhline(0, color="grey", lw=0.6)
        ax.axvspan(100, 300, color="#f2c14e", alpha=0.15)
        ax.set_title(f"stabilais mežs, {CLASS_NAME[c]}", fontsize=10)
        ax.set_xlabel("attālums, m")
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("indeksa korelācija")
    axes[0].legend(title="logs", fontsize=8)
    fig.suptitle("ΔVH+ΔVV telpiskā korelācija (dzeltens: 100–300 m)", fontsize=11)
    fig.tight_layout()
    fig.savefig(out / "c_correlation.png")
    plt.close(fig)
    keyl = corr[corr.lag_m.isin([10, 20, 30, 50, 100, 150, 200, 300, 500])].pivot_table(
        index=["class", "window"], columns="lag_m", values="corr").round(3)
    keyl.to_csv(out / "c_correlation_key_lags.csv")
    (out / "summary.json").write_text(json.dumps({"stable_ha": stable_ha, "eligible_ha": eligible_ha},
                                                 indent=1), encoding="utf-8")
    pd.set_option("display.width", 220)
    print(area.to_string(index=False))
    print(stats.to_string(index=False))
    print(summ.to_string(index=False))
    print(keyl.to_string())


if __name__ == "__main__":
    main(sys.argv[1])
