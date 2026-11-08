"""Stage 6a: feature logic and leakage tests (synthetic grids, no files)."""

import numpy as np
import pandas as pd
import pytest

from mezasargs_risk import features as F

SHAPE = (60, 60)


def _ctx(seed=0):
    rng = np.random.default_rng(seed)
    years = range(2005, 2025)
    lvm = {y: (rng.random(SHAPE) < 0.01).astype(np.float32) for y in years}
    efda = {y: np.where(rng.random(SHAPE) < 0.02, rng.choice([1, 3], SHAPE), 255).astype(np.uint8) for y in years}
    cells = np.array([0, 1])
    clim = pd.DataFrame([{"year": y, "clim_cell": c, "cwb_z": rng.normal(), "tsum_F1": rng.normal(2, .2),
                          "tsum_F2": rng.normal(1, .2), "swarming_doy": rng.integers(90, 130),
                          "n_filial": 2, "n_filial_inca": 1} for y in years for c in cells]).set_index(["year", "clim_cell"])
    cc = np.zeros(SHAPE, np.int64)
    cc[:, 30:] = 1
    return F.Ctx(shape=SHAPE, lvm620=lvm, efda=efda, climate=clim, clim_cell=cc)


def _same(a, b):
    assert a.keys() == b.keys()
    for k in a:
        assert np.array_equal(a[k], b[k], equal_nan=True), k


def test_layer_guard_raises_for_year_t_or_later():
    ctx = _ctx()
    ctx.t = 2020
    with pytest.raises(F.LeakageError):
        ctx.layer("lvm620", 2020, "x")
    with pytest.raises(F.LeakageError):
        ctx.clim("cwb_z", 2021, "x")
    ctx.layer("lvm620", 2019, "x")


def test_features_ignore_year_t_and_later_inputs():
    a = _ctx()
    fa = F.year_features(a, 2020)
    used = a.used
    b = _ctx()
    for y in (2020, 2021, 2022, 2023, 2024):            # change everything from t on
        b.lvm620[y] = np.ones(SHAPE, np.float32)
        b.efda[y] = np.full(SHAPE, 3, np.uint8)
    b.climate.loc[(2020, slice(None)), :] = 99.0
    fb = F.year_features(b, 2020)
    _same(fa, fb)
    assert max(max(v) for v in used.values()) <= 2019
    assert used["p620_dist_t1"] == {2019} and used["p620_dist_t23"] == {2017, 2018}
    assert used["cwb_z_t12"] == {2018, 2019} and used["tsum_F1_t1"] == {2019}


def test_pressure_is_not_the_label_and_t23_ignores_t1():
    ctx = _ctx()
    ctx.lvm620[2020] = np.zeros(SHAPE, np.float32)
    ctx.lvm620[2020][10, 10] = 1.0                       # label cell in year t
    f0 = F.year_features(ctx, 2020)
    ctx.lvm620[2020][10, 10] = 0.0
    f1 = F.year_features(ctx, 2020)
    _same(f0, f1)                                       # features do not see the year-t polygon of the cell
    ctx.lvm620[2019] = np.zeros(SHAPE, np.float32)
    ctx.lvm620[2019][10, 10] = 1.0                      # previous-year polygon in the same cell: allowed, t1 only
    f2 = F.year_features(ctx, 2020)
    assert f2["p620_dist_t1"][10, 10] == 0 and f2["p620_ha500_t1"][10, 10] == pytest.approx(F.CELL_HA)
    for k in ("p620_dist_t23", "p620_ha500_t23", "p620_ha2k_t23"):   # L3 sensitivity group: t-2..t-3 only
        assert np.array_equal(f2[k], f1[k]), k


def test_distance_area_and_south_edge():
    m = np.zeros((21, 21), bool)
    m[10, 10] = True
    d = F.dist_to(m)
    assert d[10, 10] == 0 and d[10, 13] == pytest.approx(90) and F.dist_to(np.zeros((3, 3), bool))[0, 0] == F.DIST_CAP
    a = F.area_within(m.astype(np.float32), 100)
    assert a[10, 10] == pytest.approx(F.CELL_HA) and a[10, 13] == pytest.approx(F.CELL_HA) and a[10, 15] < 1e-6
    cut = np.zeros((9, 9), bool)
    cut[6:, :] = True                                    # cut in the south
    e = F.south_edge(cut)
    assert e[5, 4] == 1 and e[3, 4] == 0 and e[6, 4] == 0  # 30 m north of the cut: open to the south
    cut = np.zeros((9, 9), bool)
    cut[:3, :] = True                                    # cut in the north
    assert F.south_edge(cut)[3, 4] == 0


