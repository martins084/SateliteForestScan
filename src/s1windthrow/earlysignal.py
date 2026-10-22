"""S1 early-signal test: does backscatter drop before S2 sees bark-beetle stress?

Hypothesis (Hechtl et al. 2025, Forests 16(8):1272): in stands that later die from bark
beetles, backscatter (especially total intensity) drops ~1 dB months before the damage is
visible optically. With RTC GRD (VV, VH) the full Kennaugh elements cannot be computed; a
K0-like total intensity 10*log10(VV + VH) and VH - VV are used instead.

Targets are S2 stress polygons ("S2 aizdomas", not confirmed bark beetle). For each target and
pseudo-target (placebo disc) the difference target - median(5 control discs) is computed for
every acquisition (normalized to the stable-forest median, frozen / snow acquisitions removed),
smoothed with a TRAILING 30-day median, compared with its own baseline (12-24 months before
t_first), and an "early signal" is the first date before t_first where the smoothed difference
is <= baseline - 0.5 dB and stays so for >= 60 days.
"""

from __future__ import annotations

import logging
import math
import warnings
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import yaml
from pydantic import BaseModel, Field
from rasterio.features import geometry_mask, rasterize
from scipy import ndimage

from .config import ChecksConfig, DataConfig, DetectionConfig, ForestMaskConfig, GridConfig, LayerRef
from .method import disc_offsets

log = logging.getLogger(__name__)
VARS = ["vv", "vh", "k0", "vh_minus_vv"]
VAR_NAMES = {"vv": "VV", "vh": "VH", "k0": "K0-līdzīgā 10·log10(VV+VH)", "vh_minus_vv": "VH − VV"}


# --------------------------------------------------------------------------- configuration
class TargetLayer(BaseModel):
    path: Path
    layer: str
    year: int
    run_dir: Path                      # s2forest run with z / index rasters of `year`
    prev_run_dir: Path | None = None   # s2forest run whose z rasters cover year - 1


class EarlyConfig(BaseModel):
    run_name: str
    aoi: Path
    output_dir: Path = Path("output")
    cache_dir: Path = Path("cache")
    period: tuple[date, date]
    grid: GridConfig = Field(default_factory=GridConfig)
    data: DataConfig = Field(default_factory=DataConfig)
    forest_mask: ForestMaskConfig = Field(default_factory=ForestMaskConfig)
    detection: DetectionConfig = Field(default_factory=DetectionConfig)   # for the stable mask
    checks: ChecksConfig = Field(default_factory=ChecksConfig)            # s2_exclude layers
    targets: list[TargetLayer]
    exclude_ids: dict[str, list[int]] = Field(default_factory=dict)       # main group exclusions
    single: list[str] = Field(default_factory=list)                       # shown separately
    n_controls: int = 5
    control_dist_m: tuple[float, float] = (200.0, 2000.0)
    suspects_buffer_m: float = 50.0
    class_purity: float = 0.9
    min_px: int = 10
    n_pseudo: int = 50
    seed: int = 2025
    min_valid_share: float = 0.5
    min_controls: int = 3
    freeze_temp_c: float = 0.0
    smooth_days: int = 30
    baseline_months: tuple[int, int] = (24, 12)
    drop_db: float = 0.5
    persist_days: int = 60
    persist_min_obs: int = 3
    persist_min_span_days: int = 45
    sea_bins: tuple[int, int, int] = (-540, 180, 30)
    bootstrap: int = 2000
    s2_z_threshold: float = 2.5
    s2_prev_autumn_z: float = 1.25

    @property
    def run_dir(self) -> Path:
        return self.output_dir / self.run_name


def load_early_config(path: str | Path) -> EarlyConfig:
    path = Path(path)
    cfg = EarlyConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    base = path.parent.resolve()

    def r(p):
        return None if p is None else (p if Path(p).is_absolute() else (base / p).resolve())

    cfg.aoi, cfg.output_dir, cfg.cache_dir = r(cfg.aoi), r(cfg.output_dir), r(cfg.cache_dir)
    for t in cfg.targets:
        t.path, t.run_dir, t.prev_run_dir = r(t.path), r(t.run_dir), r(t.prev_run_dir)
    for ref in cfg.checks.s2_exclude:
        ref.path = r(ref.path)
    return cfg


