"""Stage 4: climatic water balance P - ET0 over the growing season months (default IV-IX) and its
standardized anomaly against a reference period (default 1991-2020).

z = (CWB_y - mean(CWB_ref)) / sd(CWB_ref), sd with ddof = 1. This is NOT SPEI (no distribution
fit, no multi-month accumulation; user decision 2.13 point 9): name "standardizēta klimatiskās
ūdens bilances anomālija". ET0 = Open-Meteo `et0_fao_evapotranspiration` (FAO-56).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def seasonal(day: pd.DataFrame, months: tuple[int, int]) -> pd.DataFrame:
    """Per year: P, ET0 and P - ET0 summed over months m0..m1; NaN if any day is missing."""
    m0, m1 = months
    d = day[(day.index.month >= m0) & (day.index.month <= m1)]
    rows = []
    for y, g in d.groupby(d.index.year):
        expected = (pd.Timestamp(y, m1, 1) + pd.offsets.MonthEnd(0) - pd.Timestamp(y, m0, 1)).days + 1
        ok = len(g) == expected and not g[["precip", "et0"]].isna().any().any()
        p, e = (g["precip"].sum(), g["et0"].sum()) if ok else (np.nan, np.nan)
        rows.append({"year": int(y), "days": len(g), "complete": ok, "precip_mm": p, "et0_mm": e, "cwb_mm": p - e})
    return pd.DataFrame(rows)


def anomaly(s: pd.DataFrame, ref: tuple[int, int]) -> pd.DataFrame:
    """Adds `cwb_z` (standardized anomaly vs the reference years) and the reference mean / sd."""
    r = s[(s["year"] >= ref[0]) & (s["year"] <= ref[1])]
    if r["complete"].sum() != ref[1] - ref[0] + 1:
        raise ValueError(f"reference period {ref} incomplete: {int(r['complete'].sum())} complete years")
    mu, sd = r["cwb_mm"].mean(), r["cwb_mm"].std(ddof=1)
    return s.assign(cwb_ref_mean=round(mu, 2), cwb_ref_sd=round(sd, 2), cwb_z=(s["cwb_mm"] - mu) / sd)
