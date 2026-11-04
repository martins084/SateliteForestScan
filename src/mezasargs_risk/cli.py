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


def _cds_last_day():
    """Last UTC day with all 24 hours in `reanalysis-era5-land` (collection extent; no data request)."""
    from datetime import timedelta

    import cdsapi

    from . import cds

    end = cdsapi.Client(quiet=True).client.get_collection(cds.HOURLY).end_datetime
    return (end - timedelta(hours=23)).date(), str(end)


def _cds_jobs(cfg: RiskConfig, last_day) -> list[dict]:
    from . import cds

    c = cfg.climate
    pm = (int(c.pheno_start[:2]), int(c.pheno_end[:2]))
    months = cds.plan_months((c.baseline[0], c.years[1]), c.wb_months, c.years, pm)
    if c.pheno_extra_years:
        months = sorted(set(months) | set(cds.plan_months(c.pheno_extra_years, pm, c.pheno_extra_years, pm)))
    return cds.month_jobs(months, last_day, c.cds.hourly_vars, c.cds.accum_vars, c.cds.area)


@app.command("cds-download")
def cds_download(config: Path = ConfigArg,
                 only: str = typer.Option(None, help="YYYY-MM: only this month's request"),
                 dry_run: bool = typer.Option(False, "--dry-run", help="list the requests, submit nothing"),
                 skip_done_in_state: bool = typer.Option(False, "--skip-done-in-state",
                                                         help="skip jobs marked done in the state file even without a local "
                                                              "file (continuing on another machine)")):
    """Stage 4 full download (user decision 2026-10-30): hourly ERA5-Land, one request per month (24 h, all
    variables) + 00 UTC accumulations of the following month's 1st day where that month is not downloaded.
    Sequential and resumable: job ids in cache/rm/cds/hourly_state.json are never submitted twice."""
    from . import cds

    cfg = load_config(config)
    last_day, end = _cds_last_day()
    jobs = _cds_jobs(cfg, last_day)
    if only:
        jobs = [j for j in jobs if j["name"] == f"h_{only.replace('-', '_')}"]
    cache = cfg.cache_dir / "rm" / "cds"
    folder = cache / cds.HOURLY / "hourly"
    n_month = sum(j["name"].startswith("h_") for j in jobs)
    state_path = cache / "hourly_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    todo = [j for j in jobs if not cds.find_target(folder, j["name"])
            and not (skip_done_in_state and state.get(j["name"], {}).get("status") == "done")]
    typer.echo(f"dataset end {end} -> last full UTC day {last_day}; {len(jobs)} requests "
               f"({n_month} months + {len(jobs) - n_month} next-month 00 UTC accumulations), {len(todo)} not cached")
    if dry_run:
        for j in jobs:
            r = j["request"]
            typer.echo(f"  {j['name']}: {len(r['variable'])} vars x {len(r['day'])} days x {len(r['time'])} h")
        return
    if not _cds_key_present():
        typer.echo("CDS key file ~/.cdsapirc not found - stopping (nothing requested).")
        raise typer.Exit(2)
    try:
        res = cds.run_jobs(jobs, folder, state_path, cache / "requests.jsonl", echo=typer.echo,
                           skip_state_done=skip_done_in_state)
    except cds.StopDownload as e:
        typer.echo(f"STOP: {e}")
        raise typer.Exit(3)
    typer.echo(json.dumps(res))


