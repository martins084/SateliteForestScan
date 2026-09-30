"""Command line interface: `s2forest <command> CONFIG.yaml`."""

from __future__ import annotations

import json
import logging
import shutil
from importlib.metadata import version
from pathlib import Path

import pandas as pd
import typer
import xarray as xr

from .aoi import read_vector
from .config import Config, load_config
from .fetch import build_grid, fetch as run_fetch, open_cube
from .forestmask import forest_mask

app = typer.Typer(add_completion=False, help="Sentinel-2 forest stress screening (level 1).")

@app.callback()
def main() -> None:
    """Sentinel-2 forest stress screening (level 1)."""


ConfigArg = typer.Argument(..., exists=True, dir_okay=False, help="YAML configuration file")


def _setup(config: Path, verbose: bool) -> Config:
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config(config)
    cfg.run_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(config, cfg.run_dir / "config.yaml")
    return cfg


def _write_metadata(cfg: Config, extra: dict) -> None:
    path = cfg.run_dir / "run_metadata.json"
    meta = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    meta["versions"] = {p: version(p) for p in
                        ("s2forest", "odc-stac", "xarray", "numpy", "geopandas", "rasterio")}
    meta.update(extra)
    path.write_text(json.dumps(meta, indent=1, default=str), encoding="utf-8")


def conifer_reflectance_series(cube: xr.Dataset, region) -> pd.DataFrame:
    """Per-acquisition median reflectance over `region` pixels (for the harmonization plot)."""
    region_da = xr.DataArray(region, dims=("y", "x"))
    out = {}
    for b in ("B04", "B08", "B11"):
        out[b] = cube[b].where(region_da).median(dim=("y", "x")).compute().values
    df = pd.DataFrame(out)
    df["time"] = pd.to_datetime(cube.time.values)
    df["source"] = cube.source.values
    df["baseline"] = cube.baseline.values
    return df


@app.command()
def fetch(config: Path = ConfigArg, verbose: bool = typer.Option(False, "--verbose", "-v")):
    """Search, download AOI clips into the cache, and write fetch diagnostics."""
    from . import viz

    cfg = _setup(config, verbose)
    table = run_fetch(cfg, progress=typer.echo)
    diag = cfg.run_dir / "diagnostics"
    diag.mkdir(parents=True, exist_ok=True)
    table.to_csv(diag / "acquisitions.csv", index=False)

    counts = table["status"].value_counts().to_dict()
    typer.echo(f"Status: {counts}")
    failed = table[table["status"] == "failed"]
    for _, r in failed.iterrows():
        typer.echo(f"  FAILED {r['key']}: {r.get('error', '')}", err=True)

    viz.plot_valid_observations(table, cfg.data.min_valid_fraction, diag / "valid_observations.png")
    cube = open_cube(cfg, table)
    grid = build_grid(cfg)
    aoi = read_vector(cfg.aoi, cfg.data.crs)
    viz.plot_quicklooks(cube, aoi, diag / "quicklooks.png")

    fmask = forest_mask(grid.geobox, cfg.cache_dir / grid.key, cfg.forest_mask.source,
                        cfg.forest_mask.classes)
    region = grid.aoi_mask if fmask is None else (grid.aoi_mask & fmask)
    series = conifer_reflectance_series(cube, region)
    series.to_csv(diag / "harmonization_check.csv", index=False)
    viz.plot_harmonization_check(series, diag / "harmonization_check.png")

    per_year = pd.DataFrame({"time": pd.to_datetime(cube.time.values)}).groupby(
        lambda i: cube.time.dt.year.values[i]).size().to_dict()
    typer.echo(f"Usable acquisitions per year: {per_year}")
    _write_metadata(cfg, {"fetch": {"grid_key": grid.key, "status_counts": counts,
                                    "usable_per_year": per_year,
                                    "acquisitions": table["key"].tolist()}})
    typer.echo(f"Diagnostics written to {diag}")


if __name__ == "__main__":
    app()
