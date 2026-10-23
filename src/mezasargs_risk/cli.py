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
