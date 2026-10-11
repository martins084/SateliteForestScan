"""End-to-end run: acquisitions -> composites -> change index -> z -> polygons -> checks."""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr
from rasterio.features import rasterize

from s2forest.aoi import aoi_geometry, geobox_key, geometry_mask, make_geobox, read_vector
from s2forest.config import LinearFeaturesConfig
from s2forest.forestmask import dlt_on_grid
from s2forest.io import write_geotiff
from s2forest.linear import linear_mask

from . import checks
from .config import Config
from .detect import (CLASS_CUT_LIKE, CLASS_WINDTHROW, OrbitDelta, apply_mmu, classify,
                     combine_orbits, count_area, polygonize)
from .event import Acquisition, group_acquisitions, select_window
from .load import acquisition_key, composite_db, load_acquisition, to_db
from .method import (OrbitComposite, deltas_from_composites, linear_mean, normalize_acquisition,
                     z_by_class)
from .stac import open_client, search_s1
from .weather import hourly_weather, precip_before

log = logging.getLogger(__name__)
HRL_BROADLEAF, HRL_CONIFER = 1, 2


@dataclass
class Grid:
    geobox: object
    aoi_mask: np.ndarray
    aoi_wgs84: object
    key: str

    @property
    def pixel_ha(self) -> float:
        return abs(self.geobox.affine.a * self.geobox.affine.e) / 1e4


@dataclass
class Masks:
    dlt: np.ndarray
    forest: np.ndarray
    roads: np.ndarray | None
    analysis: np.ndarray
    stable: np.ndarray
    notes: list[str] = field(default_factory=list)


def build_grid(cfg: Config) -> Grid:
    aoi = read_vector(cfg.aoi, cfg.grid.crs)
    geom = aoi_geometry(aoi)
    gb = make_geobox(geom, cfg.grid.crs, cfg.grid.resolution)
    return Grid(gb, geometry_mask(geom, gb), aoi.to_crs(4326).geometry.union_all(), geobox_key(gb))


def cache_dir(cfg: Config, grid: Grid) -> Path:
    return cfg.cache_dir / "s1" / grid.key


def build_masks(cfg: Config, grid: Grid) -> Masks:
    cd = cache_dir(cfg, grid)
    dlt = dlt_on_grid(grid.geobox, cd / "hrl_dlt_2018.tif")
    forest = np.isin(dlt, cfg.forest_mask.hrl_dlt_classes) & grid.aoi_mask
    notes = []
    roads, _ = linear_mask(grid.geobox, LinearFeaturesConfig(buffer_m=cfg.forest_mask.road_buffer_m), cd)
    if roads is None:
        notes.append("OSM ceļi nav pieejami — ceļu maska NAV piemērota")
        roads_ = np.zeros(forest.shape, bool)
    else:
        roads_ = roads
    analysis = forest & ~roads_
    cut_buf = cfg.forest_mask.exclude_s2_cuts_buffer_m
    if cut_buf is not None:
        cuts = [gpd.read_file(r.path, layer=r.layer).to_crs(cfg.grid.crs) for r in cfg.checks.s2_exclude]
        cuts = pd.concat(cuts, ignore_index=True) if cuts else gpd.GeoDataFrame()
        cuts = cuts[cuts["type"] == "cut"] if len(cuts) else cuts
        if len(cuts):
            cm = rasterize([(g, 1) for g in cuts.geometry.buffer(cut_buf)], out_shape=forest.shape,
                           transform=grid.geobox.affine, fill=0, dtype="uint8").astype(bool)
            notes.append(f"analīzes maskā izslēgtas S2 cirtes: {len(cuts)} poligoni, buferis {cut_buf:g} m, "
                         f"{(analysis & cm).sum() * grid.pixel_ha:.1f} ha")
            analysis &= ~cm
    excl = np.zeros(forest.shape, bool)
    thr = cfg.detection.threshold
    for ref in cfg.checks.s2_exclude:
        g = gpd.read_file(ref.path, layer=ref.layer).to_crs(cfg.grid.crs)
        if len(g):
            excl |= rasterize([(geom, 1) for geom in g.geometry.buffer(thr.exclude_buffer_m)],
                              out_shape=forest.shape, transform=grid.geobox.affine, fill=0,
                              dtype="uint8").astype(bool)
        notes.append(f"stabilā meža izslēgšana: {ref.layer} ({len(g)} poligoni, buferis {thr.exclude_buffer_m} m)")
    return Masks(dlt, forest, roads, analysis, analysis & ~excl, notes)


