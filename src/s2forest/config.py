"""Configuration model and YAML loading.

All tunable parameters of the pipeline live here so that a run is fully
described by one YAML file (which is also copied into the run's output folder).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

# SCL classes: 0 no data, 1 saturated/defective, 2 dark area, 3 cloud shadow,
# 4 vegetation, 5 not vegetated, 6 water, 7 unclassified, 8 cloud medium prob.,
# 9 cloud high prob., 10 thin cirrus, 11 snow/ice.
DEFAULT_INVALID_SCL = [0, 1, 3, 8, 9, 10, 11]


class SourceConfig(BaseModel):
    name: Literal["earthsearch", "planetary"]
    collection: str = "sentinel-2-l2a"


class StandsConfig(BaseModel):
    path: Path | None = None
    id_field: str = "id"
    species_field: str | None = None
    spruce_values: list[str | int] = Field(default_factory=list)


class ReferenceConfig(BaseModel):
    path: Path | None = None
    id_field: str | None = None
    date_field: str = "date"
    reason_field: str | None = None
    reason_values: list[str | int] | None = None


class TimeConfig(BaseModel):
    monitor_year: int
    baseline_years: int = 3
    season_start: str = "05-01"  # MM-DD
    season_end: str = "09-30"

    @field_validator("season_start", "season_end")
    @classmethod
    def _check_mmdd(cls, v: str) -> str:
        date.fromisoformat(f"2001-{v}")
        return v

    @property
    def years(self) -> list[int]:
        return list(range(self.monitor_year - self.baseline_years, self.monitor_year + 1))

    def season_range(self, year: int) -> tuple[date, date]:
        return (
            date.fromisoformat(f"{year}-{self.season_start}"),
            date.fromisoformat(f"{year}-{self.season_end}"),
        )


class DataConfig(BaseModel):
    sources: list[SourceConfig] = Field(
        default_factory=lambda: [
            SourceConfig(name="earthsearch", collection="sentinel-2-c1-l2a"),
            SourceConfig(name="planetary", collection="sentinel-2-l2a"),
        ]
    )
    crs: str = "EPSG:3059"
    resolution: float = 10.0
    max_scene_cloud_cover: float = 95.0
    min_valid_fraction: float = 0.6
    workers: int = 4
    reflectance_resampling: str = "bilinear"


class MaskingConfig(BaseModel):
    invalid_scl: list[int] = Field(default_factory=lambda: list(DEFAULT_INVALID_SCL))
    cloud_buffer_m: float = 20.0


class ForestMaskConfig(BaseModel):
    source: Literal["hrl_dlt_2018", "none"] = "hrl_dlt_2018"
    # HRL DLT classes: 1 broadleaved, 2 coniferous
    classes: list[int] = Field(default_factory=lambda: [2])


class NormalizationConfig(BaseModel):
    enabled: bool = True
    buffer_m: float = 5000.0


class AnomalyConfig(BaseModel):
    z_threshold: float = 2.5
    persistence: int = 2
    doy_window: int = 30
    min_baseline_obs: int = 5
    mad_floor: dict[str, float] = Field(
        default_factory=lambda: {"ndvi": 0.02, "ndre": 0.02, "ndmi": 0.02, "crswir": 0.02}
    )
    primary_index: str = "crswir"
    min_confirming: int = 1
    min_area_ha: float = 0.1
    normalization: NormalizationConfig = Field(default_factory=NormalizationConfig)


class Config(BaseModel):
    run_name: str
    aoi: Path
    output_dir: Path = Path("output")
    cache_dir: Path = Path("cache")
    time: TimeConfig
    data: DataConfig = Field(default_factory=DataConfig)
    masking: MaskingConfig = Field(default_factory=MaskingConfig)
    forest_mask: ForestMaskConfig = Field(default_factory=ForestMaskConfig)
    indices: list[str] = Field(default_factory=lambda: ["ndvi", "ndre", "ndmi", "crswir"])
    anomaly: AnomalyConfig = Field(default_factory=AnomalyConfig)
    stands: StandsConfig = Field(default_factory=StandsConfig)
    reference: ReferenceConfig = Field(default_factory=ReferenceConfig)

    @model_validator(mode="after")
    def _check_primary(self) -> "Config":
        if self.anomaly.primary_index not in self.indices:
            raise ValueError(
                f"anomaly.primary_index '{self.anomaly.primary_index}' is not in indices"
            )
        return self

    @property
    def run_dir(self) -> Path:
        return self.output_dir / self.run_name

    @property
    def fetch_buffer_m(self) -> float:
        """Data is fetched for AOI + this buffer (needed for regional normalization)."""
        norm = self.anomaly.normalization
        return norm.buffer_m if norm.enabled else 0.0


def load_config(path: str | Path) -> Config:
    """Load a YAML config; relative paths are resolved against the YAML's folder."""
    path = Path(path)
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    cfg = Config.model_validate(raw)
    base = path.parent.resolve()

    def _abs(p: Path | None) -> Path | None:
        if p is None or p.is_absolute():
            return p
        return (base / p).resolve()

    cfg.aoi = _abs(cfg.aoi)
    cfg.output_dir = _abs(cfg.output_dir)
    cfg.cache_dir = _abs(cfg.cache_dir)
    cfg.stands.path = _abs(cfg.stands.path)
    cfg.reference.path = _abs(cfg.reference.path)
    return cfg
