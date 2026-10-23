"""mezasargs_risk stage 5: EFDA extent check, cross-check, patches, CSP reading (synthetic data)."""

from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from mezasargs_risk.config import BoundaryConfig, EfdaVersion
from mezasargs_risk.describe import patch_stats, read_csp, summarize_patches
from mezasargs_risk.efda import check_extent, crosscheck, grid_offset

X0, Y0 = 5_000_000.0, 3_900_000.0     # EPSG:3035 origin of the synthetic grid


def _write(path: Path, arr: np.ndarray, x0=X0, y0=Y0, nodata=255):
    arr = arr if arr.ndim == 3 else arr[None]
    with rasterio.open(path, "w", driver="GTiff", width=arr.shape[2], height=arr.shape[1],
                       count=arr.shape[0], dtype="uint8", crs="EPSG:3035",
                       transform=from_origin(x0, y0, 30, 30), nodata=nodata) as f:
        f.write(arr)
    return path


def _country(x0=X0, y0=Y0, n=100):
    return gpd.GeoDataFrame({"NUTS_ID": ["XX1"], "NAME_LATN": ["A"]},
                            geometry=[box(x0, y0 - n * 30, x0 + n * 30, y0)], crs=3035)


def _bcfg(lonlat):
    return BoundaryConfig(path=Path("unused"), country="XX", border_buffer_m=0, control_lonlat=lonlat)


def _lonlat(x, y):
    from pyproj import Transformer
    return Transformer.from_crs(3035, 4326, always_xy=True).transform(x, y)


def test_extent_check_passes_and_fails(tmp_path):
    forest = np.zeros((100, 100), "uint8")
    forest[10:90, 10:90] = 1
    f = _write(tmp_path / "forest.tif", forest, nodata=0)
    ctrl = _lonlat(X0 + 1500, Y0 - 1500)
    ok = check_extent(f, _country(), _bcfg(ctrl))
    assert ok.ok and ok.country_area_in_bounds == pytest.approx(1.0)
    # the same raster shifted by 60 km: the "country" is elsewhere (EFDA v3.0 Latvia / Lithuania swap)
    g = _write(tmp_path / "shifted.tif", forest, y0=Y0 - 60_000, nodata=0)
    bad = check_extent(g, _country(), _bcfg(ctrl))
    assert not bad.ok and bad.forest_inside_country == 0 and bad.control_forest_1km == -1


def test_patch_stats_area_and_shape():
    m = np.zeros((20, 20), bool)
    m[2:4, 2:4] = True                     # 2x2 square
    m[10, 0:10] = True                     # 1x10 line
    m[15, 15] = m[16, 16] = True           # diagonal pair = one 8-connected patch
    p = patch_stats(m, 0.09).sort_values("area_ha").reset_index(drop=True)
    assert list((p.area_ha / 0.09).round().astype(int)) == [2, 4, 10]
    si = dict(zip((p.area_ha / 0.09).round().astype(int), p.shape_index))
    assert si[4] == pytest.approx(8 / (4 * 2))                # square: 1.0
    assert si[10] == pytest.approx(22 / (4 * np.sqrt(10)))    # elongated: > 1
    s = summarize_patches(patch_stats(m, 0.1))             # 10 px = 1 ha
    assert s["n_patches"] == 3 and s["share_area_ge1ha"] == pytest.approx(10 / 16)


def test_grid_offset_and_crosscheck(tmp_path):
    years = 3
    a = np.full((years, 50, 50), 255, "uint8")
    a[1, 10:20, 10:20] = 1                 # main: class 1 in year 2 (100 px)
    a[0, 30:35, 30:35] = 3
    b = np.zeros((years, 60, 60), "uint8")  # other grid: 4 rows / 6 cols larger origin, + 0.2 px
    b[1, 14:24, 16:26] = 1                 # same 100 px, same year
    b[2, 14:19, 16:21] = 1                 # extra 25 px one year later
    ma = _write(tmp_path / "a.tif", a)
    mb = _write(tmp_path / "b.tif", b, x0=X0 - 6 * 30 - 6, y0=Y0 + 4 * 30 + 6, nodata=255)
    with rasterio.open(ma) as s1, rasterio.open(mb) as s2:
        ro, co, resid = grid_offset(s1, s2)
    assert (ro, co) == (4, 6) and resid == pytest.approx(np.hypot(6, 6), abs=0.1)
    ver = lambda p: EfdaVersion(version=p.stem, doi="-", archive="-", dir=p.parent, agent=p.name,
                                agent_aggregated=p.name, forest=p.name)
    cc = crosscheck(ver(ma), ver(mb), np.ones((50, 50), bool)).set_index("year")
    assert cc.loc[1986, "c1_main_px"] == 100 and cc.loc[1986, "c1_jaccard"] == 1.0
    assert cc.loc[1987, "c1_other_px"] == 25 and cc.loc[1987, "c1_main_px"] == 0
    assert cc.loc[1985, "any_main_px"] == 25 and cc.loc[1985, "any_other_px"] == 0


def test_read_csp_long(tmp_path):
    f = tmp_path / "t.csv"
    f.write_text('"Meža īpašuma forma","Meža bojājumi","Apjoms, tūkst. m³ 2013","Apjoms, tūkst. m³ 2014"\n'
                 '"Pavisam","Vējgāzes, snieglauzes",592.9,439.6\n', encoding="utf-8-sig")
    d = read_csp(f, 2)
    assert list(d["year"]) == [2013, 2014] and list(d["value"]) == [592.9, 439.6]
    assert d["indicator"].iloc[0] == "Apjoms, tūkst. m³"
