"""Drought comparison after stage 4 (plan L7 / 2.15 point 2; user decision 2026-11-04): DESCRIPTIVE only.

Annual damage series (CSP MEB012, EFDA v3.0 classes 1 and 3, LVM 620) against the Latvian mean water balance anomaly
(cwb_z, P - ET0 IV-IX vs 1991-2020) and the RITY-2 relative thermal sums at lags t, t-1, t-2 and t-1 + t-2. Few
years (n = 5-32), so no causal claims: Spearman rho with a permutation p value and a moving-block bootstrap 95 %
interval; every row carries n. First differences are given as a check against shared trends.

Regional panel (LVM 620 per 1000 ha LVM land x NUTS 2024 region x year): pooled rho (bootstrap and permutation over
whole years) and within-year rho (ranks centred per year; permutation of regions within year).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import rankdata

LAGS = ("t", "t-1", "t-2", "t-1+t-2")


def _rho_rows(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Spearman rho per row of 2-D arrays (ties: average ranks); NaN where a row is constant."""
    rx, ry = rankdata(x, axis=1), rankdata(y, axis=1)
    rx -= rx.mean(1, keepdims=True)
    ry -= ry.mean(1, keepdims=True)
    den = np.sqrt((rx ** 2).sum(1) * (ry ** 2).sum(1))
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 0, (rx * ry).sum(1) / den, np.nan)


def spearman(x, y) -> float:
    return float(_rho_rows(np.asarray(x, float)[None], np.asarray(y, float)[None])[0])


def perm_p(x, y, n_perm: int, rng: np.random.Generator) -> float:
    """Two-sided permutation p value of Spearman rho ((1 + #|rho*| >= |rho|) / (n_perm + 1))."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    r = spearman(x, y)
    if not np.isfinite(r):
        return np.nan
    yp = rng.permuted(np.tile(y, (n_perm, 1)), axis=1)
    rp = _rho_rows(np.tile(x, (n_perm, 1)), yp)
    return float((1 + np.sum(np.abs(rp) >= abs(r) - 1e-12)) / (n_perm + 1))


def block_length(n: int) -> int:
    return max(2, int(round(n ** (1 / 3))))


def block_boot_ci(x, y, n_boot: int, rng: np.random.Generator, block: int | None = None,
                  level: float = 0.95) -> tuple[float, float]:
    """Moving-block bootstrap percentile interval of Spearman rho for paired annual series."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    n = len(x)
    b = block or block_length(n)
    k = int(np.ceil(n / b))
    starts = rng.integers(0, n - b + 1, size=(n_boot, k))
    idx = (starts[:, :, None] + np.arange(b)[None, None, :]).reshape(n_boot, -1)[:, :n]
    r = _rho_rows(x[idx], y[idx])
    r = r[np.isfinite(r)]
    a = (1 - level) / 2
    return (float(np.quantile(r, a)), float(np.quantile(r, 1 - a))) if len(r) else (np.nan, np.nan)


