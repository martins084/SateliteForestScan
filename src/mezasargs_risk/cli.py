"""mezasargs-risk CLI. Stage 5: `labels` (EFDA input checks + v2.1.1 cross-check) and
`describe` (descriptive analysis, tables + figures)."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import typer

from .config import RiskConfig, load_config

app = typer.Typer(add_completion=False, no_args_is_help=True)
ConfigArg = typer.Argument(..., exists=True, dir_okay=False, help="YAML config")


def _commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                              cwd=Path(__file__).parent).stdout.strip()
    except OSError:
        return ""


def _metadata(cfg: RiskConfig, step: str, extra: dict) -> None:
    p = cfg.run_dir / "run_metadata.json"
    meta = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    e = cfg.efda
    meta[step] = {"time_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "code_commit": _commit(),
                  "efda": {k: {"version": v.version, "doi": v.doi, "archive": v.archive}
                           for k, v in (("main", e.main), ("crosscheck", e.crosscheck)) if v},
                  "boundaries": str(cfg.boundaries.path), **extra}
    p.write_text(json.dumps(meta, indent=1, ensure_ascii=False, default=str), encoding="utf-8")


def _country(cfg: RiskConfig, version):
    from .efda import country_regions, layer, region_raster

    regions = country_regions(cfg.boundaries)
    with rasterio.open(layer(version, "agent")) as s:
        reg = region_raster(regions, s)
    return regions, reg


@app.command()
def labels(config: Path = ConfigArg):
    """EFDA extent check (both versions), annual agent counts per region, v3.0 vs v2.1.1."""
    from .efda import annual_counts, check_extent, crosscheck, grid_offset, layer

    cfg = load_config(config)
    tdir = cfg.run_dir / "tables"
    tdir.mkdir(parents=True, exist_ok=True)
    regions, reg = _country(cfg, cfg.efda.main)
    checks = {}
    for name, v in (("main", cfg.efda.main), ("crosscheck", cfg.efda.crosscheck)):
        if v is None:
            continue
        ch = check_extent(layer(v, "forest"), regions, cfg.boundaries)
        typer.echo(f"EFDA {v.version} ({v.archive}): {ch.message()}")
        checks[name] = ch.__dict__
        if not ch.ok:
            raise typer.Exit(code=2)
    counts = annual_counts(cfg.efda.main, reg, len(regions))
    if cfg.efda.crosscheck:
        _, reg2 = _country(cfg, cfg.efda.crosscheck)
        counts = pd.concat([counts, annual_counts(cfg.efda.crosscheck, reg2, len(regions))])
        with rasterio.open(layer(cfg.efda.main, "agent")) as a, \
                rasterio.open(layer(cfg.efda.crosscheck, "agent")) as b:
            ro, co, resid = grid_offset(a, b)
        typer.echo(f"Grid offset v3.0 -> v2.1.1: rows {ro}, cols {co}, residual shift {resid:.1f} m")
        cc = crosscheck(cfg.efda.main, cfg.efda.crosscheck, reg > 0)
        cc.to_csv(tdir / "efda_crosscheck_v30_v211.csv", index=False)
        checks["grid_offset"] = {"rows": ro, "cols": co, "residual_m": resid}
    names = {0: "outside"} | {i + 1: r for i, r in enumerate(regions["NAME_LATN"])}
    counts["region_name"] = counts["region"].map(names)
    counts.to_csv(tdir / "efda_annual_counts.csv", index=False)
    with rasterio.open(layer(cfg.efda.main, "forest")) as s:
        f = s.read(1) == 1
    forest = pd.DataFrame({"region": range(len(regions) + 1),
                           "forest_px": np.bincount(reg[f], minlength=len(regions) + 1)})
    forest["region_name"] = forest["region"].map(names)
    forest.to_csv(tdir / "efda_forest_px_by_region.csv", index=False)
    _metadata(cfg, "labels", {"extent_checks": checks})
    typer.echo(f"Tables: {tdir}")


@app.command()
def describe(config: Path = ConfigArg):
    """Descriptive analysis: patches, grid map, conifer cells, official statistics, Kalsnava."""
    from . import describe as d
    from . import viz

    cfg = load_config(config)
    tdir, fdir = cfg.run_dir / "tables", cfg.run_dir / "figures"
    fdir.mkdir(parents=True, exist_ok=True)
    regions, reg = _country(cfg, cfg.efda.main)
    country = reg > 0
    patches = d.annual_patches(cfg, country)
    patches.to_csv(tdir / "efda_patches_by_year.csv", index=False)
    grid, forest_cells = d.grid_counts(cfg, country)
    grid.to_csv(tdir / "efda_grid_counts.csv", index=False)
    forest_cells.to_csv(tdir / "efda_grid_forest.csv", index=False)
    conifer = d.conifer_share(cfg, regions, grid.attrs)
    conifer.to_csv(tdir / "hrl_dlt_conifer_share_by_cell.csv", index=False)
    stats = {}
    if cfg.stats.meb012:
        stats["meb012"] = d.read_csp(cfg.stats.meb012, 2)
    if cfg.stats.mez012:
        stats["mez012"] = d.read_csp(cfg.stats.mez012, 3)
    counts = pd.read_csv(tdir / "efda_annual_counts.csv")
    cross = tdir / "efda_crosscheck_v30_v211.csv"
    cross = pd.read_csv(cross) if cross.exists() else None
    kal = None
    if cfg.kalsnava:
        kal = d.kalsnava(cfg)
        kal[0].to_csv(tdir / "kalsnava_efda_by_year.csv", index=False)
        kal[1].to_csv(tdir / f"kalsnava_s2cuts_{cfg.kalsnava.year}_efda_history.csv", index=False)
    out = viz.all_figures(cfg, fdir, regions, counts, cross, patches, grid, forest_cells, conifer,
                          stats, kal)
    for k, v in out.items():
        typer.echo(f"{k}: {v}")
    _metadata(cfg, "describe", {"dlt_cache": conifer.attrs.get("path"),
                                "stats": {k: str(v) for k, v in cfg.stats if v}})


@app.command("harvest-check")
def harvest_check(config: Path = ConfigArg):
    """EFDA class 3 vs official cut area (CSP MEZ012) and v2.1.1 pixels confirmed by v3.0 per year
    (is the v2.1.1 2023 jump an end-of-series artefact?)."""
    from . import describe as d
    from . import viz
    from .efda import followup

    cfg = load_config(config)
    tdir, fdir = cfg.run_dir / "tables", cfg.run_dir / "figures"
    fdir.mkdir(parents=True, exist_ok=True)
    versions = [cfg.efda.main.version, cfg.efda.crosscheck.version]
    counts = pd.read_csv(tdir / "efda_annual_counts.csv")
    df = d.harvest_official(d.read_csp(cfg.stats.mez012_types, 3), counts, versions)
    df.to_csv(tdir / "efda_c3_vs_csp_mez012.csv")
    _, reg = _country(cfg, cfg.efda.main)
    follow = followup(cfg.efda.main, cfg.efda.crosscheck, reg > 0)
    follow.to_csv(tdir / "efda_v211_confirmed_by_v30.csv", index=False)
    typer.echo(viz.harvest_official_fig(df, follow, versions, fdir / "rm5_cirtes_pret_csp.png"))
    _metadata(cfg, "harvest_check", {"mez012_types": str(cfg.stats.mez012_types)})


@app.command("lvm-aoi")
def lvm_aoi(config: Path = ConfigArg):
    """Stage 5b a): AOI candidates for the s2forest blind validation on LVM land (only proposed;
    the user chooses, nothing is run)."""
    import geopandas as gpd

    from . import lvm
    from . import viz
    from .efda import country_regions

    cfg = load_config(config)
    c = cfg.lvm
    if c is None:
        raise typer.BadParameter("config has no `lvm` section")
    a = c.aoi
    tdir, fdir, adir = cfg.run_dir / "tables", cfg.run_dir / "figures", cfg.run_dir / "aoi"
    for d in (tdir, fdir, adir):
        d.mkdir(parents=True, exist_ok=True)
    g, land = lvm.load_damage(c), lvm.load_land(c)
    regions = country_regions(cfg.boundaries)
    kal = gpd.read_file(cfg.kalsnava.aoi).to_crs(3059)
    cells = lvm.target_cells(g, c, regions, kal.union_all().centroid, years=a.years, top=a.top_cells)
    dlt = cfg.cache_dir / "rm" / f"hrl_dlt2018_{cfg.boundaries.country}_{int(cfg.conifer.dlt_res_m)}m.tif"
    t = lvm.aoi_check(cells, g, land, dlt, c)
    t.to_csv(tdir / "lvm_5b_aoi_candidates.csv", index=False)
    typer.echo(t.to_string(index=False))
    cand = {}
    for r in t.head(a.n_candidates).itertuples():
        lvm.aoi_geojson(r.x0, r.y0, g.crs, adir / f"aoi_kandidats_{r.rank}.geojson",
                        f"5b AOI candidate {r.rank} (LKS-92 cell {r.x0},{r.y0})")
        cell = gpd.read_file(adir / f"aoi_kandidats_{r.rank}.geojson").to_crs(g.crs)
        area = cell.union_all()
        yrs = g[~g["empty"] & g["year"].between(*a.years) & g.intersects(area)]
        cand[r.rank] = {"cell": cell, "land": land[land.intersects(area)].clip(area),
                        "pest": yrs[yrs["subtype"] == c.stem_pest].clip(area),
                        "other": yrs[yrs["subtype"] != c.stem_pest].clip(area)}
    p = viz.lvm_aoi_candidates(regions.to_crs(g.crs), t, cand, kal, fdir / "rm5b_aoi_kandidati.png")
    typer.echo(f"figure: {p}")
    _metadata(cfg, "lvm_aoi", {"lvm": {"damage": str(c.damage), "snapshot": str(c.damage_snapshot),
                                       "land_units": str(c.land_units)},
                               "dlt": str(dlt), "criteria": a.model_dump()})


@app.command("lvm-validate")
def lvm_validate(config: Path = ConfigArg):
    """Stage 5b b)-c): s2forest (frozen v0.2, runs listed in lvm.s2forest) vs LVM damage polygons
    on the validation AOI: detection per object, precision, lag, mask cover, placebo."""
    from . import s2val
    from . import viz

    cfg = load_config(config)
    c = cfg.lvm
    if c is None or c.validation is None:
        raise typer.BadParameter("config has no `lvm.validation` section")
    tdir, fdir = cfg.run_dir / "tables", cfg.run_dir / "figures"
    tdir.mkdir(parents=True, exist_ok=True)
    fdir.mkdir(parents=True, exist_ok=True)
    aoi, d, runs = s2val.load(c)
    d.drop(columns="geometry").to_csv(tdir / "val_lvm_polygons.csv", index=False)
    (d.groupby(["group", "subtype", "name", "year"]).agg(n=("ha", "size"), ha=("ha", "sum")).round(2)
       .reset_index().to_csv(tdir / "val_lvm_subtypes_by_year.csv", index=False))
    masks = {r.year: r.path.parent.parent / "rasters" / "forest_mask.tif" for r in c.s2forest if r.variant == "all"}
    cover, analysed = s2val.mask_cover(d, masks, c)
    cover.to_csv(tdir / "val_lvm_mask_cover.csv", index=False)
    typer.echo(cover.to_string(index=False))
    for v in sorted({r.variant for r in c.s2forest}):
        det = s2val.detection(d, runs, v, c)
        det.to_csv(tdir / f"val_detection_{v}.csv", index=False)
        summ = s2val.detection_summary(det, analysed)
        summ.to_csv(tdir / f"val_detection_summary_{v}.csv", index=False)
        prec = s2val.precision(d, runs, v, c)
        prec.to_csv(tdir / f"val_precision_{v}.csv", index=False)
        s2val.lag(det).to_csv(tdir / f"val_lag_{v}.csv", index=False)
        s2val.lag(det, "found_overlap25").to_csv(tdir / f"val_lag_overlap25_{v}.csv", index=False)
        typer.echo(f"--- {v}")
        typer.echo(summ[summ["size"] == ">= 0,5 ha"].to_string(index=False))
        typer.echo(prec.to_string(index=False))
    plac = s2val.placebo(d, runs, aoi, masks[c.validation.reg_years[0]], c)
    plac.to_csv(tdir / "val_placebo_all.csv", index=False)
    summ = pd.read_csv(tdir / "val_detection_summary_all.csv", dtype={"offset": str})
    obs = {}
    for g in c.validation.placebo_groups:
        obs |= s2val.group_shares(summ, g)
    obs |= s2val.precision_shares(pd.read_csv(tdir / "val_precision_all.csv"))
    cmp = s2val.placebo_compare(obs, plac)
    cmp.to_csv(tdir / "val_placebo_compare_all.csv", index=False)
    typer.echo(cmp.to_string(index=False))
    out = {"maps": viz.val5b_maps(aoi, d, runs, fdir / "rm5b_kartes.png"),
           "detection": viz.val5b_detection(summ, plac, fdir / "rm5b_detekcija.png")}
    for n, p in out.items():
        typer.echo(f"{n}: {p}")
    _metadata(cfg, "lvm_validate", {"lvm": {"damage": str(c.damage), "snapshot": str(c.damage_snapshot)},
                                    "validation": c.validation.model_dump(),
                                    "runs": [r.model_dump() for r in c.s2forest],
                                    "match_buffer_m": c.match_buffer_m})


@app.command("lvm-describe")
def lvm_describe(config: Path = ConfigArg):
    """Stage 5a: LVM open damage polygons - inventory, official statistics, EFDA timing,
    Kalsnava check of s2forest (frozen runs, read only)."""
    import geopandas as gpd

    from . import lvm
    from . import viz
    from .describe import read_csp
    from .efda import country_regions

    cfg = load_config(config)
    c = cfg.lvm
    if c is None:
        raise typer.BadParameter("config has no `lvm` section")
    tdir, fdir = cfg.run_dir / "tables", cfg.run_dir / "figures"
    tdir.mkdir(parents=True, exist_ok=True)
    fdir.mkdir(parents=True, exist_ok=True)
    g, land = lvm.load_damage(c), lvm.load_land(c)
    inv = lvm.inventory(g, land, c)
    inv.to_csv(tdir / "lvm_inventory.csv", index=False)
    typer.echo(inv.to_string(index=False))
    ann = lvm.annual(g, c)
    ann.to_csv(tdir / "lvm_annual_by_subtype.csv", index=False)
    lvm.sizes(g).to_csv(tdir / "lvm_polygon_sizes.csv", index=False)
    regions = country_regions(cfg.boundaries)
    reg = lvm.by_region(g, land, regions, c.stem_pest, c)
    reg.to_csv(tdir / "lvm_620_by_region.csv")
    cmp = lvm.csp_compare(ann, read_csp(cfg.stats.meb012_owner, 2), c.stem_pest)
    cmp.to_csv(tdir / "lvm_620_vs_csp_meb012.csv")
    m11 = lvm.meb011_compare(reg, read_csp(cfg.stats.meb011_owner, 3))
    m11.to_csv(tdir / "lvm_620_vs_csp_meb011_regions.csv", index=False)
    timing = lvm.efda_timing(g, land, cfg)
    timing.to_csv(tdir / "lvm_620_efda_timing.csv", index=False)
    kal = gpd.read_file(cfg.kalsnava.aoi).to_crs(3059).union_all().centroid
    lvm.target_cells(g, c, regions, kal).to_csv(tdir / "lvm_620_target_cells_5km.csv", index=False)
    k = lvm.kalsnava_check(cfg)
    for name, t in k.items():
        t.to_csv(tdir / f"kalsnava_{name}.csv", index=False)
    typer.echo(k["summary"].to_string(index=False))
    out = {"annual": viz.lvm_annual(cmp, ann, fdir / "rm5a_lvm_gadi.png"),
           "sizes": viz.lvm_sizes(g, fdir / "rm5a_lvm_izmeri.png"),
           "regions": viz.lvm_regions(regions.to_crs(3059), reg, m11, fdir / "rm5a_lvm_regioni.png"),
           "timing": viz.lvm_timing(timing, fdir / "rm5a_lvm_efda_laiks.png")}
    aoi = gpd.read_file(cfg.kalsnava.aoi).to_crs(3059)
    bb = tuple(aoi.total_bounds)
    layers = {"MPS nogabali": gpd.read_file(lvm._zip(c.mps, c.mps_member), bbox=bb) if c.mps else gpd.GeoDataFrame(),
              "LVM zeme": lvm.load_land(c, bbox=bb),
              "MVR nogabali": (gpd.read_file(c.mvr_kalsnava, bbox=bb, columns=["kadastrs"]).set_crs(3059, allow_override=True)
                               if c.mvr_kalsnava else gpd.GeoDataFrame()),
              "LVM bojājumi": lvm.load_damage(c, bbox=bb).pipe(lambda d: d[~d["empty"]])}
    runs = pd.concat([lvm._suspects(r) for r in c.s2forest if r.variant == "all"]).to_crs(3059)
    layers["s2forest cirtes 2025+2026"] = runs[runs["type"] == "cut"]
    layers["s2forest stress 2025+2026"] = runs[runs["type"] == "stress"]
    layers = {n: (l.clip(aoi) if len(l) else l) for n, l in layers.items()}
    out["kalsnava"] = viz.lvm_kalsnava(aoi, layers, fdir / "rm5a_lvm_kalsnava.png")
    for n, p in out.items():
        typer.echo(f"{n}: {p}")
    _metadata(cfg, "lvm_describe", {"lvm": {"damage": str(c.damage), "snapshot": str(c.damage_snapshot),
                                            "land_units": str(c.land_units), "mps": str(c.mps),
                                            "mvr_kalsnava": str(c.mvr_kalsnava)},
                                    "s2forest_runs": [r.label for r in c.s2forest]})


def _climate_nodes(cfg: RiskConfig, scope: str) -> pd.DataFrame:
    """ERA5 nodes: `points` -> nearest node of each configured point; `latvia` -> all nodes whose
    0.25 deg cell touches Latvia + `grid_buffer_cells` rings."""
    from . import weather
    from .efda import country_regions

    c = cfg.climate
    if scope == "points":
        rows = []
        for p in c.points:
            lon, lat = weather.nearest_node(p.lon, p.lat)
            rows.append({"node": weather.node_id(lon, lat), "lon": lon, "lat": lat, "core": True,
                         "point": p.name, "point_lon": p.lon, "point_lat": p.lat})
        return pd.DataFrame(rows)
    if scope == "latvia":
        lv = country_regions(cfg.boundaries).to_crs(4326).union_all()
        return weather.era5_nodes(lv, c.grid_buffer_cells)
    raise typer.BadParameter("scope must be `points` or `latvia`")


@app.command("weather")
def weather_cmd(config: Path = ConfigArg,
                scope: str = typer.Option("points", help="points | latvia"),
                dry_run: bool = typer.Option(False, help="only print nodes and the weighted calls"),
                max_wait_h: float = typer.Option(1.0, help="stop (resumable) if the budget needs a longer wait")):
    """Stage 4: daily ERA5 (Open-Meteo `models=era5`) per ERA5 node, cached in cache/rm/openmeteo/;
    weighted calls stay inside the configured minute / hour / day budget (ledger in the cache)."""
    from . import weather

    cfg = load_config(config)
    c = cfg.climate
    if c is None:
        raise typer.BadParameter("config has no `climate` section")
    cache = cfg.cache_dir / "rm" / "openmeteo"
    nodes = _climate_nodes(cfg, scope)
    todo = [n for n in nodes.itertuples()
            if not all(weather.cache_path(cache, c.openmeteo, n.lon, n.lat, s, e).exists() for s, e in weather.windows(c))]
    typer.echo(f"{len(nodes)} nodes ({int(nodes['core'].sum())} core), {len(todo)} not complete in cache; "
               f"weighted calls: all {weather.planned_weight(len(nodes), c):.0f}, "
               f"missing <= {weather.planned_weight(len(todo), c):.0f}; budget {c.openmeteo.max_per_day:.0f} / day")
    if dry_run:
        return
    budget = weather.Budget(cache / "ledger.csv", c.openmeteo, max_wait_s=max_wait_h * 3600)
    rows, stopped = [], None
    for n in nodes.itertuples():
        try:
            _, meta = weather.load_node(n.lon, n.lat, c, cache, budget)
        except weather.BudgetExceeded as e:
            stopped = str(e)
            break
        rows.append(n._asdict() | meta)
    tdir = cfg.run_dir / "tables"
    tdir.mkdir(parents=True, exist_ok=True)
    out = pd.DataFrame(rows).drop(columns=["Index"], errors="ignore")
    out.to_csv(tdir / f"era5_nodes_{scope}.csv", index=False)
    typer.echo(f"complete nodes: {len(out)} / {len(nodes)}" + (f"; stopped: {stopped}" if stopped else ""))
    _metadata(cfg, f"weather_{scope}", {"openmeteo": c.openmeteo.model_dump(), "nodes": len(nodes),
                                        "complete": len(out), "stopped": stopped,
                                        "windows": [f"{s}..{e}" for s, e in weather.windows(c)]})


def _node_climate(day: pd.DataFrame, c) -> tuple[list[dict], pd.DataFrame]:
    from . import rity, waterbalance

    ph = []
    for y in range(c.years[0], c.years[1] + 1):
        pc = rity.phenips_clim_swarming(day, y)
        for sc in c.scenarios:
            for inca in (False, True):
                ph.append(rity.rity2(day, y, sc, inca) | {"phenips_clim_swarming_doy": pc["phenips_clim_swarming_doy"]})
    wb = waterbalance.anomaly(waterbalance.seasonal(day, c.wb_months), c.baseline)
    return ph, wb


def _main_table(ph: pd.DataFrame, main: str) -> pd.DataFrame:
    """One row per (node, year): main scenario (ERA5 direct) + generations of the other scenarios
    and of the INCA variant."""
    key = ["node", "year"]
    direct = ph[ph["variant"] == "era5_direct"]
    m = direct[direct["scenario"] == main].copy()
    for sc in sorted(set(direct["scenario"]) - {main}):
        m = m.merge(direct[direct["scenario"] == sc][key + ["n_filial"]].rename(columns={"n_filial": f"n_filial_{sc}"}),
                    on=key, how="left")
    inca = ph[(ph["variant"] == "inca_1-3") & (ph["scenario"] == main)][key + ["n_filial", "tsum_F1"]]
    return m.merge(inca.rename(columns={"n_filial": "n_filial_inca", "tsum_F1": "tsum_F1_inca"}), on=key, how="left")


@app.command("climate")
def climate_cmd(config: Path = ConfigArg, scope: str = typer.Option("points", help="points | latvia")):
    """Stage 4: RITY-2 (Ogris 2020) and the water balance anomaly per cached ERA5 node; tables,
    figures and the Silava 2023 sanity check. Nodes not complete in the cache are skipped."""
    from . import viz, weather
    from .efda import country_regions

    cfg = load_config(config)
    c = cfg.climate
    cache = cfg.cache_dir / "rm" / "openmeteo"
    tdir, fdir = cfg.run_dir / "tables", cfg.run_dir / "figures"
    tdir.mkdir(parents=True, exist_ok=True)
    fdir.mkdir(parents=True, exist_ok=True)
    nodes = _climate_nodes(cfg, scope)
    ph_rows, wb_rows, meta_rows, missing = [], [], [], []
    for n in nodes.drop_duplicates("node").itertuples():
        try:
            day, meta = weather.load_node(n.lon, n.lat, c, cache, budget=None)
        except weather.BudgetExceeded:
            missing.append(n.node)
            continue
        ph, wb = _node_climate(day, c)
        ph_rows += [r | {"node": n.node} for r in ph]
        wb_rows.append(wb.assign(node=n.node))
        meta_rows.append(meta)
    typer.echo(f"nodes with complete data: {len(meta_rows)} / {nodes['node'].nunique()}")
    if not meta_rows:
        return
    ph = pd.DataFrame(ph_rows)
    wb = pd.concat(wb_rows, ignore_index=True)
    meta = pd.DataFrame(meta_rows)
    ph.to_csv(tdir / f"rity2_{scope}.csv", index=False)
    wb.to_csv(tdir / f"water_balance_{scope}.csv", index=False)
    meta.to_csv(tdir / f"era5_nodes_used_{scope}.csv", index=False)
    main = _main_table(ph, c.main_scenario).merge(wb[["node", "year", "precip_mm", "et0_mm", "cwb_mm", "cwb_z"]],
                                                   on=["node", "year"], how="left")
    main.to_csv(tdir / f"climate_summary_{scope}.csv", index=False)
    figs = {}
    if scope == "points":
        for n in nodes.itertuples():
            m = main[main["node"] == n.node].sort_values("year")
            w = wb[wb["node"] == n.node]
            safe = n.point.lower().replace(" ", "_")
            figs[n.point] = viz.climate_point(n.point, m, w, c.years, fdir / f"rm4_{safe}.png", c.check_date)
            if c.check_date is not None:
                r = m[m["year"] == c.check_date.year].iloc[0]
                doy = c.check_date.timetuple().tm_yday
                chk = pd.DataFrame([{"point": n.point, "node": n.node, "source": c.check_source,
                                     "public_date": c.check_date, "public_doy": doy,
                                     "rity2_swarming_date": r["swarming_date"], "rity2_swarming_doy": r["swarming_doy"],
                                     "rity2_minus_public_days": r["swarming_doy"] - doy,
                                     "rity2_infestation_doy": r["infestation_doy"],
                                     "phenips_clim_swarming_doy": r["phenips_clim_swarming_doy"]}])
                chk.to_csv(tdir / f"check_silava_{safe}.csv", index=False)
                typer.echo(chk.T.to_string())
            typer.echo(m[["year", "swarming_doy", "infestation_doy", "n_filial", "n_filial_MIN", "n_filial_MAX",
                          "n_filial_inca", "phenips_clim_swarming_doy", "cwb_mm", "cwb_z"]].to_string(index=False))
    else:
        lv = country_regions(cfg.boundaries).to_crs(4326)
        cells = main.merge(nodes[["node", "lon", "lat"]], on="node")
        yrs = list(range(c.years[0], c.years[1] + 1))
        figs["swarming"] = viz.climate_maps(lv, cells, "swarming_doy", yrs, "RITY-2 izlidošanas diena (DOY), ERA5",
                                            fdir / "rm4_lv_izlidosana.png", cmap="viridis_r")
        figs["generations"] = viz.climate_maps(lv, cells, "n_filial", yrs, "RITY-2 pilnas paaudzes (AVG)",
                                               fdir / "rm4_lv_paaudzes.png", cmap="YlOrRd", discrete=[0, 1, 2, 3])
        figs["cwb_z"] = viz.climate_maps(lv, cells, "cwb_z", yrs, "Ūdens bilances anomālija z (P − ET0, IV–IX)",
                                         fdir / "rm4_lv_udens_bilance.png", cmap="RdBu", vmin=-2.5, vmax=2.5)
    for k, p in figs.items():
        typer.echo(f"{k}: {p}")
    _metadata(cfg, f"climate_{scope}", {"openmeteo": c.openmeteo.model_dump(), "nodes_used": len(meta),
                                        "nodes_missing": missing, "years": c.years, "baseline": c.baseline,
                                        "wb_months": c.wb_months, "scenarios": c.scenarios})


def _cds_key_present() -> bool:
    """Only checks that the CDS key file (or the cdsapi environment variables) exists; never reads it."""
    import os

    return (Path.home() / ".cdsapirc").exists() or bool(os.environ.get("CDSAPI_URL") and os.environ.get("CDSAPI_KEY"))


@app.command("cds-pilot")
def cds_pilot(config: Path = ConfigArg):
    """Stage 4 pilot (user approval 2026-10-29): ERA5-Land for one month over Latvia (daily max / min /
    mean, 00 UTC accumulations) + hourly u/v for Kalsnava. Measures time and size, checks the format,
    the daily-mean-wind bias, and compares Kalsnava with the Open-Meteo prototype."""
    import calendar

    from . import cds, et0, weather

    cfg = load_config(config)
    c = cfg.climate
    k = c.cds
    if not _cds_key_present():
        typer.echo("CDS key file ~/.cdsapirc not found - stopping (nothing requested).")
        raise typer.Exit(2)
    cache = cfg.cache_dir / "rm" / "cds"
    log = cache / "requests.jsonl"
    y, m = k.pilot_year, k.pilot_month
    days = list(range(1, calendar.monthrange(y, m)[1] + 1))
    tag = f"{y}{m:02d}"
    jobs = {
        "tmax": (cds.DAILY, cds.daily_request(y, m, days, "daily_maximum", ["2m_temperature"], k.area, k.time_zone, k.frequency)),
        "tmin": (cds.DAILY, cds.daily_request(y, m, days, "daily_minimum", ["2m_temperature"], k.area, k.time_zone, k.frequency)),
        "mean": (cds.DAILY, cds.daily_request(y, m, days, "daily_mean", k.daily_mean_vars, k.area, k.time_zone, k.frequency)),
        "accum": (cds.HOURLY, cds.hourly_request(y, m, days, ["00:00"], k.accum_vars, k.area)),
        "wind_hourly": (cds.HOURLY, cds.hourly_request(y, m, days, [f"{h:02d}:00" for h in range(24)],
                                                       ["10m_u_component_of_wind", "10m_v_component_of_wind"], k.wind_box)),
    }
    recs, ds = [], {}
    for name, (dataset, req) in jobs.items():
        target = cds.target_path(cache, dataset, f"{name}_{tag}" + ("_kalsnava" if name == "wind_hourly" else "_lv"))
        typer.echo(f"{name}: {dataset} ...")
        r = cds.retrieve(dataset, req, target, log)
        r |= {"name": name, "kind": cds.file_kind(target), "n_vars": len(req["variable"]), "n_days": len(days)}
        recs.append({kk: v for kk, v in r.items() if kk != "request"})
        ds[name] = cds.open_any(target)
        typer.echo(f"  {r.get('seconds', 'cached')} s, {r['bytes'] / 1e6:.2f} MB, {r['kind']}")
    tdir = cfg.run_dir / "tables"
    tdir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(recs).to_csv(tdir / "cds_pilot_requests.csv", index=False)
    fmt = {n: cds.describe(d) for n, d in ds.items()}
    (tdir / "cds_pilot_format.json").write_text(json.dumps(fmt, indent=1, ensure_ascii=False), encoding="utf-8")
    typer.echo(json.dumps(fmt, indent=1, ensure_ascii=False))

    # Kalsnava point: nearest ERA5-Land cell to the configured point
    p = c.points[0]
    s = {n: cds.point_series(ds[n], p.lon, p.lat) for n in ("tmax", "tmin", "mean", "accum", "wind_hourly")}
    lat_used = float(ds["mean"].latitude.sel(latitude=p.lat, method="nearest"))
    lon_used = float(ds["mean"].longitude.sel(longitude=p.lon, method="nearest"))
    day = pd.DataFrame({"tmax": s["tmax"]["t2m"] - 273.15, "tmin": s["tmin"]["t2m"] - 273.15,
                        "tmean": s["mean"]["t2m"] - 273.15, "tdew": s["mean"]["d2m"] - 273.15,
                        "u10": s["mean"]["u10"], "v10": s["mean"]["v10"], "sp_kpa": s["mean"]["sp"] / 1000})
    day.index = day.index.normalize()
    acc = cds.accum_to_days(s["accum"])
    day = day.join(pd.DataFrame({"precip": acc["tp"] * 1000, "rs_mj": acc["ssrd"] / 1e6, "pev_mm": acc["pev"] * 1000}))
    wh = s["wind_hourly"]
    wh["speed"] = cds.wind_speed(wh["u10"], wh["v10"])
    hd = wh.groupby(wh.index.normalize()).agg(u_mean=("u10", "mean"), v_mean=("v10", "mean"), speed_hourly=("speed", "mean"),
                                              n_hours=("speed", "size"))
    day = day.join(hd)
    day["speed_from_daily_uv"] = cds.wind_speed(day["u10"], day["v10"])
    ea = et0.sat_vp(day["tdew"])                                                     # FAO-56 Eq. 14
    args = dict(tmax=day["tmax"], tmin=day["tmin"], ea=ea, rs=day["rs_mj"], lat_deg=lat_used,
                doy=day.index.dayofyear, p_kpa=day["sp_kpa"])
    day["et0_daily_uv"] = et0.et0_daily(u2=et0.wind_2m(day["speed_from_daily_uv"]), **args)
    day["et0_hourly_speed"] = et0.et0_daily(u2=et0.wind_2m(day["speed_hourly"]), **args)
    day["daylight_h_fao34"] = et0.daylight_hours(lat_used, day.index.dayofyear)
    # Open-Meteo prototype (cached, days in UTC+2 as returned by the API)
    om, meta = weather.load_node(*weather.nearest_node(p.lon, p.lat), c, cfg.cache_dir / "rm" / "openmeteo", budget=None)
    cmp = day.join(om.add_prefix("om_"), how="inner").dropna(subset=["precip", "om_tmax"])
    cmp.to_csv(tdir / "cds_pilot_kalsnava_daily.csv")
    rows = []
    for a, b, lab in (("tmax", "om_tmax", "Tmax °C"), ("tmin", "om_tmin", "Tmin °C"), ("tmean", "om_tmean", "Tmean °C"),
                      ("precip", "om_precip", "P mm/d"), ("et0_daily_uv", "om_et0", "ET0 mm/d"),
                      ("daylight_h_fao34", "om_daylight_s", "dienas garums h")):
        x, yv = cmp[a], cmp[b] / 3600 if b == "om_daylight_s" else cmp[b]
        rows.append({"measure": lab, "n_days": len(x), "era5land_mean": round(x.mean(), 3), "openmeteo_mean": round(yv.mean(), 3),
                     "bias": round((x - yv).mean(), 3), "rmse": round(float(np.sqrt(((x - yv) ** 2).mean())), 3),
                     "r": round(float(np.corrcoef(x, yv)[0, 1]), 3), "sum_era5land": round(x.sum(), 2), "sum_openmeteo": round(yv.sum(), 2)})
    comp = pd.DataFrame(rows)
    comp.to_csv(tdir / "cds_pilot_kalsnava_vs_openmeteo.csv", index=False)
    w = day.dropna(subset=["speed_hourly"])
    wind = {"days": len(w), "n_hours_per_day": sorted(set(w["n_hours"].astype(int))),
            "u_daily_minus_hourly_mean": round(float((w["u10"] - w["u_mean"]).abs().max()), 4),
            "v_daily_minus_hourly_mean": round(float((w["v10"] - w["v_mean"]).abs().max()), 4),
            "speed_daily_uv_mean": round(float(w["speed_from_daily_uv"].mean()), 3),
            "speed_hourly_mean": round(float(w["speed_hourly"].mean()), 3),
            "ratio_mean": round(float((w["speed_from_daily_uv"] / w["speed_hourly"]).mean()), 3),
            "ratio_min": round(float((w["speed_from_daily_uv"] / w["speed_hourly"]).min()), 3),
            "et0_daily_uv_sum": round(float(w["et0_daily_uv"].sum()), 2),
            "et0_hourly_speed_sum": round(float(w["et0_hourly_speed"].sum()), 2),
            "pev_sum_mm": round(float(w["pev_mm"].sum()), 2), "point_lon": lon_used, "point_lat": lat_used,
            "openmeteo_node": meta["node"]}
    (tdir / "cds_pilot_wind.json").write_text(json.dumps(wind, indent=1), encoding="utf-8")
    typer.echo(comp.to_string(index=False))
    typer.echo(json.dumps(wind, indent=1))
    _metadata(cfg, "cds_pilot", {"cds": k.model_dump(), "requests": recs, "point": [lon_used, lat_used]})
