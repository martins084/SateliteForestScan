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
    mez012_types: Path | None = None   # MEZ012, all cut types, owners total / state / other
    meb012_owner: Path | None = None   # MEB012 by owner (total / state forest / other), 2013-2024
    meb011_owner: Path | None = None   # MEB011 regions x owner, 2021-2025


class KalsnavaConfig(BaseModel):
    aoi: Path
    suspects: Path               # s2forest run output (read only)
    year: int = 2025


class S2Run(BaseModel):
    """One s2forest run (read only): suspects GPKG with layer suspects_<year>."""
    label: str
    year: int
    variant: str = "all"         # forest_mask.amplitude_scope
    path: Path


class AoiCriteria(BaseModel):
    """Stage 5b: criteria for a 5 x 5 km s2forest validation AOI on LVM land (user, 2026-10-23)."""
    min_lvm_share: float = 0.8       # LVM land units / cell area
    min_conifer_share: float = 0.5   # HRL DLT 2018 conifer / tree cover (as ConiferConfig.min_share)
    min_targets: int = 30            # stem-pest polygons >= LvmConfig.min_target_ha, registered in `years`
    years: tuple[int, int] = (2023, 2024)
    prefer_region: str = "Vidzeme"   # NUTS 2024 region name (NAME_LATN)
    top_cells: int = 10              # choose among the densest target cells
    n_candidates: int = 3


class ValidationConfig(BaseModel):
    """Stage 5b: s2forest blind validation on LVM land (runs listed in LvmConfig.s2forest)."""
    aoi: Path
    reg_years: list[int] = Field(default_factory=lambda: [2023, 2024])
    offsets: list[int] = Field(default_factory=lambda: [-1, 0, 1])
    placebo_n: int = 100
    seed: int = 42
    # damage groups (s2val.GROUPS) with placebo detection shares; "620" keys keep their plain names
    placebo_groups: list[str] = Field(default_factory=lambda: ["620"])


class LvmConfig(BaseModel):
    """Stage 5a: LVM open damage polygons (CC0, state forest) as labels; Internet Archive copies
    while the LVM PublicData server is down (provenance in docs/DATU_AVOTI.md)."""
    damage: Path                 # LVM_BOJAJUMI zip
    damage_member: str = "LVM_BOJAJUMI_Shape.shp"
    damage_snapshot: date        # file date inside the archive (registrations after it are missing)
    land_units: Path             # LVM_ZEMES_VIENIBAS zip (LVM land = analysis set)
    land_units_member: str = "LVM_ZEMES_VIENIBAS_Shape.shp"
    stem_pest: int = 620
    years: tuple[int, int] = (2013, 2024)
    timing_offsets: list[int] = Field(default_factory=lambda: [-1, 0, 1, 2])
    match_buffer_m: float = 20.0
    min_target_ha: float = 0.5   # S1 early-signal targets
    s2forest: list[S2Run] = Field(default_factory=list)
    s1_targets: Path | None = None
    mvr_kalsnava: Path | None = None   # MVR shapefile (extracted district) covering the Kalsnava AOI
    mps: Path | None = None            # "Meža pētīšanas stacija" compartments zip (owner check)
    mps_member: str = "MEZA_PETISANAS_STACIJA_NOGABALI_Shape.shp"
    aoi: AoiCriteria = Field(default_factory=AoiCriteria)
    validation: ValidationConfig | None = None


class Point(BaseModel):
    name: str
    lon: float
    lat: float


class OpenMeteoConfig(BaseModel):
    """Open-Meteo historical API (CC BY 4.0), ERA5 0.25 deg (user decision: `era5`, not best_match /
    era5_land). Free tier limits (pricing page, 2026-10-29): 600 / min, 5000 / h, 10000 / day; a
    request longer than 14 days or with more than 10 variables counts as several calls."""
    url: str = "https://archive-api.open-meteo.com/v1/archive"
    model: str = "era5"
    timezone: str = "Europe/Riga"
    daily: list[str] = Field(default_factory=lambda: [
        "temperature_2m_max", "temperature_2m_min", "temperature_2m_mean", "precipitation_sum",
        "et0_fao_evapotranspiration", "daylight_duration"])
    delay_days: int = 6              # ERA5 on Open-Meteo: "daily with 5 days delay"
    # own budget below the free limits (weighted calls)
    max_per_minute: float = 500
    max_per_hour: float = 4500
    max_per_day: float = 9000


class CdsConfig(BaseModel):
    """Copernicus CDS ERA5-Land (plan 2.21). All days are UTC days (user decision 2026-10-29)."""
    area: list[float] = Field(default_factory=lambda: [58.2, 20.8, 55.5, 28.4])   # N, W, S, E (Latvia + 0.1 deg)
    time_zone: str = "utc+00:00"
    frequency: str = "1_hourly"
    daily_mean_vars: list[str] = Field(default_factory=lambda: [
        "2m_temperature", "2m_dewpoint_temperature", "10m_u_component_of_wind", "10m_v_component_of_wind",
        "surface_pressure"])
    accum_vars: list[str] = Field(default_factory=lambda: [
        "total_precipitation", "surface_solar_radiation_downwards", "potential_evaporation"])
    pilot_year: int = 2023
    pilot_month: int = 4
    wind_box: list[float] = Field(default_factory=lambda: [56.8, 25.8, 56.6, 26.0])  # Kalsnava, hourly u/v


class ClimateConfig(BaseModel):
    """Stage 4: weather (ERA5 via Open-Meteo), RITY-2 phenology, climatic water balance."""
    openmeteo: OpenMeteoConfig = Field(default_factory=OpenMeteoConfig)
    cds: CdsConfig = Field(default_factory=CdsConfig)
    points: list[Point] = Field(default_factory=list)      # e.g. Kalsnava (nearest ERA5 node is used)
    grid_buffer_cells: int = 1       # ERA5 nodes whose 0.25 deg cell touches Latvia + this many rings
    years: tuple[int, int] = (2018, 2026)                  # RITY-2 and annual outputs
    baseline: tuple[int, int] = (1991, 2020)               # water balance reference period
    wb_months: tuple[int, int] = (4, 9)                    # P - ET0 summed over these months (incl.)
    pheno_start: str = "01-01"       # weather window per year for phenology (PHENIPS-Clim sums from 1 Jan)
    pheno_end: str = "10-31"
    scenarios: list[str] = Field(default_factory=lambda: ["AVG", "MIN", "MAX"])   # RITY-2 BTeff scenarios
    main_scenario: str = "AVG"
    check_date: date | None = None   # sanity check: public flight onset date (Silava, 2023)
    check_source: str = ""


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
    lvm: LvmConfig | None = None
    climate: ClimateConfig | None = None

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
