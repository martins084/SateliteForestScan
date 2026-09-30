"""Inter-annual and inter-platform consistency of summer reflectance indices.

Stable healthy forest pixels (analysis mask; pixels flagged or excluded in the
last detection run removed) -> per acquisition the median CRSWIR and NDVI
(raw, NOT regionally normalized) in mid-summer (15.06-31.08, avoiding spring
phenology). Summarized per year and platform (S2A / S2B / S2C) and processing
source. A systematic offset between platforms in the same year would point to
a sensor / processing difference rather than a forest change.

Usage: python scripts/check_platform_trend.py configs/test_kalsnava.yaml [first_year]
(first_year: include earlier cached years, e.g. 2022)
"""

from __future__ import annotations

import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr

from s2forest.config import load_config
from s2forest.diagnostics import healthy_mask
from s2forest.indices import compute_indices
from s2forest.pipeline import index_stage
from s2forest.viz import INK, INK_2, SERIES, SURFACE, _save

NAMES = ["crswir", "ndvi"]


def main(config: str, first_year: int | None = None) -> None:
    cfg = load_config(config)
    mask_cfg = cfg
    st = index_stage(mask_cfg)
    m = healthy_mask(cfg, st)
    if first_year is not None and first_year < cfg.time.years[0]:
        wide = cfg.model_copy(deep=True)
        wide.time.baseline_years = cfg.time.monitor_year - first_year
        from s2forest.fetch import open_cube
        cube = open_cube(wide)
        idx = compute_indices(cube, NAMES)
    else:
        cube, idx = st.cube, compute_indices(st.cube, NAMES)
    t = pd.DatetimeIndex(cube.time.values)
    mmdd = t.strftime("%m-%d")
    sel = np.flatnonzero((mmdd >= "06-15") & (mmdd <= "08-31"))
    region = xr.DataArray(m, dims=("y", "x"))
    rows = []
    for i in sel:
        rec = {"date": t[i].date(), "year": t[i].year,
               "platform": str(cube.acq_key.values[i]).split("_")[1].upper(),
               "source": str(cube.source.values[i]), "baseline": str(cube.baseline.values[i])}
        ok = True
        for n in NAMES:
            v = idx[n].isel(time=i).where(region).values
            v = v[np.isfinite(v)]
            if v.size < 0.3 * m.sum():
                ok = False
                break
            rec[n] = float(np.median(v))
            rec[f"{n}_n"] = int(v.size)
        if ok:
            rows.append(rec)
    df = pd.DataFrame(rows)
    out = cfg.run_dir / "diagnostics"
    df.to_csv(out / "platform_trend_by_date.csv", index=False)
    summ = (df.groupby(["year", "platform"]).agg(n_dates=("date", "size"),
                                                 crswir_median=("crswir", "median"),
                                                 ndvi_median=("ndvi", "median"),
                                                 sources=("source", lambda s: ",".join(sorted(set(s)))))
            .round(4).reset_index())
    summ.to_csv(out / "platform_trend_summary.csv", index=False)
    print(f"Stable healthy forest pixels: {int(m.sum())}; summer dates used: {len(df)}")
    print(summ.to_string(index=False))
    yr = df.groupby("year")[NAMES].median().round(4)
    print("\nPer year (all platforms):\n" + yr.to_string())

    plats = sorted(df["platform"].unique())
    colors = {p: SERIES[i] for i, p in enumerate(plats)}
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2))
    rng = np.random.default_rng(0)
    for ax, n in zip(axes, NAMES):
        for k, p in enumerate(plats):
            d = df[df["platform"] == p]
            x = d["year"] + (k - (len(plats) - 1) / 2) * 0.18 + rng.uniform(-0.03, 0.03, len(d))
            ax.plot(x, d[n], "o", ms=5, color=colors[p], mec=SURFACE, label=p)
            s = summ[summ["platform"] == p]
            ax.plot(s["year"] + (k - (len(plats) - 1) / 2) * 0.18, s[f"{n}_median"], "_", ms=18,
                    mew=2.5, color=colors[p])
        ax.set_xticks(sorted(df["year"].unique()))
        ax.set_title(f"{n.upper()} vasaras (15.06.–31.08.) mediāna stabilā veselā mežā", loc="left",
                     fontsize=10)
        ax.grid(axis="x", visible=False)
    axes[0].legend(title="platforma", loc="upper left")
    fig.suptitle("Starpgadu un platformu salīdzinājums (punkts = pārlidojums, svītra = mediāna)",
                 x=0.01, ha="left", color=INK, fontsize=11)
    fig.tight_layout()
    print(f"\nFigure: {_save(fig, out / 'platform_trend.png')}")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else None)
