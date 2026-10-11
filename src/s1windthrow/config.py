"""Configuration of the Sentinel-1 windthrow module (YAML -> pydantic)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class GridConfig(BaseModel):
    crs: str = "EPSG:3059"
    resolution: float = 10.0


class DataConfig(BaseModel):
    stac_url: str = "https://planetarycomputer.microsoft.com/api/stac/v1"
    collection: str = "sentinel-1-rtc"
    polarizations: list[str] = Field(default_factory=lambda: ["vv", "vh"])
    nodata: float = -32768.0
    resampling: str = "bilinear"
    min_aoi_cover: float = 0.0


class EventConfig(BaseModel):
    name: str
    date: date
    pre_window: tuple[date, date]
    post_window: tuple[date, date]
    n_pre_max: int = 5
    n_post_max: int = 5
    orbits: str | list[int] = "all"


class WeatherConfig(BaseModel):
    source: str = "open-meteo-archive"
    freeze_filter: bool = False
    # Variant B: drop acquisitions with more than this precipitation in the hours
    # before the acquisition, if at least `wet_min_remaining` remain in the orbit/window.
    wet_precip_mm: float = 5.0
    wet_hours: int = 6
    wet_min_remaining: int = 2


class ForestMaskConfig(BaseModel):
    hrl_dlt_classes: list[int] = Field(default_factory=lambda: [1, 2])
    road_buffer_m: float = 20.0
    s2_ndvi_refinement: bool = False
    # Known S2 cuts (type == "cut" in checks.s2_exclude layers) removed from the ANALYSIS
    # mask with this buffer; None = not removed (v1 / first v2 runs).
    exclude_s2_cuts_buffer_m: float | None = None


class ThresholdConfig(BaseModel):
    method: str | None = "robust_z"
    k: float = 3.0
    sensitivity_k: list[float] = Field(default_factory=lambda: [2.5, 3.0, 3.5, 4.0])
    # stable forest = forest mask minus these S2 polygons buffered by `exclude_buffer_m`
    exclude_buffer_m: float = 30.0
    value: float | None = None   # unused (threshold is derived from the data)


class DetectionConfig(BaseModel):
    index: str = "dvh_plus_dvv"
    min_area_ha: float = 0.5
    threshold: ThresholdConfig = Field(default_factory=ThresholdConfig)
    # v2 options; the defaults reproduce v1
    version: str = "v1"
    normalize_per_acquisition: bool = False   # divide each acquisition by its stable-forest median
    smoothing_window: int = 1                 # masked box mean (linear) on the composites, pixels
    z_by_class: bool = False                  # z statistics separately per HRL class


class InjectionConfig(BaseModel):
    """Synthetic windthrow injected into the post composites of the stable forest."""
    sizes_ha: list[float] = Field(default_factory=lambda: [0.5, 1.0, 2.0, 5.0])
    strengths: list[float] = Field(default_factory=lambda: [0.5, 1.0, 2.0])
    base_db: dict[str, float] = Field(default_factory=lambda: {"vv": 0.45, "vh": 0.68})  # Rüetschi 2019
    n_per_combo: int = 30
    seed: int = 42
    min_dist_suspects_m: float = 100.0
    min_gap_m: float = 50.0
    class_purity: float = 0.9
    windows: list[int] = Field(default_factory=lambda: [1, 3, 5, 7])
    k: list[float] = Field(default_factory=lambda: [2.5, 3.0, 3.5, 4.0])
    detected_fraction: float = 0.5
    max_false_alarms_per_1000ha: float = 1.0
    recommend_size_ha: float = 1.0
    recommend_strength: float = 1.0
    max_false_alarms_operational_per_1000ha: float = 5.0
    # Batches: at most this share (%) of each class's stable forest injected per run; None = all
    # sites of one size at once (first test).
    max_batch_share_pct: float | None = None
    # Exclude the smoothing spill-over ring around injected sites from the z statistics.
    exclude_spill_ring: bool = False


class LayerRef(BaseModel):
    path: Path
    layer: str
    run_dir: Path | None = None   # s2forest run that produced the layer (index rasters)


class ChecksConfig(BaseModel):
    s2_run_dir: Path | None = None
    s2_event_split: date | None = None
    s2_indices: list[str] = Field(default_factory=lambda: ["ndvi", "ndre", "ndmi", "crswir"])
    s2_exclude: list[LayerRef] = Field(default_factory=list)
    proxy_cuts: list[LayerRef] = Field(default_factory=list)
    proxy_min_area_ha: float = 0.5
    proxy_months: tuple[int, int] = (5, 9)
    proxy_window_days: int = 28


class Config(BaseModel):
    run_name: str
    aoi: Path
    output_dir: Path = Path("output")
    cache_dir: Path = Path("cache")
    grid: GridConfig = Field(default_factory=GridConfig)
    data: DataConfig = Field(default_factory=DataConfig)
    event: EventConfig
    weather: WeatherConfig = Field(default_factory=WeatherConfig)
    forest_mask: ForestMaskConfig = Field(default_factory=ForestMaskConfig)
    detection: DetectionConfig = Field(default_factory=DetectionConfig)
    checks: ChecksConfig = Field(default_factory=ChecksConfig)
    injection: InjectionConfig = Field(default_factory=InjectionConfig)

    @property
    def run_dir(self) -> Path:
        return self.output_dir / self.run_name


def _resolve(p: Path | None, base: Path) -> Path | None:
    if p is None:
        return None
    return p if p.is_absolute() else (base / p).resolve()


def load_config(path: str | Path) -> Config:
    path = Path(path)
    cfg = Config.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    base = path.parent.resolve()
    cfg.aoi = _resolve(cfg.aoi, base)
    cfg.output_dir = _resolve(cfg.output_dir, base)
    cfg.cache_dir = _resolve(cfg.cache_dir, base)
    c = cfg.checks
    c.s2_run_dir = _resolve(c.s2_run_dir, base)
    for ref in c.s2_exclude + c.proxy_cuts:
        ref.path = _resolve(ref.path, base)
        ref.run_dir = _resolve(ref.run_dir, base)
    return cfg
