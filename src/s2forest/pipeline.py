"""Pipeline steps shared by the CLI and the demo notebook."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from .config import Config
from .fetch import Grid, build_grid, open_cube
from .forestmask import (FOREST_ANALYSED, FOREST_NOT_IN_HRL, forest_mask, refine_forest_mask,
                         summer_median)
from .indices import INDICES, compute_indices
from .io import write_geotiff, write_timeseries_geotiff

if TYPE_CHECKING:
    import geopandas as gpd  # noqa: F401

OUTSIDE_AOI = 255


@dataclass
class IndexStage:
    cube: xr.Dataset          # masked reflectance (time, y, x)
    indices: xr.Dataset       # index values (time, y, x)
    grid: Grid
    forest_codes: np.ndarray  # FOREST_* codes, OUTSIDE_AOI outside the AOI
    ndvi_summer_baseline: np.ndarray
    linear_lines: "gpd.GeoDataFrame | None" = None   # OSM lines used for the mask

    @property
    def analysis_mask(self) -> np.ndarray:
        return self.forest_codes == FOREST_ANALYSED


def haze_diagnostics(cfg: Config) -> pd.DataFrame:
    """Per date: SCL-valid AOI pixels, pixels masked by the haze test, unresolved (kept)."""
    c = cfg.model_copy(deep=True)
    c.data.min_valid_fraction = 0.0
    cube = open_cube(c)
    grid = build_grid(cfg)
    region = xr.DataArray(grid.aoi_mask, dims=("y", "x"))
    if "haze" not in cube:
        return pd.DataFrame()
    stats = xr.Dataset({
        "scl_valid": ((cube.valid | cube.haze) & region).sum(("y", "x")),
        "haze_masked": (cube.haze & region).sum(("y", "x")),
        "haze_unresolved": (cube.haze_unresolved & region).sum(("y", "x")),
    }).compute()
    df = stats.to_dataframe()[["scl_valid", "haze_masked", "haze_unresolved"]].reset_index()
    df["acq_key"] = cube.acq_key.values
    df["masked_frac"] = df["haze_masked"] / df["scl_valid"].clip(lower=1)
    df["unresolved_frac"] = df["haze_unresolved"] / df["scl_valid"].clip(lower=1)
    n_aoi = int(grid.aoi_mask.sum())
    df["valid_frac_before"] = df["scl_valid"] / n_aoi
    df["valid_frac_after"] = (df["scl_valid"] - df["haze_masked"]) / n_aoi
    df["dropped"] = (df["valid_frac_before"] >= cfg.data.min_valid_fraction) & (
        df["valid_frac_after"] < cfg.data.min_valid_fraction)
    return df


def index_stage(cfg: Config) -> IndexStage:
    cube = open_cube(cfg)
    grid = build_grid(cfg)
    names = list(dict.fromkeys(["ndvi", *cfg.indices]))  # NDVI always needed for the mask
    idx = compute_indices(cube, names)

    fm = cfg.forest_mask
    hrl = forest_mask(grid.geobox, cfg.cache_dir / grid.key, fm.source, fm.classes)
    if hrl is None:
        hrl = np.ones(grid.geobox.shape, dtype=bool)
    ndvi_s = summer_median(idx.ndvi, cfg.time.baseline_year_list, fm.summer_start,
                           fm.summer_end).values
    codes = refine_forest_mask(hrl, ndvi_s, fm.min_summer_ndvi)
    from .forestmask import FOREST_LINEAR
    from .linear import linear_mask

    lin, lines = linear_mask(grid.geobox, cfg.linear_features, cfg.cache_dir / grid.key)
    if lin is not None:
        codes[lin & (codes != FOREST_NOT_IN_HRL)] = FOREST_LINEAR
    codes[~grid.aoi_mask] = OUTSIDE_AOI
    return IndexStage(cube=cube, indices=idx, grid=grid, forest_codes=codes,
                      ndvi_summer_baseline=ndvi_s, linear_lines=lines)


def write_index_outputs(cfg: Config, st: IndexStage) -> dict[str, Path]:
    """GeoTIFFs: forest mask, per-index time series and per-year summer medians."""
    crs = cfg.data.crs
    rdir = cfg.run_dir / "rasters"
    written: dict[str, Path] = {}
    template = st.cube.B04.isel(time=0, drop=True)
    written["forest_mask"] = write_geotiff(
        template.copy(data=st.forest_codes), rdir / "forest_mask.tif", crs, dtype="uint8",
        nodata=OUTSIDE_AOI, band_names=["forest code: 0 not HRL class, 1 analysed, "
                                        "2 low summer NDVI, 3 no summer data, 4 road buffer"])
    written["ndvi_summer_baseline"] = write_geotiff(
        template.copy(data=st.ndvi_summer_baseline.astype("float32")),
        rdir / "ndvi_summer_median_baseline.tif", crs, band_names=["NDVI summer median, baseline"])

    fm = cfg.forest_mask
    for name in cfg.indices:
        da = st.indices[name].compute()
        written[f"{name}_timeseries"] = write_timeseries_geotiff(
            da, rdir / "indices" / f"{name}_timeseries.tif", crs)
        for year in cfg.time.years:
            med = summer_median(da, [year], fm.summer_start, fm.summer_end)
            written[f"{name}_summer_{year}"] = write_geotiff(
                med.astype("float32"), rdir / "indices" / f"{name}_summer_median_{year}.tif", crs,
                band_names=[f"{name} summer median {year}"])
    return written


def summer_change(cfg: Config, st: IndexStage, name: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(baseline summer median, monitoring summer median, stress-oriented change)."""
    fm = cfg.forest_mask
    da = st.indices[name]
    base = summer_median(da, cfg.time.baseline_year_list, fm.summer_start, fm.summer_end).values
    mon = summer_median(da, [cfg.time.monitor_year], fm.summer_start, fm.summer_end).values
    return base, mon, (mon - base) * INDICES[name].stress_sign


