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
