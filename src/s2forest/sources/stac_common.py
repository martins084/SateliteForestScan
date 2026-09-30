"""Shared STAC search / odc-stac loading used by the concrete sources."""

from __future__ import annotations

from datetime import date
from typing import Any, Callable

import odc.stac
import pystac
import pystac_client
import xarray as xr
from dateutil.parser import isoparse
from odc.geo.geobox import GeoBox

from .base import SCL_BAND, SceneItem, reflectance_offset, REFLECTANCE_SCALE


def stac_search(
    client: pystac_client.Client, collection: str,
    bbox: tuple[float, float, float, float], start: date, end: date, max_cloud: float,
) -> list[pystac.Item]:
    search = client.search(
        collections=[collection],
        bbox=bbox,
        datetime=f"{start.isoformat()}/{end.isoformat()}T23:59:59Z",
        query={"eo:cloud_cover": {"lte": max_cloud}},
    )
    return list(search.items())


def to_scene(item: pystac.Item, source: str, collection: str, red_asset: str,
             tile: str) -> SceneItem:
    props = item.properties
    asset_offset = None
    rb = item.assets[red_asset].extra_fields.get("raster:bands")
    if rb and "offset" in rb[0]:
        asset_offset = rb[0]["offset"]
    scale = REFLECTANCE_SCALE
    if rb and rb[0].get("scale"):
        scale = float(rb[0]["scale"])
    dt = item.datetime or isoparse(props["datetime"])
    return SceneItem(
        item=item,
        source=source,
        collection=collection,
        datetime=dt,
        platform=str(props.get("platform", "")).lower(),
        tile=tile,
        baseline=props.get("s2:processing_baseline"),
        cloud_cover=props.get("eo:cloud_cover"),
        scale=scale,
        offset=reflectance_offset(props, asset_offset),
    )


def odc_load(
    scene: SceneItem, bands: list[str], geobox: GeoBox, band_map: dict[str, str],
    reflectance_resampling: str, scl_resampling: str = "nearest",
    patch_url: Callable[[str], str] | None = None,
) -> xr.Dataset:
    assets = [band_map[b] for b in bands]
    stac_cfg: dict[str, Any] = {
        scene.collection: {
            "assets": {
                "*": {"data_type": "uint16", "nodata": 0},
                band_map[SCL_BAND]: {"data_type": "uint8", "nodata": 0},
            }
        }
    }
    resampling = {a: reflectance_resampling for a in assets}
    resampling[band_map[SCL_BAND]] = scl_resampling
    ds = odc.stac.load(
        [scene.item],
        bands=assets,
        geobox=geobox,
        resampling=resampling,
        chunks={"x": 2048, "y": 2048},
        stac_cfg=stac_cfg,
        patch_url=patch_url,
        fail_on_error=True,
    )
    inverse = {v: k for k, v in band_map.items()}
    ds = ds.rename({a: inverse[a] for a in assets}).isel(time=0, drop=True)
    return ds
