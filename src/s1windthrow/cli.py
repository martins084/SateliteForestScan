"""Command line: `s1windthrow run CONFIG`."""

from __future__ import annotations

import logging
from pathlib import Path

import typer

from .config import load_config

app = typer.Typer(add_completion=False, help="Sentinel-1 windthrow screening (pre/post event).")


@app.callback()
def main() -> None:
    """Sentinel-1 windthrow screening."""


@app.command()
def run(config: Path = typer.Argument(..., exists=True, help="YAML configuration"),
        verbose: bool = typer.Option(False, "--verbose", "-v")):
    """Full run: acquisitions, composites, index, z, polygons, checks, report."""
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    from .pipeline import run as run_pipeline
    cfg = load_config(config)
    out = run_pipeline(cfg, progress=typer.echo)
    for v, r in out["results"].items():
        p = r.polygons
        n_w = int((p["class"] == "windthrow").sum()) if not p.empty else 0
        n_c = int((p["class"] == "cut_like").sum()) if not p.empty else 0
        typer.echo(f"variant {v}: windthrow {n_w}, cut_like {n_c}")
    typer.echo(f"report: {cfg.run_dir / f'atskaite_{cfg.run_name}.md'}")


@app.command()
def inject(config: Path = typer.Argument(..., exists=True, help="YAML configuration"),
           verbose: bool = typer.Option(False, "--verbose", "-v")):
    """Injection test of synthetic windthrow (variant A acquisitions)."""
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    import geopandas as gpd
    import pandas as pd

    from . import viz
    from .injection import run_injection, summarize
    from .pipeline import orbit_composites, prepare
    from .report import write_injection_report

    cfg = load_config(config)
    pr = prepare(cfg, progress=typer.echo)
    comps, _ = orbit_composites(cfg, pr.table, "used_A", pr.data, pr.masks.stable)
    sus = [gpd.read_file(r.path, layer=r.layer).to_crs(cfg.grid.crs) for r in cfg.checks.s2_exclude]
    suspects = pd.concat(sus, ignore_index=True) if sus else gpd.GeoDataFrame()
    det, fa, sites = run_injection(cfg, comps, pr.masks, pr.grid, suspects, progress=typer.echo)
    rate, table, rec = summarize(det, fa, cfg)
    out = cfg.run_dir / "injection"
    out.mkdir(parents=True, exist_ok=True)
    det.to_csv(out / "injection_sites_detection.csv", index=False)
    fa.to_csv(out / "injection_false_alarms.csv", index=False)
    rate.to_csv(out / "injection_rates.csv", index=False)
    table.to_csv(out / "injection_recommendation_table.csv", index=False)
    sites.to_csv(out / "injection_site_counts.csv", index=False)
    viz.injection_plot(rate, cfg, out / "injection_detection_vs_area.png")
    write_injection_report(cfg, rate, table, fa, sites, rec, out / "injekcijas_tests.md")
    typer.echo(f"recommendation: {rec}")


@app.command()
def earlysignal(config: Path = typer.Argument(..., exists=True, help="YAML configuration"),
                reuse: bool = typer.Option(True, help="reuse the cached per-acquisition series"),
                verbose: bool = typer.Option(False, "--verbose", "-v")):
    """S1 early-signal test (backscatter drop before S2 stress)."""
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    from .earlysignal import load_early_config
    from .earlysignal_run import run as run_es

    cfg = load_early_config(config)
    out = run_es(cfg, progress=typer.echo, reuse=reuse)
    typer.echo(out["summary"].to_string(index=False))
    typer.echo(f"report: {cfg.run_dir / f'atskaite_{cfg.run_name}.md'}")
