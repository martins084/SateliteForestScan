"""Anomaly detection on a synthetic 4-year cube with known events."""

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from s2forest.anomaly import (FEATURES, apply_baseline_exclusion, detect_block,
                              params_from_config, persistent_runs, regional_offsets,
                              run_detection)
from s2forest.config import AnomalyConfig
from s2forest.temporal import time_info
from s2forest.vectorize import polygonize

NAMES = ["ndvi", "ndre", "ndmi", "crswir"]
HEALTHY = np.array([0.85, 0.45, 0.35, 0.55], dtype="float32")
NOISE = np.array([0.01, 0.01, 0.01, 0.01], dtype="float32")


def _times():
    t = []
    for y in (2023, 2024, 2025, 2026):
        t += list(pd.date_range(f"{y}-05-05", f"{y}-09-25", freq="8D"))
    return pd.DatetimeIndex(t)


def _cube(ny=20, nx=20, seed=1):
    times = _times()
    rng = np.random.default_rng(seed)
    v = HEALTHY[:, None, None, None] + NOISE[:, None, None, None] * rng.normal(
        size=(4, len(times), ny, nx)).astype("float32")
    return times, v.astype("float32")


def _params(**kw):
    # Logic tests use a fixed small floor matching the synthetic noise (0.01),
    # independent of the calibrated defaults.
    kw.setdefault("mad_floor", {n: 0.02 for n in NAMES})
    cfg = AnomalyConfig(**kw)
    return params_from_config(cfg, NAMES, [2023, 2024, 2025], 2026)


def _t(times, day):
    return int(np.flatnonzero(times >= pd.Timestamp(day))[0])


def _feat(f, name, y, x):
    return f[FEATURES.index(name), y, x]


def test_persistent_runs_skip_invalid_and_need_n():
    anom = np.array([0, 1, 0, 1, 0, 1, 1], bool)[:, None]
    valid = np.array([1, 1, 1, 1, 0, 1, 1], bool)[:, None]
    # t=3 anomalous, t=4 cloudy (skipped), t=5 anomalous -> run of 2 starting at t=3
    flag, first, longest = persistent_runs(anom, valid, 2)
    assert flag[0] and first[0] == 3 and longest[0] == 3   # t=3, 5, 6
    flag3, _, _ = persistent_runs(anom, valid, 5)
    assert not flag3[0]


def test_stress_cut_single_outlier_and_baseline_disturbance():
    times, v = _cube()
    doy, year = time_info(times)
    p = _params()
    ts = _t(times, "2026-07-01")
    # (2, 2) stress: CRSWIR up, NDMI down, NDVI slightly down, from July 2026
    v[3, ts:, 2, 2] += 0.08
    v[2, ts:, 2, 2] -= 0.06
    v[0, ts:, 2, 2] -= 0.03
    # (5, 5) clear-cut in July 2026
    v[0, ts:, 5, 5] = 0.35
    v[1, ts:, 5, 5] = 0.15
    v[2, ts:, 5, 5] = 0.0
    v[3, ts:, 5, 5] = 0.95
    # (8, 8) single-date outlier (e.g. residual haze): must not be flagged
    v[3, ts, 8, 8] += 0.2
    v[2, ts, 8, 8] -= 0.2
    # (11, 11) stress already in 2024 (baseline) and continuing: excluded
    tb = _t(times, "2024-06-15")
    v[3, tb:, 11, 11] += 0.08
    v[2, tb:, 11, 11] -= 0.06
    # clouds: (2, 2) invalid on the date after onset -> run continues
    v[:, ts + 1, 2, 2] = np.nan

    f, z, d = detect_block(v, doy, year, p)
    assert _feat(f, "flag", 2, 2) == 1 and _feat(f, "is_cut", 2, 2) == 0
    assert times[year == 2026][int(_feat(f, "first_idx", 2, 2))] == times[ts]
    assert _feat(f, "flag", 5, 5) == 1 and _feat(f, "is_cut", 5, 5) == 1
    assert _feat(f, "flag", 8, 8) == 0
    assert _feat(f, "baseline_disturbed", 11, 11) == 1
    # healthy background: no false alarms (the baseline-disturbed pixel is still
    # flagged at this stage; the spatial exclusion step removes it, see below)
    flags = np.nan_to_num(f[FEATURES.index("flag")])
    assert flags.sum() == 3 and _feat(f, "flag", 11, 11) == 1
    assert d.shape == z.shape and d[3, -1, 2, 2] == pytest.approx(0.08, abs=0.03)


