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
    """Forest stands (State Forest Register open data schema by default).

    Informative attributes only in v0.2-kalsnava (not used in detection,
    confidence or priority).
    """
    path: Path | None = None              # GeoPackage / SHP / zip, clipped to the AOI
    id_field: str = "id"
    species_fields: list[str] = Field(default_factory=lambda: [f"s1{i}" for i in range(5)])
    basal_area_fields: list[str] = Field(default_factory=lambda: [f"g1{i}" for i in range(5)])
    tree_count_fields: list[str] = Field(default_factory=lambda: [f"n1{i}" for i in range(5)])
    age_fields: list[str] = Field(default_factory=lambda: [f"a1{i}" for i in range(5)])
    forest_type_field: str = "mt"
    # VMD species classifier: 3 = Egle, 15 = Citas egles
    spruce_values: list[int] = Field(default_factory=lambda: [3, 15])


class ReferenceConfig(BaseModel):
    path: Path | None = None
    id_field: str | None = None
    date_field: str = "date"
    reason_field: str | None = None
    reason_values: list[str | int] | None = None
    # Free text shown in the report next to the validation results (what the
    # references are, how reliable their dates / reasons are).
    description: str | None = None
    # A detection matches a reference if it intersects the reference buffered by this.
    match_buffer_m: float = 10.0
    # References cut later than this are out of scope (default: 31 March of the
    # year after the monitoring year). ISO date string.
    max_date: str | None = None


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
    def baseline_year_list(self) -> list[int]:
        return list(range(self.monitor_year - self.baseline_years, self.monitor_year))

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
    # Resolution of the context layer (AOI + normalization buffer); read from COG overviews.
    context_resolution: float = 60.0


class HazeConfig(BaseModel):
    """Per-pixel temporal test for thin cloud / haze missed by SCL.

    An observation is masked when B02 exceeds the pixel's own baseline-years
    reference (median, same DOY window) by more than `b02_threshold` AND the
    next valid observation of the same season is not elevated (transient).
    """
    enabled: bool = True
    # Calibrated on Kalsnava 2026-09-15 (haze streaks) vs clear dates: clear-date
    # forest B02 excess p95 = 0.017, p99 = 0.025. 0.015 starts masking clear-cut
    # edges on clear dates; 0.03 misses streak margins.
    b02_threshold: float = 0.02
    doy_window: int = 30
    min_ref_obs: int = 3
    # Last observation of a season (no successor to prove transience) is kept,
    # unless unresolved candidates cover at least this share of the AOI's valid
    # pixels on that date: spatially widespread B02 elevation on one date is
    # atmospheric, local change is not (clear last dates: 0.1-1.5 %, hazy: 12-24 %).
    last_obs_scene_share: float = 0.10


class MaskingConfig(BaseModel):
    invalid_scl: list[int] = Field(default_factory=lambda: list(DEFAULT_INVALID_SCL))
    cloud_buffer_m: float = 20.0
    haze: HazeConfig = Field(default_factory=HazeConfig)


class ForestMaskConfig(BaseModel):
    source: Literal["hrl_dlt_2018", "none"] = "hrl_dlt_2018"
    # HRL DLT classes: 1 broadleaved, 2 coniferous
    classes: list[int] = Field(default_factory=lambda: [2])
    # Pixels whose summer NDVI median over the baseline years is below this are
    # excluded (clear-cuts and young stands since the 2018 HRL reference year).
    # None disables the refinement.
    # Calibrated on Kalsnava: healthy canopy mode ~0.78 (sd ~0.04); felled / young
    # stands form a tail at 0.35-0.65. 0.65 ~ mode - 3 sd.
    min_summer_ndvi: float | None = 0.65
    # Pixels whose baseline-period seasonal range (p90 - p10 of all observations of
    # `seasonal_range_index`) exceeds this are excluded: not a closed conifer stand
    # (mixed / deciduous / wet / sparse). None disables. Calibrated on Kalsnava:
    # NDVI range mode ~0.10 (closed conifer), long tail of mixed / young stands;
    # median + 3 robust sd = 0.21 (baseline 2022-24) / 0.22 (2023-25).
    seasonal_range_index: str = "ndvi"
    max_seasonal_range: float | None = 0.22
    summer_start: str = "06-01"  # MM-DD
    summer_end: str = "08-31"


class LinearFeaturesConfig(BaseModel):
    """OSM linear features removed from the analysis mask (buffered)."""
    enabled: bool = True
    buffer_m: float = 20.0
    highway_types: list[str] = Field(default_factory=lambda: [
        "motorway", "trunk", "primary", "secondary", "tertiary", "unclassified",
        "residential", "service", "track", "motorway_link", "trunk_link", "primary_link",
        "secondary_link", "tertiary_link"])
    # Drainage ditches are very common in Latvian forests; masking them all may
    # remove a lot of forest, so they are off by default.
    include_waterways: bool = False
    waterway_types: list[str] = Field(default_factory=lambda: ["ditch", "drain", "canal"])
    include_power_lines: bool = False
    # Stress polygons with elongation (min. rotated rectangle long/short side) at or
    # above this are flagged `linear_feature` (not deleted).
    elongation_threshold: float = 3.0
    # Stress polygons whose edge is within this distance of a road get the flag
    # `near_road` and a lower drone priority (not deleted, mask unchanged).
    # Road enrichment test (Kalsnava 2025): stress pixels enriched 1.5-1.9x at
    # 20-100 m, i.e. a wider buffer would not remove the effect.
    near_road_m: float = 30.0
    # Ring of healthy (analysed) forest around each stress polygon used as a local
    # control in the standard ring diagnostic.
    control_ring_m: float = 100.0