# ---------------------------------------------------------------------------------------
def search_event(cfg: Config, grid: Grid, client=None) -> list[Acquisition]:
    ev = cfg.event
    bbox = tuple(gpd.GeoSeries([grid.aoi_wgs84]).total_bounds)
    scenes = search_s1(bbox, ev.pre_window[0], ev.post_window[1], client=client,
                       collection=cfg.data.collection)
    acqs = group_acquisitions(scenes, grid.aoi_wgs84)
    if ev.orbits != "all":
        acqs = [a for a in acqs if a.rel_orbit in ev.orbits]
    return acqs


def acquisition_table(cfg: Config, acqs: list[Acquisition], weather: pd.DataFrame) -> pd.DataFrame:
    """Selection per orbit and window, with precipitation; variant A / B flags and reasons."""
    ev, w = cfg.event, cfg.weather
    rows = []
    for orb in sorted({a.rel_orbit for a in acqs}):
        oa = [a for a in acqs if a.rel_orbit == orb]
        for win, (s, e), n in [("pre", ev.pre_window, ev.n_pre_max), ("post", ev.post_window, ev.n_post_max)]:
            sel, rej = select_window(oa, s, e, n, ev.date, cfg.data.min_aoi_cover)
            for a in sel:
                t = min(sc.datetime for sc in a.scenes)
                rows.append({"key": a, "rel_orbit": a.rel_orbit, "direction": a.direction,
                             "window": win, "date": a.date, "time_utc": t.strftime("%H:%M"),
                             "platform": a.platform, "aoi_cover": round(a.aoi_cover, 3),
                             f"precip_{w.wet_hours}h_mm": round(precip_before(weather, t, w.wet_hours), 1),
                             "precip_24h_mm": round(precip_before(weather, t, 24), 1),
                             "used_A": True, "reason_A": ""})
            for a, why in rej:
                rows.append({"key": a, "rel_orbit": a.rel_orbit, "direction": a.direction,
                             "window": win, "date": a.date, "platform": a.platform,
                             "aoi_cover": round(a.aoi_cover, 3), "used_A": False, "reason_A": why})
    df = pd.DataFrame(rows)
    pcol = f"precip_{w.wet_hours}h_mm"
    df["used_B"] = df["used_A"]
    df["reason_B"] = df["reason_A"]
    for (orb, win), g in df[df.used_A].groupby(["rel_orbit", "window"]):
        wet = g[g[pcol] > w.wet_precip_mm]
        if wet.empty:
            continue
        if len(g) - len(wet) >= w.wet_min_remaining:
            df.loc[wet.index, "used_B"] = False
            df.loc[wet.index, "reason_B"] = f"> {w.wet_precip_mm} mm {w.wet_hours} h pirms"
        else:
            df.loc[wet.index, "reason_B"] = (f"slapjš, bet paturēts (paliktu < {w.wet_min_remaining})")
    return df.sort_values(["rel_orbit", "window", "date"], ascending=[True, False, True],
                          ignore_index=True)


def orbit_composites(cfg: Config, table: pd.DataFrame, use_col: str, data: dict,
                     stable: np.ndarray) -> tuple[list[OrbitComposite], pd.DataFrame]:
    """Per orbit: linear mean of the (optionally normalized) acquisitions in each window.
    Returns (composites, per-acquisition normalization medians)."""
    norm = cfg.detection.normalize_per_acquisition
    out, meds = [], []
    for orb, g in table[table[use_col]].groupby("rel_orbit"):
        lin, cnt, dates = {}, {}, {}
        for win in ("pre", "post"):
            gw = g[g.window == win]
            dates[win] = [f"{d}" for d in gw.date]
            for pol in cfg.data.polarizations:
                stack = []
                for a in gw.key:
                    x = data[acquisition_key(a)][pol]
                    if norm:
                        x, m = normalize_acquisition(x, stable)
                        meds.append({"rel_orbit": orb, "window": win, "date": a.date, "pol": pol,
                                     "stable_median_db": round(10 * np.log10(m), 3)})
                    stack.append(x)
                if stack:
                    lin[(win, pol)], cnt[(win, pol)] = linear_mean(stack)
        if not dates["pre"] or not dates["post"]:
            log.warning("orbit %s skipped: empty window", orb)
            continue
        out.append(OrbitComposite(int(orb), g.direction.iloc[0],
                                  {p: lin[("pre", p)] for p in cfg.data.polarizations},
                                  {p: lin[("post", p)] for p in cfg.data.polarizations},
                                  np.minimum(cnt[("pre", "vv")], cnt[("pre", "vh")]),
                                  np.minimum(cnt[("post", "vv")], cnt[("post", "vh")]),
                                  dates["pre"], dates["post"]))
    return out, pd.DataFrame(meds)


