"""DEMO ONLY: synthetic reference polygons from the tool's own cut detections.

Until LVM reference data arrive, this builds a reference file shaped like
dated sanitary-cut records, so the validation module can be exercised end to
end. Because the references come from the tool's own output, the resulting
metrics say NOTHING about accuracy - they only demonstrate the mechanics
(outcome classes, lead time, scope, field-name and reason configuration).

* cuts that happened before the season (onset_before_season) -> dated
  15.02.<year> (winter felling; out of scope for "detection before cut");
* cuts during the season -> dated at their first detection (when the cut
  became visible), i.e. the date the forest was actually removed.

Output: data/local/<run_name>_demo_references.gpkg with Latvian field names
(nr, cirtes_datums dd.mm.yyyy, iemesls) to mimic a real export.

Usage: python scripts/make_demo_references.py configs/test_kalsnava.yaml
"""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

from s2forest.config import load_config


def main(config: str) -> None:
    cfg = load_config(config)
    year = cfg.time.monitor_year
    g = gpd.read_file(cfg.run_dir / "vectors" / "suspects.gpkg", layer=f"suspects_{year}")
    cuts = g[g["type"] == "cut"].copy()
    before = cuts["onset_before_season"].astype(bool)
    dates = pd.to_datetime(cuts["first_detected"])
    dates[before] = pd.Timestamp(f"{year}-02-15")
    out = gpd.GeoDataFrame({
        "nr": [f"DEMO-{i:03d}" for i in range(1, len(cuts) + 1)],
        "cirtes_datums": dates.dt.strftime("%d.%m.%Y").values,
        "iemesls": "sanitārā cirte (DEMO)",
        "piezime": "Sintētiska demonstrācija no rīka paša cirtēm - nav īsti references dati",
    }, geometry=cuts.geometry.values, crs=g.crs)
    path = Path(cfg.aoi).parent / "local" / f"{cfg.run_name}_demo_references.gpkg"
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_file(path, driver="GPKG")
    print(f"{len(out)} demo references ({int(before.sum())} winter, {int((~before).sum())} in season)"
          f" -> {path}")


if __name__ == "__main__":
    main(sys.argv[1])
