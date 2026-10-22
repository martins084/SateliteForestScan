"""Offline tests of the S1 early-signal functions on synthetic time series."""

import numpy as np
import pandas as pd
import pytest

from s1windthrow.earlysignal import (baseline_level, bin_series, early_signal, group_median_ci,
                                     null_group_band, smooth_trailing, unit_values, Unit)


def _series(drop_start=None, drop_db=1.0, noise=0.3, seed=0):
    rng = np.random.default_rng(seed)
    t = pd.date_range("2023-01-01", "2026-09-30", freq="3D")
    v = rng.normal(0.0, noise, len(t))
    if drop_start is not None:
        v[t >= pd.Timestamp(drop_start)] -= drop_db
    return t, v


def test_trailing_smoother_does_not_look_ahead():
    t = pd.date_range("2025-01-01", periods=40, freq="3D")
    v = np.zeros(40)
    v[20:] = -2.0                               # step at t[20]
    s = smooth_trailing(t, v, 30)
    assert np.allclose(s[:20][~np.isnan(s[:20])], 0.0)   # nothing before the step
    assert s[30] == pytest.approx(-2.0)


def test_known_drop_gives_signal_and_lead():
    t_first = pd.Timestamp("2025-06-01")
    t, v = _series(drop_start="2025-01-15", drop_db=1.0, noise=0.2)
    base, n = baseline_level(t, v, t_first)
    assert n > 50 and abs(base) < 0.15
    sig = early_signal(t, smooth_trailing(t, v), base, t_first)
    d = sig["signal_date"]
    assert d is not None and pd.Timestamp("2025-01-15") <= d <= pd.Timestamp("2025-03-15")
    assert sig["max_sustained_drop"] > 0.7


def test_noise_only_gives_no_signal():
    hits = 0
    for seed in range(20):
        t, v = _series(noise=0.3, seed=seed)
        t_first = pd.Timestamp("2025-06-01")
        base, _ = baseline_level(t, v, t_first)
        hits += early_signal(t, smooth_trailing(t, v), base, t_first)["signal_date"] is not None
    assert hits <= 1


def test_short_dip_is_not_persistent():
    t, v = _series(noise=0.05)
    v[(t >= "2025-02-01") & (t < "2025-03-01")] -= 2.0    # 28-day dip only
    t_first = pd.Timestamp("2025-06-01")
    base, _ = baseline_level(t, v, t_first)
    assert early_signal(t, smooth_trailing(t, v), base, t_first)["signal_date"] is None


def test_signal_after_t_first_is_ignored():
    t, v = _series(drop_start="2025-07-01", noise=0.05)
    t_first = pd.Timestamp("2025-06-01")
    base, _ = baseline_level(t, v, t_first)
    assert early_signal(t, smooth_trailing(t, v), base, t_first)["signal_date"] is None


def test_binning_and_bootstrap_shapes():
    edges = np.arange(-540, 210, 30)
    rel = np.arange(-600, 200, 5)
    b = bin_series(rel, np.ones(len(rel)), edges)
    assert len(b) == len(edges) - 1 and np.allclose(b, 1.0)
    rng = np.random.default_rng(0)
    mat = rng.normal(0, 1, (13, len(edges) - 1))
    m, lo, hi = group_median_ci(mat, 500, rng)
    assert (lo <= m + 1e-9).all() and (m <= hi + 1e-9).all()
    pm, plo, phi = null_group_band(rng.normal(0, 1, (50, 24)), 13, 500, rng)
    assert (plo < phi).all()


def test_unit_values_k0_and_ratio():
    vv = np.full((5, 5), 0.1)
    vh = np.full((5, 5), 0.025)
    u = Unit("x", "target", np.array([1, 2, 3]), np.array([1, 2, 3]))
    out = unit_values(vv, vh, u, 0.5)
    assert out["vv"] == pytest.approx(-10.0)
    assert out["k0"] == pytest.approx(10 * np.log10(0.125))
    assert out["vh_minus_vv"] == pytest.approx(10 * np.log10(0.25))
    vv[1, 1] = vv[2, 2] = np.nan
    assert np.isnan(unit_values(vv, vh, u, 0.5)["vv"])        # < 50 % valid
