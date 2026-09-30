"""Scene search, deduplication, download of AOI clips and the local cache.

Cache layout (one folder per analysis grid, so different AOIs never collide):

    cache/<grid_key>/index.json          one record per acquisition
    cache/<grid_key>/acq/<acq_key>.zarr  harmonized reflectance (int16, x1e4) + raw SCL

An *acquisition* is one satellite overpass on one day (platform + date). All
MGRS tiles of the same overpass that touch the grid are fused into one layer,
so AOIs on tile edges or in tile overlaps are handled correctly.
"""

from __future__ import annotations

import json
import logging
import shutil
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import dask
import numpy as np
import pandas as pd
import rioxarray  # noqa: F401  (registers .rio accessor)
import xarray as xr
from odc.geo.geobox import GeoBox

from .aoi import aoi_geometry, geobox_key, geometry_mask, make_geobox, read_vector
from .config import Config
from .masking import valid_fraction, valid_mask
from .sources import REFLECTANCE_BANDS, SCL_BAND, DataSource, SceneItem, get_source, harmonize

log = logging.getLogger(__name__)

# Bump when harmonization logic changes, so stale cache entries are refetched.
HARMONIZATION_VERSION = 1
INT16_NODATA = -32768


@dataclass
class Acquisition:
    key: str
    scenes: list[SceneItem]  # tiles of one overpass, all from one source

    @property
    def first(self) -> SceneItem:
        return self.scenes[0]


@dataclass
class Grid:
    geobox: GeoBox           # fetch extent (AOI + normalization buffer)
    aoi_mask: np.ndarray     # True inside the AOI polygon(s)
    key: str


def build_grid(cfg: Config) -> Grid:
    aoi = read_vector(cfg.aoi, cfg.data.crs)
    geom = aoi_geometry(aoi)
    gbox = make_geobox(geom, cfg.data.crs, cfg.data.resolution, buffer_m=cfg.fetch_buffer_m)
    return Grid(geobox=gbox, aoi_mask=geometry_mask(geom, gbox), key=geobox_key(gbox))


def _acq_key(s: SceneItem) -> str:
    return f"{s.acquisition_date:%Y%m%d}_{s.platform.replace('sentinel-', 'S')}"


def deduplicate(scenes_by_source: list[list[SceneItem]]) -> list[Acquisition]:
    """Pick, for every overpass, the first source (in config order) that has it.

    Within one source, if a tile exists in several processing versions (e.g.
    Planetary Computer serves both 04.00 and reprocessed 05.10 for 2022), keep
    the highest processing baseline.
    """
    chosen: dict[str, list[SceneItem]] = {}
    for scenes in scenes_by_source:
        per_acq: dict[str, dict[str, SceneItem]] = defaultdict(dict)
        for s in scenes:
            tiles = per_acq[_acq_key(s)]
            cur = tiles.get(s.tile)
            if cur is None or s.baseline_num > cur.baseline_num:
                tiles[s.tile] = s
        for key, tiles in per_acq.items():
            if key not in chosen:
                chosen[key] = sorted(tiles.values(), key=lambda s: s.tile)
    return [Acquisition(k, v) for k, v in sorted(chosen.items())]


def search_all(cfg: Config, grid: Grid, sources: list[DataSource] | None = None) -> list[Acquisition]:
    bbox = tuple(grid.geobox.to_crs("EPSG:4326").boundingbox)
    if sources is None:
        sources = [get_source(s.name, s.collection) for s in cfg.data.sources]
    per_source = []
    for src in sources:
        found: list[SceneItem] = []
        for year in cfg.time.years:
            start, end = cfg.time.season_range(year)
            found += src.search(bbox, start, end, cfg.data.max_scene_cloud_cover)
        log.info("%s/%s: %d items", src.name, src.collection, len(found))
        per_source.append(found)
    return deduplicate(per_source)


