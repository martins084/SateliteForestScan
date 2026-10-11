"""Placebo (null-event) calibration of k for the S1 windthrow methods (stage 3c).

1. Null event without a storm (same window lengths / orbit logic): every windthrow candidate
   is a false alarm by definition -> false alarms per 1000 ha as a function of k.
2. Per method the smallest k with <= 1 and <= 5 false alarms / 1000 ha.
3. With these k: injection test on the storm data (same sites and batches, "hit" criterion)
   and the number of real storm candidates compared with the null event.

    python scripts/s1_placebo_calibration.py configs/s1_kalsnava_null_2026-07.yaml \
        configs/s1_kalsnava_2026-08_v2b.yaml
"""

from __future__ import annotations

import math
import sys

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from s1windthrow.config import load_config  # noqa: E402
from s1windthrow.injection import evaluate, run_injection  # noqa: E402
from s1windthrow.pipeline import orbit_composites, prepare  # noqa: E402

LIMITS = (1.0, 5.0)
METHODS = [  # (name, version, smoothing window, k grid)
    ("v2b 3×3", "v2", 3, np.round(np.arange(2.0, 4.0001, 0.25), 2)),
    ("v2b 5×5", "v2", 5, np.round(np.arange(2.0, 4.0001, 0.25), 2)),
    ("v2b 7×7", "v2", 7, np.round(np.arange(2.0, 4.0001, 0.25), 2)),
    ("v3", "v3", 1, np.round(np.arange(3.0, 6.0001, 0.25), 2)),
]


def method_cfg(cfg, version: str, window: int, ks=None):
    det = cfg.detection.model_copy(update={"version": version, "smoothing_window": window})
    upd = {"detection": det}
    if ks is not None:
        upd["injection"] = cfg.injection.model_copy(update={"windows": [window], "k": list(ks),
                                                            "criterion": "hit"})
    return cfg.model_copy(update=upd)


def fa_curve(cfg, pr, label: str) -> pd.DataFrame:
    comps, _ = orbit_composites(cfg, pr.table, "used_A", pr.data, pr.masks.stable)
    min_px = math.ceil(cfg.detection.min_area_ha / pr.grid.pixel_ha - 1e-9)
    rows = []
    for name, version, w, ks in METHODS:
        mc = method_cfg(cfg, version, w)
        _, fa = evaluate(comps, pr.masks, pr.masks.dlt, mc, w, list(ks), [], 0.0, min_px,
                         pr.grid.pixel_ha)
        rows += [{"event": label, "method": name, **r} for r in fa]
    return pd.DataFrame(rows)


def main(null_path: str, storm_path: str) -> None:
    null_cfg, storm_cfg = load_config(null_path), load_config(storm_path)
    out = null_cfg.run_dir / "calibration"
    out.mkdir(parents=True, exist_ok=True)
    say = print
    pr_null = prepare(null_cfg, progress=say)
    acq = pr_null.table.drop(columns="key")
    acq.to_csv(out / "null_acquisitions.csv", index=False)
    null = fa_curve(null_cfg, pr_null, "null")
    pr_storm = prepare(storm_cfg, progress=say)
    storm = fa_curve(storm_cfg, pr_storm, "storm")
    curves = pd.concat([null, storm], ignore_index=True)
    curves.to_csv(out / "fa_curves.csv", index=False)

    # smallest k per method and limit (null event)
    sel = []
    for name, version, w, ks in METHODS:
        c = null[null.method == name].sort_values("k")
        for lim in LIMITS:
            ok = c[c.fa_per_1000ha <= lim]
            sel.append({"method": name, "version": version, "window": w, "fa_limit": lim,
                        "k": float(ok.k.min()) if len(ok) else np.nan,
                        "null_n": int(ok.iloc[0].n_false) if len(ok) else np.nan,
                        "null_fa_per_1000ha": float(ok.iloc[0].fa_per_1000ha) if len(ok) else np.nan})
    sel = pd.DataFrame(sel)
    st = storm.rename(columns={"n_false": "storm_n", "fa_per_1000ha": "storm_per_1000ha"})
    sel = sel.merge(st[["method", "k", "storm_n", "storm_per_1000ha"]], on=["method", "k"], how="left")
    sel.to_csv(out / "selected_k.csv", index=False)

    # injection with the selected k (storm data, same sites / batches, "hit" criterion)
    sus = pd.concat([gpd.read_file(r.path, layer=r.layer).to_crs(storm_cfg.grid.crs)
                     for r in storm_cfg.checks.s2_exclude], ignore_index=True)
    comps_storm, _ = orbit_composites(storm_cfg, pr_storm.table, "used_A", pr_storm.data,
                                      pr_storm.masks.stable)
    inj_rows = []
    for name, version, w, _ in METHODS:
        ks = sorted(set(sel[(sel.method == name)].k.dropna()))
        if not ks:
            continue
        mc = method_cfg(storm_cfg, version, w, ks)
        det, _, _ = run_injection(mc, comps_storm, pr_storm.masks, pr_storm.grid, sus, progress=say)
        r = (det.groupby(["k", "size_ha", "strength"]).hit.mean().rename("hit_rate").reset_index())
        r["method"] = name
        inj_rows.append(r)
    inj = pd.concat(inj_rows, ignore_index=True)
    inj.to_csv(out / "injection_hit_selected_k.csv", index=False)

    # plot: false alarms vs k, null (solid) and storm (dashed)
    fig, axes = plt.subplots(1, len(METHODS), figsize=(4 * len(METHODS), 3.6), dpi=150, sharey=True)
    for ax, (name, _, _, _) in zip(axes, METHODS):
        for ev, ls, col in (("null", "-", "#4c72b0"), ("storm", "--", "#d62728")):
            g = curves[(curves.method == name) & (curves.event == ev)].sort_values("k")
            ax.plot(g.k, g.fa_per_1000ha, ls, marker="o", ms=3, color=col,
                    label="null (bez vētras)" if ev == "null" else "vētra 22.–23.08.")
        for lim in LIMITS:
            ax.axhline(lim, color="grey", lw=0.7, ls=":")
        ax.set_yscale("symlog", linthresh=1)
        ax.set_title(name, fontsize=10)
        ax.set_xlabel("k")
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("windthrow kandidāti / 1000 ha")
    axes[0].legend(fontsize=8)
    fig.suptitle("Placebo kalibrēšana: kandidāti uz 1000 ha pret k (punktētas: 1 un 5)", fontsize=11)
    fig.tight_layout()
    fig.savefig(out / "fa_curves.png")
    plt.close(fig)

    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 200)
    print(acq[["rel_orbit", "window", "date", "platform", "used_A"]].to_string(index=False))
    print(curves.pivot_table(index=["method", "k"], columns="event", values="n_false").to_string())
    print(sel.to_string(index=False))
    print(inj.pivot_table(index=["method", "k", "strength"], columns="size_ha", values="hit_rate").round(2).to_string())


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
