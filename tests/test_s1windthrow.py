"""Offline tests of the Sentinel-1 windthrow module on small synthetic arrays."""

from datetime import date, datetime, timezone
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from affine import Affine

from s1windthrow.config import Config
from s1windthrow.detect import (CLASS_CUT_LIKE, CLASS_WINDTHROW, OrbitDelta, apply_mmu, classify,
                                combine_orbits, polygonize, robust_z)
from s1windthrow.event import Acquisition, select_window
from s1windthrow.load import composite_db, mask_nodata
from s1windthrow.pipeline import acquisition_table

PIXEL_HA = 0.01  # 10 m pixels
MMU_PX = 50      # 0.5 ha


def _delta(rel_orbit, d_vv, d_vh):
    n = np.ones(d_vv.shape, "int16")
    return OrbitDelta(rel_orbit, "ascending", d_vv, d_vh, n, n, ["2026-08-01"], ["2026-09-01"])


def _detect(index, k=3.0):
    stable = np.ones(index.shape, bool)
    z, med, mad, _ = robust_z(index, stable)
    cls, labels = apply_mmu(classify(z, np.isfinite(index), k), MMU_PX)
    return cls, labels, z


def test_nodata_and_nonpositive_become_nan():
    a = np.array([[-32768, 0.0, 0.05], [0.2, -1.0, np.nan]], "float32")
    m = mask_nodata(a, -32768)
    assert np.isnan(m[0, 0]) and np.isnan(m[0, 1]) and np.isnan(m[1, 1]) and np.isnan(m[1, 2])
    assert m[0, 2] == pytest.approx(0.05) and m[1, 0] == pytest.approx(0.2)


def test_composite_is_linear_mean_then_db():
    a, b = np.full((2, 2), 0.1, "float32"), np.full((2, 2), 0.3, "float32")
    b[0, 0] = np.nan
    db, n = composite_db([a, b])
    assert db[1, 1] == pytest.approx(10 * np.log10(0.2), abs=1e-5)   # not mean of dB values
    assert db[0, 0] == pytest.approx(-10.0, abs=1e-5) and n[0, 0] == 1 and n[1, 1] == 2


def test_orbits_averaged_only_where_available():
    full = np.full((3, 3), 1.0, "float32")
    part = np.full((3, 3), 3.0, "float32")
    part[:, 0] = np.nan                       # partially covering orbit
    c = combine_orbits([_delta(58, full, full), _delta(7, part, part)])
    assert c["n_orbits"][0, 0] == 1 and c["n_orbits"][0, 1] == 2
    assert c["d_vv"][0, 0] == pytest.approx(1.0) and c["d_vv"][0, 1] == pytest.approx(2.0)
    assert c["index"][0, 1] == pytest.approx(4.0)


def test_known_increase_detected_as_windthrow():
    rng = np.random.default_rng(0)
    index = rng.normal(0.2, 0.4, (120, 120)).astype("float32")
    index[40:50, 60:70] += 3.0              # 1 ha, ~7.5 sigma
    cls, labels, _ = _detect(index)
    assert (cls == CLASS_WINDTHROW)[40:50, 60:70].mean() > 0.9
    assert np.unique(labels[cls == CLASS_WINDTHROW]).size == 1
    gdf = polygonize(labels, cls, Affine(10, 0, 0, 0, -10, 1200), "EPSG:3059",
                     {"index": index}, PIXEL_HA)
    w = gdf[gdf["class"] == "windthrow"]
    assert len(w) == 1 and w.area_ha.iloc[0] >= 0.9 and w["index"].iloc[0] > 2.5


def test_known_decrease_is_cut_like_not_windthrow():
    rng = np.random.default_rng(1)
    index = rng.normal(0.0, 0.4, (100, 100)).astype("float32")
    index[10:20, 10:20] -= 3.0
    cls, _, _ = _detect(index)
    assert (cls == CLASS_CUT_LIKE)[10:20, 10:20].mean() > 0.9
    assert not (cls == CLASS_WINDTHROW).any()


def test_noise_only_gives_no_candidates():
    rng = np.random.default_rng(2)
    index = rng.normal(0.0, 0.4, (200, 200)).astype("float32")
    cls, _, z = _detect(index)
    assert (np.abs(z) >= 3).any()            # isolated pixels exceed k ...
    assert not cls.any()                     # ... but none survives the 0.5 ha MMU


def test_small_change_below_mmu_removed():
    rng = np.random.default_rng(3)
    index = rng.normal(0.0, 0.4, (100, 100)).astype("float32")
    index[5:10, 5:10] += 4.0                 # 0.25 ha < 0.5 ha
    cls, _, _ = _detect(index)
    assert not cls.any()


def _acq(d, orbit=58, hour=16):
    sc = SimpleNamespace(datetime=datetime(d.year, d.month, d.day, hour, 0, tzinfo=timezone.utc),
                         item=SimpleNamespace(id=f"x{d}"))
    return Acquisition(d, "sentinel-1c", orbit, "ascending", [sc], 1.0)


