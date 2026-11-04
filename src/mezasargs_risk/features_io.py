"""Stage 6a I/O: inputs of one block on the EFDA v3.0 30 m grid (EPSG:3035) and the training table.
Pure feature logic and the leakage guard are in `features.py`."""

from __future__ import annotations

import time
import tracemalloc

import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.warp import reproject
from rasterio.windows import Window, from_bounds
from shapely.geometry import box

from . import features as F
from . import lvm as LV
from .config import RiskConfig
from .efda import layer


def _bounds_3035(b3059, margin=0.0):
    x0, y0, x1, y1 = b3059
    tr = Transformer.from_crs(3059, 3035, always_xy=True)
    xs, ys = tr.transform([x0 - margin, x1 + margin, x0 - margin, x1 + margin], [y0 - margin, y0 - margin, y1 + margin, y1 + margin])
    return min(xs), min(ys), max(xs), max(ys)


def block_inputs(cfg: RiskConfig, years: tuple[int, int]) -> dict:
    """Window of the EFDA grid around the block (+ margin) with every input layer of the block."""
    fc, v = cfg.features, cfg.efda.main
    with rasterio.open(layer(v, "agent")) as s, rasterio.open(layer(v, "forest")) as fm:
        w = from_bounds(*_bounds_3035(fc.block_3059, fc.margin_m), transform=s.transform)
        w = Window(int(np.floor(w.col_off)), int(np.floor(w.row_off)), int(np.ceil(w.width)), int(np.ceil(w.height)))
        tf, shape = s.window_transform(w), (int(w.height), int(w.width))
        first, last = v.first_year, v.first_year + s.count - 1
        efda = {y: s.read(y - first + 1, window=w) for y in range(max(first, years[0] - 12), min(last, years[1]) + 1)}
        forest = fm.read(1, window=w) == 1
        full_w = s.width
    rows, cols = np.indices(shape)
    xs, ys = rasterio.transform.xy(tf, rows.ravel(), cols.ravel())
    xs, ys = np.asarray(xs), np.asarray(ys)
    x59, y59 = Transformer.from_crs(3035, 3059, always_xy=True).transform(xs, ys)
    x0, y0, x1, y1 = fc.block_3059
    inner = ((x59 >= x0) & (x59 < x1) & (y59 >= y0) & (y59 < y1)).reshape(shape)
    lon, lat = Transformer.from_crs(3035, 4326, always_xy=True).transform(xs, ys)
    clim_cell = (np.round(np.asarray(lat) * 10).astype(np.int64) * 10000 + np.round(np.asarray(lon) * 10).astype(np.int64)).reshape(shape)
    cell_id = (rows + int(w.row_off)).astype(np.int64) * full_w + (cols + int(w.col_off))
    # LVM land units (centre) and LVM 620 polygons per registration year (share from 3 x 3 sub-cells, centre)
    bb59 = (x0 - fc.margin_m, y0 - fc.margin_m, x1 + fc.margin_m, y1 + fc.margin_m)
    land = LV.load_land(cfg.lvm, bbox=bb59).to_crs(3035)
    lvm_land = rasterize(((g, 1) for g in land.geometry), out_shape=shape, transform=tf, fill=0, dtype="uint8") == 1
    g = LV.load_damage(cfg.lvm, bbox=bb59)
    g = g[(g["subtype"] == cfg.lvm.stem_pest) & ~g["empty"]].copy()
    g = g[g["year"].notna()]
    g["year"] = g["year"].astype(int)
    g = g.to_crs(3035)
    sub_tf = tf * rasterio.Affine.scale(1 / 3)
    share, centre = {}, {}
    for y, grp in g.groupby("year"):
        if not years[0] - 12 <= y <= years[1]:
            continue
        sub = rasterize(((geom, 1) for geom in grp.geometry), out_shape=(shape[0] * 3, shape[1] * 3), transform=sub_tf,
                        fill=0, dtype="uint8")
        share[int(y)] = sub.reshape(shape[0], 3, shape[1], 3).mean(axis=(1, 3)).astype(np.float32)
        centre[int(y)] = rasterize(((geom, 1) for geom in grp.geometry), out_shape=shape, transform=tf, fill=0,
                                   dtype="uint8") == 1
    # HRL DLT 2018 (100 m) -> 30 m nearest; conifer share of tree cover within 500 m
    dlt = np.full(shape, 255, dtype=np.uint8)
    with rasterio.open(fc.hrl_dlt) as h:
        reproject(rasterio.band(h, 1), dlt, dst_transform=tf, dst_crs="EPSG:3035", resampling=Resampling.nearest,
                  dst_nodata=255)
    con = (dlt == 2).astype(np.float32)
    tree = np.isin(dlt, (1, 2)).astype(np.float32)
    k = F.disk(500)
    with np.errstate(invalid="ignore", divide="ignore"):
        con500 = np.where(F.area_within(tree, 500) > 0, F.area_within(con, 500) / F.area_within(tree, 500), np.nan)
    static = {"hrl_conifer_100m": np.where(dlt == 255, np.nan, (dlt == 2).astype(np.float32)),
              "hrl_conifer_share_500m": con500.astype(np.float32)}
    del k
    return {"tf": tf, "shape": shape, "efda": efda, "forest": forest, "inner": inner, "lvm_land": lvm_land,
            "share": share, "centre": centre, "clim_cell": clim_cell, "cell_id": cell_id, "static": static,
            "window": w, "n_polygons": int(len(g)), "lonlat_centre": (float(np.mean(lon)), float(np.mean(lat)))}


