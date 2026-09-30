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


def test_risk_orientation_south_facing_wall_scores_higher(scene):
    """Conifer only north of the cut (wall faces S) vs only south (wall faces N)."""
    from s2forest.targets import cut_edge_zones

    cfg, polys, feats, conifer, template = scene
    cut_only = polys[polys["type"] == "cut"]            # 10x10 px cut, rows 30-40, cols 20-30
    north = np.zeros_like(conifer)
    north[:30, :] = True
    south = np.zeros_like(conifer)
    south[40:, :] = True
    zn = cut_edge_zones(cfg, cut_only, feats, north, template).iloc[0]
    zs = cut_edge_zones(cfg, cut_only, feats, south, template).iloc[0]
    assert zn["risk_orientation"] > 0.75 and zs["risk_orientation"] < 0.25
    assert zn["sw_exposed_share"] > 0.6 and zs["sw_exposed_share"] < 0.1
    assert zn["risk_score"] > zs["risk_score"]
    assert zn["risk_freshness"] == 1.0                  # cut of the monitoring year
    assert 0.2 < zn["risk_conifer"] < 0.6               # only the northern part of the ring


def test_risk_weights_configurable(scene):
    from s2forest.targets import cut_edge_zones

    cfg, polys, feats, conifer, template = scene
    cfg.targets.risk_weights = {"orientation": 0.0, "freshness": 1.0, "conifer": 0.0}
    z = cut_edge_zones(cfg, polys[polys["type"] == "cut"], feats, conifer, template).iloc[0]
    assert z["risk_score"] == pytest.approx(1.0)


def _targets_grid(cfg, n_edges=12, spacing=300.0):
    rows = [{"target_id": "S1", "kind": "stress", "priority": 1, "value": 1.9,
             "geometry": box(0, 0, 40, 40)}]
    for i in range(n_edges):
        x = 3000 + (i % 4) * spacing
        y = (i // 4) * spacing
        rows.append({"target_id": f"E{i}", "kind": "cut_edge", "priority": 3,
                     "value": 0.3 + 0.05 * i, "geometry": box(x, y, x + 60, y + 60)})
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:3059")


def test_missions_area_limit_priority_and_top_n(scene):
    from s2forest.targets import build_missions

    cfg = scene[0]
    cfg.targets.mission_max_area_ha = 30
    cfg.targets.max_missions = 3
    t = _targets_grid(cfg)
    m, t2 = build_missions(cfg, t)
    assert m.iloc[0]["n_stress"] == 1 and m.iloc[0]["priority"] == 1   # stress mission first
    big = m[~m["oversize"]]
    assert (big["flight_area_ha"] <= 30 + 1e-6).all()
    assert t2["mission_id"].notna().all()
    assert sum(m["n_targets"]) == len(t)
    # edges 300 m apart in a 4x3 grid: several edges per mission, but not all in one
    assert 1 < len(m) - 1 < 12
    # far-away stress target is not merged with the edges (gap > 500 m)
    assert m.iloc[0]["n_targets"] == 1
    assert list(m["mission_id"][:3]) == ["M01", "M02", "M03"]


def test_missions_written_top_n(scene, tmp_path):
    from s2forest.targets import build_missions

    cfg = scene[0]
    cfg.targets.max_missions = 2
    (cfg.run_dir / "vectors").mkdir(parents=True)
    t = _targets_grid(cfg)
    t["description"] = "x"
    for c in ("centroid_lon", "centroid_lat"):
        t[c] = 0.0
    m, t2 = build_missions(cfg, t)
    out = write_targets(cfg, t2, cfg.run_dir / "vectors" / "suspects.gpkg", m)
    assert len(gpd.read_file(out["drone_missions_gpkg"], layer="drone_missions")) == 2
    k = gpd.read_file(out["drone_missions_kml"])
    assert list(k["Name"]) == ["M01", "M02"]


def test_mission_rank_follows_riskiest_target(scene):
    from s2forest.targets import build_missions

    cfg = scene[0]
    rows = [{"target_id": f"E{i}", "kind": "cut_edge", "priority": 3, "value": 0.5,
             "geometry": box(i * 100, 0, i * 100 + 40, 40)} for i in range(4)]   # 4 medium, close
    rows.append({"target_id": "HOT", "kind": "cut_edge", "priority": 3, "value": 0.9,
                 "geometry": box(5000, 0, 5040, 40)})                             # 1 high, far
    m, _ = build_missions(cfg, gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:3059"))
    assert m.iloc[0]["target_ids"] == "HOT"