@dataclass
class DetectStage:
    features: xr.Dataset        # per-pixel detection features (y, x)
    z: xr.DataArray             # (index, time_mon, y, x)
    delta: xr.DataArray         # (index, time_mon, y, x)
    polygons: "gpd.GeoDataFrame"
    offsets: pd.DataFrame       # regional normalization per date and index
    status_codes: np.ndarray    # STATUS_* per pixel
    targets: "gpd.GeoDataFrame"  # drone target layer (with mission_id)
    missions: "gpd.GeoDataFrame"  # drone missions, ranked


# Per-pixel status raster codes.
STATUS_OK = 0
STATUS_STRESS = 1
STATUS_CUT = 2
STATUS_BASELINE_DISTURBED = 3
STATUS_NOT_ANALYSED = 4       # non-forest, excluded by the mask, or no baseline


def _stack(ds: xr.Dataset, names: list[str]) -> xr.DataArray:
    return ds[names].to_array("index").transpose("index", "time", "y", "x")


def context_offsets(cfg: Config, st: IndexStage, p) -> tuple[pd.DataFrame, np.ndarray]:
    """Two-pass regional normalization offsets on the coarse context grid.

    Returns (table with one row per AOI date, offsets array (index, time)).
    """
    from odc.geo.geobox import GeoBox

    from .anomaly import apply_baseline_exclusion, regional_offsets, run_detection
    from .forestmask import forest_fraction
    from .temporal import time_info

    names = p.names
    grid = st.grid
    ctx = open_cube(cfg, context=True)
    ctx = ctx.sel(time=st.cube.time.values)
    ctx_idx = compute_indices(ctx, list(dict.fromkeys(["ndvi", *names])))
    vals = _stack(ctx_idx, names).values

    fine = GeoBox.from_bbox(grid.context.boundingbox, crs=grid.context.crs,
                            resolution=cfg.data.resolution)
    frac = forest_fraction(grid.context, fine, cfg.cache_dir / grid.key, cfg.forest_mask.classes)
    forest = frac >= cfg.anomaly.normalization.min_forest_fraction
    fm = cfg.forest_mask
    if fm.min_summer_ndvi is not None:
        nd = summer_median(ctx_idx.ndvi, cfg.time.baseline_year_list, fm.summer_start,
                           fm.summer_end).values
        with np.errstate(invalid="ignore"):
            forest &= nd >= fm.min_summer_ndvi

    doy, year = time_info(ctx.time.values)
    norm = cfg.anomaly.normalization
    off1, _ = regional_offsets(vals, doy, year, forest, p, min_pixels=norm.min_pixels)
    da1 = xr.DataArray(vals - off1[:, :, None, None], dims=("index", "time", "y", "x"),
                       coords={"index": names, "time": ctx.time.values, "y": ctx.y, "x": ctx.x})
    feats1, _, _ = run_detection(da1.where(xr.DataArray(forest, dims=("y", "x"))), p)
    feats1 = apply_baseline_exclusion(feats1, 1)
    flagged = (np.nan_to_num(feats1["flag"].values) > 0) | (
        np.nan_to_num(feats1["baseline_disturbed"].values) > 0)
    off2, counts = regional_offsets(vals, doy, year, forest, p, exclude=flagged,
                                    min_pixels=norm.min_pixels)

    table = pd.DataFrame({"time": pd.DatetimeIndex(ctx.time.values), "context_pixels": counts,
                          "context_forest_pixels": int(forest.sum()),
                          "context_excluded_flagged": int((forest & flagged).sum())})
    for i, n in enumerate(names):
        table[f"offset_{n}"] = off2[i]
        table[f"offset_pass1_{n}"] = off1[i]
    table["normalized"] = counts >= norm.min_pixels
    return table, off2


