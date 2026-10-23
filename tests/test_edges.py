"""Forest-edge attributes (diagnostics.forest_edge, off by default)."""

import geopandas as gpd
import numpy as np
from affine import Affine
from shapely.geometry import box

from s2forest.config import Config, DiagnosticsConfig
from s2forest.edges import distance_to_open, edge_summary, open_mask, polygon_edge_attributes


def test_off_by_default():
    assert DiagnosticsConfig().forest_edge is False


def test_distance_and_polygon_attributes():
    tree = np.ones((20, 20), bool)
    tree[:, :2] = False                                     # open strip on the west side
    z = np.zeros_like(tree)
    open_px = open_mask(tree, z, z, z)
    dist = distance_to_open(open_px, 10.0)
    assert dist[0, 2] == 10.0 and dist[0, 10] == 90.0
    tr = Affine(10, 0, 0, 0, -10, 200)
    g = gpd.GeoDataFrame({"type": ["stress", "cut"]},
                         geometry=[box(20, 150, 40, 170), box(150, 150, 170, 170)], crs="EPSG:3059")
    att = polygon_edge_attributes(g, open_px, tr, 10.0, 20.0)
    assert att.loc[0, "edge_dist_m"] == 10.0 and att.loc[0, "edge_share_20m"] == 1.0
    assert att.loc[1, "edge_dist_m"] == 140.0 and att.loc[1, "edge_share_20m"] == 0.0
    s = edge_summary(g.join(att), dist, tree, 20.0)
    assert list(s.group) == ["analysed forest pixels", "cut polygons", "stress polygons"]


def test_polygon_own_open_pixels_do_not_count():
    """A cut is open ground itself; its distance is measured to open ground outside it."""
    tree = np.ones((40, 40), bool)
    cut = np.zeros_like(tree); cut[18:22, 18:22] = True
    z = np.zeros_like(tree)
    open_px = open_mask(tree, z, z, cut)
    tr = Affine(10, 0, 0, 0, -10, 400)
    g = gpd.GeoDataFrame({"type": ["cut"]}, geometry=[box(180, 180, 220, 220)], crs="EPSG:3059")
    att = polygon_edge_attributes(g, open_px, tr, 10.0, 20.0, margin_m=100.0)
    assert np.isnan(att.loc[0, "edge_dist_m"]) and att.loc[0, "edge_share_20m"] == 0.0
    tree[:, 0] = False                                      # open strip 170 m west of the cut
    att = polygon_edge_attributes(g, open_mask(tree, z, z, cut), tr, 10.0, 20.0, margin_m=500.0)
    assert att.loc[0, "edge_dist_m"] == 180.0


def test_cuts_and_roads_are_open():
    tree = np.ones((5, 5), bool)
    road = np.zeros_like(tree); road[0, 0] = True
    cut = np.zeros_like(tree); cut[4, 4] = True
    m = open_mask(tree, road, cut, np.zeros_like(tree))
    assert m[0, 0] and m[4, 4] and m.sum() == 2