def chm_layers(cfg: RiskConfig, inp: dict) -> tuple[dict, dict]:
    """CHMv2 -> 3 m grid aligned with the block's 30 m grid (rows / cols of the inner bounding box only) by
    windowed COG reads (no tile is stored) -> mean, p90, share > 5 m per 30 m cell. Returns layers and read info."""
    fc = cfg.features
    rr, cc = np.nonzero(inp["inner"])
    r0, r1, c0, c1 = rr.min(), rr.max() + 1, cc.min(), cc.max() + 1
    tf_in = inp["tf"] * rasterio.Affine.translation(c0, r0)
    tf3 = tf_in * rasterio.Affine.scale(1 / 10)
    out = np.full(((r1 - r0) * 10, (c1 - c0) * 10), 255, dtype=np.uint8)
    xs, ys = rasterio.transform.xy(tf_in, [0, 0, r1 - r0, r1 - r0], [0, c1 - c0, 0, c1 - c0])
    lon, lat = Transformer.from_crs(3035, 4326, always_xy=True).transform(xs, ys)
    qks = sorted({F.quadkey(lo, la, 10) for lo in np.linspace(min(lon), max(lon), 9) for la in np.linspace(min(lat), max(lat), 9)})
    info = {"tiles": qks, "seconds": 0.0}
    t0 = time.time()
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
                      GDAL_HTTP_MAX_RETRY="3", GDAL_HTTP_RETRY_DELAY="5"):
        for qk in qks:
            tmp = np.full(out.shape, 255, dtype=np.uint8)
            with rasterio.open("/vsicurl/" + fc.chm_url.format(qk=qk)) as s:
                reproject(rasterio.band(s, 1), tmp, src_nodata=None, dst_transform=tf3, dst_crs="EPSG:3035",
                          dst_nodata=255, resampling=Resampling.nearest)
            m = tmp != 255
            out[m] = tmp[m]
    info["seconds"] = round(time.time() - t0, 1)
    chm = np.where(out == 255, np.nan, out.astype(np.float32))
    agg = {k: np.full(inp["shape"], np.nan, dtype=np.float32) for k in ("chm_mean", "chm_p90", "chm_gt5")}
    for a in range(0, r1 - r0, 100):                       # row chunks: (100, W, 100) float32
        part = F.chm_aggregate(chm[a * 10:(a + 100) * 10])
        for k, v in part.items():
            agg[k][r0 + a:r0 + a + v.shape[0], c0:c1] = v
    info["coverage"] = float(np.isfinite(chm).mean())
    return agg, info


