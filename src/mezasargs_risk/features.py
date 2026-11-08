"""Stage 6a (user decision 2026-11-04): feature specification and a PILOT block training table (cell x year).

Unit: EFDA v3.0 30 m cell (EPSG:3035). Analysis set: EFDA forest land use AND LVM land (plan 2.16), cells whose
centre is inside the pilot block. Label (plan 2.5 schema `cell_id, year, label, source, confidence`): LVM 620
(stem pests) polygon registered in year t covers the cell centre; confidence = polygon cover share of the cell
(3 x 3 sub-cells). Negatives are "not registered" (positive-unlabeled, plan 2.16).

No-leakage rule (plan 2.4): every feature of year t reads inputs of years <= t-1 only. `Ctx.layer` enforces it:
asking for a year >= t raises `LeakageError`. Static inputs (forest land-use mask, LVM land units) and snapshots with
a known date (HRL DLT 2018, CHMv2 imagery ~2018) carry their date; CHMv2 is used only for t >= 2020 (L2), HRL 2018
features are flagged for t <= 2018 (plan 2.4).

Beetle pressure (main, user 2026-11-04): distance to the nearest LVM 620 polygon and 620 area within 500 m / 2 km,
for t-1 and for t-2..t-3 separately (the t-2..t-3 group alone = L3 sensitivity). EFDA class 1 only as a sensitivity
feature. Climate from ERA5-Land (CDS): cwb_z t-1, cwb_z t-1 + t-2, Tsum_F1 t-1; swarming DOY and generations t-1
for sensitivity only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import ndimage
from scipy.signal import fftconvolve

CELL = 30.0
CELL_HA = 0.09
DIST_CAP = 5000.0


class LeakageError(RuntimeError):
    pass


@dataclass
class Ctx:
    """Inputs of one block on one grid. Yearly layers: dict year -> 2-D array. `t` is set per feature year."""
    shape: tuple[int, int]
    lvm620: dict[int, np.ndarray] = field(default_factory=dict)      # cover share 0..1 per cell and year
    efda: dict[int, np.ndarray] = field(default_factory=dict)        # EFDA agent per year (1, 2, 3, 255)
    climate: pd.DataFrame | None = None     # index (year, clim_cell), columns cwb_z, tsum_F1, swarming_doy, ...
    clim_cell: np.ndarray | None = None     # int id of the ERA5-Land cell of each 30 m cell
    picea: dict[int, np.ndarray] = field(default_factory=dict)       # Picea p (0-100), key = period END year
    picea500: dict[int, np.ndarray] = field(default_factory=dict)    # mean Picea p within 500 m, same keys
    t: int | None = None
    used: dict[str, set] = field(default_factory=dict)

    def layer(self, kind: str, year: int, feature: str) -> np.ndarray:
        if self.t is None or year >= self.t:
            raise LeakageError(f"{feature}: {kind} {year} requested for t = {self.t}")
        self.used.setdefault(feature, set()).add(year)
        src = getattr(self, kind)
        return src[year] if year in src else np.zeros(self.shape, dtype=np.float32 if kind == "lvm620" else np.uint8)

    def clim(self, var: str, year: int, feature: str) -> np.ndarray:
        if self.t is None or year >= self.t:
            raise LeakageError(f"{feature}: climate {year} requested for t = {self.t}")
        self.used.setdefault(feature, set()).add(year)
        s = self.climate[var].xs(year, level="year") if year in self.climate.index.get_level_values("year") else None
        if s is None:
            return np.full(self.shape, np.nan, dtype=np.float32)
        return s.reindex(self.clim_cell.ravel()).to_numpy(dtype=np.float32).reshape(self.shape)


def mean_within(x: np.ndarray, radius_m: float) -> np.ndarray:
    """Mean of the finite values of `x` within `radius_m` of each cell centre (NaN where none)."""
    ok = np.isfinite(x)
    k = disk(radius_m)
    s = fftconvolve(np.where(ok, x, 0).astype(np.float32), k, mode="same")
    n = fftconvolve(ok.astype(np.float32), k, mode="same")
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(n > 0.5, s / np.maximum(n, 1e-6), np.nan).astype(np.float32)


def disk(radius_m: float) -> np.ndarray:
    r = int(math.ceil(radius_m / CELL))
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    return ((xx ** 2 + yy ** 2) * CELL ** 2 <= radius_m ** 2).astype(np.float32)


def dist_to(mask: np.ndarray, cap: float = DIST_CAP) -> np.ndarray:
    """Distance (m) from every cell centre to the nearest True cell (0 inside); `cap` where none is present."""
    if not mask.any():
        return np.full(mask.shape, cap, dtype=np.float32)
    return np.minimum(ndimage.distance_transform_edt(~mask) * CELL, cap).astype(np.float32)


def area_within(share: np.ndarray, radius_m: float) -> np.ndarray:
    """ha of the layer (cover share per cell) within `radius_m` of each cell centre (incl. the cell)."""
    if not share.any():
        return np.zeros(share.shape, dtype=np.float32)
    return np.maximum(fftconvolve(share.astype(np.float32), disk(radius_m), mode="same"), 0).astype(np.float32) * CELL_HA


def south_edge(cut: np.ndarray, max_m: float = 60.0) -> np.ndarray:
    """1 where the nearest cut cell lies within `max_m` to the S, SW or W of the cell (azimuth 135-270 deg from
    north, clockwise) - the stand's S / SW / W side is open; 0 otherwise (also inside the cut)."""
    if not cut.any():
        return np.zeros(cut.shape, dtype=np.uint8)
    d, (iy, ix) = ndimage.distance_transform_edt(~cut, return_indices=True)
    yy, xx = np.indices(cut.shape)
    az = (np.degrees(np.arctan2(ix - xx, -(iy - yy))) + 360) % 360       # rows grow southwards
    return ((d > 0) & (d * CELL <= max_m) & (az >= 135) & (az <= 270)).astype(np.uint8)


