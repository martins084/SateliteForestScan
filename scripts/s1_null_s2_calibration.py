"""Null-event false alarms with an S2 check, joint k selection over two null periods (stage 3d).

For each null period and method, every windthrow candidate at every k of the grid gets the
same S2 index check as the storm candidates (median in the polygon, post minus pre around the
null split, minus the same change in the stable forest). Classes:

  * "nav S2 datu"     - no S2 date with >= 50 % valid pixels in the pre or the post window;
  * "reāla izmaiņa"   - d_rel of CRSWIR, NDVI or NDMI outside the 0.5-99.5 % range of d_rel
                        over random stable-forest discs (same windows, same S2 run) - an
                        empirical "clear change" rule (chosen here; see the summary);
  * "nav izmaiņas"    - otherwise.

False alarms are recomputed from "nav izmaiņas" + "nav S2 datu" only. k is chosen as the
smallest k with <= 1 and <= 5 false alarms / 1000 ha in BOTH null periods. With the chosen k:
injection test ("hit") on the storm data and the field targets S1-01 / S1-02.

    python scripts/s1_null_s2_calibration.py configs/s1_kalsnava_null_2026-07.yaml \
        configs/s1_kalsnava_null_2025-07.yaml configs/s1_kalsnava_2026-08_v2b.yaml
"""

from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from s1windthrow import checks  # noqa: E402
from s1windthrow.config import load_config  # noqa: E402
from s1windthrow.injection import (candidate_polygons, eligible_masks, run_injection,  # noqa: E402
                                   sample_sites)
from s1windthrow.pipeline import orbit_composites, prepare  # noqa: E402

LIMITS = (1.0, 5.0)
METHODS = [
    ("v2b 3×3", "v2", 3, np.round(np.arange(2.0, 4.0001, 0.25), 2)),
    ("v2b 5×5", "v2", 5, np.round(np.arange(2.0, 4.0001, 0.25), 2)),
    ("v2b 7×7", "v2", 7, np.round(np.arange(2.0, 4.0001, 0.25), 2)),
    ("v3", "v3", 1, np.round(np.arange(3.0, 6.0001, 0.25), 2)),
]
INDICES = ["crswir", "ndvi", "ndmi"]
OUT = Path("output/s1_null_calibration")
FIELD = Path("output/s1_kalsnava_2026-08_v2b_op/field_targets_s1.gpkg")


def method_cfg(cfg, version, window, ks=None):
    det = cfg.detection.model_copy(update={"version": version, "smoothing_window": window})
    upd = {"detection": det}
    if ks is not None:
        upd["injection"] = cfg.injection.model_copy(update={"windows": [window], "k": list(ks),
                                                            "criterion": "hit"})
    return cfg.model_copy(update=upd)


def windows(cfg):
    split = cfg.checks.s2_event_split or cfg.event.date
    return (cfg.event.pre_window[0], split - timedelta(days=1)), (split, cfg.event.post_window[1])


def s2_reference(cfg, pr, sus, n_per_class=100) -> dict:
    """d_rel distribution over random stable-forest discs (60 px = 0.6 ha)."""
    elig = eligible_masks(pr.masks, pr.grid, cfg, sus)
    sites = sample_sites(elig, pr.masks.dlt, 60, n_per_class, 0.9, 5, np.random.default_rng(123))
    from shapely.geometry import box
    from shapely.ops import unary_union
    tr = pr.grid.geobox.affine
    geoms = [unary_union([box(*(tr * (c, r)), *(tr * (c + 1, r + 1))) for r, c in zip(s.rows, s.cols)])
             for s in sites]
    g = gpd.GeoDataFrame({"id": [f"R{i}" for i in range(len(sites))], "class": "reference"},
                         geometry=geoms, crs=cfg.grid.crs)
    pre, post = windows(cfg)
    summ, _ = checks.s2_index_check(g, cfg.checks.s2_run_dir, INDICES, pr.masks.stable, pre, post)
    ref = {}
    for idx in INDICES:
        v = summ[summ["index"] == idx].d_rel.dropna()
        ref[idx] = {"n": int(v.size), "p0.5": float(v.quantile(0.005)) if v.size else np.nan,
                    "p99.5": float(v.quantile(0.995)) if v.size else np.nan}
    return ref


