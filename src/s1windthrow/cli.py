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