def year_features(ctx: Ctx, t: int, efda_first: int = 1985) -> dict[str, np.ndarray]:
    """All features of year t on the block grid. Inputs are read only through `ctx.layer` / `ctx.clim` (<= t-1)."""
    ctx.t, ctx.used = t, {}
    f = {}
    # beetle pressure: LVM 620, t-1 and t-2..t-3 separately
    for tag, years in (("t1", [t - 1]), ("t23", [t - 2, t - 3])):
        name = f"p620_{tag}"
        share = sum(ctx.layer("lvm620", y, name) for y in years)
        f[f"p620_dist_{tag}"] = dist_to(share > 0)
        f[f"p620_ha500_{tag}"] = area_within(share, 500)
        f[f"p620_ha2k_{tag}"] = area_within(share, 2000)
        ctx.used.setdefault(f"p620_dist_{tag}", set()).update(years)
        ctx.used.setdefault(f"p620_ha500_{tag}", set()).update(years)
        ctx.used.setdefault(f"p620_ha2k_{tag}", set()).update(years)
    # EFDA class 1 (sensitivity only)
    for tag, years in (("t1", [t - 1]), ("t23", [t - 2, t - 3])):
        m = np.zeros(ctx.shape, bool)
        for y in years:
            if y >= efda_first:
                m |= ctx.layer("efda", y, f"efda1_{tag}") == 1
        f[f"efda1_dist_{tag}"] = dist_to(m)
        f[f"efda1_ha2k_{tag}"] = area_within(m.astype(np.float32), 2000)
    # edges and disturbance history from EFDA (harvest = 3, any = 1-3), <= t-1
    hist = {y: ctx.layer("efda", y, "efda_hist") for y in range(max(efda_first, t - 10), t)}
    cut13 = np.zeros(ctx.shape, bool)
    cut110 = np.zeros(ctx.shape, bool)
    last_any = np.full(ctx.shape, -1, dtype=np.int16)
    for y, a in hist.items():
        cut110 |= a == 3
        if y >= t - 3:
            cut13 |= a == 3
        last_any[np.isin(a, (1, 2, 3))] = y
    f["cut_dist_t13"] = dist_to(cut13)
    f["cut_dist_t110"] = dist_to(cut110)
    f["edge_s_sw_w_t13"] = south_edge(cut13)
    f["years_since_dist"] = np.where(last_any >= 0, t - last_any, 99).astype(np.float32)   # 99 = none in 10 years
    # Picea abies probability (stand, user 2026-11-05): latest period ending <= t-1 (plan 2.4), cell + 500 m mean
    if ctx.picea:
        ends = [e for e in ctx.picea if e <= t - 1]
        if ends:
            f["picea_p"] = ctx.layer("picea", max(ends), "picea_p")
            f["picea_p500"] = ctx.layer("picea500", max(ends), "picea_p500")
        else:
            f["picea_p"] = f["picea_p500"] = np.full(ctx.shape, np.nan, dtype=np.float32)
    # climate (ERA5-Land nearest 0.1 deg cell)
    if ctx.climate is not None:
        z1, z2 = ctx.clim("cwb_z", t - 1, "cwb_z_t1"), ctx.clim("cwb_z", t - 2, "cwb_z_t12")
        f["cwb_z_t1"] = z1
        f["cwb_z_t12"] = z1 + z2
        ctx.used["cwb_z_t12"].add(t - 1)
        for v in ("tsum_F1", "tsum_F2", "swarming_doy", "n_filial", "n_filial_inca"):
            f[f"{v}_t1"] = ctx.clim(v, t - 1, f"{v}_t1")
    return f