def polygon_orbit_attrs(polys: gpd.GeoDataFrame, deltas: list[OrbitDelta], grid: Grid,
                        dlt: np.ndarray) -> gpd.GeoDataFrame:
    """Orbits with data in >= 50 % of the polygon: rel_orbit, direction, n_pre/post, dates;
    dominant HRL leaf type."""
    if polys.empty:
        return polys
    from rasterio.features import geometry_mask as gm
    rows = []
    for _, p in polys.iterrows():
        m = ~gm([p.geometry], out_shape=dlt.shape, transform=grid.geobox.affine)
        used = [d for d in deltas
                if np.isfinite(d.d_vv[m] + d.d_vh[m]).mean() >= 0.5]
        dl = dlt[m]
        n_b, n_c = int((dl == HRL_BROADLEAF).sum()), int((dl == HRL_CONIFER).sum())
        rows.append({
            "rel_orbit": ",".join(str(d.rel_orbit) for d in used),
            "direction": ",".join(sorted({d.direction for d in used})),
            "n_pre": sum(len(d.pre_dates) for d in used),
            "n_post": sum(len(d.post_dates) for d in used),
            "pre_dates": "; ".join(f"o{d.rel_orbit}: " + ",".join(d.pre_dates) for d in used),
            "post_dates": "; ".join(f"o{d.rel_orbit}: " + ",".join(d.post_dates) for d in used),
            "tree_type": "skujkoki" if n_c >= n_b else "lapu koki",
            "conifer_share": round(n_c / max(n_b + n_c, 1), 2),
        })
    return pd.concat([polys.reset_index(drop=True), pd.DataFrame(rows)], axis=1)


@dataclass
class VariantResult:
    name: str
    deltas: list[OrbitDelta]
    combined: dict
    z: np.ndarray
    stats: dict            # per z group ("all" or HRL class): median, mad, n
    cls: np.ndarray
    labels: np.ndarray
    polygons: gpd.GeoDataFrame
    sensitivity: pd.DataFrame
    norm_medians: pd.DataFrame = field(default_factory=pd.DataFrame)


def run_variant(cfg: Config, grid: Grid, masks: Masks, table: pd.DataFrame, data: dict,
                name: str) -> VariantResult:
    det = cfg.detection
    comps, norm_meds = orbit_composites(cfg, table, f"used_{name}", data, masks.stable)
    deltas = deltas_from_composites(comps, masks.analysis, det.smoothing_window)
    comb = combine_orbits(deltas)
    analysis = masks.analysis & np.isfinite(comb["index"])
    z, stats = z_by_class(comb["index"], masks.stable, analysis, masks.dlt,
                          cfg.forest_mask.hrl_dlt_classes if det.z_by_class else None)
    analysis &= np.isfinite(z)
    thr = det.threshold
    min_px = math.ceil(det.min_area_ha / grid.pixel_ha - 1e-9)
    sens = []
    for k in thr.sensitivity_k:
        c, lab = apply_mmu(classify(z, analysis, k), min_px)
        row = {"variant": name, "k": k, **count_area(c, lab, grid.pixel_ha)}
        for g, st in stats.items():
            row[f"thr_up_db_{g}"] = round(st["median"] + k * 1.4826 * st["mad"], 3)
            row[f"thr_down_db_{g}"] = round(st["median"] - k * 1.4826 * st["mad"], 3)
        sens.append(row)
    cls, labels = apply_mmu(classify(z, analysis, thr.k), min_px)
    layers = {"mean_dVH": comb["d_vh"], "mean_dVV": comb["d_vv"], "index": comb["index"],
              "mean_z": z, "mean_n_orbits": comb["n_orbits"].astype("float32")}
    polys = polygonize(labels, cls, grid.geobox.affine, cfg.grid.crs, layers, grid.pixel_ha)
    polys = polygon_orbit_attrs(polys, deltas, grid, masks.dlt)
    if not polys.empty:
        polys.insert(1, "variant", name)
        for c in ["mean_dVH", "mean_dVV", "index", "mean_z", "mean_n_orbits"]:
            polys[c] = polys[c].round(3)
    return VariantResult(name, deltas, comb, z, stats, cls, labels, polys, pd.DataFrame(sens), norm_meds)


