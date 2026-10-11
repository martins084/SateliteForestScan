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
from .method import (deltas_from_composites, disc_kernel, disc_offsets, footprint_union,  # noqa: F401
                     object_classes, window_mean, window_z, z_by_class)


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


def object_setup(cfg, pixel_ha: float) -> dict[float, np.ndarray]:
    return {s: disc_kernel(int(round(s / pixel_ha))) for s in cfg.detection.object_scales_ha}


def object_window_z(z: np.ndarray, analysis: np.ndarray, stable: np.ndarray,
                    kernels: dict[float, np.ndarray], min_valid: float,
                    exclude: np.ndarray | None = None) -> tuple[dict, dict]:
    """Window z per scale; statistics from stable-forest window centres whose window does not
    touch `exclude` (injected pixels)."""
    zw, stats = {}, {}
    for s, ker in kernels.items():
        mean = window_mean(z, analysis, ker, min_valid)
        centers = stable & analysis
        if exclude is not None and exclude.any():
            centers &= ~footprint_union(exclude, ker)
        zw[s], stats[s] = window_z(mean, centers)
    return zw, stats


def evaluate(comps, masks, dlt, cfg, window: int, ks: list[float], sites: list[Site],
             strength: float, min_px: int, pixel_ha: float) -> tuple[list[dict], list[dict]]:
    """Detection per site and false alarms for one window and all k.
    v3 (cfg.detection.version == "v3"): `window` must be 1; candidates from object windows."""
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
    excl = inj
    r = (window - 1) // 2
    if cfg.injection.exclude_spill_ring and r and sites:
        excl = ndimage.binary_dilation(inj, iterations=r)   # injected + smoothing spill-over
    z, _ = z_by_class(comb["index"], masks.stable & ~excl, analysis, dlt,
                      cfg.forest_mask.hrl_dlt_classes if cfg.detection.z_by_class else None)
    analysis &= np.isfinite(z)
    area_ha = float((analysis & ~inj).sum() * pixel_ha)
    v3 = cfg.detection.version == "v3"
    if v3:
        kernels = object_setup(cfg, pixel_ha)
        zw, _ = object_window_z(z, analysis, masks.stable, kernels, cfg.detection.object_min_valid,
                                inj if sites else None)
    det_rows, fa_rows = [], []
    for k in ks:
        raw = object_classes(zw, kernels, analysis, k)[0] if v3 else classify(z, analysis, k)
        cls, labels = apply_mmu(raw, min_px)
        wt = cls == CLASS_WINDTHROW
        for i, s in enumerate(sites):
            det_rows.append({"window": window, "k": k, "site": i, "class": s.cls,
                             "detected_share": float(wt[s.rows, s.cols].mean()),
                             "center_in": bool(wt[s.rows[0], s.cols[0]])})
        lab_wt = np.unique(labels[wt])
        hit = np.unique(labels[wt & inj])
        n_fa = int(len(set(lab_wt.tolist()) - set(hit.tolist())))
        fa_rows.append({"window": window, "k": k, "n_false": n_fa, "area_ha": round(area_ha, 1),
                        "fa_per_1000ha": n_fa / area_ha * 1000 if area_ha else np.nan})
    return det_rows, fa_rows


def make_batches(sites: list[Site], size_ha: float, stable_ha: dict[int, float],
                 max_share_pct: float | None) -> list[list[int]]:
    """Split site indices into batches with < max_share_pct of each class's stable forest."""
    if not max_share_pct:
        return [list(range(len(sites)))]
    per_class = {c: [i for i, s in enumerate(sites) if s.cls == c] for c in stable_ha}
    cap = {c: max(1, int(math.ceil(max_share_pct / 100 * stable_ha[c] / size_ha)) - 1)
           for c in stable_ha}   # strictly below the share
    n_b = max((math.ceil(len(v) / cap[c]) for c, v in per_class.items() if v), default=0)
    return [sum((v[b * cap[c]:(b + 1) * cap[c]] for c, v in per_class.items()), []) for b in range(n_b)]


