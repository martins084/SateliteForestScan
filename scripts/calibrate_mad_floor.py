"""Calibrate the per-index MAD floor (minimum z-score scale).

With ~10-15 baseline observations in a +-30 day window, per-pixel MAD is often
underestimated, which inflates z-scores. This script reports the distribution of
the per-pixel robust scale (1.4826 * MAD) over analysed forest pixels, and for
candidate floors (percentiles of that distribution) the share of pixels flagged
in each baseline year by leave-one-year-out testing (an estimate of the false
alarm rate: most forest is undisturbed in any given year) and in the monitoring
year.

Usage: python scripts/calibrate_mad_floor.py configs/test_kalsnava.yaml
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd
import xarray as xr

from s2forest.anomaly import (MAD_SCALE, anomalous_obs, params_from_config, persistent_runs,
                              zscores)
from s2forest.config import load_config
from s2forest.pipeline import _stack, context_offsets, index_stage
from s2forest.temporal import doy_reference_stats, time_info

PCTS = [None, 25, 50, 75]


def flag_rate(v, doy, year, p, ref_sel, test_sel, m):
    idx = np.concatenate([np.flatnonzero(ref_sel), np.flatnonzero(test_sel)])
    sub_ref = np.concatenate([np.ones(ref_sel.sum(), bool), np.zeros(test_sel.sum(), bool)])
    z, _, _ = zscores(v[:, idx], doy[idx], sub_ref, p)
    z = z[:, ref_sel.sum():]
    anom, valid, _ = anomalous_obs(z, p)
    flag, _, _ = persistent_runs(anom, valid, p.persistence)
    return float(flag[m].mean()), float(np.nanmean(z[p.primary][:, m] >= p.k))


def main(config: str) -> None:
    cfg = load_config(config)
    st = index_stage(cfg)
    names = list(cfg.indices)
    p = params_from_config(cfg.anomaly, names, cfg.time.baseline_year_list, cfg.time.monitor_year)
    _, off = context_offsets(cfg, st, p)
    vals = _stack(st.indices, names).where(xr.DataArray(st.analysis_mask, dims=("y", "x")))
    vals = (vals - xr.DataArray(off, dims=("index", "time"))).values[:, :, ::2, ::2]
    m = st.analysis_mask[::2, ::2]
    doy, year = time_info(st.cube.time.values)
    base_sel = np.isin(year, p.baseline_years)

    scales = {}
    for i, n in enumerate(names):
        _, mad, _ = doy_reference_stats(vals[i], doy, base_sel, p.window, p.min_obs, with_mad=True)
        s = (MAD_SCALE * mad)[year == cfg.time.monitor_year][:, m]
        scales[n] = s[np.isfinite(s)]
        q = np.percentile(scales[n], [10, 25, 50, 75, 90])
        print(f"{n:7s} scale p10 {q[0]:.4f}  p25 {q[1]:.4f}  p50 {q[2]:.4f}  p75 {q[3]:.4f}  p90 {q[4]:.4f}")

    rows = []
    for pct in PCTS:
        if pct is None:
            floors = p.floors.copy()
            label = "config " + ",".join(f"{f:.3f}" for f in floors)
        else:
            floors = np.array([np.percentile(scales[n], pct) for n in names], dtype="float32")
            label = f"p{pct} " + ",".join(f"{f:.3f}" for f in floors)
        p.floors = floors
        row = {"floor": label}
        for by in p.baseline_years:
            fr, zr = flag_rate(vals, doy, year, p, base_sel & (year != by), year == by, m)
            row[f"flag_{by}"] = round(fr * 100, 1)
            row[f"obs_z_{by}"] = round(zr * 100, 1)
        fr, zr = flag_rate(vals, doy, year, p, base_sel, year == cfg.time.monitor_year, m)
        row[f"flag_{cfg.time.monitor_year}"] = round(fr * 100, 1)
        row[f"obs_z_{cfg.time.monitor_year}"] = round(zr * 100, 1)
        rows.append(row)
    df = pd.DataFrame(rows)
    print("\nShare of analysed pixels flagged (flag_*) and of observations with primary z>=k (obs_z_*), %:")
    print(df.to_string(index=False))
    out = cfg.run_dir / "diagnostics" / "mad_floor_calibration.csv"
    df.to_csv(out, index=False)
    print(f"\n{out}")


if __name__ == "__main__":
    main(sys.argv[1])
