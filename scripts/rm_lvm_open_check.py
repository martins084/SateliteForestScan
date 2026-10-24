"""Stage 5 label search: LVM open damage polygons (data.gov.lv "LVM mežkopības ģeotelpiskie dati",
layer LVM_BOJAJUMI, CC0; state forest only) against EFDA v3.0 and v2.1.1.

For damage polygons of subtype 620 (stem pests) and 100 (wind / snow break) registered in year Y
(DISTRBYEAR = year the damage was registered): share of the polygon pixels (EFDA grid, pixel
centre inside the polygon) that each EFDA version marks as class 1 / class 3 / any disturbance
in year Y-1, Y and Y+1. Also the per-year annual counts of polygons and area.

    python scripts/rm_lvm_open_check.py configs/rm_latvia.yaml cache/lvm_open/LVM_BOJAJUMI_wayback20250503.zip

LVM data are never committed (cache/ and output/ are ignored).
"""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize

from mezasargs_risk.config import load_config
from mezasargs_risk.efda import layer

SUBTYPES = {620: "stem_pests", 100: "wind_snow"}
YEARS = range(2013, 2025)


def main() -> None:
    cfg = load_config(Path(sys.argv[1]))
    z = Path(sys.argv[2])
    g = gpd.read_file(f"zip://{z.resolve()}!LVM_BOJAJUMI_Shape.shp")
    empty = g.geometry.isna() | g.geometry.is_empty
    print(f"{len(g)} polygons, {int(empty.sum())} without geometry (dropped)")
    g = g[~empty].copy()
    g["year"] = pd.to_numeric(g["DISTRBYEAR"], errors="coerce")
    g["ha"] = g.area / 1e4
    out = cfg.run_dir.parent / "rm5_label_search"
    out.mkdir(parents=True, exist_ok=True)
    g.groupby(["year", "DAMAGESUBT"]).ha.agg(["count", "sum"]).reset_index().to_csv(
        out / "lvm_open_damage_by_year.csv", index=False)
    g = g[g["DAMAGESUBT"].isin(list(SUBTYPES)) & g["year"].isin(list(YEARS))].to_crs(3035)
    rows = []
    for v in (cfg.efda.main, cfg.efda.crosscheck):
        with rasterio.open(layer(v, "agent")) as s:
            last = v.first_year + s.count - 1
            cache = {}

            def band(y):
                if y not in cache:
                    cache[y] = s.read(y - v.first_year + 1)
                return cache[y]

            for (sub, y), grp in g.groupby(["DAMAGESUBT", "year"]):
                m = rasterize(((geom, 1) for geom in grp.geometry), out_shape=s.shape,
                              transform=s.transform, fill=0, dtype="uint8") == 1
                n = int(m.sum())
                for off in (-1, 0, 1):
                    yy = int(y) + off
                    if not v.first_year <= yy <= last:
                        continue
                    a = band(yy)[m]
                    rows.append({"version": v.version, "subtype": SUBTYPES[sub], "reg_year": int(y),
                                 "efda_year_offset": off, "polygons": len(grp), "poly_px": n,
                                 "c1": float((a == 1).mean()), "c3": float((a == 3).mean()),
                                 "any": float(np.isin(a, (1, 2, 3)).mean())})
                for old in [k for k in cache if k < int(y) - 1]:
                    del cache[old]
            print(v.version, "done")
    pd.DataFrame(rows).to_csv(out / "lvm_open_vs_efda.csv", index=False)
    print(out)


if __name__ == "__main__":
    main()
