"""Orthophoto desk check: QGIS project XML, marking form round trip."""

import xml.etree.ElementTree as ET

import geopandas as gpd
import pandas as pd
from shapely.geometry import box

from s2forest.deskcheck import FORM_COLUMNS, desk_objects, qgis_project, read_form, results


def _objects():
    polys = gpd.GeoDataFrame({"id": [1, 2], "type": ["cut", "stress"], "status": ["new", "persistent"],
                              "area_ha": [1.0, 0.2]},
                             geometry=[box(0, 0, 100, 100), box(200, 0, 240, 50)], crs="EPSG:3059")
    targets = gpd.GeoDataFrame({"target_id": ["E01"], "kind": ["cut_edge"], "status": ["new"],
                                "area_ha": [0.5]}, geometry=[box(0, 100, 100, 150)], crs="EPSG:3059")
    return desk_objects(polys, targets)


def test_desk_objects_ids_and_fields():
    p, t = _objects()
    assert list(p["merka_id"]) == ["P1", "P2"] and list(t["merka_id"]) == ["DE01"]
    assert all(c in p for c in FORM_COLUMNS) and all(c in t for c in FORM_COLUMNS)


def test_qgis_project_is_xml_without_credentials():
    root = ET.fromstring(qgis_project("desk_check_2026.gpkg", 2026, True, None, None))
    ids = [e.text for e in root.iter("id")]
    assert ids == ["desk_suspects", "desk_targets"]          # no WMS layer without a URL
    xml = qgis_project("x.gpkg", 2026, False, "https://example.invalid/wms", "ortofoto")
    root = ET.fromstring(xml)
    assert [e.text for e in root.iter("provider")][-1] == "wms"
    assert "password" not in xml and "username" not in xml


def test_read_form_and_results(tmp_path):
    p, t = _objects()
    f = tmp_path / "form.csv"
    pd.DataFrame({"merka_id": ["P1", "P2", "DE01", "X9"],
                  "vertejums": ["izcirsts", "koki_stav", "", "nav_skaidrs"],
                  "piezimes": ["", "", "", ""], "datums": ["15.10.2026", "2026-10-15", "", ""],
                  "vertetajs": ["MV"] * 4}).to_csv(f, sep=";", index=False, encoding="utf-8-sig")
    df, problems = read_form(f)
    assert problems == [] and list(df["merka_id"]) == ["P1", "P2", "X9"]   # empty verdict skipped
    rows, tab = results(df, p, t)
    assert tab.loc["poligons cut/new", "izcirsts"] == 1
    assert tab.loc["nezināms merka_id", "nav_skaidrs"] == 1


def test_read_form_rejects_unknown_verdict(tmp_path):
    f = tmp_path / "form.csv"
    f.write_text("merka_id;vertejums;piezimes;datums;vertetajs\nP1;gulus;;;\n", encoding="utf-8")
    _, problems = read_form(f)
    assert problems and "vertejums" in problems[0]


def test_read_form_from_edited_gpkg(tmp_path):
    p, t = _objects()
    p.loc[0, ["vertejums", "datums"]] = ["koki_gulus", "23.10.2026"]
    g = tmp_path / "desk.gpkg"
    p.to_file(g, layer="suspects", driver="GPKG", engine="pyogrio")
    t.to_file(g, layer="targets", driver="GPKG", engine="pyogrio")
    df, problems = read_form(g)
    assert problems == [] and list(df["merka_id"]) == ["P1"] and df["vertejums"].iloc[0] == "koki_gulus"
