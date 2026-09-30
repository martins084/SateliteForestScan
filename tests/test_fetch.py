from datetime import date

import numpy as np
import pytest

from s2forest.fetch import deduplicate, fetch, open_cube
from s2forest.sources import REFLECTANCE_BANDS

from conftest import FakeSource


def _scenes(src):
    return src.search(None, date(2000, 1, 1), date(2100, 1, 1), 100)


def test_deduplicate_prefers_first_source_and_highest_baseline():
    primary = FakeSource([{"date": date(2024, 6, 1)}], name="primary")
    secondary = FakeSource([
        {"date": date(2024, 6, 1)},                                   # duplicate of primary
        {"date": date(2022, 6, 1), "baseline": "04.00"},
        {"date": date(2022, 6, 1), "baseline": "05.10"},              # reprocessed, preferred
        {"date": date(2022, 6, 3), "tile": "T1"},
        {"date": date(2022, 6, 3), "tile": "T2"},                     # same overpass, two tiles
    ], name="secondary")
    acqs = {a.key: a for a in deduplicate([_scenes(primary), _scenes(secondary)])}
    assert set(acqs) == {"20240601_S2a", "20220601_S2a", "20220603_S2a"}
    assert acqs["20240601_S2a"].first.source == "primary"
    assert [s.baseline for s in acqs["20220601_S2a"].scenes] == ["05.10"]
    assert [s.tile for s in acqs["20220603_S2a"].scenes] == ["T1", "T2"]


def test_fetch_caches_filters_and_harmonizes(base_config):
    spec = [
        {"date": date(2023, 6, 10)},                                   # clear, baseline 05
        {"date": date(2023, 7, 10), "offset": 0.0, "baseline": "03.01"},  # old baseline
        {"date": date(2024, 6, 10), "cloudy": 0.8},                    # rejected: 20 % valid
        {"date": date(2024, 7, 1), "cloudy": 0.3},                     # accepted: 70 % valid
        {"date": date(2024, 8, 1), "tile": "T1", "half": "left"},      # AOI split over 2 tiles
        {"date": date(2024, 8, 1), "tile": "T2", "half": "right"},
        {"date": date(2024, 11, 1)},                                   # outside season
    ]
    src = FakeSource(spec)
    table = fetch(base_config, progress=lambda m: None, sources=[src])
    status = dict(zip(table["key"], table["status"]))
    assert status == {"20230610_S2a": "accepted", "20230710_S2a": "accepted",
                      "20240610_S2a": "rejected", "20240701_S2a": "accepted",
                      "20240801_S2a": "accepted"}

    cube = open_cube(base_config)
    assert cube.sizes["time"] == 4
    assert str(cube.rio.crs) == "EPSG:3059"
    assert float(cube.x.diff("x")[0]) == 10.0
    for b in REFLECTANCE_BANDS:
        vals = cube[b].values
        np.testing.assert_allclose(np.nanmedian(vals, axis=(1, 2)), FakeSource.true_reflectance(b), atol=1e-4)
    # cloudy rows masked, fused two-tile acquisition fully valid
    vf = dict(zip(cube.acq_key.values, cube.valid_fraction.values))
    assert vf["20240701_S2a"] == pytest.approx(0.7, abs=0.05)
    assert vf["20240801_S2a"] == pytest.approx(1.0)

    # second run: everything from cache, no loads
    calls = src.load_calls
    fetch(base_config, progress=lambda m: None, sources=[src])
    assert src.load_calls == calls


def test_lowering_threshold_refetches_rejected(base_config):
    src = FakeSource([{"date": date(2024, 6, 10), "cloudy": 0.5}])
    t1 = fetch(base_config, progress=lambda m: None, sources=[src])
    assert list(t1["status"]) == ["rejected"]
    base_config.data.min_valid_fraction = 0.4
    t2 = fetch(base_config, progress=lambda m: None, sources=[src])
    assert list(t2["status"]) == ["accepted"]
