"""Seasonal bias of z in healthy forest, per year, for several baseline methods.

Usage: python scripts/diagnose_seasonal_bias.py configs/test_kalsnava.yaml [window harmonic1 harmonic2]
Writes diagnostics/seasonal_bias.csv, seasonal_bias_summary.csv and seasonal_bias.png.
"""

from __future__ import annotations

import sys

import pandas as pd

from s2forest.config import load_config
from s2forest.diagnostics import plot_z_by_doy, summarize, z_by_date
from s2forest.pipeline import index_stage


def main(config: str, methods: list[str]) -> None:
    cfg = load_config(config)
    st = index_stage(cfg)
    parts = []
    for m in methods:
        if m == "window":
            parts.append(z_by_date(cfg, st, "window"))
        else:
            parts.append(z_by_date(cfg, st, "harmonic", harmonics=int(m[-1])))
        print(f"{m}: done")
    df = pd.concat(parts, ignore_index=True)
    out = cfg.run_dir / "diagnostics"
    df.to_csv(out / "seasonal_bias.csv", index=False)
    s = summarize(df)
    s.to_csv(out / "seasonal_bias_summary.csv", index=False)
    print(s.to_string(index=False))
    for m, d in df.groupby("method"):
        print(f"\n{m}: median z by year and early / late season")
        d = d.assign(part=pd.cut(d["doy"], [0, 150, 200, 366], labels=["<=30 May", "Jun-Jul", "Aug-Sep"]))
        print(d.pivot_table(index="year", columns="part", values="z_median", aggfunc="median",
                            observed=False).round(2).to_string())
    plot_z_by_doy(df, cfg.anomaly.z_threshold, out / "seasonal_bias.png")
    print(f"\n{out / 'seasonal_bias.png'}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:] or ["window", "harmonic1", "harmonic2"])
