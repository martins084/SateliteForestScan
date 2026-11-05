"""Drought comparison statistics (synthetic data, no files)."""

import numpy as np
import pandas as pd
import pytest

from mezasargs_risk import drought as D


def test_spearman_perm_and_block_bootstrap():
    rng = np.random.default_rng(0)
    x = np.arange(20.0)
    assert D.spearman(x, x ** 3) == pytest.approx(1.0)
    assert D.spearman(x, -x) == pytest.approx(-1.0)
    assert np.isnan(D.spearman(x, np.ones(20)))
    assert D.perm_p(x, x, 999, rng) == pytest.approx(1 / 1000)          # nothing as extreme among permutations
    lo, hi = D.block_boot_ci(x, x + rng.normal(0, 0.1, 20), 2000, rng)
    assert lo > 0.9 and hi <= 1.0
    # independent noise: p roughly uniform, interval covers 0 most of the time
    ps, cover = [], 0
    for s in range(40):
        r = np.random.default_rng(s)
        a, b = r.normal(size=15), r.normal(size=15)
        ps.append(D.perm_p(a, b, 499, r))
        lo, hi = D.block_boot_ci(a, b, 499, r)
        cover += lo <= 0 <= hi
    assert 0.25 < np.mean(ps) < 0.75 and cover >= 30
    assert D.block_length(12) == 2 and D.block_length(32) == 3


def test_lagged_features_and_lag_table():
    f = pd.DataFrame({"z": [1.0, 2.0, 3.0, 4.0]}, index=[2000, 2001, 2002, 2003])
    lf = D.lagged(f, ["z"])
    assert lf.loc[2003, "z|t-1"] == 3 and lf.loc[2003, "z|t-2"] == 2 and lf.loc[2003, "z|t-1+t-2"] == 5
    assert lf.loc[2005, "z|t-2"] == 4 and np.isnan(lf.loc[2001, "z|t-2"])
    years = range(1990, 2020)
    z = pd.Series(np.random.default_rng(1).normal(size=30), index=years)
    dmg = {"follows_t-1": -z.shift(1), "short": z.loc[2015:]}
    t = D.lag_table(dmg, D.lagged(z.to_frame("z"), ["z"]), 499, 499, 0)
    r = t[(t.series == "follows_t-1") & (t.lag == "t-1")].iloc[0]
    assert r["n"] == 29 and r["rho"] == pytest.approx(-1.0) and r["ci_hi"] <= -0.9
    s = t[(t.series == "short") & (t.lag == "t")].iloc[0]
    assert s["n"] == 5 and np.isnan(s.get("ci_lo", np.nan))                # n < 8: no bootstrap interval


def test_panel_within_year_and_events():
    rng = np.random.default_rng(2)
    rows = []
    for y in range(2010, 2022):
        shock = rng.normal() * 5                                       # common year effect in y only
        for i, reg in enumerate("ABCDE"):
            x = rng.normal()
            rows.append({"region": reg, "year": y, "x": x, "y": shock - 2 * x + rng.normal() * 0.01})
    p = D.panel_stats(pd.DataFrame(rows), "y", "x", 999, 999, 0)
    assert p["n_region_years"] == 60 and p["n_years"] == 12
    assert p["rho_within"] < -0.95 and p["p_perm_within"] < 0.01 and p["ci_within_hi"] < -0.9
    s = pd.Series([1, 1, 1, 1, 1, 5, 2, 1.0], index=range(2013, 2021))
    e = D.event_table({"s": s}, [2018], pre=5, after=3)
    assert list(e.year) == [2018, 2019, 2020] and e.iloc[0]["ratio_to_pre"] == 5 and e.iloc[0]["pre_n"] == 5