def classify_s2(summ: pd.DataFrame, ref: dict) -> pd.DataFrame:
    rows = []
    for pid, g in summ.groupby("id"):
        g = g.set_index("index")
        n_pre, n_post = int(g.loc["crswir", "n_pre"]), int(g.loc["crswir", "n_post"])
        row = {"id": pid, "s2_n_pre": n_pre, "s2_n_post": n_post}
        for idx in INDICES:
            row[f"d_rel_{idx}"] = g.loc[idx, "d_rel"]
        if n_pre == 0 or n_post == 0 or not np.isfinite(row["d_rel_crswir"]):
            row["s2_class"] = "nav S2 datu"
        else:
            out = [not (ref[i]["p0.5"] <= row[f"d_rel_{i}"] <= ref[i]["p99.5"]) for i in INDICES
                   if np.isfinite(row[f"d_rel_{i}"])]
            row["s2_class"] = "reāla izmaiņa" if any(out) else "nav izmaiņas"
        rows.append(row)
    return pd.DataFrame(rows)


def null_period(path: str, sus) -> tuple[pd.DataFrame, pd.DataFrame, dict, object]:
    cfg = load_config(path)
    label = cfg.run_name.replace("s1_kalsnava_", "")
    pr = prepare(cfg, progress=print)
    comps, _ = orbit_composites(cfg, pr.table, "used_A", pr.data, pr.masks.stable)
    polys = []
    for name, version, w, ks in METHODS:
        mc = method_cfg(cfg, version, w)
        for k in ks:
            p = candidate_polygons(mc, comps, pr.masks, pr.grid, float(k))
            if len(p):
                p["method"], p["k"] = name, float(k)
                p["id"] = [f"{label}|{name}|{k:.2f}|{i}" for i in p["id"]]
                polys.append(p)
    polys = gpd.GeoDataFrame(pd.concat(polys, ignore_index=True), geometry="geometry", crs=cfg.grid.crs)
    pre, post = windows(cfg)
    summ, _ = checks.s2_index_check(polys.assign(**{"class": "windthrow"}), cfg.checks.s2_run_dir,
                                    INDICES, pr.masks.stable, pre, post)
    ref = s2_reference(cfg, pr, sus)
    cls = classify_s2(summ, ref)
    polys = polys.merge(cls, on="id", how="left")
    polys["period"] = label
    area = float((pr.masks.analysis).sum() * pr.grid.pixel_ha)
    rows = []
    for name, _, _, ks in METHODS:
        for k in ks:
            g = polys[(polys.method == name) & (polys.k == float(k))]
            n_all = len(g)
            n_fa = int((g.s2_class != "reāla izmaiņa").sum()) if n_all else 0
            rows.append({"period": label, "method": name, "k": float(k), "n_all": n_all,
                         "n_real_change": n_all - n_fa, "n_no_change": int((g.s2_class == "nav izmaiņas").sum()),
                         "n_no_s2": int((g.s2_class == "nav S2 datu").sum()), "n_fa": n_fa,
                         "fa_raw_per_1000ha": n_all / area * 1000, "fa_per_1000ha": n_fa / area * 1000,
                         "area_ha": round(area, 1)})
    return polys, pd.DataFrame(rows), {"period": label, "reference": ref, "pre": str(pre), "post": str(post),
                                       "n_acq": int(pr.table.used_A.sum())}, cfg


