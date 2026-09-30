"""Command line interface: `s2forest <command> CONFIG.yaml`."""

from __future__ import annotations

import json
import logging
import shutil
import sys
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd
import typer
import xarray as xr

from .aoi import read_vector
from .config import Config, load_config
from .fetch import build_grid, fetch as run_fetch, open_cube
from .forestmask import FOREST_ANALYSED, forest_mask

app = typer.Typer(add_completion=False, help="Sentinel-2 forest stress screening (level 1).")


@app.callback()
def main() -> None:
    """Sentinel-2 forest stress screening (level 1)."""
    # Windows consoles default to a legacy code page; keep output printable everywhere.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


ConfigArg = typer.Argument(..., exists=True, dir_okay=False, help="YAML configuration file")
VerboseOpt = typer.Option(False, "--verbose", "-v")


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
def fetch(config: Path = ConfigArg, verbose: bool = VerboseOpt):
    """Search, download AOI clips into the cache, and write fetch diagnostics."""
    from . import viz
    from .pipeline import haze_diagnostics

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

    haze = haze_diagnostics(cfg)
    if not haze.empty:
        haze.to_csv(diag / "haze_by_date.csv", index=False)
        viz.plot_haze_diagnostics(haze, diag / "haze_by_date.png")
        typer.echo(f"Haze test: {int(haze['haze_masked'].sum())} pixel-observations masked, "
                   f"{int(haze['haze_unresolved'].sum())} unresolved (kept), "
                   f"{int(haze['dropped'].sum())} dates dropped below the valid-fraction threshold")

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

    per_year = pd.Series(pd.DatetimeIndex(cube.time.values).year).value_counts().sort_index()
    per_year = {int(k): int(v) for k, v in per_year.items()}
    typer.echo(f"Usable acquisitions per year: {per_year}")
    _write_metadata(cfg, {"fetch": {"grid_key": grid.key, "status_counts": counts,
                                    "usable_per_year": per_year,
                                    "acquisitions": table["key"].tolist()}})
    typer.echo(f"Diagnostics written to {diag}")


@app.command()
def indices(config: Path = ConfigArg, verbose: bool = VerboseOpt):
    """Compute vegetation indices and the forest mask; write GeoTIFFs and maps."""
    from . import viz
    from .pipeline import index_stage, summer_change, write_index_outputs

    cfg = _setup(config, verbose)
    st = index_stage(cfg)
    written = write_index_outputs(cfg, st)

    codes = st.forest_codes
    inside = codes != 255
    shares = {k: float(np.mean(codes[inside] == k)) for k in (0, 1, 2, 3)}
    labels = {0: "not in HRL class", 1: "analysed", 2: "low summer NDVI", 3: "no summer data"}
    typer.echo("Forest mask (share of AOI): " + ", ".join(
        f"{labels[k]} {v:.0%}" for k, v in shares.items()))

    fig_dir = cfg.run_dir / "figures"
    template = st.cube.B04.isel(time=0, drop=True)
    viz.plot_forest_mask(codes, template, fig_dir / "forest_mask.png")
    maps = {n: summer_change(cfg, st, n) for n in cfg.indices}
    base_years = cfg.time.baseline_year_list
    viz.plot_index_change_maps(maps, template, codes == FOREST_ANALYSED,
                               f"{base_years[0]}–{base_years[-1]}", str(cfg.time.monitor_year),
                               fig_dir / f"index_summer_change_{cfg.time.monitor_year}.png")
    _write_metadata(cfg, {"indices": {"names": cfg.indices, "forest_mask_shares": shares,
                                      "rasters": {k: str(v) for k, v in written.items()}}})
    typer.echo(f"{len(written)} rasters written to {cfg.run_dir / 'rasters'}")


@app.command()
def detect(config: Path = ConfigArg, verbose: bool = VerboseOpt):
    """Baseline, anomalies, persistence and suspect polygons for the monitoring year."""
    from . import viz
    from .pipeline import detect_stage, index_stage, write_detect_outputs, write_index_outputs

    cfg = _setup(config, verbose)
    st = index_stage(cfg)
    if not (cfg.run_dir / "rasters" / "forest_mask.tif").exists():
        write_index_outputs(cfg, st)
    ds = detect_stage(cfg, st)
    written = write_detect_outputs(cfg, st, ds)

    year = cfg.time.monitor_year
    fig_dir = cfg.run_dir / "figures"
    aoi = read_vector(cfg.aoi, cfg.data.crs)
    viz.plot_suspects_map(st.cube, ds.polygons, aoi, year, fig_dir / f"suspects_{year}.png")
    stress = ds.polygons[ds.polygons["type"] == "stress"] if len(ds.polygons) else ds.polygons
    if len(stress):
        viz.plot_polygon_chips(st.cube, st.indices, stress, year,
                               fig_dir / f"suspect_chips_stress_{year}.png", n=8)
    if len(ds.polygons):
        viz.plot_polygon_chips(st.cube, st.indices, ds.polygons, year,
                               fig_dir / f"suspect_chips_all_{year}.png", n=8)
    if cfg.anomaly.normalization.enabled:
        viz.plot_regional_offsets(ds.offsets, list(cfg.indices), fig_dir / "regional_offsets.png")

    codes = ds.status_codes
    analysed = np.isin(codes, [0, 1, 2])
    gdf = ds.polygons
    summary = {
        "analysed_ha": float(analysed.sum() * cfg.data.resolution ** 2 / 1e4),
        "baseline_disturbed_ha": float((codes == 3).sum() * cfg.data.resolution ** 2 / 1e4),
        "n_polygons": int(len(gdf)),
        "n_stress": int((gdf["type"] == "stress").sum()) if len(gdf) else 0,
        "n_cut": int((gdf["type"] == "cut").sum()) if len(gdf) else 0,
        "stress_ha": float(gdf.loc[gdf["type"] == "stress", "area_ha"].sum()) if len(gdf) else 0.0,
        "cut_ha": float(gdf.loc[gdf["type"] == "cut", "area_ha"].sum()) if len(gdf) else 0.0,
    }
    typer.echo(f"Analysed forest: {summary['analysed_ha']:.0f} ha "
               f"(excluded as disturbed in baseline: {summary['baseline_disturbed_ha']:.1f} ha)")
    typer.echo(f"Suspect polygons {year}: {summary['n_stress']} stress ({summary['stress_ha']:.2f} ha), "
               f"{summary['n_cut']} cut ({summary['cut_ha']:.2f} ha)")
    _write_metadata(cfg, {"detect": {**summary, "outputs": {k: str(v) for k, v in written.items()}}})
    typer.echo(f"GeoPackage: {written['suspects']}")


if __name__ == "__main__":
    app()