class Cache:
    def __init__(self, root: Path, grid_key: str):
        self.dir = root / grid_key
        self.acq_dir = self.dir / "acq"
        self.acq_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.dir / "index.json"
        self._lock = threading.Lock()
        self.index: dict[str, dict] = {}
        if self.index_path.exists():
            self.index = json.loads(self.index_path.read_text(encoding="utf-8"))

    def store_path(self, key: str) -> Path:
        return self.acq_dir / f"{key}.zarr"

    def record(self, key: str, entry: dict) -> None:
        with self._lock:
            self.index[key] = entry
            tmp = self.index_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.index, indent=1, sort_keys=True), encoding="utf-8")
            tmp.replace(self.index_path)

    def is_done(self, key: str, min_valid: float) -> bool:
        e = self.index.get(key)
        if not e or e.get("harmonization_version") != HARMONIZATION_VERSION:
            return False
        if e["status"] == "accepted":
            return self.store_path(key).exists()
        if e["status"] == "rejected":
            # Re-evaluate only if the threshold was lowered below this scene's value.
            return e["valid_fraction"] < min_valid
        return False


def _fuse(layers: list[xr.Dataset]) -> xr.Dataset:
    """Combine tiles of one overpass: first tile wins where it has data."""
    out = layers[0]
    for other in layers[1:]:
        have = out[SCL_BAND] != 0
        out = xr.Dataset({v: out[v].where(have, other[v]) for v in out.data_vars})
    return out


def _retry(fn: Callable, attempts: int = 3, wait: float = 5.0):
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:  # network errors from GDAL/HTTP are varied
            if i == attempts - 1:
                raise
            log.warning("retrying after error: %s", exc)
            time.sleep(wait * (i + 1))


def fetch_acquisition(acq: Acquisition, src: DataSource, grid: Grid, cfg: Config,
                      cache: Cache) -> dict:
    """Two-step download: SCL first to check clear-sky coverage, bands only if accepted."""
    m = cfg.masking
    buffer_px = int(round(m.cloud_buffer_m / cfg.data.resolution))
    gbox, rs = grid.geobox, cfg.data.reflectance_resampling
    s0 = acq.first
    entry = {
        "harmonization_version": HARMONIZATION_VERSION,
        "datetime": s0.datetime.isoformat(),
        "platform": s0.platform,
        "source": s0.source,
        "collection": s0.collection,
        "baselines": sorted({s.baseline or "" for s in acq.scenes}),
        "tiles": [s.tile for s in acq.scenes],
        "item_ids": [s.id for s in acq.scenes],
        "offsets": sorted({s.offset for s in acq.scenes}),
        "cloud_cover": s0.cloud_cover,
    }

    with dask.config.set(scheduler="synchronous"):
        scl_layers = [
            _retry(lambda s=s: src.load(s, [SCL_BAND], gbox, rs).compute()) for s in acq.scenes
        ]
        scl = _fuse(scl_layers)[SCL_BAND]
        vf = float(valid_fraction(valid_mask(scl, m.invalid_scl, buffer_px), grid.aoi_mask))
        entry["valid_fraction"] = round(vf, 4)
        if vf < cfg.data.min_valid_fraction:
            entry["status"] = "rejected"
            return entry

        layers = []
        for s in acq.scenes:
            raw = _retry(lambda s=s: src.load(s, REFLECTANCE_BANDS + [SCL_BAND], gbox, rs).compute())
            layer = xr.Dataset({SCL_BAND: raw[SCL_BAND]})
            for b in REFLECTANCE_BANDS:
                refl = harmonize(raw[b], s.scale, s.offset)
                layer[b] = (refl * 10000).round().fillna(INT16_NODATA).astype("int16")
            layers.append(layer)
        ds = _fuse(layers)

    for b in REFLECTANCE_BANDS:
        ds[b].attrs = {"scale_factor": 1e-4, "_FillValue": INT16_NODATA}
    ds.attrs = {k: (json.dumps(v) if isinstance(v, list) else ("" if v is None else v))
                for k, v in entry.items()}
    path = cache.store_path(acq.key)
    tmp = path.with_suffix(".tmp.zarr")
    if tmp.exists():
        shutil.rmtree(tmp)
    ds = ds.drop_vars([c for c in ds.coords if c not in ("x", "y")], errors="ignore")
    ds.chunk({"x": 1024, "y": 1024}).to_zarr(tmp, mode="w", consolidated=False)
    if path.exists():
        shutil.rmtree(path)
    tmp.rename(path)
    entry["status"] = "accepted"
    return entry


