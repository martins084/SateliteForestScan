"""Synthetic, offline fixtures: a fake STAC source that serves generated DN arrays."""

from __future__ import annotations

from datetime import date, datetime, timezone

import geopandas as gpd
import numpy as np
import pystac
import pytest
import xarray as xr
from odc.geo.geobox import GeoBox
from odc.geo.xr import xr_zeros
from shapely.geometry import box

from s2forest.config import Config, DataConfig, SourceConfig, TimeConfig
from s2forest.sources import REFLECTANCE_BANDS, SCL_BAND, DataSource, SceneItem

# AOI: 1 x 1 km square in EPSG:3059 (central Latvia)
AOI_BOUNDS = (614000.0, 283000.0, 615000.0, 284000.0)


def make_item(item_id: str, dt: datetime, props: dict | None = None, red_offset: float | None = -0.1) -> pystac.Item:
    item = pystac.Item(id=item_id, geometry=None, bbox=None, datetime=dt,
                       properties={"platform": "sentinel-2a", **(props or {})})
    rb = {"scale": 0.0001, "nodata": 0}
    if red_offset is not None:
        rb["offset"] = red_offset
    item.add_asset("red", pystac.Asset(href="memory://red", extra_fields={"raster:bands": [rb]}))
    return item


class FakeSource(DataSource):
    """Serves scenes whose true reflectance is known.

    Each scene is described by (date, platform, tile, baseline, offset, cloudy_fraction).
    True reflectance: B04 = 0.03, B08 = 0.30, others 0.10 (+0.001 * band index).
    DN is derived from the declared offset, so correct harmonization must give
    back exactly the true reflectance.
    """

    name = "fake"

    def __init__(self, scenes: list[dict], collection: str = "fake-l2a", name: str = "fake"):
        super().__init__(collection)
        self.name = name
        self.spec = scenes
        self.load_calls = 0

    @staticmethod
    def true_reflectance(band: str) -> float:
        if band == "B04":
            return 0.03
        if band == "B08":
            return 0.30
        return 0.10 + 0.001 * REFLECTANCE_BANDS.index(band)

    def search(self, bbox_wgs84, start: date, end: date, max_cloud: float) -> list[SceneItem]:
        out = []
        for s in self.spec:
            if not (start <= s["date"] <= end):
                continue
            dt = datetime(s["date"].year, s["date"].month, s["date"].day, 9, 40, tzinfo=timezone.utc)
            item = make_item(f"{self.name}_{s['date']:%Y%m%d}_{s.get('tile', 'T1')}_{s.get('baseline', '05.00')}", dt,
                             {"platform": s.get("platform", "sentinel-2a")})
            out.append(SceneItem(item=item, source=self.name, collection=self.collection,
                                 datetime=dt, platform=s.get("platform", "sentinel-2a"),
                                 tile=s.get("tile", "T1"), baseline=s.get("baseline", "05.00"),
                                 cloud_cover=10.0, scale=1e-4, offset=s.get("offset", -0.1)))
        return out

    def load(self, scene: SceneItem, bands: list[str], geobox: GeoBox,
             reflectance_resampling: str = "bilinear",
             scl_resampling: str = "nearest") -> xr.Dataset:
        self.load_calls += 1
        spec = next(s for s in self.spec if s["date"] == scene.acquisition_date
                    and s.get("tile", "T1") == scene.tile and s.get("baseline", "05.00") == scene.baseline)
        ny, nx = geobox.shape
        ds = xr.Dataset()
        scl = np.full((ny, nx), 4, dtype="uint8")
        cloudy_rows = int(round(spec.get("cloudy", 0.0) * ny))
        scl[:cloudy_rows, :] = 9
        if spec.get("half") == "left":
            scl[:, nx // 2:] = 0
        elif spec.get("half") == "right":
            scl[:, : nx // 2] = 0
        for b in bands:
            if b == SCL_BAND:
                ds[b] = xr_zeros(geobox, dtype="uint8").copy(data=scl)
            else:
                refl = self.true_reflectance(b) + (0.05 if spec.get("hazy") and b == "B02" else 0.0)
                dn = np.round((refl - scene.offset) / 1e-4).astype("uint16")
                arr = np.full((ny, nx), dn, dtype="uint16")
                arr[scl == 0] = 0
                ds[b] = xr_zeros(geobox, dtype="uint16").copy(data=arr)
        return ds


@pytest.fixture
def aoi_file(tmp_path):
    gdf = gpd.GeoDataFrame({"name": ["test"]}, geometry=[box(*AOI_BOUNDS)], crs="EPSG:3059")
    path = tmp_path / "aoi.geojson"
    gdf.to_crs(4326).to_file(path, driver="GeoJSON")
    return path


@pytest.fixture
def base_config(tmp_path, aoi_file) -> Config:
    cfg = Config(
        run_name="test",
        aoi=aoi_file,
        output_dir=tmp_path / "out",
        cache_dir=tmp_path / "cache",
        time=TimeConfig(monitor_year=2024, baseline_years=1),
        data=DataConfig(sources=[SourceConfig(name="earthsearch")], workers=2),
    )
    cfg.anomaly.normalization.enabled = False
    cfg.masking.cloud_buffer_m = 0
    return cfg