# --------------------------------------------------------------------------- pure functions
def smooth_trailing(t: pd.DatetimeIndex, v: np.ndarray, days: int = 30, min_obs: int = 2) -> np.ndarray:
    """Trailing median over (t - days, t]; NaN with fewer than `min_obs` valid values."""
    t = pd.DatetimeIndex(t)
    v = np.asarray(v, float)
    out = np.full(v.shape, np.nan)
    tv = t.values
    for i in range(len(v)):
        sel = (tv > tv[i] - np.timedelta64(days, "D")) & (tv <= tv[i]) & np.isfinite(v)
        if sel.sum() >= min_obs:
            out[i] = np.median(v[sel])
    return out


def baseline_level(t: pd.DatetimeIndex, v: np.ndarray, t_first: pd.Timestamp,
                   months: tuple[int, int] = (24, 12)) -> tuple[float, int]:
    lo = pd.Timestamp(t_first) - pd.DateOffset(months=months[0])
    hi = pd.Timestamp(t_first) - pd.DateOffset(months=months[1])
    sel = (t >= lo) & (t < hi) & np.isfinite(v)
    return (float(np.median(v[sel])) if sel.any() else np.nan), int(sel.sum())


def early_signal(t: pd.DatetimeIndex, smooth: np.ndarray, base: float, t_first: pd.Timestamp,
                 drop: float = 0.5, persist_days: int = 60, min_obs: int = 3,
                 min_span_days: int = 45) -> dict:
    """First date d < t_first where all smoothed values in [d, d + persist_days] are
    <= base - drop (window with >= min_obs values spanning >= min_span_days), and the largest
    sustained drop M = max_d (base - max(smoothed in the window)) over valid windows d < t_first."""
    t = pd.DatetimeIndex(t)
    ok = np.isfinite(smooth)
    tt, ss = t[ok], smooth[ok]
    first, best = None, -np.inf
    if not np.isfinite(base):
        return {"signal_date": None, "max_sustained_drop": np.nan}
    for i, d in enumerate(tt):
        if d >= t_first:
            break
        w = (tt >= d) & (tt <= d + pd.Timedelta(days=persist_days))
        if w.sum() < min_obs or (tt[w].max() - d).days < min_span_days:
            continue
        m = base - ss[w].max()
        best = max(best, m)
        if first is None and m >= drop:
            first = d
    return {"signal_date": first, "max_sustained_drop": best if np.isfinite(best) else np.nan}


def bin_series(rel_days: np.ndarray, values: np.ndarray, edges: np.ndarray) -> np.ndarray:
    """Median of `values` per bin of `rel_days` (NaN where empty)."""
    out = np.full(len(edges) - 1, np.nan)
    for i in range(len(edges) - 1):
        sel = (rel_days >= edges[i]) & (rel_days < edges[i + 1]) & np.isfinite(values)
        if sel.any():
            out[i] = np.median(values[sel])
    return out


def group_median_ci(mat: np.ndarray, n_boot: int, rng: np.random.Generator, q=(5, 95)) -> tuple:
    """mat (units, bins): median over units per bin and a bootstrap CI (units resampled)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        med = np.nanmedian(mat, axis=0)
        idx = rng.integers(0, mat.shape[0], (n_boot, mat.shape[0]))
        boots = np.nanmedian(mat[idx], axis=1)
        lo, hi = np.nanpercentile(boots, q, axis=0)
    return med, lo, hi


def null_group_band(mat: np.ndarray, group_size: int, n_boot: int, rng: np.random.Generator,
                    q=(5, 95)) -> tuple:
    """Distribution of the median of `group_size` randomly drawn placebo units per bin."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        idx = rng.integers(0, mat.shape[0], (n_boot, group_size))
        meds = np.nanmedian(mat[idx], axis=1)
        return np.nanmedian(meds, axis=0), *np.nanpercentile(meds, q, axis=0)


# --------------------------------------------------------------------------- units (targets etc.)
@dataclass
class Unit:
    uid: str
    kind: str                 # target / control / pseudo / pseudo_control
    rows: np.ndarray
    cols: np.ndarray
    parent: str | None = None
    attrs: dict = field(default_factory=dict)


