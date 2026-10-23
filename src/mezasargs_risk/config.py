"""Configuration of the risk-model tools (YAML -> pydantic). Relative paths are resolved
against the YAML file's directory."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class EfdaVersion(BaseModel):
    """One EFDA release, members already extracted from the country archive into `dir`."""
    version: str
    doi: str
    archive: str                 # zip the members come from (v3.0: Latvia is in Lithuania.zip)
    dir: Path
    first_year: int = 1985
    agent: str                   # annual agent layer (one band per year): 1 wind/bark beetle, 2 fire, 3 harvest
    agent_aggregated: str
    forest: str                  # forest land-use mask (1 = forest)


class EfdaConfig(BaseModel):
    main: EfdaVersion            # used for labels / analysis (v3.0)
    crosscheck: EfdaVersion | None = None   # v2.1.1


class BoundaryConfig(BaseModel):
    path: Path                   # GISCO NUTS level 3 (EPSG:3035)
    country: str = "LV"
    min_cover: float = 0.95      # plan 2.2: raster must cover >= 95 % of the country / its forest
    border_buffer_m: float = 1000.0  # 1:1M boundary vs. the EFDA country clip
    control_lonlat: tuple[float, float] = (25.85, 56.69)   # Kalsnava test AOI


class ConiferConfig(BaseModel):
    dlt_res_m: float = 100.0     # HRL DLT 2018 sampled at this step (server-side nearest)
    min_share: float = 0.5       # cell is "conifer-dominated" if conifer >= this share of tree cover
    sensitivity: list[float] = Field(default_factory=lambda: [0.4, 0.6])


class Storm(BaseModel):
    date: date
    name: str
    note: str
    url: str


class StatsConfig(BaseModel):
    """CSP tables (data: VMD), downloaded as CSV from data.stat.gov.lv."""
    meb012: Path | None = None   # forest damage by type 2013-2024
    mez012: Path | None = None   # cut areas by cut type and species 2014-2025


class KalsnavaConfig(BaseModel):
    aoi: Path
    suspects: Path               # s2forest run output (read only)
    year: int = 2025


class RiskConfig(BaseModel):
    run_name: str
    output_dir: Path
    cache_dir: Path
    efda: EfdaConfig
    boundaries: BoundaryConfig
    grid_km: float = 10.0
    conifer: ConiferConfig = Field(default_factory=ConiferConfig)
    stats: StatsConfig = Field(default_factory=StatsConfig)
    storms: list[Storm] = Field(default_factory=list)
    kalsnava: KalsnavaConfig | None = None

    @property
    def run_dir(self) -> Path:
        return self.output_dir / self.run_name


def _resolve(obj, base: Path):
    if isinstance(obj, BaseModel):
        for name, value in obj:
            if isinstance(value, Path) and not value.is_absolute():
                setattr(obj, name, (base / value).resolve())
            else:
                _resolve(value, base)
    elif isinstance(obj, list):
        for v in obj:
            _resolve(v, base)


def load_config(path: str | Path) -> RiskConfig:
    path = Path(path)
    cfg = RiskConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    _resolve(cfg, path.parent.resolve())
    return cfg