def add_linear_attributes(gdf: "gpd.GeoDataFrame", lines, threshold: float) -> "gpd.GeoDataFrame":
    """elongation, dist_to_road_m and the `linear_feature` flag for stress polygons."""
    from .linear import elongation

    if gdf.empty:
        return gdf
    gdf = gdf.copy()
    gdf["elongation"] = [round(elongation(g), 2) for g in gdf.geometry]
    if lines is not None and len(lines):
        roads = lines[lines["kind"] == "road"].to_crs(gdf.crs)
        if len(roads):
            u = roads.geometry.union_all()
            gdf["dist_to_road_m"] = [round(float(g.distance(u)), 1) for g in gdf.geometry]
    gdf["linear_feature"] = (gdf["type"] == "stress") & (gdf["elongation"] >= threshold)
    return gdf


def detect_stage(cfg: Config, st: IndexStage) -> DetectStage:
    from .anomaly import apply_baseline_exclusion, params_from_config, run_detection
    from .vectorize import polygonize

    names = list(cfg.indices)
    p = params_from_config(cfg.anomaly, names, cfg.time.baseline_year_list, cfg.time.monitor_year)
    values = _stack(st.indices, names)
    values = values.where(xr.DataArray(st.analysis_mask, dims=("y", "x")))

    if cfg.anomaly.normalization.enabled:
        offsets, off = context_offsets(cfg, st, p)
        values = values - xr.DataArray(off, dims=("index", "time"),
                                       coords={"index": names, "time": values.time})
    else:
        offsets = pd.DataFrame({"time": pd.DatetimeIndex(values.time.values)})

    feats, z, delta = run_detection(values, p)
    min_px = int(np.ceil(cfg.anomaly.min_area_ha * 1e4 / cfg.data.resolution ** 2))
    feats = apply_baseline_exclusion(feats, min_px)
    gdf = polygonize(feats, z, delta, cfg.data.crs, cfg.anomaly.min_area_ha, p.k,
                     p.persistence, p.min_obs, primary=cfg.anomaly.primary_index,
                     status_min_obs=cfg.anomaly.status_min_obs)
    gdf = add_linear_attributes(gdf, st.linear_lines, cfg.linear_features.elongation_threshold)

    codes = np.full(st.forest_codes.shape, STATUS_NOT_ANALYSED, dtype="uint8")
    flag = feats["flag"].values
    codes[flag == 0] = STATUS_OK
    cut = np.nan_to_num(feats["is_cut"].values) > 0
    codes[(flag == 1) & ~cut] = STATUS_STRESS
    codes[(flag == 1) & cut] = STATUS_CUT
    codes[np.nan_to_num(feats["baseline_disturbed"].values) > 0] = STATUS_BASELINE_DISTURBED
    codes[~st.analysis_mask] = STATUS_NOT_ANALYSED
    codes[st.forest_codes == OUTSIDE_AOI] = OUTSIDE_AOI
    from .targets import build_missions, build_targets

    targets = build_targets(cfg, gdf, feats, st.analysis_mask, st.cube.B04.isel(time=0, drop=True))
    missions, targets = build_missions(cfg, targets)
    return DetectStage(features=feats, z=z, delta=delta, polygons=gdf, offsets=offsets,
                       status_codes=codes, targets=targets, missions=missions)