def compare_variants(a: VariantResult, b: VariantResult) -> dict:
    out = {}
    for c, name in ((CLASS_WINDTHROW, "windthrow"), (CLASS_CUT_LIKE, "cut_like")):
        pa, pb = a.cls == c, b.cls == c
        inter, union = int((pa & pb).sum()), int((pa | pb).sum())
        ga = a.polygons[a.polygons["class"] == name] if not a.polygons.empty else a.polygons
        gb = b.polygons[b.polygons["class"] == name] if not b.polygons.empty else b.polygons
        a_in_b = int(sum(gb.intersects(g).any() for g in ga.geometry)) if len(ga) and len(gb) else 0
        b_in_a = int(sum(ga.intersects(g).any() for g in gb.geometry)) if len(ga) and len(gb) else 0
        out[name] = {"n_A": len(ga), "n_B": len(gb), "A_overlapping_B": a_in_b,
                     "B_overlapping_A": b_in_a, "pixel_IoU": round(inter / union, 3) if union else None}
    return out


def stable_series(cfg: Config, table: pd.DataFrame, data: dict, stable: np.ndarray) -> pd.DataFrame:
    rows = []
    for r in table[table.used_A].itertuples():
        row = {"date": r.date, "time_utc": r.time_utc, "rel_orbit": r.rel_orbit,
               "direction": r.direction, "window": r.window,
               "precip_6h_mm": getattr(r, f"precip_{cfg.weather.wet_hours}h_mm")}
        for pol in cfg.data.polarizations:
            v = data[acquisition_key(r.key)][pol][stable]
            row[f"{pol}_db"] = float(to_db(np.array([np.nanmedian(v)]))[0]) if np.isfinite(v).any() else np.nan
            row[f"{pol}_valid"] = round(float(np.isfinite(v).mean()), 3)
        rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------------------
def run_proxy(cfg: Config, grid: Grid, masks: Masks, client) -> tuple[pd.DataFrame, pd.DataFrame]:
    """PROXY: S1 dVV / dVH over S2 summer cuts (own windows per cut)."""
    c = cfg.checks
    if not c.proxy_cuts:
        return pd.DataFrame(), pd.DataFrame()
    cuts, dropped = checks.proxy_cuts(c.proxy_cuts, c.proxy_min_area_ha, c.proxy_months)
    rows = []
    bbox = tuple(gpd.GeoSeries([grid.aoi_wgs84]).total_bounds)
    cd = cache_dir(cfg, grid) / "acq"
    from rasterio.features import geometry_mask as gm
    for _, cut in cuts.iterrows():
        win = checks.proxy_windows(cut, c.proxy_window_days)
        base = {"layer": cut["source_layer"], "id": int(cut["id"]), "area_ha": round(cut["area_ha"], 2),
                "first_detected": win["first_detected"], "prev_clear_s2": win["prev_clear"]}
        if win["pre"] is None:
            rows.append({**base, "note": "nav iepriekšējā skaidrā S2 datuma"})
            continue
        acqs = group_acquisitions(search_s1(bbox, win["pre"][0], win["post"][1], client=client,
                                            collection=cfg.data.collection), grid.aoi_wgs84)
        m = ~gm([cut.geometry], out_shape=grid.aoi_mask.shape, transform=grid.geobox.affine)
        st = masks.stable
        for orb in sorted({a.rel_orbit for a in acqs}):
            oa = [a for a in acqs if a.rel_orbit == orb]
            pre = [a for a in oa if win["pre"][0] <= a.date <= win["pre"][1]]
            post = [a for a in oa if win["post"][0] <= a.date <= win["post"][1]]
            if not pre or not post:
                continue
            res = {**base, "rel_orbit": orb, "direction": oa[0].direction,
                   "pre_dates": ",".join(str(a.date) for a in pre),
                   "post_dates": ",".join(str(a.date) for a in post)}
            for pol in cfg.data.polarizations:
                ld = lambda a: load_acquisition(a, grid.geobox, cfg.data.polarizations,
                                                cfg.data.nodata, cfg.data.resampling, cd)[pol]
                pre_db, _ = composite_db([ld(a) for a in pre])
                post_db, _ = composite_db([ld(a) for a in post])
                d = post_db - pre_db
                res[f"d_{pol}_cut"] = float(np.nanmean(d[m])) if np.isfinite(d[m]).mean() >= 0.5 else np.nan
                res[f"d_{pol}_stable"] = float(np.nanmedian(d[st])) if np.isfinite(d[st]).any() else np.nan
                res[f"d_{pol}_rel"] = res[f"d_{pol}_cut"] - res[f"d_{pol}_stable"]
            rows.append(res)
    return pd.DataFrame(rows), dropped