@app.command("cds-check-month")
def cds_check_month(config: Path = ConfigArg):
    """Pilot month from the hourly download vs. the pilot files (user 2026-10-30): Tmax / Tmin / Tmean and the
    other daily means vs. `derived-era5-land-daily-statistics`, daily accumulations vs. the pilot 00 UTC file,
    Kalsnava ET0 and precipitation vs. the pilot table."""
    from . import cds, et0

    cfg = load_config(config)
    k = cfg.climate.cds
    y, m = k.pilot_year, k.pilot_month
    tag = f"{y}{m:02d}"
    cache = cfg.cache_dir / "rm" / "cds"
    f = cds.find_target(cache / cds.HOURLY / "hourly", f"h_{y}_{m:02d}")
    ds = cds.open_any(f)
    d = cds.daily_from_hourly(ds).rename(valid_time="day")

    def grid(x):
        x = x.drop_vars([c for c in ("number", "expver") if c in x.coords])
        x = x.assign_coords(latitude=np.round(x.latitude.values, 1), longitude=np.round(x.longitude.values, 1))
        return x.rename(valid_time="day") if "valid_time" in x.dims else x

    d = grid(d)
    pil = {n: grid(cds.open_any(cache / cds.DAILY / f"{n}_{tag}_lv.nc")) for n in ("tmax", "tmin", "mean")}
    acc = grid(cds.open_any(cache / cds.HOURLY / f"accum_{tag}_lv.nc"))
    acc = acc.assign_coords(day=acc.day.dt.floor("D") - np.timedelta64(1, "D"))
    pairs = {"tmax": pil["tmax"]["t2m"] - 273.15, "tmin": pil["tmin"]["t2m"] - 273.15,
             "tmean": pil["mean"]["t2m"] - 273.15, "tdew": pil["mean"]["d2m"] - 273.15,
             "u10": pil["mean"]["u10"], "v10": pil["mean"]["v10"], "sp_kpa": pil["mean"]["sp"] / 1000,
             "precip": acc["tp"] * 1000, "rs_mj": acc["ssrd"] / 1e6, "pev_mm": acc["pev"] * 1000}
    rows = []
    for v, ref in pairs.items():
        a, b = xr_align(d[v], ref)
        diff = (a - b).values.ravel()
        diff = diff[np.isfinite(diff)]
        rows.append({"var": v, "n": int(diff.size), "mean_diff": float(diff.mean()), "max_abs_diff": float(np.abs(diff).max()),
                     "share_diff_gt_0.01": float((np.abs(diff) > 0.01).mean())})
    tab = pd.DataFrame(rows)
    # Kalsnava ET0 / precipitation vs. the pilot table (same FAO-56 code, hourly-speed wind)
    p = cfg.climate.points[0]
    s = d.sel(longitude=p.lon, latitude=p.lat, method="nearest").to_dataframe()
    s.index = pd.DatetimeIndex(s.index)
    lat_used = float(d.latitude.sel(latitude=p.lat, method="nearest"))
    s["et0"] = et0.et0_daily(tmax=s["tmax"], tmin=s["tmin"], ea=et0.sat_vp(s["tdew"]), u2=et0.wind_2m(s["wind_speed"]),
                             rs=s["rs_mj"], lat_deg=lat_used, doy=s.index.dayofyear, p_kpa=s["sp_kpa"])
    pt = pd.read_csv(cfg.run_dir / "tables" / "cds_pilot_kalsnava_daily.csv", index_col=0, parse_dates=True)
    j = s.join(pt[["et0_hourly_speed", "precip"]].add_prefix("pilot_"), how="inner").dropna(subset=["et0", "pilot_et0_hourly_speed"])
    kal = {"days": len(j), "et0_sum": round(float(j["et0"].sum()), 3), "pilot_et0_hourly_speed_sum": round(float(j["pilot_et0_hourly_speed"].sum()), 3),
           "et0_max_abs_diff": float((j["et0"] - j["pilot_et0_hourly_speed"]).abs().max()),
           "precip_sum": round(float(j["precip"].sum()), 3), "pilot_precip_sum": round(float(j["pilot_precip"].sum()), 3),
           "precip_max_abs_diff": float((j["precip"] - j["pilot_precip"]).abs().max())}
    st = json.loads((cache / "hourly_state.json").read_text(encoding="utf-8")).get(f"h_{y}_{m:02d}", {})
    out = {"file": f.name, "kind": cds.file_kind(f), "bytes": f.stat().st_size, "seconds": st.get("seconds"),
           "queue_seconds": st.get("queue_seconds"), "format": cds.describe(ds), "kalsnava": kal,
           "compare": tab.to_dict(orient="records")}
    tdir = cfg.run_dir / "tables"
    tab.to_csv(tdir / f"cds_check_{tag}_vs_pilot.csv", index=False)
    (tdir / f"cds_check_{tag}.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    typer.echo(tab.to_string(index=False))
    typer.echo(json.dumps({kk: v for kk, v in out.items() if kk not in ("format", "compare")}, indent=1))


def xr_align(a, b):
    import xarray as xr

    return xr.align(a, b, join="inner")


def _lv_paths(cfg: RiskConfig):
    from . import cds

    cache = cfg.cache_dir / "rm" / "cds"
    return cache / cds.HOURLY / "hourly", cache / "daily", cfg.run_dir / "latvia"


@app.command("cds-latvia")
def cds_latvia(config: Path = ConfigArg, step: str = typer.Option("all", help="daily | wb | pheno | all")):
    # phenology years: `years` plus `pheno_extra_years` (user 2026-11-04); parts/rity2_<y>.csv per year
    """Stage 4, Latvia (user decision 2026-11-04; run on the server, one year in memory): daily ERA5-Land cubes per
    year (cache/rm/cds/daily/), water balance P - ET0 (IV-IX) 1991-2026 with the standardized anomaly vs 1991-2020,
    RITY-2 per 0.1 deg cell 2018-2026 (resumable per year). Results: <run_dir>/latvia/ (NetCDF + tables)."""
    import time

    import xarray as xr

    from . import lvclimate as L

    cfg = load_config(config)
    c = cfg.climate
    folder, ddir, odir = _lv_paths(cfg)
    (odir / "parts").mkdir(parents=True, exist_ok=True)
    years_all = range(c.baseline[0], c.years[1] + 1)
    dfile = lambda y: ddir / f"era5land_daily_{y}.nc"  # noqa: E731

    def load(y):
        with xr.open_dataset(dfile(y), engine="h5netcdf") as d:
            return d.load()

    if step in ("daily", "all"):
        cov = []
        for y in years_all:
            t0 = time.time()
            done = dfile(y).exists()
            L.year_daily(folder, y, dfile(y))
            d = load(y)
            t = pd.DatetimeIndex(d["valid_time"].values)
            last = lambda v: str(t[d[v].notnull().any(["latitude", "longitude"]).values][-1].date())  # noqa: E731
            cov.append({"year": y, "first_day": str(t[0].date()),
                        "last_day_temperature": last("tmax"), "last_day_accumulations": last("precip"),
                        "days": int(d.sizes["valid_time"])})
            typer.echo(f"daily {y}: {'cached' if done else f'{time.time() - t0:.0f} s'}; {cov[-1]}")
        pd.DataFrame(cov).to_csv(odir / "data_coverage.csv", index=False)
    if step in ("wb", "all"):
        wb = L.anomaly_grid(xr.concat([L.seasonal_grid(load(y), y, c.wb_months) for y in years_all], "year"),
                            c.baseline)
        wb.attrs = {"what": "climatic water balance P - ET0 (FAO-56), months %d-%d, standardized anomaly vs %d-%d "
                            "(ddof 1); not SPEI" % (*c.wb_months, *c.baseline),
                    "incomplete_year": "2026: temperature to 2026-10-27, accumulations to 2026-10-26"}
        wb.to_netcdf(odir / "water_balance_latvia.nc", engine="h5netcdf")
        t = wb[["precip_mm", "et0_mm", "cwb_mm", "cwb_z"]].to_dataframe().dropna(subset=["cwb_mm"]).reset_index()
        t.round(3).to_csv(odir / "water_balance_cells.csv", index=False)
        typer.echo(f"water balance: {wb.sizes['year']} years, {int(wb['cwb_z'].notnull().any('year').sum())} cells")
    if step in ("pheno", "all"):
        pyears = list(range(c.years[0], c.years[1] + 1))
        if c.pheno_extra_years:
            pyears = sorted(set(pyears) | set(range(c.pheno_extra_years[0], c.pheno_extra_years[1] + 1)))
        for y in pyears:
            part = odir / "parts" / f"rity2_{y}.csv"
            if part.exists():
                continue
            t0 = time.time()
            d = load(y)
            rows = []
            for la, lo in L.land_cells(d):
                rows += L.rity_cell(d, la, lo, y, c.scenarios)
            pd.DataFrame(rows).to_csv(part, index=False)
            typer.echo(f"RITY-2 {y}: {len(rows)} rows, {time.time() - t0:.0f} s")
        ph = pd.concat([pd.read_csv(p) for p in sorted((odir / "parts").glob("rity2_*.csv"))], ignore_index=True)
        ph.to_csv(odir / "rity2_cells_long.csv.gz", index=False)
        wide = L.pheno_wide(ph, c.main_scenario)
        wide.to_csv(odir / "rity2_cells.csv", index=False)
        g = load(pyears[0])
        cols = [k for k in wide.columns if k not in ("latitude", "longitude", "year", "scenario", "variant",
                                                     "last_date", "swarming_date", "daylength_shift_min")]
        grid = L.to_grid(wide.assign(complete=wide["complete"].astype(float)), cols, g.latitude.values,
                         g.longitude.values)
        grid.attrs = {"what": "RITY-2 (Ogris 2020) per ERA5-Land cell; main: AVG, ERA5-Land direct, day length FAO-56 "
                              "Eq. 34; suffixes: _MIN/_MAX scenarios, _inca = (1)-(3), _dl-16/_dl+16 = day length "
                              "-/+16 min",
                      "incomplete_year": "2026: temperature to 2026-10-27 (Tsum at that day)"}
        grid.to_netcdf(odir / "rity2_latvia.nc", engine="h5netcdf")
        typer.echo(f"RITY-2: {len(wide)} cell-years, {wide['year'].nunique()} years")
    _metadata(cfg, f"cds_latvia_{step}", {"years": c.years, "baseline": c.baseline, "wb_months": c.wb_months,
                                         "scenarios": c.scenarios, "daylength": "FAO-56 Eq. 34, +-16 min"})


@app.command("cds-latvia-report")
def cds_latvia_report(config: Path = ConfigArg):
    """Stage 4, Latvia, from the results copied from the server (<run_dir>/latvia/): Latvia mask (statistics: cell
    centre in Latvia; maps: cell touches Latvia), checks (Kalsnava vs the Open-Meteo prototype, Silava 2023, 2018
    water balance sign, south-west vs north-east swarming), year tables and maps. Exit 4 if 2018 is not negative
    in most of Latvia (user 2026-11-04: stop and report)."""
    from shapely.geometry import Point as SPoint
    from shapely.geometry import box

    from . import viz
    from .efda import country_regions

    cfg = load_config(config)
    c = cfg.climate
    _, _, odir = _lv_paths(cfg)
    tdir, fdir = cfg.run_dir / "tables", cfg.run_dir / "figures"
    lv = country_regions(cfg.boundaries).to_crs(4326)
    shape = lv.union_all()
    ph = pd.read_csv(odir / "rity2_cells.csv")
    wb = pd.read_csv(odir / "water_balance_cells.csv")
    cov = pd.read_csv(odir / "data_coverage.csv").set_index("year")
    cells = pd.concat([ph, wb])[["latitude", "longitude"]].drop_duplicates().reset_index(drop=True)
    cells["in_lv"] = [shape.contains(SPoint(lo, la)) for la, lo in zip(cells["latitude"], cells["longitude"])]
    cells["touch_lv"] = [shape.intersects(box(lo - 0.05, la - 0.05, lo + 0.05, la + 0.05))
                         for la, lo in zip(cells["latitude"], cells["longitude"])]
    ph, wb = (x.merge(cells, on=["latitude", "longitude"]) for x in (ph, wb))
    pin, win = ph[ph["in_lv"]], wb[wb["in_lv"]]
    incomplete = [int(y) for y in cov.index if cov.loc[y, "last_day_temperature"] < f"{y}-10-31" and y >= c.years[0]]
    out = {"cells_in_latvia": int(cells["in_lv"].sum()), "cells_touching_latvia": int(cells["touch_lv"].sum()),
           "incomplete_years": incomplete, "coverage_last_year": cov.loc[c.years[1]].to_dict()}

    def q(s, p):
        return float(np.nanpercentile(s, p)) if s.notna().any() else np.nan

    # year tables (cells with their centre in Latvia)
    rows = []
    for y, g in pin.groupby("year"):
        r = {"year": y, "incomplete": y in incomplete, "cells": len(g),
             "swarming_not_reached": int(g["swarming_doy"].isna().sum()),
             "swarming_not_reached_all_cells": int(ph.loc[ph["year"] == y, "swarming_doy"].isna().sum()),
             "swarming_doy_min": g["swarming_doy"].min(), "swarming_doy_p10": q(g["swarming_doy"], 10),
             "swarming_doy_median": g["swarming_doy"].median(), "swarming_doy_p90": q(g["swarming_doy"], 90),
             "swarming_doy_max": g["swarming_doy"].max(), "infestation_doy_median": g["infestation_doy"].median(),
             "phenips_clim_doy_median": g["phenips_clim_swarming_doy"].median()}
        for k in ("tsum_F1", "tsum_F2", "tsum_F1_inca", "tsum_F2_inca"):
            r |= {f"{k}_min": g[k].min(), f"{k}_mean": g[k].mean(), f"{k}_max": g[k].max()}
        for k in ("n_filial", "n_filial_inca", "n_filial_MIN", "n_filial_MAX"):
            r |= {f"{k}_{n}": round(float((g[k] == n).mean()), 3) for n in range(4)}
        for s in ("-16", "+16"):
            r[f"share_n_filial_changed_dl{s}"] = round(float((g[f"n_filial_dl{s}"] != g["n_filial"]).mean()), 3)
            r[f"share_n_filial_inca_changed_dl{s}"] = round(float((g[f"n_filial_inca_dl{s}"] != g["n_filial_inca"]).mean()), 3)
            r[f"tsum_F2_dl{s}_mean_diff"] = float((g[f"tsum_F2_dl{s}"] - g["tsum_F2"]).mean())
            r[f"onset_doy_F2_dl{s}_mean_diff"] = float((g[f"onset_doy_F2_dl{s}"] - g["onset_doy_F2"]).mean())
        rows.append(r)
    pd.DataFrame(rows).round(3).to_csv(tdir / "lv_rity2_years.csv", index=False)
    out["swarming_not_reached"] = {int(r["year"]): [r["swarming_not_reached"], r["cells"]] for r in rows}
    wyears = win.groupby("year").agg(cells=("cwb_z", "count"), precip_mm=("precip_mm", "mean"), et0_mm=("et0_mm", "mean"),
                                     cwb_mm=("cwb_mm", "mean"), cwb_z_mean=("cwb_z", "mean"), cwb_z_min=("cwb_z", "min"),
                                     cwb_z_max=("cwb_z", "max"),
                                     share_z_negative=("cwb_z", lambda s: float((s < 0).mean())),
                                     share_z_below_minus1=("cwb_z", lambda s: float((s < -1).mean()))).reset_index()
    wyears["incomplete"] = wyears["year"].isin(incomplete)
    wyears.round(3).to_csv(tdir / "lv_water_balance_years.csv", index=False)

    # Kalsnava: nearest ERA5-Land cell vs the Open-Meteo prototype (ERA5 0.25 deg node)
    p = c.points[0]
    k = cells.iloc[int(np.argmin(np.hypot((cells["longitude"] - p.lon) * np.cos(np.radians(p.lat)),
                                          cells["latitude"] - p.lat)))]
    at_k = lambda d: d[(d["latitude"] == k["latitude"]) & (d["longitude"] == k["longitude"])].set_index("year")  # noqa: E731
    kc, kw = at_k(ph), at_k(wb)
    om = pd.read_csv(tdir / "climate_summary_points.csv").set_index("year")
    cmp_cols = ["swarming_doy", "infestation_doy", "f1_complete_doy", "tsum_F1", "tsum_F2", "n_filial", "n_filial_MIN",
                "n_filial_MAX", "n_filial_inca", "tsum_F1_inca", "phenips_clim_swarming_doy"]
    kal = pd.concat({"era5land": kc[cmp_cols].join(kw[["cwb_mm", "cwb_z"]]),
                     "openmeteo": om[cmp_cols + ["cwb_mm", "cwb_z"]]}, axis=1)
    kal = kal[kal.index >= c.years[0]]
    for col in cmp_cols + ["cwb_mm", "cwb_z"]:
        kal[("diff", col)] = kal[("era5land", col)] - kal[("openmeteo", col)]
    kal.columns = [f"{a}_{b}" for a, b in kal.columns]
    kal.round(3).to_csv(tdir / "lv_kalsnava_era5land_vs_openmeteo.csv")
    out["kalsnava_cell"] = [float(k["latitude"]), float(k["longitude"])]
    out["kalsnava_mean_diff"] = {col: round(float(kal[f"diff_{col}"].mean()), 3) for col in cmp_cols + ["cwb_mm", "cwb_z"]}

    # Silava 2023 (public flight onset 20 April)
    if c.check_date is not None:
        y, doy = c.check_date.year, c.check_date.timetuple().tm_yday
        g = pin[pin["year"] == y]
        out["silava"] = {"public_date": str(c.check_date), "public_doy": doy,
                         "kalsnava_cell_swarming_doy": float(kc.loc[y, "swarming_doy"]),
                         "kalsnava_cell_minus_public": float(kc.loc[y, "swarming_doy"] - doy),
                         "openmeteo_prototype_swarming_doy": float(om.loc[y, "swarming_doy"]),
                         "latvia_swarming_doy_p10_median_p90": [q(g["swarming_doy"], 10), float(g["swarming_doy"].median()),
                                                                q(g["swarming_doy"], 90)],
                         "latvia_share_cells_swarming_by_public_date": round(float((g["swarming_doy"] <= doy).mean()), 3),
                         "kalsnava_cell_phenips_clim_doy": float(kc.loc[y, "phenips_clim_swarming_doy"])}

    # south-west -> north-east gradient of the swarming day (expected earlier in the SW; only reported)
    sw = []
    for y, g in pin.groupby("year"):
        s = ((g["longitude"] - g["longitude"].mean()) * np.cos(np.radians(57.0))
             + (g["latitude"] - g["latitude"].mean())) / np.sqrt(2) * 111.2      # km along the SW -> NE diagonal
        ok = g["swarming_doy"].notna()
        slope = float(np.polyfit(s[ok], g.loc[ok, "swarming_doy"], 1)[0] * 100) if ok.sum() > 2 else np.nan
        lo_, hi_ = s.quantile(1 / 3), s.quantile(2 / 3)
        sw.append({"year": y, "slope_days_per_100km_towards_NE": round(slope, 2),
                   "swarming_doy_mean_SW_third": round(float(g.loc[s <= lo_, "swarming_doy"].mean()), 2),
                   "swarming_doy_mean_NE_third": round(float(g.loc[s >= hi_, "swarming_doy"].mean()), 2),
                   "lon_corr": round(float(g["swarming_doy"].corr(g["longitude"])), 3),
                   "lat_corr": round(float(g["swarming_doy"].corr(g["latitude"])), 3)})
    swt = pd.DataFrame(sw)
    swt["NE_minus_SW_days"] = (swt["swarming_doy_mean_NE_third"] - swt["swarming_doy_mean_SW_third"]).round(2)
    swt.to_csv(tdir / "lv_swarming_sw_ne.csv", index=False)
    out["sw_ne"] = swt[["year", "NE_minus_SW_days", "slope_days_per_100km_towards_NE"]].to_dict(orient="records")

    # 2018 drought sign check
    z18 = win[win["year"] == 2018]["cwb_z"]
    out["check_2018"] = {"cells": int(z18.notna().sum()), "share_z_negative": round(float((z18 < 0).mean()), 3),
                         "mean_z": round(float(z18.mean()), 3)}
    (tdir / "lv_checks.json").write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    typer.echo(json.dumps(out, indent=1, ensure_ascii=False, default=str))
    if not out["check_2018"]["share_z_negative"] > 0.5:
        typer.echo("STOP: 2018 water balance anomaly is not negative in most of Latvia (user 2026-11-04)")
        raise typer.Exit(4)

    # maps (cells touching Latvia)
    yrs = list(range(c.years[0], c.years[1] + 1))
    mp, mw = (x[x["touch_lv"]].rename(columns={"latitude": "lat", "longitude": "lon"}) for x in (ph, wb))
    mp = mp[mp["year"].isin(yrs)]                     # maps: `years` only (pheno_extra_years are in the tables)
    kw_ = {"step": 0.1, "marked": tuple(incomplete)}
    figs = {
        "swarming": viz.climate_maps(lv, mp, "swarming_doy", yrs, "RITY-2 izlidošanas diena (DOY), ERA5-Land 0,1°",
                                     fdir / "rm4_lv_era5land_izlidosana.png", cmap="viridis_r", **kw_),
        "tsum_F1": viz.climate_maps(lv, mp, "tsum_F1", yrs, "Relatīvā termālā summa Tsum_F1 (AVG, ERA5-Land tieši)",
                                    fdir / "rm4_lv_era5land_tsum_f1.png", cmap="YlOrRd", **kw_),
        "tsum_F2": viz.climate_maps(lv, mp, "tsum_F2", yrs, "Relatīvā termālā summa Tsum_F2 (AVG, ERA5-Land tieši)",
                                    fdir / "rm4_lv_era5land_tsum_f2.png", cmap="YlOrRd", **kw_),
        "generations": viz.climate_maps(lv, mp, "n_filial", yrs, "Paaudzes (AVG, ERA5-Land tieši)",
                                        fdir / "rm4_lv_era5land_paaudzes.png", cmap="YlOrRd", discrete=[0, 1, 2, 3], **kw_),
        "generations_inca": viz.climate_maps(lv, mp, "n_filial_inca", yrs, "Paaudzes (AVG, INCA (1)–(3))",
                                             fdir / "rm4_lv_era5land_paaudzes_inca.png", cmap="YlOrRd",
                                             discrete=[0, 1, 2, 3], **kw_),
        "cwb_z": viz.climate_maps(lv, mw, "cwb_z", sorted(int(y) for y in mw["year"].unique()),
                                  "Standartizēta ūdens bilances anomālija z (P − ET0, IV–IX; bāze 1991–2020)",
                                  fdir / "rm4_lv_era5land_udens_bilance.png", cmap="RdBu", vmin=-2.5, vmax=2.5,
                                  ncol=6, step=0.1, marked=()),          # IV-IX 2026 is complete: no '*'
    }
    for n, f in figs.items():
        typer.echo(f"{n}: {f}")
    _metadata(cfg, "cds_latvia_report", {"cells_in_latvia": out["cells_in_latvia"], "incomplete_years": incomplete})


@app.command("drought-compare")
def drought_compare(config: Path = ConfigArg):
    """Drought comparison after stage 4 (user 2026-11-04; DESCRIPTIVE): national damage series (CSP MEB012, EFDA
    classes 1 / 3, LVM 620) and the regional LVM 620 panel vs the ERA5-Land water balance anomaly and RITY-2 thermal
    sums at lags t, t-1, t-2, t-1 + t-2 (Spearman, permutation p, block bootstrap CI, n in every row); event table
    (2002 / 2006 / 2018 / 2023) and the 2023 eastern drought by region. Reads existing outputs only."""
    from shapely.geometry import Point as SPoint

    from . import drought as D
    from . import lvm as LV
    from . import viz
    from .describe import read_csp
    from .efda import country_regions

    cfg = load_config(config)
    d = cfg.drought
    if d is None:
        raise typer.BadParameter("config has no `drought` section")
    tdir, fdir = cfg.run_dir / "tables", cfg.run_dir / "figures"
    tdir.mkdir(parents=True, exist_ok=True)
    fdir.mkdir(parents=True, exist_ok=True)
    y0, y1 = d.damage_years

    # --- climate features (stage 4) ------------------------------------------------------------------------------
    wb = pd.read_csv(d.climate_dir / "tables" / "lv_water_balance_years.csv").set_index("year")
    ry = pd.read_csv(d.climate_dir / "tables" / "lv_rity2_years.csv").set_index("year")
    nat = pd.DataFrame({"cwb_z": wb["cwb_z_mean"], "tsum_F1": ry["tsum_F1_mean"], "tsum_F2": ry["tsum_F2_mean"]})
    feats = ["cwb_z", "tsum_F1", "tsum_F2"]
    regions = country_regions(cfg.boundaries).to_crs(4326)
    wc = pd.read_csv(d.climate_dir / "latvia" / "water_balance_cells.csv")
    pc = pd.read_csv(d.climate_dir / "latvia" / "rity2_cells.csv")
    cells = wc[["latitude", "longitude"]].drop_duplicates().reset_index(drop=True)
    pts = [SPoint(lo, la) for la, lo in zip(cells["latitude"], cells["longitude"])]
    cells["region"] = [next((r.NAME_LATN for r in regions.itertuples() if r.geometry.contains(p)), None) for p in pts]
    cells = cells.dropna(subset=["region"])
    reg_feat = (wc.merge(cells, on=["latitude", "longitude"]).groupby(["region", "year"])["cwb_z"].mean().to_frame()
                .join(pc.merge(cells, on=["latitude", "longitude"]).groupby(["region", "year"])[["tsum_F1", "tsum_F2"]]
                      .mean(), how="left"))
    reg_feat.reset_index().round(4).to_csv(tdir / "drought_region_features.csv", index=False)
    nat.round(4).to_csv(tdir / "drought_national_features.csv")

    # --- damage series (existing tables) -------------------------------------------------------------------------
    meb = read_csp(cfg.stats.meb012, 2)
    meb = meb[meb["Meža īpašuma forma"] == "Pavisam"]

    def csp(kind, ind):
        m = meb[(meb["Meža bojājumi"] == kind) & (meb["indicator"] == ind)]
        return m.set_index("year")["value"].astype(float)

    m3, ha = "Bojājumu rezultātā izcirstais apjoms, tūkst. m³", "Bojā aizgājušās audzes, ha"
    ef = pd.read_csv(d.efda_counts)
    ef = ef[(ef["version"] == d.efda_version) & (ef["region_name"] != "outside")]
    efy = ef.groupby(["agent", "year"])["px"].sum().unstack("agent") * viz.PX_HA
    la = pd.read_csv(d.lvm_annual).set_index("year")
    la = la[(la.index >= y0) & (la.index <= y1)]
    damage = {
        "CSP MEB012 stumbra kaitēkļi, izcirsts tūkst. m3": csp("..kaitēkļu izraisīti stumbru bojājumi", m3),
        "CSP MEB012 stumbra kaitēkļi, bojā gājušas audzes ha": csp("..kaitēkļu izraisīti stumbru bojājumi", ha),
        "CSP MEB012 vējgāzes (kontrole), izcirsts tūkst. m3": csp("Vējgāzes, snieglauzes", m3),
        "EFDA v3.0 klase 1, ha": efy["wind_bark_beetle"],
        "EFDA v3.0 klase 3 (cirte), ha": efy["harvest"],
        "LVM 620, ha": la["lvm_ha"],
        "LVM 620, poligoni": la["lvm_n"].astype(float),
    }
    pd.DataFrame(damage).round(2).to_csv(tdir / "drought_national_damage.csv")

    # --- 1. national lags ----------------------------------------------------------------------------------------
    lf = D.lagged(nat, feats)
    lt = D.lag_table(damage, lf, d.n_perm, d.n_boot, d.seed, d.min_n_ci)
    lt.round(3).to_csv(tdir / "drought_national_lags.csv", index=False)

    # --- 2. regional panel (LVM 620 per 1000 ha LVM land) + 0.1 deg sparsity ----------------------------------------
    lr = pd.read_csv(d.lvm_regions).set_index("NAME_LATN")
    yrs = [c for c in lr.columns if c.isdigit() and y0 <= int(c) <= y1]
    dens = (lr[yrs].div(lr["lvm_land_ha"], axis=0) * 1000).stack().rename("lvm_620_ha_per_1000ha").reset_index()
    dens.columns = ["region", "year", "lvm_620_ha_per_1000ha"]
    dens["year"] = dens["year"].astype(int)
    rl = pd.concat({r: D.lagged(g.droplevel("region"), feats) for r, g in reg_feat.groupby(level="region")},
                   names=["region", "year"]).reset_index()
    panel = dens.merge(rl, on=["region", "year"], how="left")
    panel.round(4).to_csv(tdir / "drought_regional_panel_data.csv", index=False)
    prow = []
    for col in [c for c in rl.columns if "|" in c]:
        s = D.panel_stats(panel, "lvm_620_ha_per_1000ha", col, d.n_perm, d.n_boot, d.seed)
        f, lag = col.split("|")
        prow.append({"feature": f, "lag": lag} | {k: v for k, v in s.items() if k != "feature"})
    pd.DataFrame(prow).round(3).to_csv(tdir / "drought_regional_panel.csv", index=False)
    sparse = None
    if d.lvm_cells and cfg.lvm is not None:
        g = LV.load_damage(cfg.lvm)
        g = g[(g["subtype"] == cfg.lvm.stem_pest) & ~g["empty"] & g["year"].between(y0, y1)].to_crs(4326)
        rp = g.geometry.representative_point()
        key = pd.DataFrame({"year": g["year"].astype(int).to_numpy(),
                            "latitude": np.round(np.round(rp.y.to_numpy() / 0.1) * 0.1, 1),
                            "longitude": np.round(np.round(rp.x.to_numpy() / 0.1) * 0.1, 1)})
        key = key.merge(cells[["latitude", "longitude"]], on=["latitude", "longitude"])
        per = key.groupby(["year", "latitude", "longitude"]).size()
        sparse = pd.DataFrame({"polygons": key.groupby("year").size(),
                               "cells_with_polygon": per.groupby("year").size(),
                               "cells_in_latvia": len(cells),
                               "median_polygons_per_nonempty_cell": per.groupby("year").median()})
        sparse["share_cells_with_polygon"] = (sparse["cells_with_polygon"] / len(cells)).round(3)
        sparse.to_csv(tdir / "drought_lvm_cells_sparsity.csv")

    # --- 3. events -------------------------------------------------------------------------------------------------
    ev = D.event_table({**damage, "cwb_z (Latvijas vid.)": nat["cwb_z"]}, d.events)
    ev.round(3).to_csv(tdir / "drought_events_national.csv", index=False)
    m11 = read_csp(cfg.stats.meb011_owner, 3)
    m11 = m11[(m11["Meža bojājumi"] == "..kaitēkļu izraisīti stumbru bojājumi") & (m11["Meža īpašuma forma"] == "Pavisam")
              & m11["Teritoriālā vienība"].isin(list(LV.MEB011_REGIONS))]
    m11 = m11.assign(region=m11["Teritoriālā vienība"].map(LV.MEB011_REGIONS))
    e23 = reg_feat["cwb_z"].unstack("year")[[2022, 2023, 2024]].add_prefix("cwb_z_")
    e23 = e23.join(dens.pivot(index="region", columns="year", values="lvm_620_ha_per_1000ha")[[2022, 2023, 2024]]
                   .add_prefix("lvm620_ha_per_1000ha_"))
    for ind, tag in ((ha, "meb011_dead_ha"), (m3, "meb011_km3")):
        e23 = e23.join(m11[m11["indicator"] == ind].pivot(index="region", columns="year", values="value")
                       .add_prefix(f"{tag}_"))
    e23["lvm620_ratio_2024_2022"] = e23["lvm620_ha_per_1000ha_2024"] / e23["lvm620_ha_per_1000ha_2022"]
    e23["meb011_dead_ha_ratio_2024_2022"] = e23["meb011_dead_ha_2024"] / e23["meb011_dead_ha_2022"]
    e23["meb011_dead_ha_ratio_2025_2022"] = e23["meb011_dead_ha_2025"] / e23["meb011_dead_ha_2022"]
    e23["region_area_ha"] = regions.set_index("NAME_LATN").to_crs(3035).area.reindex(e23.index) / 1e4
    e23.round(3).to_csv(tdir / "drought_event_2023_regions.csv")

    # --- figures ---------------------------------------------------------------------------------------------------
    figs = {"series": viz.drought_series(nat, damage, cfg.storms, fdir / "rm4b_sausums_gadi.png"),
            "regions": viz.drought_regions(reg_feat.reset_index(), dens, (y0, y1), fdir / "rm4b_sausums_regioni.png")}
    out = {"national_rows": len(lt), "regional_rows": len(prow),
           "sparsity": None if sparse is None else sparse[["polygons", "cells_with_polygon"]].to_dict()}
    typer.echo(json.dumps(out, indent=1, default=str, ensure_ascii=False))
    for n, f in figs.items():
        typer.echo(f"{n}: {f}")
    _metadata(cfg, "drought_compare", {"inputs": {k: str(v) for k, v in d.model_dump().items() if "Path" in type(v).__name__},
                                       "n_perm": d.n_perm, "n_boot": d.n_boot, "seed": d.seed})