# --- static layers ---------------------------------------------------------------------------------------------

def chm_aggregate(chm3m: np.ndarray, k: int = 10, tall: float = 5.0) -> dict[str, np.ndarray]:
    """CHM on a 3 m grid aligned with the 30 m grid (k x k sub-cells per cell; NaN = no data) -> mean, p90, share of
    sub-cells > `tall` m."""
    h, w = chm3m.shape[0] // k, chm3m.shape[1] // k
    b = chm3m[:h * k, :w * k].reshape(h, k, w, k).transpose(0, 2, 1, 3).reshape(h, w, k * k).astype(np.float32)
    import warnings

    with np.errstate(invalid="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return {"chm_mean": np.nanmean(b, axis=2), "chm_p90": np.nanpercentile(b, 90, axis=2),
                "chm_gt5": np.nanmean(np.where(np.isnan(b), np.nan, b > tall), axis=2)}


def quadkey(lon: float, lat: float, z: int) -> str:
    """Bing / Web Mercator quadkey (CHMv2 tiles are z10 quadkeys, checked on 1201223023 = Kalsnava)."""
    x = (lon + 180) / 360
    s = math.sin(math.radians(lat))
    y = 0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)
    n = 2 ** z
    tx, ty = min(int(x * n), n - 1), min(int(y * n), n - 1)
    q = ""
    for i in range(z, 0, -1):
        m = 1 << (i - 1)
        q += str((1 if tx & m else 0) + (2 if ty & m else 0))
    return q


# --- labels and description --------------------------------------------------------------------------------------

def labels(share_t: np.ndarray, centre_t: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """label = 620 polygon of year t covers the cell centre; confidence = cover share (0..1)."""
    return centre_t.astype(np.uint8), share_t.astype(np.float32)


def describe(tab: pd.DataFrame, feats: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Positives per year and feature distributions positives vs other cells (median, IQR, mean, standardised
    mean difference); training rows only (in_set)."""
    d = tab[tab["in_set"] == 1]
    py = d.groupby("year").agg(cells=("label", "size"), positives=("label", "sum"))
    py["share_pos"] = py["positives"] / py["cells"]
    rows = []
    for c in feats:
        x = d[[c, "label"]].dropna()
        if x.empty:
            continue
        p, n = x.loc[x.label == 1, c], x.loc[x.label == 0, c]
        sd = math.sqrt((p.var() + n.var()) / 2) if len(p) > 1 and len(n) > 1 else np.nan
        rows.append({"feature": c, "n_pos": len(p), "n_other": len(n),
                     "pos_median": p.median(), "pos_q25": p.quantile(0.25), "pos_q75": p.quantile(0.75),
                     "other_median": n.median(), "other_q25": n.quantile(0.25), "other_q75": n.quantile(0.75),
                     "pos_mean": p.mean(), "other_mean": n.mean(),
                     "smd": (p.mean() - n.mean()) / sd if sd and sd > 0 else np.nan})
    return py.reset_index(), pd.DataFrame(rows)
