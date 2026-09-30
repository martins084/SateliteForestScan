"""Temporal haze test: transient haze is masked, persistent change (clear-cut) is not."""

import numpy as np
import pandas as pd
import xarray as xr

from s2forest.config import HazeConfig
from s2forest.haze import haze_mask, haze_mask_numpy
from s2forest.temporal import time_info

BASELINE = [2023, 2024, 2025]


def _series():
    """4 seasons, ~every 10 days, 3 pixels: 0 = stable forest, 1 = hazy once,
    2 = clear-cut in the monitoring year (B02 up and staying up)."""
    times = []
    for y in (2023, 2024, 2025, 2026):
        times += list(pd.date_range(f"{y}-05-05", f"{y}-09-25", freq="10D"))
    times = pd.DatetimeIndex(times)
    rng = np.random.default_rng(0)
    b02 = 0.02 + rng.normal(0, 0.002, (len(times), 3)).astype("float32")
    t_haze = int(np.flatnonzero(times == pd.Timestamp("2026-07-14"))[0])
    b02[t_haze, 1] += 0.05                                   # transient haze
    t_cut = int(np.flatnonzero(times == pd.Timestamp("2026-06-24"))[0])
    b02[t_cut:, 2] += 0.04                                   # clear-cut, persists
    valid = np.ones_like(b02, dtype=bool)
    return times, b02, valid, t_haze, t_cut


def _run(times, b02, valid, thr=0.02):
    doy, year = time_info(times)
    return haze_mask_numpy(b02, valid, doy, year, BASELINE, thr, 30, 3)


def test_transient_haze_masked_persistent_cut_kept():
    times, b02, valid, t_haze, t_cut = _series()
    masked, unresolved = _run(times, b02, valid)
    assert masked[t_haze, 1]
    assert masked[:, 1].sum() == 1
    assert not masked[:, 2].any()          # clear-cut never masked
    assert not masked[:, 0].any()          # stable forest untouched


def test_last_observation_of_season_is_kept_and_reported():
    times, b02, valid, _, t_cut = _series()
    last = len(times) - 1
    b02[last, 0] += 0.05                   # haze on the very last date
    masked, unresolved = _run(times, b02, valid)
    assert not masked[last, 0]
    assert unresolved[last, 0]
    # the clear-cut pixel's last obs is also elevated and unresolved (kept)
    assert unresolved[last, 2] and not masked[last, 2]


def test_next_valid_obs_skips_cloudy_dates():
    times, b02, valid, t_haze, _ = _series()
    # next date after the haze is SCL-invalid for pixel 1; the one after is clear
    valid[t_haze + 1, 1] = False
    b02[t_haze + 1, 1] = 0.3
    masked, _ = _run(times, b02, valid)
    assert masked[t_haze, 1]


def test_reference_excludes_monitoring_year():
    times, b02, valid, _, _ = _series()
    doy, year = time_info(times)
    # Whole 2026 season elevated for pixel 0 (e.g. canopy change): if 2026 were in
    # the reference it would absorb the change; with baseline years only, every
    # 2026 obs is a candidate and, being persistent, is kept (not masked).
    b02[year == 2026, 0] += 0.04
    masked, unresolved = _run(times, b02, valid)
    assert not masked[year == 2026, 0].any()
    assert unresolved[year == 2026, 0].sum() == 1   # only the season's last obs


def test_xarray_dask_wrapper_matches_numpy():
    times, b02, valid, _, _ = _series()
    b = xr.DataArray(b02[:, :, None], dims=("time", "y", "x"), coords={"time": times})
    v = xr.DataArray(valid[:, :, None], dims=("time", "y", "x"), coords={"time": times})
    m_np, u_np = _run(times, b02, valid)
    m, u = haze_mask(b.chunk({"time": 1}), v.chunk({"time": 1}), BASELINE,
                     HazeConfig(b02_threshold=0.02))
    np.testing.assert_array_equal(m.values[:, :, 0], m_np)
    np.testing.assert_array_equal(u.values[:, :, 0], u_np)


def test_widespread_haze_on_last_date_is_masked_in_open_cube(base_config):
    """Scene-level rule: last obs kept, unless the elevation covers much of the AOI."""
    from datetime import date

    from conftest import FakeSource
    from s2forest.fetch import fetch, open_cube

    base_config.time.monitor_year = 2024
    base_config.time.baseline_years = 1
    base_config.masking.haze.min_ref_obs = 1
    spec = [{"date": date(2023, 9, 1)}, {"date": date(2023, 9, 10)},
            {"date": date(2024, 9, 1)}, {"date": date(2024, 9, 10), "hazy": True}]
    src = FakeSource(spec)
    fetch(base_config, progress=lambda m: None, sources=[src])
    base_config.data.min_valid_fraction = 0.0
    cube = open_cube(base_config)
    assert bool(cube.haze_last_obs_scene.values[-1])
    assert bool(cube.haze.isel(time=-1).all())
    assert not bool(cube.haze.isel(time=slice(0, 3)).any())
