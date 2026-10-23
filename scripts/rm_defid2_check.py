"""Stage 5 label search: does DEFID2 (JRC, VER1-0, CC BY 4.0) contain Latvia?

Lists the layers and fields of defid2.gpkg, then counts records whose geometry intersects Latvia
(GISCO NUTS 2024 level 0, buffered 1 km) per layer, with agents, years and geometry types.
Positive control: the same count for Sweden and Finland.

    python scripts/rm_defid2_check.py cache/defid2/defid2.gpkg cache/boundaries/NUTS_RG_01M_2024_3035_LEVL_0.geojson
"""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio

COUNTRIES = ("LV", "SE", "FI")


def main() -> None:
    gpkg, nuts = Path(sys.argv[1]), Path(sys.argv[2])
    out = Path("output/rm5_label_search")
    out.mkdir(parents=True, exist_ok=True)
    c = gpd.read_file(nuts)
    c = c[c["CNTR_CODE"].isin(COUNTRIES)]
    rows = []
    for name, gtype in pyogrio.list_layers(gpkg):
        info = pyogrio.read_info(gpkg, layer=name)
        print(f"## {name} ({gtype}), {info['features']} features, crs {info['crs']}")
        print("   fields:", list(info["fields"]))
        if gtype is None:
            continue
        cc = c.to_crs(info["crs"])
        for code, geom in zip(cc["CNTR_CODE"], cc.geometry):
            area = geom.buffer(1000 if cc.crs.is_projected else 0.01)
            g = gpd.read_file(gpkg, layer=name, bbox=tuple(area.bounds))
            g = g[g.intersects(area)]
            print(f"   {code}: {len(g)} records")
            if len(g):
                rows.append(g.drop(columns="geometry").assign(layer=name, country=code,
                                                               geom_type=g.geom_type.values))
    if rows:
        d = pd.concat(rows)
        d.to_csv(out / "defid2_lv_se_fi_records.csv", index=False)
        lv = d[d.country == "LV"]
        print("LV records:", len(lv))
        for col in lv.columns:
            if lv[col].nunique() <= 40:
                print(col, lv[col].value_counts(dropna=False).to_dict())


if __name__ == "__main__":
    main()