class NormalizationConfig(BaseModel):
    enabled: bool = True
    buffer_m: float = 5000.0
    # Context pixel (coarse grid) counts as forest if at least this share of it is
    # in the HRL forest classes.
    min_forest_fraction: float = 0.5
    # Dates with fewer usable context forest pixels are not normalized (offset 0).
    min_pixels: int = 50


class AnomalyConfig(BaseModel):
    # Baseline model per pixel and index:
    #  "harmonic": robust (IRLS, Huber) fit of intercept + `harmonics` annual
    #              harmonics to all baseline-year observations; scale = MAD of the
    #              model residuals. Follows the seasonal curve, so an early-season
    #              observation is compared with the early-season level.
    #  "window":   median / MAD of baseline observations within +-doy_window days.
    #              Biased at the season edges (the window is one-sided there).
    baseline_method: Literal["harmonic", "window"] = "harmonic"
    harmonics: int = 1
    robust_iterations: int = 5
    huber_k: float = 1.345
    z_threshold: float = 2.5
    persistence: int = 2
    # The persistent run must also span at least this many days (first to last
    # anomalous observation): two images a few days apart share weather and
    # atmosphere and are not independent confirmations. A run still shorter than
    # this at the end of the season is kept with status "new".
    persistence_min_days: int = 7
    # Previous-autumn check: median primary z of the polygon in the previous
    # year's observations from `prev_autumn_start` to the season end; at or above
    # `onset_prev_autumn_z` the change is flagged as having started last autumn.
    prev_autumn_start: str = "08-15"
    onset_prev_autumn_z: float = 1.25
    doy_window: int = 30
    min_baseline_obs: int = 5
    # Minimum z-score scale per index. MAD from ~10-15 baseline observations in a
    # +-30 day window is often underestimated, inflating z. Calibrated on Kalsnava
    # (scripts/calibrate_mad_floor.py) as the 75th percentile of the per-pixel
    # robust scale (1.4826 * MAD) over analysed forest.
    mad_floor: dict[str, float] = Field(
        default_factory=lambda: {"ndvi": 0.035, "ndre": 0.034, "ndmi": 0.047, "crswir": 0.061}
    )
    primary_index: str = "crswir"
    min_confirming: int = 1
    min_area_ha: float = 0.1
    # "cut" (stand-replacing change) signature per observation, either:
    #  a) NDVI <= cut_ndvi_max and >= cut_ndvi_drop below the baseline, or
    #  b) NDMI >= cut_ndmi_drop below the baseline. Calibrated on Kalsnava 2026:
    #     visually confirmed winter clear-cuts have NDMI change -0.16 .. -0.28 while
    #     NDVI stays ~0.6 (regrowing ground vegetation), so rule (a) alone missed them.
    cut_ndvi_max: float = 0.5
    cut_ndvi_drop: float = 0.25
    cut_ndmi_drop: float = 0.15
    # Polygon status needs at least this many valid observations after the first
    # detection: fewer -> "new"; else median primary z >= k/2 -> "persistent",
    # below -> "recovered" (e.g. early-spring phenology artefacts).
    status_min_obs: int = 2
    normalization: NormalizationConfig = Field(default_factory=NormalizationConfig)


class TargetsConfig(BaseModel):
    """Drone target layer (`drone_targets`)."""
    statuses: list[str] = Field(default_factory=lambda: ["new", "persistent"])
    # High-risk zone: band of conifer forest along recent cuts (bark beetles often
    # attack newly exposed stand edges).
    cut_edge_enabled: bool = True
    cut_edge_width_m: float = 30.0
    cut_edge_years: int = 2        # cuts of the monitoring year and the year before
    cut_edge_min_cut_ha: float = 0.3   # ignore smaller cuts / thinning patches
    cut_edge_min_area_ha: float = 0.05  # minimum band area per cut
    # risk_score of a cut-edge zone = weighted sum of three 0..1 components:
    #  orientation: how much the exposed forest wall faces `risk_peak_azimuth`
    #               (S/SW/W walls get the most sun -> heat stress, beetle attacks);
    #               per pixel (1 + cos(face - peak)) / 2, averaged over the band;
    #  freshness:   1 for cuts of the monitoring year, decreasing linearly to
    #               1 / cut_edge_years for the oldest year considered;
    #  conifer:     share of the full band (before masking) that is conifer forest.
    risk_weights: dict[str, float] = Field(
        default_factory=lambda: {"orientation": 0.4, "freshness": 0.3, "conifer": 0.3})
    risk_peak_azimuth: float = 225.0   # direction the exposed wall faces; S=180, SW=225, W=270
    # Missions: targets grouped by proximity into flight areas.
    mission_max_area_ha: float = 30.0  # convex hull of buffered targets (~1-2 Mavic 3M batteries, low altitude)
    mission_buffer_m: float = 20.0     # margin around targets in the flight area
    mission_max_gap_m: float = 500.0   # do not join targets farther apart than this
    max_missions: int = 10             # missions exported (by priority)


class Config(BaseModel):
    run_name: str
    aoi: Path
    output_dir: Path = Path("output")
    cache_dir: Path = Path("cache")
    time: TimeConfig
    data: DataConfig = Field(default_factory=DataConfig)
    masking: MaskingConfig = Field(default_factory=MaskingConfig)
    forest_mask: ForestMaskConfig = Field(default_factory=ForestMaskConfig)
    linear_features: LinearFeaturesConfig = Field(default_factory=LinearFeaturesConfig)
    indices: list[str] = Field(default_factory=lambda: ["ndvi", "ndre", "ndmi", "crswir"])
    anomaly: AnomalyConfig = Field(default_factory=AnomalyConfig)
    targets: TargetsConfig = Field(default_factory=TargetsConfig)
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