# ---------------------------------------------------------------------------------------
def write_rasters(cfg: Config, grid: Grid, masks: Masks, res: VariantResult) -> list[Path]:
    rd = cfg.run_dir / "rasters"
    c = grid.geobox.coordinates

    def da(a):
        return xr.DataArray(a, dims=("y", "x"), coords={"y": c["y"].values, "x": c["x"].values})

    out = []
    v = res.name
    for name, arr in [("index_dvh_plus_dvv_db", res.combined["index"]), ("d_vv_db", res.combined["d_vv"]),
                      ("d_vh_db", res.combined["d_vh"]), ("z", res.z)]:
        out.append(write_geotiff(da(arr), rd / f"{name}_{v}.tif", cfg.grid.crs, band_names=[name]))
    out.append(write_geotiff(da(res.combined["n_orbits"]), rd / f"n_orbits_{v}.tif", cfg.grid.crs,
                             band_names=["n_orbits"], dtype="int16", nodata=-1))
    out.append(write_geotiff(da(res.cls), rd / f"class_{v}.tif", cfg.grid.crs,
                             band_names=["0 none, 1 windthrow, 2 cut_like"], dtype="uint8", nodata=255))
    bands, names = [], []
    for d in res.deltas:
        bands += [d.d_vv, d.d_vh]
        names += [f"o{d.rel_orbit}_{d.direction}_dVV", f"o{d.rel_orbit}_{d.direction}_dVH"]
    arr = xr.DataArray(np.stack(bands), dims=("band", "y", "x"),
                       coords={"y": c["y"].values, "x": c["x"].values})
    out.append(write_geotiff(arr, rd / f"orbit_deltas_db_{v}.tif", cfg.grid.crs, band_names=names))
    if v == "A":
        mask_codes = np.zeros(grid.aoi_mask.shape, "uint8")
        mask_codes[masks.forest] = 1
        mask_codes[masks.analysis] = 2
        mask_codes[masks.stable] = 3
        out.append(write_geotiff(da(mask_codes), rd / "masks.tif", cfg.grid.crs,
                                 band_names=["0 ne mežs, 1 mežs ceļu buferī, 2 analizēts, 3 stabilais"],
                                 dtype="uint8", nodata=255))
    return out


@dataclass
class Prepared:
    grid: Grid
    client: object
    table: pd.DataFrame
    data: dict
    masks: Masks
    weather: pd.DataFrame
    wmeta: dict


def prepare(cfg: Config, progress=print) -> Prepared:
    """Search, weather, acquisition selection, loading (cached) and masks."""
    grid = build_grid(cfg)
    client = open_client(cfg.data.stac_url)
    progress("searching S1 acquisitions ...")
    acqs = search_event(cfg, grid, client)
    cen = grid.aoi_wgs84.centroid
    ev = cfg.event
    weather, wmeta = hourly_weather(cen.y, cen.x, ev.pre_window[0] - timedelta(days=2),
                                    ev.post_window[1], cache_dir(cfg, grid))
    table = acquisition_table(cfg, acqs, weather)
    progress(f"loading {int(table.used_A.sum())} acquisitions ...")
    data = {}
    for a in table[table.used_A].key:
        data[acquisition_key(a)] = load_acquisition(a, grid.geobox, cfg.data.polarizations,
                                                    cfg.data.nodata, cfg.data.resampling,
                                                    cache_dir(cfg, grid) / "acq")
    progress("masks ...")
    return Prepared(grid, client, table, data, build_masks(cfg, grid), weather, wmeta)


