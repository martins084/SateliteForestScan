"""Checks of catalogue assumptions against the live services.

Deselected by default; run with `pytest -m network`. If these fail, a provider
has changed its metadata and the harmonization rules must be re-verified.
"""

from datetime import date

import pytest

from s2forest.sources import get_source

BBOX = (25.83, 56.65, 25.91, 56.70)  # Kalsnava test AOI

pytestmark = pytest.mark.network


def test_earthsearch_c1_declares_offset_for_all_years():
    src = get_source("earthsearch", "sentinel-2-c1-l2a")
    for year in (2019, 2024):
        scenes = src.search(BBOX, date(year, 6, 1), date(year, 6, 30), 100)
        assert scenes, f"no c1 data for {year}"
        assert all(s.offset == -0.1 for s in scenes)
        assert all(s.baseline_num >= 5.0 for s in scenes)


def test_earthsearch_c1_gap_2022_is_still_present():
    """Documents the known gap; if it starts failing, the gap was filled upstream."""
    src = get_source("earthsearch", "sentinel-2-c1-l2a")
    assert src.search(BBOX, date(2022, 6, 1), date(2022, 8, 31), 100) == []


def test_earthsearch_legacy_applied_offset_not_reapplied():
    src = get_source("earthsearch", "sentinel-2-l2a")
    scenes = src.search(BBOX, date(2022, 6, 1), date(2022, 6, 30), 100)
    applied = [s for s in scenes if s.item.properties.get("earthsearch:boa_offset_applied") is True]
    assert applied and all(s.offset == 0.0 for s in applied)


def test_planetary_offset_from_baseline():
    src = get_source("planetary", "sentinel-2-l2a")
    scenes = src.search(BBOX, date(2022, 6, 1), date(2022, 6, 30), 100)
    assert scenes
    for s in scenes:
        assert s.offset == (-0.1 if s.baseline_num >= 4.0 else 0.0)


def test_overpass_roads_in_test_aoi(tmp_path):
    from odc.geo.geobox import GeoBox

    from s2forest.config import LinearFeaturesConfig
    from s2forest.linear import fetch_osm_lines

    gb = GeoBox.from_bbox(BBOX, crs="EPSG:4326", resolution=0.001)
    g = fetch_osm_lines(gb, LinearFeaturesConfig(), tmp_path)
    assert len(g) > 10 and set(g["kind"]) == {"road"}
