"""Stage 5 descriptive analysis of EFDA in Latvia (no model, no conclusions on causes).

* patches: 8-connected patches of one agent in one year; area and a raster shape index
  SI = edge length / (4 * sqrt(area)) in pixel units (1 = square, larger = more elongated /
  irregular);
* grid: per `grid_km` cell of the EEA reference grid (EPSG:3035, multiples of the cell size);
* conifer cells: HRL Dominant Leaf Type 2018 sampled at `dlt_res_m` (server-side nearest),
  conifer share of tree cover (classes 1 + 2) per grid cell;
* official statistics: CSP tables MEB012 / MEZ012 (data: VMD).
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize
from scipy import ndimage

from .config import RiskConfig
from .efda import AGENTS, layer

EIGHT = np.ones((3, 3), bool)


def patch_stats(mask: np.ndarray, px_ha: float) -> pd.DataFrame:
    """Area (ha) and shape index of every 8-connected patch in `mask`."""
    lab, n = ndimage.label(mask, structure=EIGHT)
    if n == 0:
        return pd.DataFrame(columns=["area_ha", "shape_index"])
    area = np.bincount(lab.ravel(), minlength=n + 1)[1:]
    edges = np.zeros(n + 1, dtype=np.int64)
    padded = np.pad(lab, 1)
    core = padded[1:-1, 1:-1]
    for sl in ((slice(None, -2), slice(1, -1)), (slice(2, None), slice(1, -1)),
               (slice(1, -1), slice(None, -2)), (slice(1, -1), slice(2, None))):
        diff = (core != padded[sl]) & (core > 0)
        edges += np.bincount(core[diff], minlength=n + 1)
    edges = edges[1:]
    return pd.DataFrame({"area_ha": area * px_ha, "shape_index": edges / (4 * np.sqrt(area))})


def summarize_patches(p: pd.DataFrame) -> dict:
    if p.empty:
        return {"n_patches": 0}
    a = p["area_ha"]
    w = a / a.sum()
    return {"n_patches": len(p), "area_ha": a.sum(), "median_ha": a.median(),
            "p90_ha": a.quantile(0.9), "max_ha": a.max(),
            "share_area_ge1ha": a[a >= 1].sum() / a.sum(), "share_area_ge10ha": a[a >= 10].sum() / a.sum(),
            "si_median": p["shape_index"].median(), "si_area_weighted": float((p["shape_index"] * w).sum())}


def annual_patches(cfg: RiskConfig, country: np.ndarray, agents=(1, 3)) -> pd.DataFrame:
    v = cfg.efda.main
    rows = []
    with rasterio.open(layer(v, "agent")) as s:
        px_ha = s.res[0] * s.res[1] / 1e4
        for b in range(1, s.count + 1):
            a = s.read(b)
            for code in agents:
                rows.append({"year": v.first_year + b - 1, "agent": AGENTS[code],
                             **summarize_patches(patch_stats((a == code) & country, px_ha))})
    return pd.DataFrame(rows)


def cell_index(src: rasterio.DatasetReader, cell_m: float) -> tuple[np.ndarray, np.ndarray, int, float, float]:
    """Row / column cell index of every pixel row / column (EEA grid: cell edges at multiples
    of `cell_m`)."""
    xs = src.transform.c + (np.arange(src.width) + 0.5) * src.res[0]
    ys = src.transform.f - (np.arange(src.height) + 0.5) * src.res[1]
    x0, y1 = np.floor(xs.min() / cell_m) * cell_m, np.ceil(ys.max() / cell_m) * cell_m
    cc = ((xs - x0) // cell_m).astype(np.int32)
    rr = ((y1 - ys) // cell_m).astype(np.int32)
    return rr, cc, int(cc.max() + 1), x0, y1


def grid_counts(cfg: RiskConfig, country: np.ndarray, codes=(1, 3)) -> pd.DataFrame:
    """Pixels per grid cell x year x agent (inside the country) + forest pixels per cell."""
    v = cfg.efda.main
    cell_m = cfg.grid_km * 1000
    rows = []
    with rasterio.open(layer(v, "agent")) as s:
        rr, cc, ncol, x0, y1 = cell_index(s, cell_m)
        for b in range(1, s.count + 1):
            a = s.read(b)
            for code in codes:
                r, c = np.nonzero((a == code) & country)
                if r.size == 0:
                    continue
                ids, n = np.unique(rr[r] * ncol + cc[c], return_counts=True)
                rows.append(pd.DataFrame({"cell": ids, "year": v.first_year + b - 1,
                                          "agent": AGENTS[code], "px": n}))
    with rasterio.open(layer(v, "forest")) as s:
        r, c = np.nonzero((s.read(1) == 1) & country)
        ids, n = np.unique(rr[r] * ncol + cc[c], return_counts=True)
    forest = pd.DataFrame({"cell": ids, "forest_px": n})
    out = pd.concat(rows, ignore_index=True)
    out.attrs.update(ncol=ncol, x0=x0, y1=y1, cell_m=cell_m)
    forest.attrs.update(out.attrs)
    return out, forest


def cell_geometry(ids: np.ndarray, attrs: dict) -> gpd.GeoSeries:
    from shapely.geometry import box

    m, ncol = attrs["cell_m"], attrs["ncol"]
    r, c = np.divmod(ids, ncol)
    x = attrs["x0"] + c * m
    y = attrs["y1"] - r * m
    return gpd.GeoSeries([box(a, b - m, a + m, b) for a, b in zip(x, y)], crs=3035)


def conifer_share(cfg: RiskConfig, regions: gpd.GeoDataFrame, cells_attrs: dict) -> pd.DataFrame:
    """Conifer share of HRL DLT 2018 tree cover per grid cell (cached GeoTIFF)."""
    from s2forest.forestmask import _download_dlt

    res = cfg.conifer.dlt_res_m
    cache = cfg.cache_dir / "rm" / f"hrl_dlt2018_{cfg.boundaries.country}_{int(res)}m.tif"
    if cache.exists():
        with rasterio.open(cache) as s:
            dlt, tr = s.read(1), s.transform
    else:
        minx, miny, maxx, maxy = regions.total_bounds
        dlt, tr = _download_dlt((minx - 1000, miny - 1000, maxx + 1000, maxy + 1000), res=res)
        cache.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(cache, "w", driver="GTiff", width=dlt.shape[1], height=dlt.shape[0], count=1,
                           dtype="uint8", crs="EPSG:3035", transform=tr, nodata=255, compress="deflate") as f:
            f.write(dlt, 1)
    inside = rasterize([(g, 1) for g in regions.geometry], out_shape=dlt.shape, transform=tr,
                       fill=0, dtype="uint8") > 0
    m, ncol = cells_attrs["cell_m"], cells_attrs["ncol"]
    ys = tr.f + (np.arange(dlt.shape[0]) + 0.5) * tr.e
    xs = tr.c + (np.arange(dlt.shape[1]) + 0.5) * tr.a
    rr = ((cells_attrs["y1"] - ys) // m).astype(np.int64)
    cc = ((xs - cells_attrs["x0"]) // m).astype(np.int64)
    out = {}
    for k, cls in (("broadleaf", 1), ("conifer", 2)):
        r, c = np.nonzero((dlt == cls) & inside)
        ids, n = np.unique(rr[r] * ncol + cc[c], return_counts=True)
        out[k] = pd.Series(n, index=ids)
    df = pd.DataFrame(out).fillna(0)
    df["conifer_share"] = df["conifer"] / (df["conifer"] + df["broadleaf"]).replace(0, np.nan)
    df.index.name = "cell"
    df.attrs["path"] = str(cache)
    return df.reset_index()


def read_csp(path: Path, id_cols: int) -> pd.DataFrame:
    """CSP PxWeb CSV (wide: '<indicator> <year>' columns) -> long."""
    d = pd.read_csv(path, encoding="utf-8-sig")
    ids = list(d.columns[:id_cols])
    long = d.melt(id_vars=ids, var_name="col", value_name="value")
    long["year"] = long["col"].str.extract(r"(\d{4})$").astype(int)
    long["indicator"] = long["col"].str.replace(r"\s*\d{4}$", "", regex=True)
    long["value"] = pd.to_numeric(long["value"].astype(str).str.replace(",", "."), errors="coerce")
    return long.drop(columns="col")


def kalsnava(cfg: RiskConfig) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """EFDA classes 1 / 3 in the Kalsnava AOI per year, and the EFDA history of the s2forest
    cut polygons of `kalsnava.year` (context only: EFDA ends 2024)."""
    k = cfg.kalsnava
    v = cfg.efda.main
    aoi = gpd.read_file(k.aoi).to_crs(3035)
    cuts = gpd.read_file(k.suspects, layer=f"suspects_{k.year}")
    cuts = cuts[cuts["type"] == "cut"].to_crs(3035)
    with rasterio.open(layer(v, "agent")) as s:
        win = rasterio.windows.from_bounds(*aoi.total_bounds, transform=s.transform).round_offsets().round_lengths()
        a = s.read(window=win)
        tr = s.window_transform(win)
        px_ha = s.res[0] * s.res[1] / 1e4
    shape = a.shape[1:]
    in_aoi = rasterize([(g, 1) for g in aoi.geometry], out_shape=shape, transform=tr, fill=0) > 0
    in_cut = rasterize([(g, 1) for g in cuts.geometry], out_shape=shape, transform=tr, fill=0) > 0
    with rasterio.open(layer(v, "forest")) as s:
        forest = s.read(1, window=win) == 1
    years = v.first_year + np.arange(a.shape[0])
    rows = []
    for i, y in enumerate(years):
        for code in (1, 3):
            m = a[i] == code
            rows.append({"year": int(y), "agent": AGENTS[code], "aoi_ha": (m & in_aoi).sum() * px_ha,
                         "in_s2cut_ha": (m & in_cut).sum() * px_ha})
    per_year = pd.DataFrame(rows)
    disturbed_any = np.isin(a, (1, 2, 3))
    last = np.where(disturbed_any.any(0), years[::-1][np.argmax(disturbed_any[::-1], axis=0)], 0)
    prow = []
    for _, c in cuts.iterrows():
        m = rasterize([(c.geometry, 1)], out_shape=shape, transform=tr, fill=0) > 0
        n = int(m.sum())
        if n == 0:
            continue
        hist = {f"share_{AGENTS[code]}_ever": float((a[:, m] == code).any(0).mean()) for code in (1, 3)}
        ly = last[m][last[m] > 0]
        prow.append({"id": int(c["id"]), "area_ha": c["area_ha"], "status": c["status"],
                     "first_detected": c["first_detected"], "efda_px": n, **hist,
                     "share_any_ever": float(disturbed_any[:, m].any(0).mean()),
                     "latest_efda_year_mode": int(pd.Series(ly).mode().iloc[0]) if ly.size else None,
                     "efda_forest_share": float(forest[m].mean())})
    summary = {"aoi_efda_forest_ha": float((forest & in_aoi).sum() * px_ha),
               "s2_cut_polygons": len(cuts), "s2_cut_ha": float(cuts["area_ha"].sum())}
    return per_year, pd.DataFrame(prow), summary