def status_summary(polygons: "gpd.GeoDataFrame") -> pd.DataFrame:
    """Polygon counts and area per type and status."""
    if polygons.empty or "status" not in polygons:
        return pd.DataFrame(columns=["type", "status", "n", "area_ha"])
    return (polygons.groupby(["type", "status"])["area_ha"].agg(n="size", area_ha="sum")
            .round(2).reset_index())


def write_detect_outputs(cfg: Config, st: IndexStage, ds: DetectStage) -> dict[str, Path]:
    crs = cfg.data.crs
    year = cfg.time.monitor_year
    rdir = cfg.run_dir / "rasters" / "anomaly"
    vdir = cfg.run_dir / "vectors"
    tdir = cfg.run_dir / "tables"
    tdir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    template = st.cube.B04.isel(time=0, drop=True)

    written["status"] = write_geotiff(
        template.copy(data=ds.status_codes), rdir / f"status_{year}.tif", crs, dtype="uint8",
        nodata=OUTSIDE_AOI, band_names=["0 no anomaly, 1 stress, 2 cut, 3 disturbed in baseline, "
                                        "4 not analysed"])
    f = ds.features
    times = pd.DatetimeIndex(ds.z.time.values)
    fi = f["first_idx"].values
    doy = np.full(fi.shape, np.nan, dtype="float32")
    ok = np.isfinite(fi)
    doy[ok] = times.dayofyear.values[fi[ok].astype(int)]
    written["first_doy"] = write_geotiff(template.copy(data=doy), rdir / f"first_detected_doy_{year}.tif",
                                         crs, band_names=[f"first detection, day of year {year}"])
    written["max_z"] = write_geotiff(template.copy(data=f["max_z_primary"].values.astype("float32")),
                                     rdir / f"max_z_{cfg.anomaly.primary_index}_{year}.tif", crs,
                                     band_names=[f"max stress z ({cfg.anomaly.primary_index}) {year}"])
    for name in ds.z["index"].values:
        written[f"z_{name}"] = write_timeseries_geotiff(ds.z.sel(index=name, drop=True),
                                                        rdir / f"z_{name}_{year}.tif", crs)

    gpkg = vdir / "suspects.gpkg"
    vdir.mkdir(parents=True, exist_ok=True)
    layer = f"suspects_{year}"
    gdf = ds.polygons
    if gdf.empty:
        import geopandas as gpd
        gdf = gpd.GeoDataFrame({"id": pd.Series(dtype="int64")}, geometry=gpd.GeoSeries([], crs=crs))
    gdf.to_file(gpkg, layer=layer, driver="GPKG", engine="pyogrio")
    written["suspects"] = gpkg
    ds.polygons.drop(columns="geometry", errors="ignore").to_csv(tdir / f"suspects_{year}.csv", index=False)
    ds.offsets.to_csv(tdir / "regional_offsets.csv", index=False)
    status_summary(ds.polygons).to_csv(tdir / f"polygon_status_{year}.csv", index=False)

    from .targets import write_targets

    written.update(write_targets(cfg, ds.targets, gpkg, ds.missions))
    return written