def polygon_pixels(geom, shape, transform) -> tuple[np.ndarray, np.ndarray]:
    m = ~geometry_mask([geom], out_shape=shape, transform=transform)
    r, c = np.nonzero(m)
    return r, c


def sample_discs(eligible: np.ndarray, n_px: int, n: int, rng, occupied: np.ndarray,
                 centre_mask: np.ndarray | None = None, max_tries: int = 20000) -> list[tuple]:
    """Non-overlapping compact discs fully inside `eligible`, centres in `centre_mask`."""
    off = disc_offsets(n_px)
    cand = np.argwhere(eligible if centre_mask is None else (eligible & centre_mask))
    out, tries = [], 0
    H, W = eligible.shape
    while len(out) < n and tries < max_tries and len(cand):
        tries += 1
        cy, cx = cand[rng.integers(len(cand))]
        r, c = off[:, 0] + cy, off[:, 1] + cx
        if r.min() < 0 or c.min() < 0 or r.max() >= H or c.max() >= W:
            continue
        if not eligible[r, c].all() or occupied[r, c].any():
            continue
        out.append((r, c))
        occupied[r, c] = True
    return out


# --------------------------------------------------------------------------- S2 reference dates
def _read(path: Path):
    import rasterio
    with rasterio.open(path) as s:
        return s.read().astype("float32"), pd.DatetimeIndex(s.descriptions), s.transform


def t_last_normal(geom, t_first: pd.Timestamp, layer: TargetLayer, cfg: EarlyConfig,
                  onset_before_season: bool) -> tuple[pd.Timestamp | None, str]:
    """Last valid S2 date before t_first at which the target was not yet anomalous.

    * Same season (t_first is not the first valid date of its season): z rasters of the
      detecting run; last valid date before the uninterrupted stretch of median CRSWIR z >= 2.5
      that ends at t_first.
    * Season start: previous season. If z rasters of the previous year exist (prev_run_dir),
      the same rule with the previous-autumn threshold (z >= 1.25); otherwise the last valid S2
      date of the previous year from the index time series (s2forest onset_prev_autumn = False).
    """
    yr = layer.year
    if not onset_before_season:
        z, zt, tr = _read(layer.run_dir / "rasters" / "anomaly" / f"z_crswir_{yr}.tif")
        return _last_before_run(geom, z, zt, tr, t_first, cfg.s2_z_threshold, cfg), "z ≥ 2,5 (tā pati sezona)"
    if layer.prev_run_dir is not None:
        z, zt, tr = _read(layer.prev_run_dir / "rasters" / "anomaly" / f"z_crswir_{yr - 1}.tif")
        return (_last_before_run(geom, z, zt, tr, t_first, cfg.s2_prev_autumn_z, cfg),
                f"iepr. sezona, z ≥ {cfg.s2_prev_autumn_z:g}")
    a, at, tr = _read(layer.run_dir / "rasters" / "indices" / "ndvi_timeseries.tif")
    r, c = polygon_pixels(geom, a.shape[1:], tr)
    valid = [d for i, d in enumerate(at) if d.year == yr - 1 and np.isfinite(a[i][r, c]).mean() >= cfg.min_valid_share]
    return (max(valid) if valid else None), "iepr. sezonas pēdējais derīgais (z nav; onset_prev_autumn = nē) [N]"


def _last_before_run(geom, z, zt, tr, t_first, thr, cfg) -> pd.Timestamp | None:
    r, c = polygon_pixels(geom, z.shape[1:], tr)
    pts = []
    for i, d in enumerate(zt):
        if d >= t_first:
            continue
        v = z[i][r, c]
        if np.isfinite(v).mean() >= cfg.min_valid_share:
            pts.append((d, float(np.nanmedian(v))))
    pts.sort()
    last_normal = None
    for d, val in pts:   # the last date below thr precedes the elevated stretch ending at t_first
        if val < thr:
            last_normal = d
    return last_normal


