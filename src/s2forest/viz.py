"""Static figures (PNG) for diagnostics, maps and the report."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import xarray as xr  # noqa: E402

# Validated categorical palette (fixed order) and neutral inks.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e4e3df"
SURFACE = "#fcfcfb"
MUTED = "#b9b8b3"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": MUTED, "axes.labelcolor": INK_2, "xtick.color": INK_2, "ytick.color": INK_2,
    "axes.titlecolor": INK, "axes.titlesize": 11, "axes.labelsize": 9,
    "xtick.labelsize": 8, "ytick.labelsize": 8, "legend.fontsize": 8, "legend.frameon": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.spines.top": False, "axes.spines.right": False, "font.size": 9,
})


def _save(fig, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_valid_observations(table: pd.DataFrame, threshold: float, path: Path) -> Path:
    """Small multiples per year: clear-sky fraction over the AOI for every overpass."""
    t = table[table["status"].isin(["accepted", "rejected"])].copy()
    t["year"] = t["datetime"].dt.year
    t["doy_date"] = pd.to_datetime("2001-" + t["datetime"].dt.strftime("%m-%d"))
    years = sorted(t["year"].unique())
    fig, axes = plt.subplots(len(years), 1, figsize=(8, 1.6 * len(years) + 0.6), sharex=True,
                             squeeze=False)
    for ax, year in zip(axes[:, 0], years):
        d = t[t["year"] == year]
        acc = d[d["status"] == "accepted"]
        rej = d[d["status"] == "rejected"]
        ax.vlines(rej["doy_date"], 0, rej["valid_fraction"], color=MUTED, lw=2)
        ax.vlines(acc["doy_date"], 0, acc["valid_fraction"], color=SERIES[0], lw=2)
        ax.axhline(threshold, color=INK_2, lw=0.8, ls="--")
        ax.set_ylim(0, 1.05)
        ax.set_yticks([0, 0.5, 1])
        ax.text(0.005, 0.97, f"{year}: {len(acc)} derīgi / {len(d)} pārlidojumi",
                transform=ax.transAxes, va="top", color=INK, fontsize=8.5)
    axes[-1, 0].xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%d.%m"))
    axes[0, 0].set_title("Skaidro pikseļu daļa AOI katrā pārlidojumā "
                         "(zils = pieņemts, pelēks = atmests, svītra = slieksnis)", loc="left")
    fig.supylabel("derīgā daļa", color=INK_2, fontsize=9)
    return _save(fig, path)


def rgb_image(ds: xr.Dataset, t: int, gain: float = 3.5) -> np.ndarray:
    rgb = np.stack([ds[b].isel(time=t).values for b in ("B04", "B03", "B02")], axis=-1)
    rgb = np.clip(rgb * gain, 0, 1)
    rgb = np.where(np.isnan(rgb), 0.85, rgb)  # masked -> light grey
    return rgb


def plot_quicklooks(cube: xr.Dataset, aoi_outline, path: Path, max_panels: int = 12) -> Path:
    """RGB of the clearest acquisition per month (masked pixels shown light grey)."""
    df = pd.DataFrame({"time": pd.to_datetime(cube.time.values), "vf": cube.valid_fraction.values,
                       "i": np.arange(cube.sizes["time"])})
    df["month"] = df["time"].dt.to_period("M")
    pick = df.loc[df.groupby("month")["vf"].idxmax()].sort_values("time").tail(max_panels)
    n = len(pick)
    ncol = min(4, n)
    nrow = int(np.ceil(n / ncol))
    fig, axes = plt.subplots(nrow, ncol, figsize=(3 * ncol, 3 * nrow), squeeze=False)
    extent = [float(cube.x.min()) - 5, float(cube.x.max()) + 5, float(cube.y.min()) - 5,
              float(cube.y.max()) + 5]
    for ax in axes.ravel():
        ax.axis("off")
    for ax, (_, row) in zip(axes.ravel(), pick.iterrows()):
        ax.imshow(rgb_image(cube, int(row["i"])), extent=extent, interpolation="nearest")
        if aoi_outline is not None:
            aoi_outline.boundary.plot(ax=ax, color="#ffffff", lw=1.2)
            aoi_outline.boundary.plot(ax=ax, color=INK, lw=0.6)
        src = cube.source.values[int(row["i"])]
        ax.set_title(f"{row['time']:%Y-%m-%d}  {row['vf']:.0%}  ({src})", fontsize=8)
    fig.suptitle("Skaidrākā aina katrā mēnesī (pelēks = maskēts)", color=INK, fontsize=11,
                 x=0.01, ha="left")
    return _save(fig, path)


def plot_harmonization_check(series: pd.DataFrame, path: Path) -> Path:
    """Median reflectance of conifer-forest pixels per acquisition, per band, by source.

    If the baseline 04.00 offset were handled wrongly, one group of years/sources
    would sit ~0.1 above the others - most visible in the dark red band.
    """
    bands = [b for b in ("B04", "B08", "B11") if b in series]
    sources = sorted(series["source"].unique())
    fig, axes = plt.subplots(len(bands), 1, figsize=(8, 2.1 * len(bands) + 0.5), sharex=True,
                             squeeze=False)
    names = {"B04": "B04 sarkanais", "B08": "B08 NIR", "B11": "B11 SWIR1"}
    for ax, b in zip(axes[:, 0], bands):
        for k, s in enumerate(sources):
            d = series[series["source"] == s]
            ax.plot(d["time"], d[b], "o", ms=4, color=SERIES[k], label=s, mec=SURFACE, mew=0.8)
        ax.set_ylabel(names[b])
    axes[0, 0].legend(loc="upper right", ncol=len(sources))
    axes[0, 0].set_title("Harmonizācijas pārbaude: skujkoku meža pikseļu mediānā atstarošanās",
                         loc="left")
    return _save(fig, path)
