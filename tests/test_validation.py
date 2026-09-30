import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

from s2forest.config import Config, ReferenceConfig, TimeConfig
from s2forest.validation import load_references, match_references, metrics, validate


def _polys():
    return gpd.GeoDataFrame({
        "id": [1, 2, 3, 4, 5],
        "type": ["stress", "stress", "cut", "stress", "stress"],
        "status": ["persistent", "persistent", "persistent", "new", "recovered"],
        "first_detected": ["2026-06-10", "2026-08-01", "2026-07-20", "2026-07-01", "2026-05-05"],
        "area_ha": [0.3, 0.2, 1.0, 0.1, 0.12],
        "confidence": [0.9, 0.8, 0.9, 0.6, 0.6],
    }, geometry=[
        box(0, 0, 50, 50),          # 1: overlaps ref A (cut 2026-09-15) -> before cut
        box(200, 0, 250, 50),       # 2: overlaps ref B (cut 2026-07-15) -> after cut
        box(400, 0, 500, 100),      # 3: cut polygon over ref C
        box(1000, 1000, 1030, 1030),  # 4: false alarm
        box(605, 0, 650, 40),       # 5: 5 m away from ref E -> matches via 10 m buffer
    ], crs="EPSG:3059")


def _refs_file(tmp_path):
    g = gpd.GeoDataFrame({
        "nr": ["A", "B", "C", "D", "E", "F", "G"],
        "cirtes_datums": ["15.09.2026", "15.07.2026", "01.08.2026", "10.10.2026", "01.11.2026",
                          "01.02.2026", "20.09.2026"],
        "iemesls": ["mizgrauži"] * 6 + ["vējgāze"],
    }, geometry=[box(10, 10, 60, 60), box(210, 10, 260, 60), box(410, 10, 490, 90),
                 box(3000, 3000, 3050, 3050), box(540, 0, 600, 40), box(10, 10, 60, 60),
                 box(10, 10, 60, 60)], crs="EPSG:3059")
    p = tmp_path / "refs.gpkg"
    g.to_file(p, driver="GPKG")
    return p


def _cfg(tmp_path, **ref):
    rc = ReferenceConfig(path=_refs_file(tmp_path), id_field="nr", date_field="cirtes_datums",
                         reason_field="iemesls", reason_values=["mizgrauži"], **ref)
    return Config(run_name="v", aoi=tmp_path / "a.geojson", output_dir=tmp_path,
                  time=TimeConfig(monitor_year=2026), reference=rc)


def test_reason_filter_custom_fields_and_dayfirst_dates(tmp_path):
    ref, info = load_references(_cfg(tmp_path))
    assert info["n_loaded"] == 7 and info["n_filtered_by_reason"] == 1
    assert list(ref["ref_id"]) == ["A", "B", "C", "D", "E", "F"]
    assert ref.loc[0, "ref_date"] == pd.Timestamp("2026-09-15")


def test_outcomes_lead_time_scope_and_metrics(tmp_path):
    cfg = _cfg(tmp_path)
    ref, _ = load_references(cfg)
    refs, polys = match_references(cfg, ref, _polys())
    r = refs.set_index("ref_id")
    assert r.loc["A", "outcome"] == "stress_before_cut"
    assert r.loc["A", "lead_days"] == (pd.Timestamp("2026-09-15") - pd.Timestamp("2026-06-10")).days
    assert r.loc["B", "outcome"] == "stress_on_or_after_cut"
    assert r.loc["C", "outcome"] == "cut_only"
    assert r.loc["D", "outcome"] == "missed"
    assert r.loc["E", "outcome"] == "stress_before_cut"      # via the 10 m buffer
    assert r.loc["F", "scope"] == "before_season"            # cut in February: out of scope

    m = metrics(refs, polys)
    assert m["references_in_scope"] == 5 and m["references_out_of_scope"] == 1
    assert m["tp_references"] == 2 and m["recall"] == pytest.approx(2 / 5)
    assert m["stress_polygons"] == 4 and m["tp_polygons"] == 2
    assert m["precision"] == pytest.approx(0.5)
    assert m["f1"] == pytest.approx(2 * 0.5 * 0.4 / 0.9)
    assert m["refs_cut_only"] == 1 and m["refs_missed"] == 1

    # drone statuses only: polygon 5 (recovered) drops out
    m2 = metrics(refs, polys, ["new", "persistent"])
    assert m2["stress_polygons"] == 3 and m2["tp_polygons"] == 1


def test_buffer_zero_misses_nearby_polygon(tmp_path):
    cfg = _cfg(tmp_path, match_buffer_m=0.0)
    ref, _ = load_references(cfg)
    refs, _ = match_references(cfg, ref, _polys())
    assert refs.set_index("ref_id").loc["E", "outcome"] == "missed"


def test_validate_without_timeseries(tmp_path):
    res, info = validate(_cfg(tmp_path), _polys(), indices=None)
    assert len(res.summary) == 2 and res.timeseries.empty
    assert set(res.references["outcome"]) <= {"stress_before_cut", "stress_on_or_after_cut",
                                              "cut_only", "missed"}


def test_reference_timeseries_split_at_cut():
    import xarray as xr

    from s2forest.validation import reference_timeseries

    times = pd.date_range("2026-05-01", periods=6, freq="20D")
    x = 5 + 10 * np.arange(20)
    y = 195 - 10 * np.arange(20)
    v = np.full((6, 20, 20), 0.8, dtype="float32")
    v[3:, :5, :5] = 1.2                       # change inside the reference after the cut
    ds = xr.Dataset({"crswir": (("time", "y", "x"), v)},
                    coords={"time": times, "y": y, "x": x})
    refs = gpd.GeoDataFrame({"ref_id": ["A"], "ref_date": [times[3].date()]},
                            geometry=[box(0, 150, 50, 200)], crs="EPSG:3059")
    ts = reference_timeseries(refs, ds, ["crswir"])
    assert list(ts["phase"]) == ["pre_cut"] * 3 + ["post_cut"] * 3
    assert ts["crswir"].tolist() == pytest.approx([0.8] * 3 + [1.2] * 3)
    assert ts["days_to_cut"].iloc[0] == 60
