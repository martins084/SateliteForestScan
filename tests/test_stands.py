import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import box

from s2forest.config import StandsConfig
from s2forest.stands import annotate, composition, stand_id


def _stands():
    return gpd.GeoDataFrame({
        "kadastrs": ["70620070018", "70620070018", "70620070002"],
        "kvart": [229, 229, 237], "nog": [10, 11, 1], "anog": [None, None, None],
        "mt": [4, 4, 3],
        "s10": [3, 1, 4], "g10": [20.0, 25.0, 0.0], "n10": [800, 600, 3000], "a10": [80, 110, 15],
        "s11": [1, 3, None], "g11": [5.0, 5.0, None], "n11": [100, 200, None], "a11": [80, 90, None],
        "s12": [4, None, 3], "g12": [5.0, None, 0.0], "n12": [50, None, 1000], "a12": [60, None, 15],
    }, geometry=[box(0, 0, 100, 100), box(100, 0, 200, 100), box(0, 100, 200, 200)],
        crs="EPSG:3059")


def test_composition_basal_area_and_fallback():
    s = composition(_stands(), StandsConfig())
    assert s.loc[0, "spruce_share"] == pytest.approx(20 / 30, abs=0.01)
    assert s.loc[0, "dom_species"] == "egle" and s.loc[0, "dom_age"] == 80
    assert s.loc[1, "spruce_share"] == pytest.approx(5 / 30, abs=0.01)
    assert s.loc[1, "dom_species"] == "priede"
    # no basal area -> tree counts: spruce 1000 / 4000
    assert s.loc[2, "composition_basis"] == "n"
    assert s.loc[2, "spruce_share"] == pytest.approx(0.25, abs=0.01)
    assert s.loc[0, "forest_type"] == "damaksnis" and s.loc[2, "forest_type"] == "lāns"


def test_stand_id_fallback():
    s = _stands()
    assert stand_id(s.iloc[0], StandsConfig()) == "70620070018-229-10"


def test_annotate_main_stand_weighted_share_and_cover():
    st = composition(_stands(), StandsConfig())
    polys = gpd.GeoDataFrame({"id": [1, 2], "type": ["stress", "stress"]},
                             geometry=[box(50, 0, 130, 100), box(500, 500, 540, 540)], crs="EPSG:3059")
    a = annotate(polys, st, StandsConfig()).set_index("id")
    assert a.loc[1, "stand_kvart_nog"] == "229-10"         # 50 m in stand 10, 30 m in stand 11
    assert a.loc[1, "stand_spruce_share"] == pytest.approx(0.67, abs=0.01)
    w = (0.67 * 50 + 0.17 * 30) / 80
    assert a.loc[1, "spruce_share_weighted"] == pytest.approx(w, abs=0.02)
    assert a.loc[1, "stand_cover_share"] == pytest.approx(1.0)
    assert a.loc[2, "stand_cover_share"] == 0 and a.loc[2, "stand_id"] is None
    assert np.isnan(a.loc[2, "stand_spruce_share"])
