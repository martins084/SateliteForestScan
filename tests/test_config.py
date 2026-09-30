import pytest
import yaml

from s2forest.config import load_config


def test_load_config_resolves_relative_paths(tmp_path):
    (tmp_path / "configs").mkdir()
    p = tmp_path / "configs" / "c.yaml"
    p.write_text(yaml.safe_dump({
        "run_name": "x", "aoi": "../data/aoi.geojson",
        "time": {"monitor_year": 2025},
    }), encoding="utf-8")
    cfg = load_config(p)
    assert cfg.aoi == (tmp_path / "data" / "aoi.geojson").resolve()
    assert cfg.time.years == [2022, 2023, 2024, 2025]
    assert cfg.anomaly.z_threshold == 2.5 and cfg.anomaly.persistence == 2
    assert cfg.fetch_buffer_m == 5000
    assert [s.collection for s in cfg.data.sources] == ["sentinel-2-c1-l2a", "sentinel-2-l2a"]


def test_invalid_primary_index_rejected(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump({
        "run_name": "x", "aoi": "a.geojson", "time": {"monitor_year": 2025},
        "indices": ["ndvi"],
    }), encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(p)


def test_template_config_is_valid():
    from pathlib import Path

    cfg = load_config(Path(__file__).parents[1] / "configs" / "template_aoi.yaml")
    assert cfg.time.monitor_year == 2026 and cfg.targets.cut_edge_width_m == 30
    assert cfg.reference.path is None and cfg.stands.path is None
