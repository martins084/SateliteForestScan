import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from s2forest.fieldcheck import FORM_COLUMNS, form_to_references, read_form


def _form(tmp_path, rows, sep=";"):
    df = pd.DataFrame([{c: "" for c in FORM_COLUMNS} | r for r in rows])
    p = tmp_path / "forma.csv"
    df.to_csv(p, index=False, sep=sep, encoding="utf-8-sig")
    return p


def _targets():
    return gpd.GeoDataFrame({"merka_id": ["F01", "F02", "F03"],
                             "kind": ["stress", "cut_edge", "control"],
                             "source_id": ["25", "T004", None]},
                            geometry=[box(0, 0, 10, 10), box(20, 0, 30, 10), box(40, 0, 50, 10)],
                            crs="EPSG:3059")


def test_read_valid_form_both_separators(tmp_path):
    rows = [{"merka_id": "F01", "datums": "15.10.2026", "secinajums": "mizgrauzi",
             "vainaga_krasa": "dzeltenzala", "apskatito_koku_skaits": "12",
             "koki_ar_urbumu_miltiem": "5", "gps_platums": "56,69", "gps_garums": "25.84"},
            {"merka_id": "F03", "datums": "2026-10-15", "secinajums": "vesels",
             "vainaga_krasa": "zala"}]
    for sep in (";", ","):
        df, problems = read_form(_form(tmp_path, rows, sep))
        assert problems == []
        assert list(df["merka_id"]) == ["F01", "F03"]
        assert str(df.iloc[0]["datums"]) == "2026-10-15"


def test_read_form_reports_problems(tmp_path):
    rows = [{"merka_id": "F01", "datums": "vakar", "secinajums": "varbūt",
             "vainaga_krasa": "zila", "koki_ar_sveku_tecem": "daži"}]
    _, problems = read_form(_form(tmp_path, rows))
    text = " ".join(problems)
    assert "secinajums" in text and "vainaga_krasa" in text and "datums" in text
    assert "koki_ar_sveku_tecem" in text


def test_form_to_references_and_table(tmp_path):
    rows = [{"merka_id": "F01", "datums": "15.10.2026", "secinajums": "mizgrauzi"},
            {"merka_id": "F02", "datums": "15.10.2026", "secinajums": "cits_bojajums"},
            {"merka_id": "F03", "datums": "16.10.2026", "secinajums": "vesels"}]
    df, _ = read_form(_form(tmp_path, rows))
    ref, table = form_to_references(df, _targets())
    assert len(ref) == 3 and ref.crs.to_epsg() == 3059
    assert table.loc["stress", "mizgrauzi"] == 1 and table.loc["control", "vesels"] == 1
    bad = df.copy()
    bad.loc[bad.index[0], "merka_id"] = "F99"
    with pytest.raises(KeyError):
        form_to_references(bad, _targets())
