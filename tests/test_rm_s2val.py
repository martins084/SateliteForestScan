"""mezasargs_risk stage 5b: s2forest vs LVM damage polygons (synthetic data)."""

from datetime import date
from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from mezasargs_risk import s2val
from mezasargs_risk.config import LvmConfig, ValidationConfig

X0, Y0 = 500_000.0, 300_000.0


def _cfg():
    return LvmConfig(damage=Path("d.zip"), damage_snapshot=date(2025, 4, 27), land_units=Path("l.zip"),
                     validation=ValidationConfig(aoi=Path("a.geojson"), placebo_n=3))


def _damage():
    d = gpd.GeoDataFrame({"year": [2023, 2023, 2023], "subtype": [620, 620, 100]},
                         geometry=[box(X0, Y0, X0 + 100, Y0 + 100), box(X0 + 500, Y0, X0 + 600, Y0 + 100),
                                   box(X0, Y0 + 500, X0 + 100, Y0 + 600)], crs=3059)
    d["ha"] = d.area / 1e4
    d["group"] = d["subtype"].map(s2val.group)
    d["lvm_id"] = range(len(d))
    return d


def _suspects(rows):
    return gpd.GeoDataFrame({"id": range(1, len(rows) + 1), "type": [r[0] for r in rows],
                             "first_detected": [r[1] for r in rows], "onset_before_season": False,
                             "area_ha": 0.25}, geometry=[r[2] for r in rows], crs=3059)


def _runs():
    return {("all", 2022): _suspects([("cut", "2022-07-01", box(X0 + 2000, Y0, X0 + 2050, Y0 + 50))]),
            ("all", 2023): _suspects([("stress", "2023-06-10", box(X0 + 10, Y0 + 510, X0 + 60, Y0 + 560))]),
            ("all", 2024): _suspects([("cut", "2024-05-02", box(X0 + 110, Y0, X0 + 160, Y0 + 50)),   # 10 m away
                                      ("cut", "2024-08-01", box(X0 + 3000, Y0, X0 + 3050, Y0 + 50))])}


def test_detection_precision_lag():
    c, d, runs = _cfg(), _damage(), _runs()
    det = s2val.detection(d, runs, "all", c)
    s = s2val.detection_summary(det).set_index(["group", "size", "offset"])
    assert s.loc[("620", "visi", "r-1..r+1"), "found_share"] == 0.5
    assert s.loc[("620", "visi", 1), "by_cut_n"] == 1 and s.loc[("620", "visi", 0), "found_n"] == 0
    assert s.loc[("100", "visi", 0), "by_stress_n"] == 1
    assert s.loc[("620", "visi", 1), "found_overlap25_n"] == 0       # 10 m away, no overlap
    assert s.loc[("100", "visi", 0), "found_overlap25_share"] == 1.0  # 0.25 ha suspect inside a 1 ha polygon
    p = s2val.precision(d, runs, "all", c).set_index(["run_year", "type"])
    assert p.loc[(2024, "cut"), "in_lvm_damage_any_year"] == 1 and p.loc[(2024, "cut"), "unconfirmed"] == 1
    assert p.loc[(2022, "cut"), "unconfirmed"] == 1 and not p.loc[(2024, "cut"), "register_incomplete"]
    lg = s2val.lag(det)
    assert list(lg["lag_years"]) == [1]


def test_placebo_relocates_inside_aoi(tmp_path):
    c, d, runs = _cfg(), _damage(), _runs()
    path = tmp_path / "mask.tif"
    codes = np.ones((400, 400), dtype="uint8")
    codes[:, :100] = 0                                         # not conifer: no placebo centroids here
    with rasterio.open(path, "w", driver="GTiff", width=400, height=400, count=1, dtype="uint8", crs=3059,
                       transform=from_origin(X0, Y0 + 4000, 10, 10), nodata=255) as f:
        f.write(codes, 1)
    aoi = gpd.GeoDataFrame(geometry=[box(X0, Y0, X0 + 4000, Y0 + 4000)], crs=3059)
    pl = s2val.placebo(d, runs, aoi, path, c)
    assert len(pl) == 3 and {"found_share_r-1..r+1", "cut_in_lvm_damage_any_year"} <= set(pl.columns)
    assert not any(k.startswith("100_") for k in pl.columns)
    c.validation.placebo_groups = ["620", "100"]               # wind placebo: extra columns only
    pw = s2val.placebo(d, runs, aoi, path, c)
    assert {"100_found_share_0", "100_found_overlap25_share_r-1..r+1"} <= set(pw.columns)
    assert pw[pl.columns].equals(pl)
    cmp = s2val.placebo_compare({"cut_in_lvm_damage_any_year": 2.0}, pl)
    assert cmp["p_one_sided"].iloc[0] == 0.25                  # (1 + 0) / (3 + 1)
    moved = s2val.relocate(d, np.array([[X0 + 2000.0, Y0 + 2000.0]]), aoi.union_all(), np.random.default_rng(1))
    assert moved.within(aoi.union_all()).all()
    assert moved.area.values == pytest.approx(d.area.values)
