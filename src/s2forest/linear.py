"""Linear features: OpenStreetMap roads (optionally ditches / power lines).

Pixels within `buffer_m` of a road are removed from the analysis forest mask:
road edges are mixed pixels and change with traffic dust, verge mowing and
road works, which the detector otherwise reports as stress. OSM data are
fetched from the public Overpass API (no key; ODbL licence) and cached as
GeoPackage per analysis grid.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import requests
from odc.geo.geobox import GeoBox
from rasterio.features import rasterize
from shapely.geometry import LineString

from . import __version__
from .config import LinearFeaturesConfig

log = logging.getLogger(__name__)
# Public Overpass instances, tried in order (the main one is often overloaded).
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
USER_AGENT = f"s2forest/{__version__} (Sentinel-2 forest screening, LBTU student project)"


def overpass_query(bbox_wgs84: tuple[float, float, float, float], cfg: LinearFeaturesConfig) -> str:
    w, s, e, n = bbox_wgs84
    bb = f"({s:.6f},{w:.6f},{n:.6f},{e:.6f})"
    parts = [f'way["highway"~"^({"|".join(cfg.highway_types)})$"]{bb};']
    if cfg.include_waterways:
        parts.append(f'way["waterway"~"^({"|".join(cfg.waterway_types)})$"]{bb};')
    if cfg.include_power_lines:
        parts.append(f'way["power"="line"]{bb};')
    return f"[out:json][timeout:120];({''.join(parts)});out geom;"


def parse_overpass(payload: dict) -> gpd.GeoDataFrame:
    rows = []
    for el in payload.get("elements", []):
        geom = el.get("geometry")
        if el.get("type") != "way" or not geom or len(geom) < 2:
            continue
        tags = el.get("tags", {})
        kind = ("road" if "highway" in tags else "waterway" if "waterway" in tags
                else "power_line" if tags.get("power") == "line" else "other")
        rows.append({"osm_id": el["id"], "kind": kind,
                     "subtype": tags.get("highway") or tags.get("waterway") or tags.get("power"),
                     "geometry": LineString([(p["lon"], p["lat"]) for p in geom])})
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326") if rows else \
        gpd.GeoDataFrame(columns=["osm_id", "kind", "subtype", "geometry"], geometry="geometry",
                         crs="EPSG:4326")


def _post_overpass(query: str, attempts: int = 2, wait: float = 10.0) -> dict:
    import time

    errors = []
    for url in OVERPASS_URLS:
        for i in range(attempts):
            try:
                resp = requests.post(url, data={"data": query}, timeout=180,
                                     headers={"User-Agent": USER_AGENT,
                                              "Accept": "application/json"})
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{url}: {exc}")
                log.info("Overpass attempt failed: %s", exc)
                if i < attempts - 1:
                    time.sleep(wait)
    raise RuntimeError("all Overpass endpoints failed: " + " | ".join(errors[-3:]))


def fetch_osm_lines(geobox: GeoBox, cfg: LinearFeaturesConfig, cache_dir: Path) -> gpd.GeoDataFrame:
    bbox = tuple(geobox.to_crs("EPSG:4326").boundingbox)
    pad = 0.003  # ~200-300 m, so buffers of features just outside the AOI are included
    bbox = (bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad)
    query = overpass_query(bbox, cfg)
    key = hashlib.sha1(query.encode()).hexdigest()[:10]
    path = cache_dir / f"osm_lines_{key}.gpkg"
    if path.exists():
        return gpd.read_file(path)
    gdf = parse_overpass(_post_overpass(query))
    path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(path, driver="GPKG")
    (cache_dir / f"osm_lines_{key}.query.json").write_text(json.dumps({"query": query}),
                                                           encoding="utf-8")
    return gdf


def buffer_mask(lines: gpd.GeoDataFrame, geobox: GeoBox, buffer_m: float) -> np.ndarray:
    """Boolean (y, x): pixel centre within `buffer_m` of any line."""
    if lines.empty:
        return np.zeros(geobox.shape, dtype=bool)
    shapes_ = [(g, 1) for g in lines.to_crs(str(geobox.crs)).geometry.buffer(buffer_m)]
    return rasterize(shapes_, out_shape=geobox.shape, transform=geobox.affine, fill=0,
                     dtype="uint8").astype(bool)


def linear_mask(geobox: GeoBox, cfg: LinearFeaturesConfig, cache_dir: Path
                ) -> tuple[np.ndarray | None, gpd.GeoDataFrame | None]:
    """(mask or None, lines or None). Network errors disable the mask with a warning."""
    if not cfg.enabled:
        return None, None
    try:
        lines = fetch_osm_lines(geobox, cfg, cache_dir)
    except Exception as exc:  # noqa: BLE001 - the analysis can run without it
        log.warning("OSM linear features unavailable (%s); road mask disabled", exc)
        return None, None
    return buffer_mask(lines, geobox, cfg.buffer_m), lines


def elongation(geom) -> float:
    """Long / short side of the minimum rotated rectangle (1 = compact)."""
    r = geom.minimum_rotated_rectangle
    if r.geom_type != "Polygon":
        return float("inf")
    xs, ys = r.exterior.coords.xy
    d = [float(np.hypot(xs[i + 1] - xs[i], ys[i + 1] - ys[i])) for i in range(2)]
    return max(d) / max(min(d), 1e-6)
