"""Harmonic baseline model and the early-season bias it fixes."""

import numpy as np
import pytest

from s2forest.anomaly import params_from_config, zscores
from s2forest.config import AnomalyConfig
from s2forest.temporal import harmonic_fit, harmonic_predict, harmonic_reference

NAMES = ["ndvi", "ndre", "ndmi", "crswir"]


def _curve(doy):
    w = 2 * np.pi * doy / 365.25
    return 0.9 + 0.12 * np.cos(w) + 0.05 * np.sin(w)


def test_fit_recovers_curve_and_scale():
    rng = np.random.default_rng(0)
    doy = np.tile(np.arange(125, 270, 8), 3)
    y = _curve(doy)[:, None] + rng.normal(0, 0.01, (doy.size, 50))
    coef, scale, n = harmonic_fit(y, doy, 1)
    assert coef[:, 0] == pytest.approx([0.9, 0.12, 0.05], abs=0.03)
    assert np.median(scale) == pytest.approx(0.01, rel=0.3)
    assert (n == doy.size).all()


def test_fit_is_robust_to_outliers_and_handles_missing():
    rng = np.random.default_rng(1)
    doy = np.tile(np.arange(125, 270, 8), 3)
    y = _curve(doy)[:, None] + rng.normal(0, 0.01, (doy.size, 3))
    y[[3, 20, 40], 0] += 0.4                 # residual clouds
    y[::2, 1] = np.nan                       # half the observations missing
    y[:, 2] = np.nan
    y[:4, 2] = 0.9                           # too few observations
    coef, scale, n = harmonic_fit(y, doy, 1, iterations=5)
    pred = harmonic_predict(coef, np.array([130, 200, 260]), 1)
    assert pred[:, 0] == pytest.approx(_curve(np.array([130, 200, 260])), abs=0.02)
    assert pred[:, 1] == pytest.approx(_curve(np.array([130, 200, 260])), abs=0.02)
    assert np.isnan(coef[:, 2]).all() and np.isnan(scale[2])


def test_harmonic_removes_early_season_bias_of_window_median():
    """Smooth seasonal curve, steep in spring; the monitoring year's first observation
    is earlier in the season than most baseline observations -> window median too low."""
    rng = np.random.default_rng(2)
    def season(doy):
        return 0.8 + 0.2 * np.cos(2 * np.pi * (doy - 110) / 365.25)   # CRSWIR-like
    base_doy = np.concatenate([np.arange(140, 271, 10) + o for o in (0, 3, 6)])
    mon_doy = np.array([123, 135, 150, 170, 190])
    doy = np.concatenate([base_doy, mon_doy])
    year = np.concatenate([np.repeat([2023, 2024, 2025], base_doy.size // 3),
                           np.full(mon_doy.size, 2026)])
    vals = np.zeros((4, doy.size, 20, 20), dtype="float32")
    for i, sign in enumerate([-1, -1, -1, 1]):
        vals[i] = (0.6 + sign * (season(doy) - 0.8))[:, None, None]
    vals += rng.normal(0, 0.01, vals.shape).astype("float32")
    ref = year < 2026
    first = np.flatnonzero(year == 2026)[0]

    zs = {}
    for method in ("window", "harmonic"):
        cfg = AnomalyConfig(baseline_method=method, mad_floor={n: 0.02 for n in NAMES})
        p = params_from_config(cfg, NAMES, [2023, 2024, 2025], 2026)
        z, _, _ = zscores(vals, doy, ref, p)
        zs[method] = float(np.median(z[3, first]))
    assert zs["window"] > 1.5            # biased: looks like stress
    assert abs(zs["harmonic"]) < 1.0     # follows the seasonal curve


def test_harmonic_reference_contract():
    doy = np.arange(125, 270, 5)
    vals = np.broadcast_to(_curve(doy)[:, None, None], (doy.size, 2, 2)).astype("float32").copy()
    vals[:, 1, 1] = np.nan
    pred, mad, cnt = harmonic_reference(vals, doy, np.ones(doy.size, bool), min_obs=5)
    assert pred.shape == mad.shape == cnt.shape == vals.shape
    assert np.isnan(pred[:, 1, 1]).all() and np.allclose(pred[:, 0, 0], vals[:, 0, 0], atol=1e-4)
