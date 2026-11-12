"""CHMv2 imagery dates (stage 7c, user 2026-11-12): leakage check of the canopy height feature.

Source: `forests/v2/global/dinov3_global_chm_v2_ml3/metadata/<z10 quadkey>.geojson` next to the CHMv2 tiles: polygons
(EPSG:4326) with one property `acq_date` = "observation date of the input imagery" (dataset notebook
facebookresearch/dinov3 notebooks/chmv2_dataset_exploration.ipynb). One tile has several dates, so the date is taken
per 30 m cell: the tile polygons are rasterised on a regular lon / lat grid of the tile (n x n, ~5 m at 57 N) and
sampled at the cell centre and at 8 points +-10 m around it (the 30 m aggregate mixes sub-pixels of the whole cell).
Dates are int32 yyyymmdd, 0 = no polygon (unknown date). Leakage rule: the CHM value of a cell may be used in year y
only if the LATEST date in the cell is in a year < y."""
from __future__ import annotations

import math

import numpy as np
from rasterio import features as rfeatures
from rasterio.enums import MergeAlg
from rasterio.transform import from_bounds

OFFSETS_M = [(dx, dy) for dy in (-10.0, 0.0, 10.0) for dx in (-10.0, 0.0, 10.0)]   # index 4 = cell centre


def tile_xy(lon: np.ndarray, lat: np.ndarray, z: int = 10) -> tuple[np.ndarray, np.ndarray]:
    """Web Mercator tile column / row of points (same rule as features.quadkey)."""
    n = 2 ** z
    s = np.sin(np.radians(lat))
    tx = np.clip(((np.asarray(lon) + 180.0) / 360.0 * n).astype(np.int64), 0, n - 1)
    ty = np.clip(((0.5 - np.log((1 + s) / (1 - s)) / (4 * math.pi)) * n).astype(np.int64), 0, n - 1)
    return tx, ty


def quadkey_of(tx: int, ty: int, z: int = 10) -> str:
    q = ""
    for i in range(z, 0, -1):
        m = 1 << (i - 1)
        q += str((1 if tx & m else 0) + (2 if ty & m else 0))
    return q


def tile_bounds(tx: int, ty: int, z: int = 10) -> tuple[float, float, float, float]:
    """lon0, lat0, lon1, lat1 of a Web Mercator tile."""
    n = 2 ** z
    lat = lambda r: math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * r / n))))  # noqa: E731
    return tx / n * 360.0 - 180.0, lat(ty + 1), (tx + 1) / n * 360.0 - 180.0, lat(ty)


def to_int(date: str) -> int:
    """'2019-09-09' -> 20190909 (raises on anything else: the format is part of the check)."""
    y, m, d = date.split("-")
    v = int(y) * 10000 + int(m) * 100 + int(d)
    if not (1990 <= int(y) <= 2100 and 1 <= int(m) <= 12 and 1 <= int(d) <= 31):
        raise ValueError(f"unexpected acq_date {date!r}")
    return v


def rasterize_dates(feats: list[dict], bounds: tuple[float, float, float, float], n: int = 4096) -> tuple[np.ndarray, dict]:
    """GeoJSON features with `acq_date` -> (n, n) int32 yyyymmdd raster on the regular lon / lat grid of `bounds`
    (0 = no polygon). Where polygons overlap the LATEST date wins (conservative for the leakage rule). Info: number
    of polygons, dates, share of pixels without a date and with more than one polygon."""
    tf = from_bounds(*bounds, n, n)
    shapes = sorted(((f["geometry"], to_int(f["properties"]["acq_date"])) for f in feats), key=lambda s: s[1])
    if not shapes:
        return np.zeros((n, n), np.int32), {"polygons": 0, "dates": [], "share_no_date": 1.0, "share_overlap": 0.0}
    r = rfeatures.rasterize(shapes, out_shape=(n, n), transform=tf, fill=0, dtype="int32")
    cnt = rfeatures.rasterize(((g, 1) for g, _ in shapes), out_shape=(n, n), transform=tf, fill=0, dtype="uint8",
                              merge_alg=MergeAlg.add)
    return r, {"polygons": len(shapes), "dates": sorted({v for _, v in shapes}), "share_no_date": float((r == 0).mean()),
               "share_overlap": float((cnt > 1).mean())}


def sample(raster: np.ndarray, bounds: tuple[float, float, float, float], lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    """Raster value at points inside `bounds` (points must belong to the tile)."""
    n = raster.shape[0]
    lon0, lat0, lon1, lat1 = bounds
    c = np.clip(((lon - lon0) / (lon1 - lon0) * n).astype(np.int64), 0, n - 1)
    r = np.clip(((lat1 - lat) / (lat1 - lat0) * n).astype(np.int64), 0, n - 1)
    return raster[r, c]


def year(d: np.ndarray) -> np.ndarray:
    """yyyymmdd -> year (0 stays 0 = unknown)."""
    return np.asarray(d) // 10000


def allowed(d_max: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Leakage rule: CHM usable for row-year y only if the latest image date in the cell is known and in a year < y."""
    dy = year(d_max)
    return (dy > 0) & (dy < np.asarray(y))
