"""Control-ring inspection of selected polygons (the same logic as the standard
diagnostic written by `detect`, here for any polygon ids, including cuts).

Usage: python scripts/inspect_polygons.py configs/test_kalsnava.yaml 23 24 34
Writes diagnostics/inspect_<ids>.csv / .png.
"""

from __future__ import annotations

import sys

import geopandas as gpd
import pandas as pd

from s2forest.config import load_config
from s2forest.pipeline import index_stage
from s2forest.ringcontrol import plot_ring, ring_series, summarize_ring


def main(config: str, ids: list[int]) -> None:
    cfg = load_config(config)
    year = cfg.time.monitor_year
    st = index_stage(cfg)
    g = gpd.read_file(cfg.run_dir / "vectors" / "suspects.gpkg", layer=f"suspects_{year}")
    g = g[g["id"].isin(ids)].set_index("id").loc[ids].reset_index()
    prim = cfg.anomaly.primary_index
    ser = ring_series(st.indices[prim].transpose("time", "y", "x").values, st.cube.time.values,
                      st.cube.x.values, st.cube.y.values, g, st.analysis_mask,
                      cfg.linear_features.control_ring_m)
    summ = summarize_ring(ser)
    tag = "_".join(map(str, ids))
    out = cfg.run_dir / "diagnostics"
    summ.to_csv(out / f"inspect_{tag}.csv", index=False)
    pd.set_option("display.width", 200)
    print(summ.to_string(index=False))
    print(f"\nFigure: {plot_ring(ser, g, prim, out / f'inspect_{tag}.png', max_panels=len(ids))}")


if __name__ == "__main__":
    main(sys.argv[1], [int(a) for a in sys.argv[2:]])