def run_injection(cfg, comps, masks, grid, suspects, progress=print) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    inj = cfg.injection
    min_px = math.ceil(cfg.detection.min_area_ha / grid.pixel_ha - 1e-9)
    gap_px = int(round(inj.min_gap_m / cfg.grid.resolution))
    elig = eligible_masks(masks, grid, cfg, suspects)
    rng = np.random.default_rng(inj.seed)
    det_all, fa_all, site_info = [], [], []
    stable_ha = {int(c): float((masks.stable & (masks.dlt == c)).sum() * grid.pixel_ha)
                 for c in cfg.forest_mask.hrl_dlt_classes}
    # baseline without injection: false alarms of the real data
    for w in inj.windows:
        _, fa = evaluate(comps, masks, masks.dlt, cfg, w, inj.k, [], 0.0, min_px, grid.pixel_ha)
        fa_all += [{**r, "size_ha": 0.0, "strength": 0.0} for r in fa]
    for size in inj.sizes_ha:
        n_px = int(round(size / grid.pixel_ha))
        sites = sample_sites(elig, masks.dlt, n_px, inj.n_per_combo, inj.class_purity, gap_px, rng)
        for c in elig:
            n = sum(s.cls == c for s in sites)
            site_info.append({"size_ha": size, "class": c, "n_sites": n, "requested": inj.n_per_combo,
                              "injected_share_pct_total": round(100 * n * size / stable_ha[c], 2)})
        batches = make_batches(sites, size, stable_ha, inj.max_batch_share_pct)
        progress(f"injection {size} ha: {len(sites)} sites, {len(batches)} batch(es)")
        for strength in inj.strengths:
            for w in inj.windows:
                for b, batch in enumerate(batches):
                    det, fa = evaluate(comps, masks, masks.dlt, cfg, w, inj.k,
                                       [sites[i] for i in batch], strength, min_px, grid.pixel_ha)
                    for row in det:   # site index back to the position in `sites`
                        row["site"] = batch[row["site"]]
                    det_all += [{**r, "size_ha": size, "strength": strength, "batch": b} for r in det]
                    fa_all += [{**r, "size_ha": size, "strength": strength, "batch": b} for r in fa]
    det = pd.DataFrame(det_all)
    det["detected"] = det["detected_share"] >= inj.detected_fraction
    # "hit": the candidate covers >= hit_fraction of the site OR the site centre is inside it
    det["hit"] = (det["detected_share"] >= inj.hit_fraction) | det["center_in"]
    return det, pd.DataFrame(fa_all), pd.DataFrame(site_info)


def summarize(det: pd.DataFrame, fa: pd.DataFrame, cfg) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    inj = cfg.injection
    det = det.copy()
    det["detected"] = det["hit"] if inj.criterion == "hit" else det["detected_share"] >= inj.detected_fraction
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
    rec = {}
    for name, lim in (("strict", inj.max_false_alarms_per_1000ha),
                      ("operational", inj.max_false_alarms_operational_per_1000ha)):
        ok = table[table.fa_per_1000ha <= lim]
        if len(ok):
            best = ok.sort_values(["rate", "fa_per_1000ha", "k"], ascending=[False, True, False]).iloc[0]
            rec[name] = {"fa_limit": lim, "window": int(best.window), "k": float(best.k),
                         "rate_1ha_1x": float(best.rate), "fa_per_1000ha": float(best.fa_per_1000ha),
                         "ties": ok[ok.rate == best.rate][["window", "k", "fa_per_1000ha"]].to_dict("records")}
        else:
            rec[name] = {"fa_limit": lim}
    return rate, table.sort_values(["window", "k"]), rec


def candidate_polygons(cfg, comps, masks, grid, k: float):
    """Windthrow candidate polygons (after MMU) for one method configuration and k, with the
    mean index / dVH / dVV; same processing as `evaluate` without injection."""
    from .detect import CLASS_WINDTHROW as WT
    from .detect import polygonize
    w = cfg.detection.smoothing_window
    deltas = deltas_from_composites(comps, masks.analysis, w)
    comb = combine_orbits(deltas)
    analysis = masks.analysis & np.isfinite(comb["index"])
    z, _ = z_by_class(comb["index"], masks.stable, analysis, masks.dlt,
                      cfg.forest_mask.hrl_dlt_classes if cfg.detection.z_by_class else None)
    analysis &= np.isfinite(z)
    min_px = math.ceil(cfg.detection.min_area_ha / grid.pixel_ha - 1e-9)
    if cfg.detection.version == "v3":
        kernels = object_setup(cfg, grid.pixel_ha)
        zw, _ = object_window_z(z, analysis, masks.stable, kernels, cfg.detection.object_min_valid)
        raw = object_classes(zw, kernels, analysis, k)[0]
    else:
        raw = classify(z, analysis, k)
    cls, labels = apply_mmu(raw, min_px)
    labels = np.where(cls == WT, labels, 0)
    return polygonize(labels, cls, grid.geobox.affine, cfg.grid.crs,
                      {"mean_z": z, "index": comb["index"], "mean_dVH": comb["d_vh"],
                       "mean_dVV": comb["d_vv"]}, grid.pixel_ha)