def main(null1: str, null2: str, storm: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    storm_cfg = load_config(storm)
    sus = pd.concat([gpd.read_file(r.path, layer=r.layer).to_crs(storm_cfg.grid.crs)
                     for r in storm_cfg.checks.s2_exclude], ignore_index=True)
    allp, curves, meta = [], [], []
    for path in (null1, null2):
        p, c, m, _ = null_period(path, sus)
        allp.append(p)
        curves.append(c)
        meta.append(m)
    polys = gpd.GeoDataFrame(pd.concat(allp, ignore_index=True), geometry="geometry")
    curves = pd.concat(curves, ignore_index=True)
    polys.to_file(OUT / "null_candidates.gpkg", layer="candidates", driver="GPKG")
    curves.to_csv(OUT / "null_fa_curves.csv", index=False)
    (OUT / "null_meta.json").write_text(json.dumps(meta, indent=1, default=str, ensure_ascii=False),
                                        encoding="utf-8")

    # k selection: per period and jointly (both periods), raw and S2-corrected
    sel = []
    for name, version, w, ks in METHODS:
        for basis, col in (("raw", "fa_raw_per_1000ha"), ("S2-korigēts", "fa_per_1000ha")):
            for lim in LIMITS:
                c = curves[curves.method == name].pivot_table(index="k", columns="period", values=col)
                row = {"method": name, "version": version, "window": w, "basis": basis, "fa_limit": lim}
                for per in c.columns:
                    ok = c[c[per] <= lim]
                    row[f"k_{per}"] = float(ok.index.min()) if len(ok) else np.nan
                both = c[(c <= lim).all(axis=1)]
                row["k_both"] = float(both.index.min()) if len(both) else np.nan
                sel.append(row)
    sel = pd.DataFrame(sel)
    sel.to_csv(OUT / "selected_k.csv", index=False)

    # storm: candidates and injection at the final (S2-corrected, both periods) k
    pr = prepare(storm_cfg, progress=print)
    comps, _ = orbit_composites(storm_cfg, pr.table, "used_A", pr.data, pr.masks.stable)
    field = gpd.read_file(FIELD, layer="targets")
    final = sel[(sel.basis == "S2-korigēts")].dropna(subset=["k_both"])
    inj_rows, storm_rows, hits = [], [], {t: {} for t in field.merka_id}
    checks_k = {("v2b 5×5", 3.25), ("v3", 5.25)} | {(r.method, r.k_both) for r in final.itertuples()}
    spec = {m[0]: m for m in METHODS}
    for name, k in sorted(checks_k):
        _, version, w, _ = spec[name]
        p = candidate_polygons(method_cfg(storm_cfg, version, w), comps, pr.masks, pr.grid, k)
        storm_rows.append({"method": name, "k": k, "storm_n": len(p)})
        for _, t in field.iterrows():
            hits[t.merka_id][f"{name} k={k:g}"] = bool(len(p) and p.intersects(t.geometry).any())
    for name in final.method.unique():
        ks = sorted(set(final[final.method == name].k_both))
        _, version, w, _ = spec[name]
        det, _, _ = run_injection(method_cfg(storm_cfg, version, w, ks), comps, pr.masks, pr.grid, sus,
                                  progress=print)
        r = det.groupby(["k", "size_ha", "strength"]).hit.mean().rename("hit_rate").reset_index()
        r["method"] = name
        inj_rows.append(r)
    inj = pd.concat(inj_rows, ignore_index=True) if inj_rows else pd.DataFrame()
    inj.to_csv(OUT / "injection_hit_final_k.csv", index=False)
    pd.DataFrame(storm_rows).to_csv(OUT / "storm_candidates_at_k.csv", index=False)
    (OUT / "field_target_hits.json").write_text(json.dumps(hits, indent=1, ensure_ascii=False), encoding="utf-8")

    # field targets: attributes for the null-calibrated thresholds
    for tid, d in hits.items():
        for key, val in d.items():
            col = "exceeds_" + key.replace(" ", "_").replace("×", "x").replace("=", "").replace(".", "_")
            field.loc[field.merka_id == tid, col] = val
    field["null_calibration_note"] = ("exceeds_*: vai kandidāts pārklājas ar vētras kandidātu pie null-kalibrēta k "
                                      "(scripts/s1_null_s2_calibration.py)")
    field.to_file(FIELD, layer="targets", driver="GPKG")
    pts = field.copy()
    pts["geometry"] = field.geometry.representative_point()
    pts.to_file(FIELD, layer="points", driver="GPKG")

    # plot: FA curves for both periods, raw (dotted) and S2-corrected (solid)
    fig, axes = plt.subplots(1, len(METHODS), figsize=(4 * len(METHODS), 3.6), dpi=150, sharey=True)
    colors = {meta[0]["period"]: "#4c72b0", meta[1]["period"]: "#dd8452"}
    for ax, (name, _, _, _) in zip(axes, METHODS):
        for per, col in colors.items():
            g = curves[(curves.method == name) & (curves.period == per)].sort_values("k")
            ax.plot(g.k, g.fa_raw_per_1000ha, ":", color=col, marker=".", label=f"{per} (visi)")
            ax.plot(g.k, g.fa_per_1000ha, "-", color=col, marker="o", ms=3, label=f"{per} (bez S2 izmaiņām)")
        for lim in LIMITS:
            ax.axhline(lim, color="grey", lw=0.7, ls="--")
        ax.set_yscale("symlog", linthresh=1)
        ax.set_title(name, fontsize=10)
        ax.set_xlabel("k")
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("viltus trauksmes / 1000 ha")
    axes[0].legend(fontsize=7)
    fig.suptitle("Null periodi: viltus trauksmes pret k (punktēti — visi kandidāti, līnija — bez S2 "
                 "apstiprinātām izmaiņām)", fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT / "null_fa_curves.png")
    plt.close(fig)

    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 300)
    print(json.dumps(meta, indent=1, default=str, ensure_ascii=False))
    print(curves.to_string(index=False))
    print(sel.to_string(index=False))
    print(pd.DataFrame(storm_rows).to_string(index=False))
    print(json.dumps(hits, indent=1, ensure_ascii=False))
    if len(inj):
        print(inj.pivot_table(index=["method", "k", "strength"], columns="size_ha", values="hit_rate").round(2).to_string())


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
