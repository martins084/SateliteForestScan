"""Microsoft Planetary Computer. Anonymous access; asset URLs get short-lived
SAS tokens from the public token endpoint (no API key needed)."""

from __future__ import annotations

from datetime import date

import planetary_computer
import pystac_client
import xarray as xr
from odc.geo.geobox import GeoBox

from .base import DataSource, SceneItem
from .stac_common import odc_load, stac_search, to_scene

URL = "https://planetarycomputer.microsoft.com/api/stac/v1"

BAND_MAP = {b: b for b in
            ["B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "B12", "SCL"]}


class PlanetaryComputer(DataSource):
    name = "planetary"

    def __init__(self, collection: str = "sentinel-2-l2a"):
        super().__init__(collection)
        self._client: pystac_client.Client | None = None

    @property
    def client(self) -> pystac_client.Client:
        if self._client is None:
            self._client = pystac_client.Client.open(URL)
        return self._client

    def search(self, bbox_wgs84, start: date, end: date, max_cloud: float) -> list[SceneItem]:
        items = stac_search(self.client, self.collection, bbox_wgs84, start, end, max_cloud)
        return [
            to_scene(it, self.name, self.collection, BAND_MAP["B04"],
                     str(it.properties.get("s2:mgrs_tile", "")))
            for it in items
        ]

    def load(self, scene: SceneItem, bands: list[str], geobox: GeoBox,
             reflectance_resampling: str = "bilinear") -> xr.Dataset:
        # Sign at load time: tokens expire, so signing at search time is fragile.
        return odc_load(scene, bands, geobox, BAND_MAP, reflectance_resampling,
                        patch_url=planetary_computer.sign)