def test_chm_aggregate_and_quadkey():
    x = np.zeros((20, 20), np.float32)
    x[:10, :10] = np.arange(100).reshape(10, 10)
    x[10:, 10:] = np.nan
    a = F.chm_aggregate(x)
    assert a["chm_mean"][0, 0] == pytest.approx(49.5) and a["chm_p90"][0, 0] == pytest.approx(89.1)
    assert a["chm_gt5"][0, 0] == pytest.approx(0.94) and np.isnan(a["chm_mean"][1, 1])
    assert F.quadkey(25.8688, 56.6771, 10) == "1201223023"


def test_describe_counts_and_smd():
    t = pd.DataFrame({"year": [1, 1, 1, 2, 2, 2], "label": [1, 0, 0, 1, 1, 0], "in_set": [1, 1, 1, 1, 1, 0],
                      "x": [5.0, 1.0, 3.0, 6.0, 4.0, 9.0]})
    py, dist = F.describe(t, ["x"])
    assert list(py["positives"]) == [1, 2] and list(py["cells"]) == [3, 2]
    r = dist.iloc[0]
    assert r["n_pos"] == 3 and r["n_other"] == 2 and r["pos_median"] == 5 and r["other_median"] == 2


def test_picea_uses_latest_period_ending_before_t():
    ctx = _ctx()
    ctx.picea = {e: np.full(SHAPE, float(e - 2000), np.float32) for e in (2010, 2014, 2018, 2020)}
    ctx.picea500 = {e: v + 0.5 for e, v in ctx.picea.items()}
    f = F.year_features(ctx, 2015)                       # t-1 = 2014 -> period 2010-2014
    assert f["picea_p"][0, 0] == 14 and f["picea_p500"][0, 0] == 14.5 and ctx.used["picea_p"] == {2014}
    f = F.year_features(ctx, 2020)                       # 2018-2020 ends in 2020 = t -> not allowed; 2014-2018 used
    assert f["picea_p"][0, 0] == 18 and max(max(v) for v in ctx.used.values()) <= 2019
    f = F.year_features(ctx, 2011)                       # no period ends <= 2010? 2006-2010 ends 2010 -> allowed
    assert f["picea_p"][0, 0] == 10
    f = F.year_features(ctx, 2010)                       # nothing ends <= 2009
    assert np.isnan(f["picea_p"]).all()


def test_mean_within_ignores_nan():
    x = np.full((21, 21), np.nan, np.float32)
    x[10, 10], x[10, 11] = 10.0, 20.0
    m = F.mean_within(x, 100)
    assert m[10, 10] == pytest.approx(15.0, abs=1e-3) and np.isnan(m[0, 0])


def test_boundless_edge_cells_are_nodata_and_outside_the_set(tmp_path):
    import rasterio
    from rasterio.transform import from_origin
    from rasterio.windows import Window

    from mezasargs_risk import features_io as FIO

    prof = {"driver": "GTiff", "width": 10, "height": 10, "count": 1, "dtype": "uint8", "crs": "EPSG:3035",
            "transform": from_origin(0, 300, 30, 30)}
    with rasterio.open(tmp_path / "forest.tif", "w", nodata=0, **prof) as d:
        d.write(np.ones((1, 10, 10), np.uint8))           # all forest inside the raster
    with rasterio.open(tmp_path / "agent.tif", "w", nodata=255, **prof) as d:
        d.write(np.full((1, 10, 10), 3, np.uint8))        # harvest everywhere inside
    w = Window(6, -2, 8, 8)                                # crosses the right and top edges
    with rasterio.open(tmp_path / "forest.tif") as fm, rasterio.open(tmp_path / "agent.tif") as ag:
        forest = FIO.read_boundless(fm, 1, w) == 1
        agent = FIO.read_boundless(ag, 1, w)
        valid = FIO.inside_raster(w, fm.height, fm.width)
    assert forest.shape == agent.shape == valid.shape == (8, 8)
    assert valid.sum() == 6 * 4 and (forest == valid).all()          # outside: not forest, not valid
    assert (agent[~valid] == 255).all() and (agent[valid] == 3).all()  # outside: nodata, not "no disturbance" data