def fetch(cfg: Config, progress: Callable[[str], None] = print,
          sources: list[DataSource] | None = None) -> pd.DataFrame:
    """Search all sources and make sure every usable acquisition is in the cache.

    Returns a table with one row per acquisition (accepted, rejected or failed).
    """
    grid = build_grid(cfg)
    if sources is None:
        sources = [get_source(s.name, s.collection) for s in cfg.data.sources]
    src_by_name = {(s.name, s.collection): s for s in sources}
    progress(f"Grid {grid.key}: {grid.geobox.shape[1]}x{grid.geobox.shape[0]} px, "
             f"AOI {grid.aoi_mask.sum() * cfg.data.resolution ** 2 / 1e4:.0f} ha")
    acqs = search_all(cfg, grid, sources)
    cache = Cache(cfg.cache_dir, grid.key)
    todo = [a for a in acqs if not cache.is_done(a.key, cfg.data.min_valid_fraction)]
    progress(f"{len(acqs)} acquisitions found, {len(acqs) - len(todo)} already cached, "
             f"{len(todo)} to process")

    def work(a: Acquisition) -> tuple[str, dict]:
        src = src_by_name[(a.first.source, a.first.collection)]
        try:
            return a.key, fetch_acquisition(a, src, grid, cfg, cache)
        except Exception as exc:
            log.exception("failed: %s", a.key)
            return a.key, {"status": "failed", "error": str(exc)[:500],
                           "datetime": a.first.datetime.isoformat(),
                           "source": a.first.source, "harmonization_version": -1}

    done = 0
    with ThreadPoolExecutor(max_workers=cfg.data.workers) as pool:
        futures = [pool.submit(work, a) for a in todo]
        for fut in as_completed(futures):
            key, entry = fut.result()
            cache.record(key, entry)
            done += 1
            if done % 10 == 0 or done == len(todo):
                progress(f"  {done}/{len(todo)} processed")

    keys = {a.key for a in acqs}
    rows = [{"key": k, **v} for k, v in cache.index.items() if k in keys]
    df = pd.DataFrame(rows)
    if not df.empty:
        df["datetime"] = pd.to_datetime(df["datetime"], format="ISO8601", utc=True)
        df = df.sort_values("datetime").reset_index(drop=True)
    return df


def open_cube(cfg: Config, fetch_table: pd.DataFrame | None = None) -> xr.Dataset:
    """Open cached acquisitions as one lazy cube: reflectance (float32, NaN masked)
    with dims (time, y, x), plus coords valid_fraction / source / baseline per time.

    The SCL mask is applied here (not at download time), so changing the
    masking settings does not require a new download.
    """
    grid = build_grid(cfg)
    cache = Cache(cfg.cache_dir, grid.key)
    entries = {k: v for k, v in cache.index.items() if v.get("status") == "accepted"}
    if fetch_table is not None:
        entries = {k: v for k, v in entries.items() if k in set(fetch_table["key"])}
    if not entries:
        raise RuntimeError("No accepted acquisitions in cache - run `fetch` first")

    keys = sorted(entries, key=lambda k: entries[k]["datetime"])
    layers = [xr.open_zarr(cache.store_path(k), consolidated=False, mask_and_scale=False)
              for k in keys]
    times = pd.to_datetime([entries[k]["datetime"] for k in keys], format="ISO8601",
                           utc=True).tz_localize(None)
    ds = xr.concat(layers, dim=pd.Index(times, name="time"), combine_attrs="drop")

    buffer_px = int(round(cfg.masking.cloud_buffer_m / cfg.data.resolution))
    ok = valid_mask(ds[SCL_BAND], cfg.masking.invalid_scl, buffer_px)
    out = xr.Dataset(coords={"time": ds.time, "y": ds.y, "x": ds.x})
    for b in REFLECTANCE_BANDS:
        v = ds[b]
        out[b] = (v.where(v != INT16_NODATA) * np.float32(1e-4)).astype("float32").where(ok)
    out["valid"] = ok & (ds["B04"] != INT16_NODATA)
    out[SCL_BAND] = ds[SCL_BAND]

    vf = valid_fraction(out["valid"], grid.aoi_mask).compute()
    out = out.assign_coords(
        valid_fraction=("time", vf.values.astype("float32")),
        source=("time", [entries[k]["source"] for k in keys]),
        baseline=("time", [",".join(entries[k]["baselines"]) for k in keys]),
        acq_key=("time", keys),
    )
    out = out.isel(time=np.flatnonzero(vf.values >= cfg.data.min_valid_fraction))
    out = out.rio.write_crs(cfg.data.crs)
    out.attrs.update(grid_key=grid.key, crs=cfg.data.crs)
    return out
