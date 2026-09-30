import geopandas as gpd
import numpy as np
import pytest
import xarray as xr
from shapely.geometry import box

from s2forest.anomaly import FEATURES
from s2forest.config import Config, TimeConfig
from s2forest.targets import build_targets, write_targets
from s2forest.vectorize import polygon_status

K = 2.5


def _z(values):
    """Polygon of 4 pixels with the same z per date."""
    return np.repeat(np.array(values, dtype="float32")[:, None, None], 2, axis=1).repeat(2, axis=2)


SEL = np.ones((2, 2), bool)


def test_status_new_persistent_recovered():
    # detected at t=0; afterwards only one valid obs -> new
    assert polygon_status(_z([3, 3.2, np.nan]), SEL, 0, K, 2)[0] == "new"
    # still elevated -> persistent
    st, n, med = polygon_status(_z([3, 3, 2.9, 2.0, 2.2]), SEL, 0, K, 2)
    assert st == "persistent" and n == 4 and med >= K / 2
    # spring artefact: back to normal -> recovered
    st, n, med = polygon_status(_z([3.5, 0.4, 0.2, -0.1, 0.3]), SEL, 0, K, 2)
    assert st == "recovered" and med < K / 2
    # a date with < 50 % valid pixels does not count
    z = _z([3, 3, 3])
    z[1, 0, :] = np.nan
    z[1, 1, 0] = np.nan
    assert polygon_status(z, SEL, 0, K, 2)[1] == 1


@pytest.fixture
def scene(tmp_path):
    n = 60
    x = 614000 + 10 * np.arange(n) + 5
    y = 284000 - 10 * np.arange(n) - 5
    template = xr.DataArray(np.zeros((n, n), "float32"), dims=("y", "x"), coords={"y": y, "x": x})
    feats = xr.Dataset({f: (("y", "x"), np.full((n, n), np.nan, "float32")) for f in FEATURES},
                       coords={"y": y, "x": x})
    conifer = np.ones((n, n), bool)
    conifer[:, 45:] = False                        # right part: not conifer
    cut = box(614200, 283600, 614300, 283700)       # 1 ha cut, 10x10 px
    polys = gpd.GeoDataFrame({
        "id": [1, 2, 3, 4],
        "type": ["cut", "stress", "stress", "stress"],
        "status": ["persistent", "persistent", "recovered", "new"],
        "area_ha": [1.0, 0.2, 0.15, 0.1],
        "first_detected": ["2026-05-05", "2026-07-12", "2026-05-05", "2026-09-12"],
        "confidence": [0.9, 0.8, 0.7, 0.6],
        "delta_crswir": [0.3, 0.12, 0.01, 0.1],
    }, geometry=[cut, box(614050, 283850, 614100, 283900), box(614050, 283450, 614100, 283480),
                 box(614350, 283850, 614380, 283880)], crs="EPSG:3059")
    cfg = Config(run_name="t", aoi=tmp_path / "a.geojson", output_dir=tmp_path,
                 time=TimeConfig(monitor_year=2026))
    return cfg, polys, feats, conifer, template


def test_targets_select_statuses_and_cut_edges(scene):
    cfg, polys, feats, conifer, template = scene
    t = build_targets(cfg, polys, feats, conifer, template)
    stress = t[t["kind"] == "stress"]
    assert sorted(stress["source_id"]) == [2, 4]              # recovered one excluded
    assert stress.iloc[0]["status"] == "persistent"           # priority order
    edges = t[t["kind"] == "cut_edge"]
    assert len(edges) == 1
    ring = edges.geometry.iloc[0]
    cut = polys.geometry.iloc[0]
    assert ring.intersection(cut).area < 1.0                  # band excludes the cut itself
    assert ring.area == pytest.approx(cut.buffer(30).area - cut.area, rel=0.25)
    assert list(t["target_id"][:2]) == ["T001", "T002"]
    assert t["centroid_lat"].between(56, 58).all() and t["centroid_lon"].between(20, 29).all()
    assert all(isinstance(d, str) and d for d in t["description"])


def test_cut_edge_only_in_conifer_and_from_baseline_cuts(scene):
    cfg, polys, feats, conifer, template = scene
    polys = polys[polys["type"] != "cut"]
    # 2025 cut in the baseline period, at the right edge where there is no conifer
    feats["baseline_cut_year"].values[20:30, 40:50] = 2025
    feats["baseline_disturbed"].values[20:30, 40:50] = 1
    t = build_targets(cfg, polys, feats, conifer, template)
    edges = t[t["kind"] == "cut_edge"]
    assert len(edges) == 1
    assert edges.geometry.iloc[0].bounds[2] <= 614000 + 450 + 1   # clipped to conifer
    # a 2023 cut is too old (cut_edge_years = 2)
    feats["baseline_cut_year"].values[20:30, 40:50] = 2023
    assert (build_targets(cfg, polys, feats, conifer, template)["kind"] == "cut_edge").sum() == 0


def test_write_targets_gpkg_geojson_kml(scene, tmp_path):
    cfg, polys, feats, conifer, template = scene
    (cfg.run_dir / "tables").mkdir(parents=True)
    (cfg.run_dir / "vectors").mkdir(parents=True)
    t = build_targets(cfg, polys, feats, conifer, template)
    out = write_targets(cfg, t, cfg.run_dir / "vectors" / "suspects.gpkg")
    back = gpd.read_file(out["drone_targets_kml"])
    assert len(back) == len(t) and back.crs.to_epsg() == 4326
    assert "T001" in set(back["Name"])
    gj = gpd.read_file(out["drone_targets_geojson"])
    assert gj.crs.to_epsg() == 4326 and "description" in gj
    assert len(gpd.read_file(out["drone_targets_gpkg"], layer="drone_targets")) == len(t)