def test_window_selection_keeps_closest_to_event():
    acqs = [_acq(date(2026, 8, d)) for d in (1, 5, 9, 13, 17, 21)]
    sel, rej = select_window(acqs, date(2026, 8, 1), date(2026, 8, 21), 5, date(2026, 8, 22), 0.0)
    assert [a.date.day for a in sel] == [5, 9, 13, 17, 21]
    assert len(rej) == 1 and rej[0][0].date.day == 1


def test_variant_b_drops_wet_only_if_two_remain():
    cfg = Config.model_validate({
        "run_name": "t", "aoi": "x.geojson",
        "event": {"name": "e", "date": "2026-08-22", "pre_window": ["2026-08-01", "2026-08-21"],
                  "post_window": ["2026-08-24", "2026-09-10"]}})
    pre = [_acq(date(2026, 8, d)) for d in (2, 8, 14)]
    post = [_acq(date(2026, 8, 26)), _acq(date(2026, 9, 1))]
    hours = pd.date_range("2026-07-30", "2026-09-12", freq="h")
    w = pd.DataFrame({"precip_mm": 0.0, "temp_c": 15.0}, index=hours)
    w.loc[pd.Timestamp("2026-08-08 14:00"), "precip_mm"] = 6.0   # wet pre acquisition
    w.loc[pd.Timestamp("2026-09-01 14:00"), "precip_mm"] = 6.0   # wet post acquisition
    t = acquisition_table(cfg, pre + post, w)
    row = lambda d: t[t.date == d].iloc[0]
    assert row(date(2026, 8, 8)).used_A and not row(date(2026, 8, 8)).used_B   # 2 pre remain
    assert row(date(2026, 9, 1)).used_B                                          # only 1 would remain
    assert t.used_A.all() and int(t.used_B.sum()) == 4


# --- v2: normalization, masked spatial averaging, per-class z, injection ------------------
from s1windthrow.injection import disc_offsets, sample_sites  # noqa: E402
from s1windthrow.method import masked_mean_filter, normalize_acquisition, z_by_class  # noqa: E402


def test_normalization_equals_subtracting_stable_median_in_db():
    lin = np.full((4, 4), 0.2, "float32")
    lin[0, 0] = 0.8
    stable = np.ones((4, 4), bool)
    out, med = normalize_acquisition(lin, stable)
    assert med == pytest.approx(0.2)
    assert 10 * np.log10(out[0, 0]) == pytest.approx(10 * np.log10(0.8) - 10 * np.log10(0.2), abs=1e-5)


def test_masked_filter_ignores_pixels_outside_mask():
    lin = np.full((5, 5), 1.0, "float32")
    lin[:, 0] = 100.0                         # e.g. a road / field next to the forest
    mask = np.ones((5, 5), bool)
    mask[:, 0] = False
    out = masked_mean_filter(lin, mask, 3)
    assert np.isnan(out[:, 0]).all()
    assert np.allclose(out[:, 1:], 1.0)        # outside values do not leak in
    assert np.allclose(masked_mean_filter(lin, mask, 1)[:, 1:], 1.0)


def test_masked_filter_reduces_noise():
    rng = np.random.default_rng(4)
    lin = rng.gamma(4.4, 0.1 / 4.4, (200, 200)).astype("float32")   # speckle-like
    mask = np.ones(lin.shape, bool)
    assert masked_mean_filter(lin, mask, 5)[10:-10, 10:-10].std() < lin.std() / 3


def test_z_by_class_uses_own_statistics():
    index = np.zeros((10, 10), "float32")
    dlt = np.full((10, 10), 2, "uint8")
    dlt[:, :5] = 1
    rng = np.random.default_rng(5)
    index[:, :5] = 1.0 + rng.normal(0, 0.1, (10, 5))   # broadleaf: other level and spread
    index[:, 5:] = rng.normal(0, 0.5, (10, 5))
    ok = np.ones(index.shape, bool)
    z, stats = z_by_class(index, ok, ok, dlt, [1, 2])
    assert stats[1]["median"] == pytest.approx(1.0, abs=0.1) and abs(stats[2]["median"]) < 0.3
    assert abs(np.median(z[:, :5])) < 0.2 and abs(np.median(z[:, 5:])) < 0.2


def test_disc_offsets_compact_and_exact():
    off = disc_offsets(100)
    assert len(off) == 100 and len({tuple(o) for o in off}) == 100
    assert np.hypot(off[:, 0], off[:, 1]).max() < 6.5      # ~ radius sqrt(100/pi) = 5.6


def test_sample_sites_respect_class_mask_and_gap():
    dlt = np.full((120, 120), 2, "uint8")
    dlt[:, :60] = 1
    elig = {1: dlt == 1, 2: dlt == 2}
    sites = sample_sites(elig, dlt, 50, 5, 0.9, 5, np.random.default_rng(0))
    assert sum(s.cls == 1 for s in sites) == 5 and sum(s.cls == 2 for s in sites) == 5
    occ = np.zeros(dlt.shape, int)
    for s in sites:
        assert (dlt[s.rows, s.cols] == s.cls).mean() >= 0.9
        occ[s.rows, s.cols] += 1
    assert occ.max() == 1
