"""PNG figures: index preview with candidates, stable-forest backscatter series."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ORBIT_COLORS = {58: "#1f77b4", 160: "#17becf", 80: "#d62728", 7: "#ff7f0e", 153: "#9467bd"}


def preview(cfg, grid, masks, res, path: Path) -> Path:
    b = grid.geobox.boundingbox
    ext = (b.left, b.right, b.bottom, b.top)
    fig, axes = plt.subplots(1, 2, figsize=(13, 6.2), dpi=150)
    idx = np.where(masks.analysis, res.combined["index"], np.nan)
    med = float(np.nanmedian([st["median"] for st in res.stats.values()]))
    lim = np.nanpercentile(np.abs(idx - med), 99) + abs(med)
    im0 = axes[0].imshow(idx, extent=ext, cmap="RdBu_r", vmin=med - lim, vmax=med + lim)
    fig.colorbar(im0, ax=axes[0], shrink=0.8, label="ΔVH + ΔVV, dB (pēc − pirms)")
    zz = np.where(masks.analysis, res.z, np.nan)
    im1 = axes[1].imshow(zz, extent=ext, cmap="RdBu_r", vmin=-5, vmax=5)
    fig.colorbar(im1, ax=axes[1], shrink=0.8, label="z (stabilā meža mediāna / MAD)")
    for ax in axes:
        if not res.polygons.empty:
            for cls, col in (("windthrow", "black"), ("cut_like", "#2ca02c")):
                g = res.polygons[res.polygons["class"] == cls]
                if len(g):
                    g.boundary.plot(ax=ax, color=col, linewidth=1.2)
        ax.set_xticks([]); ax.set_yticks([])
    k = cfg.detection.threshold.k
    axes[0].set_title(f"Variants {res.name}: izmaiņu indekss (tikai analizētais mežs)", fontsize=10)
    axes[1].set_title(f"z; melns — z ≥ {k} (windthrow), zaļš — z ≤ −{k} (cut_like), ≥ "
                      f"{cfg.detection.min_area_ha} ha", fontsize=10)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def stable_series_plot(series: pd.DataFrame, weather: pd.DataFrame, cfg, path: Path) -> Path:
    s = series.copy()
    s["t"] = pd.to_datetime(s["date"].astype(str) + " " + s["time_utc"])
    fig, axes = plt.subplots(3, 1, figsize=(11, 8.5), dpi=150, sharex=True,
                             gridspec_kw={"height_ratios": [3, 3, 1.4]})
    for ax, pol in zip(axes[:2], ("vv", "vh")):
        for orb, g in s.groupby("rel_orbit"):
            d = g.direction.iloc[0][:4]
            ax.plot(g.t, g[f"{pol}_db"], "o-", color=ORBIT_COLORS.get(orb, "grey"),
                    label=f"orbīta {orb} ({d}.)", ms=4, lw=1)
        ax.set_ylabel(f"{pol.upper()} mediāna, dB")
        ax.grid(alpha=0.3)
    axes[0].legend(fontsize=8, ncol=5, loc="upper left")
    daily = weather["precip_mm"].resample("D").sum()
    daily = daily[(daily.index >= pd.Timestamp(cfg.event.pre_window[0]) - pd.Timedelta(days=1))
                  & (daily.index <= pd.Timestamp(cfg.event.post_window[1]) + pd.Timedelta(days=1))]
    axes[2].bar(daily.index + pd.Timedelta(hours=12), daily.values, width=0.8, color="#4c72b0")
    axes[2].set_ylabel("nokrišņi, mm/d")
    axes[2].grid(alpha=0.3)
    for ax in axes:
        ax.axvspan(pd.Timestamp(cfg.event.pre_window[1]) + pd.Timedelta(days=1),
                   pd.Timestamp(cfg.event.post_window[0]), color="#e34948", alpha=0.15)
        for w in (cfg.event.pre_window, cfg.event.post_window):
            ax.axvline(pd.Timestamp(w[0]), color="grey", lw=0.6, ls=":")
            ax.axvline(pd.Timestamp(w[1]) + pd.Timedelta(days=1), color="grey", lw=0.6, ls=":")
    axes[2].xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
    axes[0].set_title("Stabilā meža atpakaļizkliede katrā uzņēmumā (mediāna, dB); "
                      f"sarkanā josla — starp logiem ({cfg.event.name}); punktētas — logu robežas",
                      fontsize=10)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def injection_plot(rate: pd.DataFrame, cfg, path: Path) -> Path:
    """Detection rate vs injected area: rows = k, columns = smoothing window;
    colour = strength, line style = HRL class."""
    inj = cfg.injection
    ks, ws = inj.k, inj.windows
    fig, axes = plt.subplots(len(ks), len(ws), figsize=(3.2 * len(ws), 2.6 * len(ks)), dpi=150,
                             sharex=True, sharey=True, squeeze=False)
    colors = {0.5: "#9ecae1", 1.0: "#3182bd", 2.0: "#08306b"}
    styles = {1: "--", 2: "-"}
    names = {1: "lapu koki", 2: "skujkoki"}
    for i, k in enumerate(ks):
        for j, w in enumerate(ws):
            ax = axes[i, j]
            sub = rate[(rate.k == k) & (rate.window == w)]
            for (st, c), g in sub.groupby(["strength", "class"]):
                g = g.sort_values("size_ha")
                ax.plot(g.size_ha, g.rate, styles.get(c, "-"), marker="o", ms=3,
                        color=colors.get(st, "grey"), label=f"{st:g}× ({names.get(c, c)})")
            ax.set_xscale("log")
            ax.minorticks_off()
            ax.set_xticks(inj.sizes_ha)
            ax.set_xticklabels([f"{s:g}" for s in inj.sizes_ha])
            ax.set_ylim(-0.03, 1.03)
            ax.grid(alpha=0.3)
            if i == 0:
                ax.set_title(f"logs {w}×{w}", fontsize=9)
            if j == 0:
                ax.set_ylabel(f"k = {k:g}\natklāts", fontsize=9)
            if i == len(ks) - 1:
                ax.set_xlabel("platība, ha", fontsize=9)
    axes[0, -1].legend(fontsize=6.5, loc="upper left", title="stiprums (Rüetschi = 1×)",
                       title_fontsize=6.5)
    fig.suptitle("Injekcijas tests: atklāšanas īpatsvars pret platību", fontsize=11)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path