# --------------------------------------------------------------------------- per-unit series
def unit_values(vv: np.ndarray, vh: np.ndarray, u: Unit, min_valid: float) -> dict:
    a, b = vv[u.rows, u.cols], vh[u.rows, u.cols]
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.mean() < min_valid:
        return {k: np.nan for k in VARS}
    a, b = a[ok], b[ok]
    with np.errstate(divide="ignore", invalid="ignore"):
        return {"vv": 10 * np.log10(np.median(a)), "vh": 10 * np.log10(np.median(b)),
                "k0": 10 * np.log10(np.median(a + b)),
                "vh_minus_vv": float(np.median(10 * np.log10(b) - 10 * np.log10(a)))}


# --------------------------------------------------------------------------- driver
def _naive(ts) -> pd.Timestamp:
    t = pd.Timestamp(ts)
    return t.tz_convert(None) if t.tzinfo is not None else t


def build_units(cfg: EarlyConfig, grid, masks) -> tuple[list[Unit], pd.DataFrame]:
    """Targets (S2 stress polygons), their controls, pseudo-targets and their controls."""
    rng = np.random.default_rng(cfg.seed)
    shape, tr = masks.stable.shape, grid.geobox.affine
    sus = pd.concat([gpd.read_file(r.path, layer=r.layer).to_crs(cfg.grid.crs)
                     for r in cfg.checks.s2_exclude], ignore_index=True)
    near_sus = rasterize([(g, 1) for g in sus.geometry.buffer(cfg.suspects_buffer_m)], out_shape=shape,
                         transform=tr, fill=0, dtype="uint8").astype(bool)
    base_elig = masks.stable & ~near_sus
    units, rows = [], []
    occupied = np.zeros(shape, bool)
    for layer in cfg.targets:
        g = gpd.read_file(layer.path, layer=layer.layer).to_crs(cfg.grid.crs)
        g = g[g["type"] == "stress"]
        for _, p in g.iterrows():
            r, c = polygon_pixels(p.geometry, shape, tr)
            dl = masks.dlt[r, c]
            cls = 2 if (dl == 2).sum() >= (dl == 1).sum() else 1
            uid = f"{layer.year}#{int(p['id'])}"
            t_first = pd.Timestamp(p["first_detected"])
            tln, rule = t_last_normal(p.geometry, t_first, layer, cfg, bool(p.get("onset_before_season")))
            excl = int(p["id"]) in cfg.exclude_ids.get(str(layer.year), [])
            attrs = {"year": layer.year, "id": int(p["id"]), "area_ha": round(float(p.area_ha), 3),
                     "n_px": len(r), "hrl_class": cls, "t_first": t_first, "t_last_normal": tln,
                     "t_last_normal_rule": rule, "status": p.get("status"),
                     "linear_feature": bool(p.get("linear_feature")), "main_group": not excl,
                     "onset_before_season": bool(p.get("onset_before_season"))}
            units.append(Unit(uid, "target", r, c, None, attrs))
            occupied[r, c] = True
            rows.append({"uid": uid, **attrs})
    targets = [u for u in units if u.kind == "target"]
    lo, hi = (d / cfg.grid.resolution for d in cfg.control_dist_m)

    def controls_for(parent: Unit, n_px: int, cls: int) -> list[Unit]:
        m = np.zeros(shape, bool)
        m[parent.rows, parent.cols] = True
        dist = ndimage.distance_transform_edt(~m)
        ring = (dist >= lo) & (dist <= hi)
        elig = base_elig & (masks.dlt == cls)
        found = sample_discs(elig, n_px, cfg.n_controls, rng, occupied.copy(), ring)
        kind = "control" if parent.kind == "target" else "pseudo_control"
        return [Unit(f"{parent.uid}/c{i}", kind, r, c, parent.uid) for i, (r, c) in enumerate(found)]

    for t in targets:
        cs = controls_for(t, max(cfg.min_px, len(t.rows)), t.attrs["hrl_class"])
        t.attrs["n_controls"] = len(cs)
        units += cs
    main = [t for t in targets if t.attrs["main_group"]]
    elig_c = base_elig & (masks.dlt == 2)
    for j in range(cfg.n_pseudo):
        src = main[j % len(main)]
        n_px = max(cfg.min_px, len(src.rows))
        found = sample_discs(elig_c, n_px, 1, rng, occupied)
        if not found:
            continue
        r, c = found[0]
        pu = Unit(f"P{j:02d}", "pseudo", r, c, None,
                  {"t_first": src.attrs["t_first"], "t_last_normal": src.attrs["t_last_normal"],
                   "source": src.uid, "n_px": n_px, "area_ha": round(n_px * grid.pixel_ha, 3), "hrl_class": 2})
        cs = controls_for(pu, n_px, 2)
        pu.attrs["n_controls"] = len(cs)
        units += [pu] + cs
    for r in rows:
        r["n_controls"] = next(u.attrs["n_controls"] for u in targets if u.uid == r["uid"])
    return units, pd.DataFrame(rows)


