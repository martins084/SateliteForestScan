import geopandas as gpd
import numpy as np
import pytest
from odc.geo.geobox import GeoBox
from shapely.geometry import LineString, box

from s2forest.config import LinearFeaturesConfig
from s2forest.linear import buffer_mask, elongation, overpass_query, parse_overpass
from s2forest.pipeline import add_linear_attributes

PAYLOAD = {"elements": [
    {"type": "way", "id": 1, "tags": {"highway": "track"},
     "geometry": [{"lat": 56.67, "lon": 25.85}, {"lat": 56.68, "lon": 25.86}]},
    {"type": "way", "id": 2, "tags": {"waterway": "ditch"},
     "geometry": [{"lat": 56.67, "lon": 25.87}, {"lat": 56.671, "lon": 25.872}]},
    {"type": "way", "id": 3, "tags": {"highway": "track"}, "geometry": [{"lat": 56.6, "lon": 25.8}]},
    {"type": "node", "id": 4},
]}


def test_parse_overpass():
    g = parse_overpass(PAYLOAD)
    assert list(g["osm_id"]) == [1, 2] and list(g["kind"]) == ["road", "waterway"]
    assert g.crs.to_epsg() == 4326
    assert parse_overpass({"elements": []}).empty


def test_query_includes_optional_layers():
    cfg = LinearFeaturesConfig()
    q = overpass_query((25.8, 56.6, 25.9, 56.7), cfg)
    assert '"highway"' in q and "track" in q and "waterway" not in q
    cfg.include_waterways = True
    cfg.include_power_lines = True
    q = overpass_query((25.8, 56.6, 25.9, 56.7), cfg)
    assert "ditch" in q and '"power"="line"' in q


def test_buffer_mask_width():
    gb = GeoBox.from_bbox((0, 0, 400, 400), crs="EPSG:3059", resolution=10)
    line = gpd.GeoDataFrame(geometry=[LineString([(0, 200), (400, 200)])], crs="EPSG:3059")
    m = buffer_mask(line, gb, 20)
    col = m[:, 20]
    assert col.sum() == 4                     # pixel centres within 20 m: 185, 195, 205, 215
    assert not buffer_mask(line.iloc[:0], gb, 20).any()


def test_elongation_and_linear_flag():
    assert elongation(box(0, 0, 100, 100)) == pytest.approx(1.0)
    assert elongation(box(0, 0, 200, 20)) == pytest.approx(10.0)
    polys = gpd.GeoDataFrame({"id": [1, 2, 3], "type": ["stress", "stress", "cut"]},
                             geometry=[box(0, 0, 40, 40), box(0, 100, 200, 130), box(0, 200, 300, 220)],
                             crs="EPSG:3059")
    roads = gpd.GeoDataFrame({"kind": ["road"]}, geometry=[LineString([(0, 150), (300, 150)])],
                             crs="EPSG:3059")
    out = add_linear_attributes(polys, roads, 3.0)
    assert list(out["linear_feature"]) == [False, True, False]   # cuts are never flagged
    assert out.loc[1, "dist_to_road_m"] == pytest.approx(20.0)
    assert "dist_to_road_m" not in add_linear_attributes(polys, None, 3.0)