def climate_table(climate_dir) -> pd.DataFrame:
    wb = pd.read_csv(climate_dir / "latvia" / "water_balance_cells.csv")
    ph = pd.read_csv(climate_dir / "latvia" / "rity2_cells.csv")
    cols = ["tsum_F1", "tsum_F2", "swarming_doy", "n_filial", "n_filial_inca"]
    t = wb[["year", "latitude", "longitude", "cwb_z"]].merge(ph[["year", "latitude", "longitude"] + cols],
                                                           on=["year", "latitude", "longitude"], how="outer")
    t["clim_cell"] = np.round(t["latitude"] * 10).astype(np.int64) * 10000 + np.round(t["longitude"] * 10).astype(np.int64)
    return t.set_index(["year", "clim_cell"])[["cwb_z"] + cols].sort_index()


def training_table(cfg: RiskConfig) -> tuple[pd.DataFrame, dict]:
    """Cell x year table of the pilot block with labels (2.5 schema), all features and timing / memory info."""
    fc = cfg.features
    tracemalloc.start()
    t0 = time.time()
    inp = block_inputs(cfg, fc.years)
    t_in = time.time() - t0
    chm, chm_info = ({}, {"tiles": [], "seconds": 0})
    if fc.chm:
        cpath = cfg.cache_dir / "rm" / "chmv2_30m" / ("block_%d_%d_%d_%d.npz" % tuple(fc.block_3059))
        if cpath.exists():                                  # derived 30 m layers of this block (not in git)
            z = np.load(cpath)
            chm = {k: z[k] for k in ("chm_mean", "chm_p90", "chm_gt5")}
            chm_info = {"tiles": str(z["tiles"]).split(","), "seconds": 0, "cached": str(cpath.name),
                        "coverage": float(z["coverage"])}
        else:
            chm, chm_info = chm_layers(cfg, inp)
            cpath.parent.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(cpath, **chm, tiles=",".join(chm_info["tiles"]), coverage=chm_info["coverage"])
    ctx = F.Ctx(shape=inp["shape"], lvm620=inp["share"], efda=inp["efda"], climate=climate_table(fc.climate_dir),
                clim_cell=inp["clim_cell"])
    sel = inp["inner"] & inp["forest"] & inp["lvm_land"]
    idx = np.nonzero(sel)
    parts, used = [], {}
    t1 = time.time()
    for t in range(fc.years[0], fc.years[1] + 1):
        f = F.year_features(ctx, t, cfg.efda.main.first_year)
        used[t] = {k: sorted(v) for k, v in ctx.used.items()}
        share_t = inp["share"].get(t, np.zeros(inp["shape"], np.float32))
        centre_t = inp["centre"].get(t, np.zeros(inp["shape"], bool))
        lab, conf = F.labels(share_t, centre_t)
        d = {"cell_id": inp["cell_id"][idx], "year": np.full(len(idx[0]), t, np.int16), "label": lab[idx],
             "confidence": conf[idx]}
        d["in_set"] = (f["years_since_dist"][idx] > fc.k_exclude).astype(np.uint8)
        for k, v in f.items():
            d[k] = v[idx]
        for k, v in inp["static"].items():
            d[k] = v[idx]
        d["hrl_after_t"] = np.full(len(idx[0]), t <= 2018, np.uint8)   # HRL 2018 snapshot not before t (2.4)
        for k, v in chm.items():
            d[k] = v[idx] if t >= fc.chm_from_year else np.full(len(idx[0]), np.nan, np.float32)
        parts.append(pd.DataFrame(d))
    tab = pd.concat(parts, ignore_index=True)
    tab.insert(4, "source", fc.source)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    info = {"window": [int(inp["window"].col_off), int(inp["window"].row_off), int(inp["window"].width),
                       int(inp["window"].height)],
            "cells_inner": int(inp["inner"].sum()), "cells_forest_lvm": int(sel.sum()),
            "polygons_620_in_window": inp["n_polygons"], "seconds_inputs": round(t_in, 1),
            "seconds_features": round(time.time() - t1, 1), "seconds_total": round(time.time() - t0, 1),
            "peak_traced_mb": round(peak / 2 ** 20, 1), "chm": chm_info, "years_used": used}
    return tab, info
