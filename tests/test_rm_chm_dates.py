"""Stage 7c: CHMv2 imagery dates per cell and the leakage rule (chm_dates.py)."""
import numpy as np
import pytest

from mezasargs_risk import chm_dates as CD
from mezasargs_risk import features as F


def _poly(x0, y0, x1, y1, date):
    return {"type": "Feature", "properties": {"acq_date": date},
            "geometry": {"type": "Polygon", "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}}


def test_tile_index_matches_quadkey_and_bounds_contain_point():
    lon, lat = np.array([25.85, 21.05, 28.2]), np.array([56.69, 56.5, 57.9])
    tx, ty = CD.tile_xy(lon, lat)
    for k in range(3):
        qk = CD.quadkey_of(int(tx[k]), int(ty[k]))
        assert qk == F.quadkey(float(lon[k]), float(lat[k]), 10)
        lon0, lat0, lon1, lat1 = CD.tile_bounds(int(tx[k]), int(ty[k]))
        assert lon0 <= lon[k] < lon1 and lat0 < lat[k] <= lat1
        assert lon1 - lon0 == pytest.approx(360 / 1024)


def test_rasterize_latest_date_wins_and_gaps_are_zero():
    b = (24.0, 57.0, 24.4, 57.2)
    feats = [_poly(24.0, 57.0, 24.2, 57.2, "2021-07-01"), _poly(24.1, 57.0, 24.3, 57.2, "2018-05-30")]
    r, info = CD.rasterize_dates(feats, b, n=400)
    lon = np.array([24.05, 24.15, 24.25, 24.35])
    lat = np.full(4, 57.1)
    assert CD.sample(r, b, lon, lat).tolist() == [20210701, 20210701, 20180530, 0]   # overlap -> latest; east strip empty
    assert info["polygons"] == 2 and info["dates"] == [20180530, 20210701]
    assert info["share_no_date"] == pytest.approx(0.25, abs=0.01)
    assert info["share_overlap"] == pytest.approx(0.25, abs=0.01)
    # north is up: a polygon in the northern half is found at northern latitudes only
    r2, _ = CD.rasterize_dates([_poly(24.0, 57.1, 24.4, 57.2, "2019-09-09")], b, n=400)
    assert CD.sample(r2, b, np.array([24.2, 24.2]), np.array([57.15, 57.05])).tolist() == [20190909, 0]


def test_empty_tile_and_bad_date():
    r, info = CD.rasterize_dates([], (24.0, 57.0, 24.4, 57.2), n=16)
    assert not r.any() and info["share_no_date"] == 1.0
    with pytest.raises(ValueError):
        CD.to_int("09/09/2019")
    with pytest.raises(ValueError):
        CD.to_int("2019-13-01")


def test_leakage_rule_needs_known_date_in_an_earlier_year():
    d_max = np.array([20181231, 20190101, 20200615, 0, 20230801])
    y = np.array([2019, 2019, 2021, 2024, 2023])
    # 2018 image for 2019: ok; 2019 image for 2019: not; 2020 for 2021: ok; unknown: not; same year: not
    assert CD.allowed(d_max, y).tolist() == [True, False, True, False, False]
    assert CD.year(d_max).tolist() == [2018, 2019, 2020, 0, 2023]
