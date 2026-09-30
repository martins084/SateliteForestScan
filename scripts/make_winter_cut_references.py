"""Reference polygons from winter cuts found by a later run (e.g. 2026), for
validating an earlier run (e.g. 2025): was stress visible before the stand was cut?

Winter cuts = `type == "cut"` polygons with `onset_before_season` in the later
run: the stand was intact in the last observations of the previous season and
gone at the first observation of the later season. The exact cut date is
unknown; it lies between those two observations. The reference date is set to
the EARLIEST possible date (the day after the last clear observation of the
previous season), so lead times computed from it are LOWER BOUNDS.

The cut reason is unknown (not necessarily bark beetles: most will be regular
final fellings). These references therefore do not measure bark-beetle
detection accuracy; they show whether a pre-cut stress signal existed.

Usage:
  python scripts/make_winter_cut_references.py configs/test_kalsnava.yaml configs/test_kalsnava_2025.yaml
  (1st config: the later run with the cut detections; 2nd: the run to validate)
"""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

from s2forest.config import load_config


def main(later_config: str, earlier_config: str) -> None:
    later = load_config(later_config)
    earlier = load_config(earlier_config)
    year = later.time.monitor_year
    prev = earlier.time.monitor_year
    g = gpd.read_file(later.run_dir / "vectors" / "suspects.gpkg", layer=f"suspects_{year}")
    cuts = g[(g["type"] == "cut") & g["onset_before_season"].astype(bool)].copy()

    acq = pd.read_csv(later.run_dir / "diagnostics" / "acquisitions.csv", parse_dates=["datetime"])
    acc = acq[acq["status"] == "accepted"]["datetime"].dt.tz_localize(None)
    last_prev = acc[acc.dt.year == prev].max()
    first_next = acc[acc.dt.year == year].min()
    earliest = (last_prev + pd.Timedelta(days=1)).normalize()

    out = gpd.GeoDataFrame({
        "nr": [f"ZC-{i:03d}" for i in range(1, len(cuts) + 1)],
        "cirtes_datums": earliest.strftime("%d.%m.%Y"),
        "datums_no": last_prev.strftime("%Y-%m-%d"),
        "datums_lidz": first_next.strftime("%Y-%m-%d"),
        "iemesls": "nezināms",
        "piezime": ("Ziemas cirte no satelīta datiem; precīzs datums un iemesls nav zināmi. "
                    "cirtes_datums = agrākais iespējamais, aizkave ir apakšējā robeža."),
        "platiba_ha": cuts["area_ha"].round(2).values,
    }, geometry=cuts.geometry.values, crs=g.crs)
    path = Path(earlier.aoi).parent / "local" / f"{earlier.run_name}_winter_cut_references.gpkg"
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_file(path, driver="GPKG")
    print(f"{len(out)} winter cuts; cut between {last_prev:%Y-%m-%d} and {first_next:%Y-%m-%d}; "
          f"reference date {earliest:%Y-%m-%d} (earliest possible) -> {path}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
