"""Are stress detections enriched near roads?

Per distance band to the nearest OSM road (pixel centres): share of analysed
conifer forest vs share of stress-polygon pixels (and cut pixels for
comparison). Enrichment = detection share / forest share; ~1 means no road effect.

Note: the forest share is computed over ALL HRL conifer pixels in the AOI before
the road buffer (code 1 or 4 in the forest mask), so the 0-20 m band shows what
the current buffer removes.

Usage: python scripts/road_enrichment.py configs/test_kalsnava.yaml configs/test_kalsnava_2025.yaml
"""

from __future__ import annotations

import sys

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize
from scipy import ndimage

from s2forest.config import load_config
from s2forest.fetch import build_grid
from s2forest.linear import fetch_osm_lines

BANDS = [0, 20, 30, 50, 100, np.inf]
LABELS = ["0-20", "20-30", "30-50", "50-100", ">100"]


def one(config: str) -> pd.DataFrame:
    cfg = load_config(config)
    year = cfg.time.monitor_year
    grid = build_grid(cfg)
    gb = grid.geobox
    lines = fetch_osm_lines(gb, cfg.linear_features, cfg.cache_dir / grid.key)
    roads = lines[lines["kind"] == "road"].to_crs(str(gb.crs))
    road_px = rasterize([(g, 1) for g in roads.geometry], out_shape=gb.shape, transform=gb.affine,
                        fill=0, all_touched=True, dtype="uint8").astype(bool)
    dist = ndimage.distance_transform_edt(~road_px) * cfg.data.resolution
    with rasterio.open(cfg.run_dir / "rasters" / "forest_mask.tif") as src:
        codes = src.read(1)
    forest_all = np.isin(codes, [1, 4]) & grid.aoi_mask      # before the road buffer
    analysed = codes == 1
    polys = gpd.read_file(cfg.run_dir / "vectors" / "suspects.gpkg", layer=f"suspects_{year}")
    def px(sub):
        if sub.empty:
            return np.zeros(gb.shape, bool)
        return rasterize([(g, 1) for g in sub.geometry], out_shape=gb.shape, transform=gb.affine,
                         fill=0, dtype="uint8").astype(bool)
    stress = px(polys[polys["type"] == "stress"]) & analysed
    cut = px(polys[polys["type"] == "cut"]) & analysed
    band = pd.cut(dist.ravel(), BANDS, labels=LABELS, right=False)
    rows = []
    for lab in LABELS:
        sel = (band == lab).reshape(gb.shape)
        rows.append({"year": year, "band_m": lab,
                     "forest_ha": forest_all[sel].sum() / 100, "analysed_ha": analysed[sel].sum() / 100,
                     "stress_px": int(stress[sel].sum()), "cut_px": int(cut[sel].sum())})
    df = pd.DataFrame(rows)
    df["forest_share"] = df["analysed_ha"] / df["analysed_ha"].sum()
    df["stress_share"] = df["stress_px"] / max(df["stress_px"].sum(), 1)
    df["cut_share"] = df["cut_px"] / max(df["cut_px"].sum(), 1)
    df["stress_enrichment"] = df["stress_share"] / df["forest_share"].replace(0, np.nan)
    df["cut_enrichment"] = df["cut_share"] / df["forest_share"].replace(0, np.nan)
    # per-polygon: distance band of the closest pixel
    s = polys[polys["type"] == "stress"]
    if "dist_to_road_m" in s:
        df["stress_polygons_by_nearest_edge"] = [
            int(((s["dist_to_road_m"] >= lo) & (s["dist_to_road_m"] < hi)).sum())
            for lo, hi in zip(BANDS[:-1], BANDS[1:])]
    return df


def main(configs: list[str]) -> None:
    out = pd.concat([one(c) for c in configs], ignore_index=True)
    pd.set_option("display.width", 200)
    print(out.round(3).to_string(index=False))
    cfg = load_config(configs[0])
    path = cfg.run_dir / "diagnostics" / "road_enrichment.csv"
    out.to_csv(path, index=False)
    print(f"\n{path}")


if __name__ == "__main__":
    main(sys.argv[1:])
