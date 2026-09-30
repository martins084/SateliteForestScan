"""Element84 Earth Search (AWS), public, no authentication."""

from __future__ import annotations

import warnings
from datetime import date

import pystac_client
import xarray as xr
from odc.geo.geobox import GeoBox

from .base import DataSource, SceneItem
from .stac_common import odc_load, stac_search, to_scene

URL = "https://earth-search.aws.element84.com/v1"

BAND_MAP = {
    "B02": "blue", "B03": "green", "B04": "red", "B05": "rededge1", "B06": "rededge2",
    "B07": "rededge3", "B08": "nir", "B8A": "nir08", "B11": "swir16", "B12": "swir22",
    "SCL": "scl",
}


class EarthSearch(DataSource):
    name = "earthsearch"

    def __init__(self, collection: str = "sentinel-2-c1-l2a"):
        super().__init__(collection)
        self._client: pystac_client.Client | None = None

    @property
    def client(self) -> pystac_client.Client:
        if self._client is None:
            self._client = pystac_client.Client.open(URL)
        return self._client

    def search(self, bbox_wgs84, start: date, end: date, max_cloud: float) -> list[SceneItem]:
        with warnings.catch_warnings():
            # pystac's storage-extension migration warns on these hrefs; harmless.
            warnings.simplefilter("ignore", UserWarning)
            items = stac_search(self.client, self.collection, bbox_wgs84, start, end, max_cloud)
        scenes = []
        for it in items:
            p = it.properties
            tile = p.get("grid:code", "").replace("MGRS-", "") or (
                f"{p.get('mgrs:utm_zone')}{p.get('mgrs:latitude_band')}{p.get('mgrs:grid_square')}"
            )
            scenes.append(to_scene(it, self.name, self.collection, BAND_MAP["B04"], tile))
        return scenes

    def load(self, scene: SceneItem, bands: list[str], geobox: GeoBox,
             reflectance_resampling: str = "bilinear") -> xr.Dataset:
        return odc_load(scene, bands, geobox, BAND_MAP, reflectance_resampling)
