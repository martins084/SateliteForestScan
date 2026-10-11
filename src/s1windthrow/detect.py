"""Change index, stable-forest robust z, classes and polygons (pure numpy / geopandas)."""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import geopandas as gpd
import numpy as np
from affine import Affine
from rasterio.features import shapes
from scipy import ndimage
from shapely.geometry import shape

MAD_SCALE = 1.4826
CLASS_NONE, CLASS_WINDTHROW, CLASS_CUT_LIKE = 0, 1, 2
CLASS_NAMES = {CLASS_WINDTHROW: "windthrow", CLASS_CUT_LIKE: "cut_like"}


@dataclass
class OrbitDelta:
    rel_orbit: int
    direction: str
    d_vv: np.ndarray        # post - pre [dB]
    d_vh: np.ndarray
    n_pre: np.ndarray       # acquisitions with data per pixel
    n_post: np.ndarray
    pre_dates: list[str]
    post_dates: list[str]


def combine_orbits(deltas: list[OrbitDelta]) -> dict[str, np.ndarray]:
    """Mean dVV, dVH over the orbits available per pixel; index = dVH + dVV; n_orbits."""
    vv = np.stack([d.d_vv for d in deltas])
    vh = np.stack([d.d_vh for d in deltas])
    both = np.isfinite(vv) & np.isfinite(vh)
    vv = np.where(both, vv, np.nan)
    vh = np.where(both, vh, np.nan)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        d_vv = np.nanmean(vv, axis=0)
        d_vh = np.nanmean(vh, axis=0)
    return {"d_vv": d_vv.astype("float32"), "d_vh": d_vh.astype("float32"),
            "index": (d_vh + d_vv).astype("float32"),
            "n_orbits": both.sum(axis=0).astype("int16")}


def robust_z(index: np.ndarray, stable: np.ndarray) -> tuple[np.ndarray, float, float, int]:
    """z = (x - median_stable) / (1.4826 * MAD_stable). Returns (z, median, MAD, n_stable)."""
    v = index[stable & np.isfinite(index)]
    if v.size == 0:
        raise ValueError("no stable-forest pixels with a valid index")
    med = float(np.median(v))
    mad = float(np.median(np.abs(v - med)))
    if mad <= 0:
        raise ValueError("MAD of the stable forest is zero")
    return ((index - med) / (MAD_SCALE * mad)).astype("float32"), med, mad, int(v.size)


def classify(z: np.ndarray, analysis: np.ndarray, k: float) -> np.ndarray:
    cls = np.full(z.shape, CLASS_NONE, dtype="uint8")
    with np.errstate(invalid="ignore"):
        cls[analysis & (z >= k)] = CLASS_WINDTHROW
        cls[analysis & (z <= -k)] = CLASS_CUT_LIKE
    return cls


def apply_mmu(cls: np.ndarray, min_pixels: int) -> tuple[np.ndarray, np.ndarray]:
    """Remove 8-connected patches smaller than `min_pixels`, per class.
    Returns (filtered classes, label image with unique ids across classes)."""
    out = np.zeros_like(cls)
    labels = np.zeros(cls.shape, dtype="int32")
    nxt = 0
    for c in (CLASS_WINDTHROW, CLASS_CUT_LIKE):
        lab, n = ndimage.label(cls == c, structure=np.ones((3, 3), dtype=int))
        if n == 0:
            continue
        sizes = ndimage.sum(np.ones_like(lab), lab, index=np.arange(1, n + 1))
        keep = np.flatnonzero(sizes >= min_pixels) + 1
        for lid in keep:
            nxt += 1
            sel = lab == lid
            out[sel] = c
            labels[sel] = nxt
    return out, labels


def count_area(cls_mmu: np.ndarray, labels: np.ndarray, pixel_ha: float) -> dict:
    res = {}
    for c, name in CLASS_NAMES.items():
        ids = np.unique(labels[cls_mmu == c])
        res[f"n_{name}"] = int(ids.size)
        res[f"ha_{name}"] = round(float((cls_mmu == c).sum() * pixel_ha), 2)
    return res


def polygonize(labels: np.ndarray, cls: np.ndarray, transform: Affine, crs: str,
               layers: dict[str, np.ndarray], pixel_ha: float) -> gpd.GeoDataFrame:
    """One polygon per label; mean of each layer in `layers` over the polygon pixels."""
    geoms: dict[int, list] = {}
    for geom, val in shapes(labels, mask=labels > 0, transform=transform, connectivity=8):
        geoms.setdefault(int(val), []).append(shape(geom))
    rows = []
    idx = ndimage.find_objects(labels)
    for lab, sl in enumerate(idx, start=1):
        if sl is None:
            continue
        sel = labels[sl] == lab
        row = {"id": lab, "class": CLASS_NAMES[int(cls[sl][sel][0])],
               "area_ha": round(float(sel.sum() * pixel_ha), 3), "n_pixels": int(sel.sum())}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            for name, arr in layers.items():
                row[name] = float(np.nanmean(arr[sl][sel]))
        from shapely.ops import unary_union
        row["geometry"] = unary_union(geoms[lab])
        rows.append(row)
    if not rows:
        return gpd.GeoDataFrame(columns=["id", "class", "area_ha", "n_pixels", "geometry"],
                                geometry="geometry", crs=crs)
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=crs)