def lagged(feat: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Columns `<col>|<lag>` for lags t, t-1, t-2 and the two-year sum t-1 + t-2 (index = year)."""
    f = feat[cols].sort_index()
    f = f.reindex(range(int(f.index.min()), int(f.index.max()) + 3))   # room for the shifted years
    out = {}
    for c in cols:
        out[f"{c}|t"] = f[c]
        out[f"{c}|t-1"] = f[c].shift(1)
        out[f"{c}|t-2"] = f[c].shift(2)
        out[f"{c}|t-1+t-2"] = f[c].shift(1) + f[c].shift(2)
    return pd.DataFrame(out)


def lag_table(damage: dict[str, pd.Series], lf: pd.DataFrame, n_perm: int, n_boot: int, seed: int,
              min_n_ci: int = 8) -> pd.DataFrame:
    """Spearman rho of every damage series against every lagged feature; n, years, rho, permutation p, block
    bootstrap 95 % interval (only if n >= min_n_ci) and the same for first differences."""
    rows = []
    for name, s in damage.items():
        for col in lf.columns:
            feature, lag = col.split("|")
            j = pd.concat([s.rename("y"), lf[col].rename("x")], axis=1).dropna()
            n = len(j)
            r = {"series": name, "feature": feature, "lag": lag, "n": n,
                 "years": f"{j.index.min()}-{j.index.max()}" if n else ""}
            if n < 4:
                rows.append(r | {"rho": np.nan})
                continue
            rng = np.random.default_rng(seed)
            r["rho"] = spearman(j.x, j.y)
            r["p_perm"] = perm_p(j.x, j.y, n_perm, rng)
            if n >= min_n_ci:
                r["ci_lo"], r["ci_hi"] = block_boot_ci(j.x, j.y, n_boot, rng)
                r["block"] = block_length(n)
            d = j.diff().dropna()
            d = d[np.diff(j.index.to_numpy()) == 1]                       # consecutive years only
            r["n_diff"] = len(d)
            if len(d) >= 4:
                r["rho_diff"] = spearman(d.x, d.y)
                r["p_perm_diff"] = perm_p(d.x, d.y, n_perm, rng)
                if len(d) >= min_n_ci:
                    r["ci_diff_lo"], r["ci_diff_hi"] = block_boot_ci(d.x, d.y, n_boot, rng)
            rows.append(r)
    return pd.DataFrame(rows)


def panel_stats(p: pd.DataFrame, y: str, x: str, n_perm: int, n_boot: int, seed: int) -> dict:
    """Region x year panel (columns region, year, y, x; balanced over regions after dropping NaN years).
    pooled: Spearman over all region-years; CI = bootstrap of whole years; p = permutation of whole years of x.
    within: Spearman of ranks centred per year (spatial pattern only); CI = bootstrap of years; p = permutation of
    x among regions within each year."""
    d = p[["region", "year", y, x]].dropna()
    full = d.groupby("year")["region"].transform("count") == d["region"].nunique()
    d = d[full].sort_values(["year", "region"])
    years = d["year"].unique()
    k = d["region"].nunique()
    out = {"feature": x, "n_region_years": len(d), "n_years": len(years), "n_regions": k,
           "years": f"{years.min()}-{years.max()}" if len(years) else ""}
    if len(years) < 3:
        return out
    Y, X = d[y].to_numpy().reshape(-1, k), d[x].to_numpy().reshape(-1, k)   # years x regions
    rng = np.random.default_rng(seed)
    T = len(years)

    def pooled(Xs, Ys):
        return _rho_rows(Xs.reshape(Xs.shape[0], -1), Ys.reshape(Ys.shape[0], -1))

    def within(Xs, Ys):
        rx, ry = rankdata(Xs, axis=-1), rankdata(Ys, axis=-1)
        rx -= rx.mean(-1, keepdims=True)
        ry -= ry.mean(-1, keepdims=True)
        num, den = (rx * ry).sum((-1, -2)), np.sqrt((rx ** 2).sum((-1, -2)) * (ry ** 2).sum((-1, -2)))
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(den > 0, num / den, np.nan)

    out["rho_pooled"] = float(pooled(X[None], Y[None])[0])
    out["rho_within"] = float(within(X[None], Y[None])[0])
    bi = rng.integers(0, T, size=(n_boot, T))
    for tag, f in (("pooled", pooled), ("within", within)):
        b = f(X[bi], Y[bi])
        b = b[np.isfinite(b)]
        out[f"ci_{tag}_lo"], out[f"ci_{tag}_hi"] = float(np.quantile(b, 0.025)), float(np.quantile(b, 0.975))
    pi = np.argsort(rng.random((n_perm, T)), axis=1)                     # whole years of x permuted
    rp = pooled(X[pi], np.broadcast_to(Y, (n_perm, T, k)))
    out["p_perm_pooled"] = float((1 + np.sum(np.abs(rp) >= abs(out["rho_pooled"]) - 1e-12)) / (n_perm + 1))
    Xw = rng.permuted(np.broadcast_to(X, (n_perm, T, k)).copy(), axis=2)  # regions permuted within year
    rw = within(Xw, np.broadcast_to(Y, (n_perm, T, k)))
    out["p_perm_within"] = float((1 + np.sum(np.abs(rw) >= abs(out["rho_within"]) - 1e-12)) / (n_perm + 1))
    return out


def event_table(series: dict[str, pd.Series], events: list[int], pre: int = 5, after: int = 3) -> pd.DataFrame:
    """Value in the event year and the 1-3 following years against the median of the `pre` years before, plus the
    percentile rank of each year within the whole series. Missing years stay empty."""
    rows = []
    for name, s in series.items():
        s = s.dropna()
        pct = s.rank(pct=True)
        for e in events:
            base = s[(s.index >= e - pre) & (s.index < e)]
            for k in range(0, after + 1):
                y = e + k
                if y not in s.index:
                    continue
                rows.append({"series": name, "event": e, "year": y, "offset": k, "value": s[y],
                             "pre_median": base.median() if len(base) else np.nan, "pre_n": len(base),
                             "ratio_to_pre": s[y] / base.median() if len(base) and base.median() > 0 else np.nan,
                             "percentile_in_series": round(float(pct[y]), 3), "series_n": len(s)})
    return pd.DataFrame(rows)
