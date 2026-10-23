"""EFDA input: extent check (plan 2.2, decision 1), country / region rasters, annual agent counts,
v3.0 vs v2.1.1 cross-check.

Layer conventions [P: 0_METADATA_EFDA_v3.0.txt]: annual agent 1 = wind / bark beetle complex,
2 = fire, 3 = harvest, 255 = no disturbance / nodata; one band per year from `first_year`.
v3.0 agent bands carry no country footprint (255 everywhere outside disturbances), so the
extent check uses the forest land-use mask. v2.1.1 bands use 0 = not disturbed inside the
country footprint.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from rasterio.features import rasterize
from shapely.geometry import box

from .config import BoundaryConfig, EfdaVersion

AGENTS = {1: "wind_bark_beetle", 2: "fire", 3: "harvest"}


def layer(v: EfdaVersion, name: str) -> Path:
    return v.dir / getattr(v, name)


def country_regions(b: BoundaryConfig) -> gpd.GeoDataFrame:
    g = gpd.read_file(b.path)
    g = g[g["CNTR_CODE"] == b.country].to_crs(3035)
    return g[["NUTS_ID", "NAME_LATN", "geometry"]].sort_values("NUTS_ID").reset_index(drop=True)


def region_raster(regions: gpd.GeoDataFrame, src: rasterio.DatasetReader,
                  buffer_m: float = 0.0) -> np.ndarray:
    """uint8 raster on the EFDA grid: 0 outside the country, i+1 = regions.iloc[i]."""
    shapes = [((geom.buffer(buffer_m) if buffer_m else geom), i + 1)
              for i, geom in enumerate(regions.geometry)]
    return rasterize(shapes, out_shape=src.shape, transform=src.transform, fill=0, dtype="uint8")


@dataclass
class ExtentCheck:
    country_area_in_bounds: float   # share of the country polygon inside the raster bounds
    forest_inside_country: float    # share of forest-mask pixels inside the (buffered) country
    forest_px: int
    control_forest_1km: float       # forest share within 1 km of the control point (-1 = outside)
    ok: bool

    def message(self) -> str:
        return (f"country area in raster bounds {self.country_area_in_bounds:.1%}, forest pixels inside "
                f"country {self.forest_inside_country:.1%} (n={self.forest_px:,}), forest within 1 km "
                f"of control point {self.control_forest_1km:.1%} -> {'OK' if self.ok else 'FAIL'}")


def check_extent(forest_path: Path, regions: gpd.GeoDataFrame, b: BoundaryConfig) -> ExtentCheck:
    """Is this raster really the country? Independent of the file name (EFDA v3.0 swapped
    Latvia.zip / Lithuania.zip)."""
    country = regions.union_all()
    with rasterio.open(forest_path) as s:
        cover = country.intersection(box(*s.bounds)).area / country.area
        forest = s.read(1) == 1
        inside = region_raster(regions, s, b.border_buffer_m) > 0
        n = int(forest.sum())
        share = float((forest & inside).sum() / n) if n else 0.0
        x, y = Transformer.from_crs(4326, 3035, always_xy=True).transform(*b.control_lonlat)
        r, c = s.index(x, y)
        k = int(round(1000 / s.res[0]))
        if 0 <= r < s.height and 0 <= c < s.width:
            win = forest[max(r - k, 0):r + k + 1, max(c - k, 0):c + k + 1]
            ctrl = float(win.mean())
        else:
            ctrl = -1.0
    ok = cover >= b.min_cover and share >= b.min_cover and ctrl > 0
    return ExtentCheck(cover, share, n, ctrl, ok)


def annual_counts(v: EfdaVersion, region: np.ndarray, n_regions: int) -> pd.DataFrame:
    """Pixels per year x agent x region (region 0 = outside the country)."""
    rows = []
    with rasterio.open(layer(v, "agent")) as s:
        for b in range(1, s.count + 1):
            a = s.read(b)
            for code, name in AGENTS.items():
                m = a == code
                cnt = np.bincount(region[m], minlength=n_regions + 1)
                for reg, n in enumerate(cnt):
                    rows.append({"version": v.version, "year": v.first_year + b - 1, "agent": name,
                                 "region": reg, "px": int(n)})
    return pd.DataFrame(rows)


def grid_offset(a: rasterio.DatasetReader, b: rasterio.DatasetReader) -> tuple[int, int, float]:
    """Integer (row, col) offset of grid `a` inside grid `b` (same resolution) and the residual
    sub-pixel shift in metres (the grids of v3.0 and v2.1.1 are not aligned)."""
    dr = (b.transform.f - a.transform.f) / a.res[1]
    dc = (a.transform.c - b.transform.c) / a.res[0]
    ro, co = int(round(dr)), int(round(dc))
    resid = float(np.hypot(dr - ro, dc - co) * a.res[0])
    return ro, co, resid


def crosscheck(main: EfdaVersion, other: EfdaVersion, country_main: np.ndarray) -> pd.DataFrame:
    """Per common year: class-1 and any-disturbance pixels in both versions inside the country
    (on the main grid; `other` read with the nearest integer offset) and pixel agreement of
    class 1 (same year, and within +-1 year)."""
    rows = []
    with rasterio.open(layer(main, "agent")) as a, rasterio.open(layer(other, "agent")) as b:
        ro, co, _ = grid_offset(a, b)
        win = ((ro, ro + a.height), (co, co + a.width))
        years = range(max(main.first_year, other.first_year),
                      min(main.first_year + a.count, other.first_year + b.count))
        ylist = list(years)

        def read_b(y):
            return b.read(y - other.first_year + 1, window=win)

        prev = read_b(ylist[0] - 1) if ylist[0] - 1 >= other.first_year else None
        cur = read_b(ylist[0])
        for i, y in enumerate(ylist):
            nxt = read_b(y + 1) if y + 1 < other.first_year + b.count else None
            am = a.read(y - main.first_year + 1)
            a1 = (am == 1) & country_main
            b1 = (cur == 1) & country_main
            near = b1.copy()
            for o in (prev, nxt):
                if o is not None:
                    near |= (o == 1) & country_main
            any_a = np.isin(am, (1, 2, 3)) & country_main
            any_b = np.isin(cur, (1, 2, 3)) & country_main
            inter = int((a1 & b1).sum())
            union = int((a1 | b1).sum())
            rows.append({"year": y,
                         "c1_main_px": int(a1.sum()), "c1_other_px": int(b1.sum()),
                         "any_main_px": int(any_a.sum()), "any_other_px": int(any_b.sum()),
                         "c1_both_px": inter, "c1_jaccard": inter / union if union else np.nan,
                         "c1_main_matched_pm1": float((a1 & near).sum() / a1.sum()) if a1.any() else np.nan})
            prev, cur = cur, nxt
    df = pd.DataFrame(rows)
    for k in ("c1", "any"):
        df[f"{k}_diff_px"] = df[f"{k}_main_px"] - df[f"{k}_other_px"]
        df[f"{k}_diff_pct"] = 100 * df[f"{k}_diff_px"] / df[f"{k}_other_px"].replace(0, np.nan)
    return df
