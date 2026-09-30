"""Data source abstraction.

A DataSource searches a STAC catalogue and loads a clipped, reprojected cube for
one item. Everything downstream works with canonical ESA band names (B04, B8A,
SCL, ...), so adding a new source (e.g. Copernicus Data Space Ecosystem) only
means writing a new subclass with its own band mapping and URL handling.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import numpy as np
import pystac
import xarray as xr
from odc.geo.geobox import GeoBox

# Canonical bands used by the tool.
REFLECTANCE_BANDS = ["B02", "B03", "B04", "B05", "B08", "B8A", "B11", "B12"]
SCL_BAND = "SCL"

REFLECTANCE_SCALE = 1e-4
BOA_ADD_OFFSET = -0.1  # -1000 DN, introduced with processing baseline 04.00


@dataclass
class SceneItem:
    """One STAC item plus the metadata needed for harmonization and dedup."""

    item: pystac.Item
    source: str
    collection: str
    datetime: datetime
    platform: str
    tile: str
    baseline: str | None
    cloud_cover: float | None
    scale: float
    offset: float

    @property
    def id(self) -> str:
        return self.item.id

    @property
    def acquisition_date(self) -> date:
        return self.datetime.date()

    @property
    def baseline_num(self) -> float:
        try:
            return float(self.baseline) if self.baseline else 0.0
        except ValueError:
            return 0.0

    def cache_attrs(self) -> dict[str, Any]:
        return {
            "item_id": self.id,
            "source": self.source,
            "collection": self.collection,
            "datetime": self.datetime.isoformat(),
            "platform": self.platform,
            "tile": self.tile,
            "baseline": self.baseline or "",
            "cloud_cover": -1.0 if self.cloud_cover is None else float(self.cloud_cover),
            "scale": self.scale,
            "offset": self.offset,
        }


def reflectance_offset(props: dict[str, Any], asset_offset: float | None) -> float:
    """Offset (in reflectance units) that must be ADDED after scaling DN by 1e-4.

    Rules, verified empirically against the catalogues (see README):
    * Earth Search legacy `sentinel-2-l2a` with `earthsearch:boa_offset_applied=True`:
      pixel values were already shifted by -1000 DN, although `raster:bands`
      still advertises offset=-0.1. Applying it again would double-correct.
    * Otherwise, if the asset declares an offset in `raster:bands`, use it
      (Earth Search `sentinel-2-c1-l2a`: -0.1 for all years).
    * Otherwise (e.g. Planetary Computer, which has no raster:bands), use the
      processing baseline: >= 04.00 means -0.1.
    """
    if props.get("earthsearch:boa_offset_applied") is True:
        return 0.0
    if asset_offset is not None:
        return float(asset_offset)
    baseline = props.get("s2:processing_baseline")
    try:
        if baseline is not None and float(baseline) >= 4.0:
            return BOA_ADD_OFFSET
    except ValueError:
        pass
    return 0.0


def harmonize(dn: xr.DataArray, scale: float, offset: float) -> xr.DataArray:
    """DN (uint16, 0 = nodata) -> surface reflectance float32 (NaN = nodata)."""
    refl = dn.astype("float32") * np.float32(scale) + np.float32(offset)
    return refl.where(dn != 0)


class DataSource(ABC):
    name: str

    def __init__(self, collection: str):
        self.collection = collection

    @abstractmethod
    def search(
        self, bbox_wgs84: tuple[float, float, float, float], start: date, end: date,
        max_cloud: float,
    ) -> list[SceneItem]:
        """Return scene items intersecting bbox within [start, end]."""

    @abstractmethod
    def load(self, scene: SceneItem, bands: list[str], geobox: GeoBox,
             reflectance_resampling: str = "bilinear",
             scl_resampling: str = "nearest") -> xr.Dataset:
        """Load raw DN for `bands` (canonical names) on `geobox`, lazily (dask).

        For a geobox coarser than the native resolution, the reader uses COG
        overviews, so only a fraction of the data is transferred.
        """


def get_source(name: str, collection: str) -> DataSource:
    if name == "earthsearch":
        from .earthsearch import EarthSearch

        return EarthSearch(collection)
    if name == "planetary":
        from .planetary import PlanetaryComputer

        return PlanetaryComputer(collection)
    raise ValueError(f"Unknown data source: {name}")
