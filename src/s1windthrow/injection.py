"""Injection test: synthetic windthrow in the real post composites of the stable forest.

Each site is a compact pixel disc (pixels nearest to a random centre) of 0.5 / 1 / 2 / 5 ha.
Inside a site, the post composite of every orbit is multiplied by 10^(s * base_dB / 10) per
polarization (s = strength). Multiplying the post *composite* equals multiplying every post
acquisition, because the composite is a linear mean and the per-acquisition normalization
medians are computed before the injection (i.e. injected pixels do not influence them).
z statistics are computed from the stable forest WITHOUT the injected pixels.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
from rasterio.features import rasterize
from scipy import ndimage

from .detect import CLASS_WINDTHROW, apply_mmu, classify, combine_orbits
from .method import deltas_from_composites, z_by_class


def disc_offsets(n_px: int) -> np.ndarray:
    """Offsets (dy, dx) of the n pixels closest to the centre (compact shape)."""
    r = int(math.ceil(math.sqrt(n_px / math.pi))) + 2
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    d = np.hypot(yy, xx) + 1e-6 * (yy * (2 * r + 1) + xx)   # deterministic tie-break
    order = np.argsort(d.ravel())[:n_px]
    return np.stack([yy.ravel()[order], xx.ravel()[order]], axis=1)


@dataclass
class Site:
    cls: int
    rows: np.ndarray
    cols: np.ndarray


def sample_sites(eligible: dict[int, np.ndarray], dlt: np.ndarray, n_px: int, n_per_class: int,
                 purity: float, gap_px: int, rng: np.random.Generator,
                 max_tries: int = 20000) -> list[Site]:
    """Non-overlapping sites (>= gap_px apart) fully inside `eligible[cls]`'s support
    (the union of all eligible masks) with >= purity of the target class."""
    shape = dlt.shape
    allowed = np.zeros(shape, bool)
    for m in eligible.values():
        allowed |= m
    off = disc_offsets(n_px)
    occupied = np.zeros(shape, bool)
    sites = []
    for cls, elig in eligible.items():
        cand = np.argwhere(elig)
        got, tries = 0, 0
        while got < n_per_class and tries < max_tries:
            tries += 1
            cy, cx = cand[rng.integers(len(cand))]
            r, c = off[:, 0] + cy, off[:, 1] + cx
            if r.min() < 0 or c.min() < 0 or r.max() >= shape[0] or c.max() >= shape[1]:
                continue
            if not allowed[r, c].all() or occupied[r, c].any():
                continue
            if (dlt[r, c] == cls).mean() < purity:
                continue
            sites.append(Site(cls, r, c))
            got += 1
            blk = np.zeros(shape, bool)
            blk[r, c] = True
            occupied |= ndimage.binary_dilation(blk, iterations=gap_px) if gap_px else blk
    return sites


def eligible_masks(masks, grid, cfg, suspects) -> dict[int, np.ndarray]:
    """Stable forest of each HRL class, >= min_dist_suspects_m from S2 suspects."""
    inj = cfg.injection
    near = np.zeros(masks.stable.shape, bool)
    if len(suspects):
        near = rasterize([(g, 1) for g in suspects.geometry.buffer(inj.min_dist_suspects_m)],
                         out_shape=near.shape, transform=grid.geobox.affine, fill=0,
                         dtype="uint8").astype(bool)
    base = masks.stable & ~near
    return {int(c): base & (masks.dlt == c) for c in cfg.forest_mask.hrl_dlt_classes}


def evaluate(comps, masks, dlt, cfg, window: int, ks: list[float], sites: list[Site],
             strength: float, min_px: int, pixel_ha: float) -> tuple[list[dict], list[dict]]:
    """Detection per site and false alarms for one window and all k."""
    shape = masks.analysis.shape
    inj = np.zeros(shape, bool)
    factor = {p: np.ones(shape, "float32") for p in ("vv", "vh")}
    for s in sites:
        inj[s.rows, s.cols] = True
        for p in ("vv", "vh"):
            factor[p][s.rows, s.cols] = 10 ** (strength * cfg.injection.base_db[p] / 10)
    deltas = deltas_from_composites(comps, masks.analysis, window, factor if sites else None)
    comb = combine_orbits(deltas)
    analysis = masks.analysis & np.isfinite(comb["index"])
    z, _ = z_by_class(comb["index"], masks.stable & ~inj, analysis, dlt,
                      cfg.forest_mask.hrl_dlt_classes if cfg.detection.z_by_class else None)
    analysis &= np.isfinite(z)
    area_ha = float((analysis & ~inj).sum() * pixel_ha)
    det_rows, fa_rows = [], []
    for k in ks:
        cls, labels = apply_mmu(classify(z, analysis, k), min_px)
        wt = cls == CLASS_WINDTHROW
        for i, s in enumerate(sites):
            det_rows.append({"window": window, "k": k, "site": i, "class": s.cls,
                             "detected_share": float(wt[s.rows, s.cols].mean())})
        lab_wt = np.unique(labels[wt])
        hit = np.unique(labels[wt & inj])
        n_fa = int(len(set(lab_wt.tolist()) - set(hit.tolist())))
        fa_rows.append({"window": window, "k": k, "n_false": n_fa, "area_ha": round(area_ha, 1),
                        "fa_per_1000ha": n_fa / area_ha * 1000 if area_ha else np.nan})
    return det_rows, fa_rows


def run_injection(cfg, comps, masks, grid, suspects, progress=print) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    inj = cfg.injection
    min_px = math.ceil(cfg.detection.min_area_ha / grid.pixel_ha - 1e-9)
    gap_px = int(round(inj.min_gap_m / cfg.grid.resolution))
    elig = eligible_masks(masks, grid, cfg, suspects)
    rng = np.random.default_rng(inj.seed)
    det_all, fa_all, site_info = [], [], []
    # baseline without injection: false alarms of the real data
    for w in inj.windows:
        _, fa = evaluate(comps, masks, masks.dlt, cfg, w, inj.k, [], 0.0, min_px, grid.pixel_ha)
        fa_all += [{**r, "size_ha": 0.0, "strength": 0.0} for r in fa]
    for size in inj.sizes_ha:
        n_px = int(round(size / grid.pixel_ha))
        sites = sample_sites(elig, masks.dlt, n_px, inj.n_per_combo, inj.class_purity, gap_px, rng)
        for c in elig:
            site_info.append({"size_ha": size, "class": c, "n_sites": sum(s.cls == c for s in sites),
                              "requested": inj.n_per_combo})
        progress(f"injection {size} ha: {len(sites)} sites")
        for strength in inj.strengths:
            for w in inj.windows:
                det, fa = evaluate(comps, masks, masks.dlt, cfg, w, inj.k, sites, strength,
                                   min_px, grid.pixel_ha)
                det_all += [{**r, "size_ha": size, "strength": strength} for r in det]
                fa_all += [{**r, "size_ha": size, "strength": strength} for r in fa]
    det = pd.DataFrame(det_all)
    det["detected"] = det["detected_share"] >= inj.detected_fraction
    return det, pd.DataFrame(fa_all), pd.DataFrame(site_info)


def summarize(det: pd.DataFrame, fa: pd.DataFrame, cfg) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    inj = cfg.injection
    rate = (det.groupby(["window", "k", "size_ha", "strength", "class"])
            .agg(n=("detected", "size"), n_detected=("detected", "sum")).reset_index())
    rate["rate"] = rate.n_detected / rate.n
    both = (det.groupby(["window", "k", "size_ha", "strength"])
            .agg(n=("detected", "size"), n_detected=("detected", "sum")).reset_index())
    both["rate"] = both.n_detected / both.n
    base_fa = fa[fa.strength == 0.0][["window", "k", "n_false", "area_ha", "fa_per_1000ha"]]
    inj_fa = (fa[fa.strength > 0].groupby(["window", "k"]).fa_per_1000ha.mean()
              .rename("fa_per_1000ha_injection_runs").reset_index())
    table = (both[(both.size_ha == inj.recommend_size_ha) & (both.strength == inj.recommend_strength)]
             .merge(base_fa, on=["window", "k"]).merge(inj_fa, on=["window", "k"]))
    ok = table[table.fa_per_1000ha <= inj.max_false_alarms_per_1000ha]
    rec = {}
    if len(ok):
        best = ok.sort_values(["rate", "fa_per_1000ha", "k"], ascending=[False, True, False]).iloc[0]
        rec = {"window": int(best.window), "k": float(best.k), "rate_1ha_1x": float(best.rate),
               "fa_per_1000ha": float(best.fa_per_1000ha),
               "ties": ok[ok.rate == best.rate][["window", "k", "fa_per_1000ha"]].to_dict("records")}
    return rate, table.sort_values(["window", "k"]), rec