def acquisition_series(cfg: EarlyConfig, grid, masks, units: list[Unit], progress=print
                       ) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Long table (uid, acquisition, time, orbit, variables), acquisition table and metadata."""
    from .event import group_acquisitions
    from .load import acquisition_key, load_acquisition
    from .stac import open_client, search_s1
    from .weather import hourly_weather

    client = open_client(cfg.data.stac_url)
    bbox = tuple(gpd.GeoSeries([grid.aoi_wgs84]).total_bounds)
    acqs = group_acquisitions(search_s1(bbox, cfg.period[0], cfg.period[1], client=client,
                                        collection=cfg.data.collection), grid.aoi_wgs84)
    acqs = sorted((a for a in acqs if a.aoi_cover > 0), key=lambda a: min(s.datetime for s in a.scenes))
    cen = grid.aoi_wgs84.centroid
    cd = cfg.cache_dir / "s1" / grid.key
    w, wmeta = hourly_weather(cen.y, cen.x, cfg.period[0], cfg.period[1], cd, snow=True)
    have_snow = bool(w["snow_depth_m"].notna().any())
    rows, arows = [], []
    for i, a in enumerate(acqs):
        t = _naive(min(s.datetime for s in a.scenes))
        h = w.index.get_indexer([t.floor("h")], method="nearest")[0]
        temp = float(w["temp_c"].iloc[h])
        snow = float(w["snow_depth_m"].iloc[h]) if have_snow else np.nan
        reason = ""
        if not np.isfinite(temp):
            reason = "nav temperatūras"
        elif temp < cfg.freeze_temp_c:
            reason = f"temperatūra {temp:.1f} °C"
        elif have_snow and np.isfinite(snow) and snow > 0:
            reason = f"sniegs {snow * 100:.0f} cm"
        arows.append({"key": acquisition_key(a), "time": t, "rel_orbit": a.rel_orbit,
                      "direction": a.direction, "platform": a.platform, "aoi_cover": round(a.aoi_cover, 3),
                      "temp_c": temp, "snow_depth_m": snow, "used": reason == "", "reason": reason})
        if reason:
            continue
        if i % 25 == 0:
            progress(f"acquisition {i + 1}/{len(acqs)} {t:%Y-%m-%d}")
        d = load_acquisition(a, grid.geobox, cfg.data.polarizations, cfg.data.nodata,
                             cfg.data.resampling, cd / "acq")
        norm = {}
        for p in ("vv", "vh"):
            v = d[p][masks.stable]
            med = np.nanmedian(v) if np.isfinite(v).any() else np.nan
            norm[p] = d[p] / med
        for u in units:
            rows.append({"uid": u.uid, "key": acquisition_key(a), "time": t, "rel_orbit": a.rel_orbit,
                         **unit_values(norm["vv"], norm["vh"], u, cfg.min_valid_share)})
    meta = {"weather": wmeta, "snow_available": have_snow, "n_acq_found": len(acqs),
            "n_acq_used": int(sum(r["used"] for r in arows))}
    return pd.DataFrame(rows), pd.DataFrame(arows), meta


def differences(series: pd.DataFrame, units: list[Unit], min_controls: int) -> pd.DataFrame:
    """Target / pseudo value minus the median of its controls, per acquisition and variable."""
    parents = [u.uid for u in units if u.kind in ("target", "pseudo")]
    ctrl: dict[str, list[str]] = {}
    for u in units:
        if u.parent:
            ctrl.setdefault(u.parent, []).append(u.uid)
    out = []
    for uid in parents:
        if uid not in ctrl:
            continue
        tv = series[series.uid == uid].set_index("key")
        cv = series[series.uid.isin(ctrl[uid])]
        for var in VARS:
            pv = cv.pivot_table(index="key", columns="uid", values=var)
            n = pv.notna().sum(axis=1)
            med = pv.median(axis=1).where(n >= min_controls).reindex(tv.index)
            out.append(pd.DataFrame({"uid": uid, "key": tv.index, "time": tv["time"].values,
                                     "rel_orbit": tv["rel_orbit"].values, "var": var,
                                     "diff": (tv[var] - med).values}))
    return pd.concat(out, ignore_index=True)


def analyse(cfg: EarlyConfig, diffs: pd.DataFrame, units: list[Unit]) -> pd.DataFrame:
    """Per unit and variable: baseline, early signal (all orbits pooled), lead times, and the
    number of orbits whose own series shows the signal."""
    info = {u.uid: u for u in units if u.kind in ("target", "pseudo")}
    sig_args = (cfg.drop_db, cfg.persist_days, cfg.persist_min_obs, cfg.persist_min_span_days)
    rows = []
    for (uid, var), g in diffs.groupby(["uid", "var"]):
        g = g.sort_values("time")
        u = info[uid]
        t = pd.DatetimeIndex(g.time)
        v = g["diff"].to_numpy(float)
        t_first = pd.Timestamp(u.attrs["t_first"])
        tln = u.attrs.get("t_last_normal")
        base, nb = baseline_level(t, v, t_first, cfg.baseline_months)
        sig = early_signal(t, smooth_trailing(t, v, cfg.smooth_days), base, t_first, *sig_args)
        d = sig["signal_date"]
        per_orbit = 0
        for _, go in g.groupby("rel_orbit"):
            to = pd.DatetimeIndex(go.time)
            vo = go["diff"].to_numpy(float)
            bo, _ = baseline_level(to, vo, t_first, cfg.baseline_months)
            so = early_signal(to, smooth_trailing(to, vo, cfg.smooth_days), bo, t_first, *sig_args)
            per_orbit += so["signal_date"] is not None
        rows.append({"uid": uid, "kind": u.kind, "var": var, "baseline_db": base, "baseline_n": nb,
                     "signal_date": d, "max_sustained_drop_db": sig["max_sustained_drop"],
                     "lead_vs_t_first_months": (t_first - d).days / 30.44 if d is not None else np.nan,
                     "lead_vs_t_last_normal_months": ((pd.Timestamp(tln) - d).days / 30.44
                                                      if d is not None and tln is not None else np.nan),
                     "before_t_last_normal": bool(d is not None and tln is not None and d < pd.Timestamp(tln)),
                     "orbits_with_signal": per_orbit, "n_orbits": int(g.rel_orbit.nunique())})
    return pd.DataFrame(rows)


def superposed(cfg: EarlyConfig, diffs: pd.DataFrame, res: pd.DataFrame, units: list[Unit],
               uids: list[str]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per unit and bin: median of (diff - own baseline) on days relative to t_last_normal.
    Returns (edges, values (var, unit, bin), acquisitions per bin (var, unit, bin))."""
    lo, hi, step = cfg.sea_bins
    edges = np.arange(lo, hi + step, step)
    info = {u.uid: u for u in units}
    base = res.set_index(["uid", "var"]).baseline_db
    vals = np.full((len(VARS), len(uids), len(edges) - 1), np.nan)
    cnt = np.zeros_like(vals)
    for j, uid in enumerate(uids):
        tln = info[uid].attrs.get("t_last_normal")
        if tln is None:
            continue
        for i, var in enumerate(VARS):
            g = diffs[(diffs.uid == uid) & (diffs["var"] == var)]
            rel = (pd.DatetimeIndex(g.time) - pd.Timestamp(tln)).days.to_numpy()
            v = g["diff"].to_numpy(float) - base.get((uid, var), np.nan)
            vals[i, j] = bin_series(rel, v, edges)
            for b in range(len(edges) - 1):
                cnt[i, j, b] = ((rel >= edges[b]) & (rel < edges[b + 1]) & np.isfinite(v)).sum()
    return edges, vals, cnt