def run(cfg: Config, progress=print) -> dict:
    rd = cfg.run_dir
    (rd / "tables").mkdir(parents=True, exist_ok=True)
    (rd / "vectors").mkdir(parents=True, exist_ok=True)
    (rd / "figures").mkdir(parents=True, exist_ok=True)
    pr = prepare(cfg, progress)
    grid, client, table, data, masks = pr.grid, pr.client, pr.table, pr.data, pr.masks
    weather, wmeta = pr.weather, pr.wmeta
    ev = cfg.event
    results = {}
    for v in ("A", "B"):
        progress(f"variant {v} ...")
        results[v] = run_variant(cfg, grid, masks, table, data, v)
        write_rasters(cfg, grid, masks, results[v])
    progress("diagnostics and S2 check ...")
    series = stable_series(cfg, table, data, masks.stable)
    comparison = compare_variants(results["A"], results["B"])

    # S2 index check of the candidates of both variants (read-only)
    s2_sum, s2_long = pd.DataFrame(), pd.DataFrame()
    c = cfg.checks
    if c.s2_run_dir is not None:
        split = c.s2_event_split or ev.date
        pre = (ev.pre_window[0], split - timedelta(days=1))
        post = (split, ev.post_window[1])
        parts = [results[v].polygons.assign(variant=v) for v in results
                 if not results[v].polygons.empty]
        polys = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
        if len(polys):
            polys = gpd.GeoDataFrame(polys, geometry="geometry", crs=cfg.grid.crs)
            polys["id"] = polys["variant"] + polys["id"].astype(str)
            s2_sum, s2_long = checks.s2_index_check(polys, c.s2_run_dir, c.s2_indices,
                                                    masks.stable, pre, post)
    progress("proxy: S2 summer cuts ...")
    proxy, proxy_dropped = run_proxy(cfg, grid, masks, client)

    # outputs
    gpkg = rd / "vectors" / "s1_windthrow.gpkg"
    if gpkg.exists():
        gpkg.unlink()
    for v, r in results.items():
        if not r.polygons.empty:
            r.polygons.to_file(gpkg, layer=f"candidates_{v}", driver="GPKG")
    t = table.drop(columns="key").copy()
    t.to_csv(rd / "tables" / "acquisitions.csv", index=False)
    pd.concat([r.sensitivity for r in results.values()]).to_csv(rd / "tables" / "sensitivity.csv", index=False)
    series.to_csv(rd / "tables" / "stable_forest_series.csv", index=False)
    for v, r in results.items():
        if not r.norm_medians.empty:
            r.norm_medians.to_csv(rd / "tables" / f"normalization_medians_{v}.csv", index=False)
    s2_sum.to_csv(rd / "tables" / "s2_check_summary.csv", index=False)
    s2_long.to_csv(rd / "tables" / "s2_check_by_date.csv", index=False)
    proxy.to_csv(rd / "tables" / "proxy_cuts.csv", index=False)
    proxy_dropped.to_csv(rd / "tables" / "proxy_cuts_excluded.csv", index=False)
    k = cfg.detection.threshold.k
    stats = {v: {"orbits": [d.rel_orbit for d in r.deltas],
                 "groups": {str(g): {"stable_median_db": round(st["median"], 4),
                                     "stable_mad_db": round(st["mad"], 4), "stable_pixels": st["n"],
                                     "k": k,
                                     "threshold_db_up": round(st["median"] + k * 1.4826 * st["mad"], 3),
                                     "threshold_db_down": round(st["median"] - k * 1.4826 * st["mad"], 3)}
                            for g, st in r.stats.items()}} for v, r in results.items()}
    meta = {"config": json.loads(cfg.model_dump_json()), "grid_key": grid.key, "weather": wmeta,
            "stats": stats, "comparison_A_B": comparison, "mask_notes": masks.notes,
            "areas_ha": {"aoi": round(float(grid.aoi_mask.sum() * grid.pixel_ha), 1),
                         "forest_hrl_1_2": round(float(masks.forest.sum() * grid.pixel_ha), 1),
                         "analysis": round(float(masks.analysis.sum() * grid.pixel_ha), 1),
                         "stable": round(float(masks.stable.sum() * grid.pixel_ha), 1)}}
    (rd / "run_metadata.json").write_text(json.dumps(meta, indent=1, default=str, ensure_ascii=False),
                                          encoding="utf-8")
    from . import viz
    viz.preview(cfg, grid, masks, results["A"], rd / "figures" / "preview_A.png")
    viz.preview(cfg, grid, masks, results["B"], rd / "figures" / "preview_B.png")
    viz.stable_series_plot(series, weather, cfg, rd / "figures" / "stable_forest_series.png")
    from .report import write_report
    write_report(cfg, meta, t, results, s2_sum, proxy, proxy_dropped, rd / f"atskaite_{cfg.run_name}.md")
    return {"results": results, "meta": meta, "table": t, "s2": s2_sum, "proxy": proxy}