def test_needs_confirming_index():
    times, v = _cube()
    doy, year = time_info(times)
    ts = _t(times, "2026-07-01")
    v[3, ts:, 3, 3] += 0.08          # CRSWIR alone
    f, _, _ = detect_block(v, doy, year, _params())
    assert _feat(f, "flag", 3, 3) == 0
    f, _, _ = detect_block(v, doy, year, _params(min_confirming=0))
    assert _feat(f, "flag", 3, 3) == 1


def test_regional_offsets_remove_common_drought_signal():
    times, v = _cube(seed=3)
    doy, year = time_info(times)
    p = _params()
    # regional drought in 2026: every pixel shifts towards "stress"
    mon = year == 2026
    v[3][mon] += 0.06
    v[2][mon] -= 0.05
    f_raw, _, _ = detect_block(v, doy, year, p)
    assert np.nan_to_num(f_raw[FEATURES.index("flag")]).mean() > 0.5

    forest = np.ones(v.shape[2:], bool)
    off, counts = regional_offsets(v, doy, year, forest, p, min_pixels=10)
    assert off[3][mon].mean() == pytest.approx(0.06, abs=0.01)
    f_norm, _, _ = detect_block(v - off[:, :, None, None], doy, year, p)
    assert np.nan_to_num(f_norm[FEATURES.index("flag")]).sum() == 0


def test_run_detection_and_polygonize():
    times, v = _cube(ny=40, nx=40)
    ts = _t(times, "2026-07-01")
    v[3, ts:, 10:16, 10:16] += 0.08    # 36 px = 0.36 ha stress patch
    v[2, ts:, 10:16, 10:16] -= 0.06
    v[3, ts:, 30:32, 30:32] += 0.08    # 4 px = 0.04 ha -> below min area
    v[2, ts:, 30:32, 30:32] -= 0.06
    x = 614000 + 10 * np.arange(40) + 5
    y = 284000 - 10 * np.arange(40) - 5
    da = xr.DataArray(v, dims=("index", "time", "y", "x"),
                      coords={"index": NAMES, "time": times, "y": y, "x": x})
    p = _params()
    feats, z, delta = run_detection(da.chunk({"y": 16, "x": 16}), p, chunk=16)
    gdf = polygonize(feats, z, delta, "EPSG:3059", 0.1, p.k, p.persistence, p.min_obs)
    assert len(gdf) == 1
    r = gdf.iloc[0]
    assert r["area_ha"] == pytest.approx(0.36)
    assert r["type"] == "stress"
    assert r["first_detected"] == times[ts].strftime("%Y-%m-%d")
    assert r["delta_crswir"] == pytest.approx(0.08, abs=0.02)
    assert 0 < r["confidence"] <= 1
    assert gdf.crs.to_epsg() == 3059


def test_baseline_exclusion_keeps_isolated_pixels_and_excludes_patches():
    f = np.zeros((len(FEATURES), 10, 10), dtype="float32")
    f[FEATURES.index("flag")] = 1
    bd = np.zeros((10, 10))
    bd[1, 1] = 1                 # isolated noisy pixel
    bd[5:8, 5:8] = 1             # 9-pixel patch
    f[FEATURES.index("baseline_disturbed")] = bd
    feats = xr.Dataset({n: (("y", "x"), f[i]) for i, n in enumerate(FEATURES)})
    out = apply_baseline_exclusion(feats, min_pixels=5)
    assert out["flag"].values[1, 1] == 1
    assert np.isnan(out["flag"].values[6, 6])
    assert out["baseline_disturbed"].values.sum() == 9


def test_winter_clearcut_with_regrowth_is_cut_via_ndmi():
    """Kalsnava pattern: NDVI stays ~0.6 (ground vegetation) but NDMI drops sharply."""
    times, v = _cube()
    doy, year = time_info(times)
    mon = year == 2026
    v[0, mon, 4, 4] = 0.62          # NDVI drop 0.23, above cut_ndvi_max 0.5
    v[1, mon, 4, 4] = 0.30
    v[2, mon, 4, 4] = 0.13          # NDMI drop 0.22 >= 0.15
    v[3, mon, 4, 4] = 0.85
    f, _, _ = detect_block(v, doy, year, _params())
    assert _feat(f, "flag", 4, 4) == 1 and _feat(f, "is_cut", 4, 4) == 1
