"""Edge diagnostic for the S1 early-signal test (read-only; the method is not changed).

Is the +0.8 dB baseline offset of the targets (S2 stress polygons) against their controls a
forest-edge effect? For every target, control and pseudo-target:
  * distance from the unit centre to the nearest non-forest pixel (analysed forest mask:
    HRL 1+2 minus roads minus S2 cuts; everything else is "non-forest");
  * share of the unit's pixels within 20 m of the edge;
  * azimuth from the centre to the nearest non-forest pixel (where the open side is).
Targets vs pseudo-targets: Mann-Whitney. Baseline offset (target - controls, 24-12 months before
t_first) against the edge distance, and per orbit direction (ascending / descending).

ASSUMPTION [N]: Sentinel-1 is right-looking; ascending passes look roughly east, descending
roughly west, so a forest wall with open ground on its WEST side faces an ascending sensor.

    python scripts/s1_edge_diagnostics.py configs/s1_earlysignal_kalsnava.yaml
"""

from __future__ import annotations

import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy import ndimage  # noqa: E402
from scipy.stats import mannwhitneyu, spearmanr  # noqa: E402

from s1windthrow.earlysignal import baseline_level, build_units, load_early_config  # noqa: E402
from s1windthrow.pipeline import build_grid, build_masks  # noqa: E402

ASC, DESC = {58, 160}, {7, 80, 153}


def main(path: str) -> None:
    cfg = load_early_config(path)
    rd = cfg.run_dir
    out = rd / "edge_diagnostics"
    out.mkdir(parents=True, exist_ok=True)
    grid = build_grid(cfg)
    masks = build_masks(cfg, grid)
    units, _ = build_units(cfg, grid, masks)

    # the units must be the same as in the run (same seed)
    saved = pd.read_csv(rd / "tables" / "units.csv")
    now = pd.DataFrame([{"uid": u.uid, "n_px": len(u.rows)} for u in units])
    same = saved[["uid", "n_px"]].merge(now, on="uid", suffixes=("_run", "_now"))
    assert len(same) == len(saved) == len(now) and (same.n_px_run == same.n_px_now).all(), "units differ"

    res = cfg.grid.resolution
    forest = masks.analysis
    dist, (iy, ix) = ndimage.distance_transform_edt(forest, return_indices=True)
    dist_m = dist * res
    rows = []
    for u in units:
        cy, cx = int(round(u.rows.mean())), int(round(u.cols.mean()))
        ny, nx = iy[cy, cx], ix[cy, cx]
        az = (np.degrees(np.arctan2(nx - cx, -(ny - cy))) + 360) % 360   # 0 = north, 90 = east
        d_px = dist_m[u.rows, u.cols]
        rows.append({"uid": u.uid, "kind": u.kind, "parent": u.parent, "n_px": len(u.rows),
                     "centre_dist_m": float(dist_m[cy, cx]), "edge_share_20m": float((d_px <= 20).mean()),
                     "edge_azimuth_deg": float(az),
                     "edge_side": "W" if 180 <= az < 360 else "E"})
    geo = pd.DataFrame(rows)

    # baselines: pooled (from the run) and per orbit direction (recomputed from the differences)
    sig = pd.read_csv(rd / "tables" / "signals.csv")
    tgt = pd.read_csv(rd / "tables" / "targets.csv")
    diffs = pd.read_csv(rd / "tables" / "differences.csv.gz", parse_dates=["time"])
    tfirst = {u.uid: pd.Timestamp(u.attrs["t_first"]) for u in units if u.kind in ("target", "pseudo")}
    brow = []
    for (uid, var), g in diffs[diffs["var"].isin(["vv", "k0"])].groupby(["uid", "var"]):
        for name, orbs in (("asc", ASC), ("desc", DESC)):
            go = g[g.rel_orbit.isin(orbs)]
            b, n = baseline_level(pd.DatetimeIndex(go.time), go["diff"].to_numpy(float), tfirst[uid])
            brow.append({"uid": uid, "var": var, "direction": name, "baseline_db": b, "n": n})
    bdir = pd.DataFrame(brow).pivot_table(index=["uid", "var"], columns="direction", values="baseline_db")
    bdir.columns = [f"baseline_{c}" for c in bdir.columns]
    bdir = bdir.reset_index()

    # unit-level table (targets and pseudo-targets) with the mean geometry of their controls
    ctrl = geo[geo.parent.notna()].groupby("parent")[["centre_dist_m", "edge_share_20m"]].mean()
    ctrl.columns = ["ctrl_centre_dist_m", "ctrl_edge_share_20m"]
    main = set(tgt[tgt.main_group].uid)
    units_t = geo[geo.kind.isin(["target", "pseudo"])].merge(ctrl, left_on="uid", right_index=True, how="left")
    units_t["group"] = np.where(units_t.kind == "pseudo", "pseudo",
                                np.where(units_t.uid.isin(main), "target_main", "target_other"))
    piv = sig[sig["var"].isin(["vv", "k0"])].pivot_table(index="uid", columns="var", values="baseline_db")
    piv.columns = [f"baseline_{c}" for c in piv.columns]
    units_t = units_t.merge(piv, left_on="uid", right_index=True, how="left")
    units_t.to_csv(out / "unit_edge_geometry.csv", index=False)
    geo.to_csv(out / "all_units_edge_geometry.csv", index=False)
    bdir.to_csv(out / "baseline_by_direction.csv", index=False)

    # tests
    T = units_t[units_t.group == "target_main"]
    P = units_t[units_t.group == "pseudo"]
    C = geo[geo.kind == "control"]
    tests = []
    for col in ("centre_dist_m", "edge_share_20m"):
        for name, other in (("pseudo", P[col]), ("controls", C[col])):
            st = mannwhitneyu(T[col], other, alternative="two-sided")
            tests.append({"metric": col, "targets_median": T[col].median(), "vs": name,
                          "other_median": other.median(), "U": st.statistic, "p": st.pvalue,
                          "n_targets": len(T), "n_other": len(other)})
    for var in ("vv", "k0"):
        for grp, d in (("targets (13)", T), ("pseudo (50)", P)):
            r = spearmanr(d.centre_dist_m, d[f"baseline_{var}"], nan_policy="omit")
            tests.append({"metric": f"spearman baseline_{var} ~ centre_dist_m", "vs": grp,
                          "targets_median": r.statistic, "p": r.pvalue, "n_targets": len(d)})
            dd = d.assign(rel_edge=d.edge_share_20m - d.ctrl_edge_share_20m)
            r = spearmanr(dd.rel_edge, dd[f"baseline_{var}"], nan_policy="omit")
            tests.append({"metric": f"spearman baseline_{var} ~ (edge share - controls' edge share)",
                          "vs": grp, "targets_median": r.statistic, "p": r.pvalue, "n_targets": len(d)})
    tests = pd.DataFrame(tests)
    tests.to_csv(out / "tests.csv", index=False)

    # direction: baseline asc vs desc, by edge side
    bd = bdir.merge(units_t[["uid", "group", "edge_side", "edge_azimuth_deg", "centre_dist_m"]], on="uid")
    bd["asc_minus_desc"] = bd.baseline_asc - bd.baseline_desc
    dir_tab = (bd[bd.group.isin(["target_main", "pseudo"])]
               .groupby(["var", "group", "edge_side"])
               .agg(n=("uid", "size"), baseline_asc=("baseline_asc", "median"),
                    baseline_desc=("baseline_desc", "median"),
                    asc_minus_desc=("asc_minus_desc", "median")).reset_index())
    dir_tab.to_csv(out / "direction_by_edge_side.csv", index=False)

    # figure
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.2), dpi=150)
    for ax, var in zip(axes[:2], ("vv", "k0")):
        ax.scatter(P.centre_dist_m, P[f"baseline_{var}"], s=14, color="#999999", label="pseido-mērķi (50)")
        ax.scatter(T.centre_dist_m, T[f"baseline_{var}"], s=26, color="#d62728", label="mērķi (13)")
        o = units_t[units_t.group == "target_other"]
        ax.scatter(o.centre_dist_m, o[f"baseline_{var}"], s=26, facecolors="none", edgecolors="#d62728",
                   label="#57, #60")
        ax.axhline(0, color="grey", lw=0.6)
        ax.set_xlabel("centra attālums līdz meža malai, m")
        ax.set_ylabel(f"bāzes nobīde pret kontrolēm, {var.upper()} dB")
        ax.set_title(f"{var.upper()}: bāzes nobīde pret attālumu līdz malai", fontsize=10)
        ax.grid(alpha=0.3)
    axes[0].legend(fontsize=8)
    ax = axes[2]
    for grp, col, mk in (("pseudo", "#999999", "o"), ("target_main", "#d62728", "s")):
        d = bd[(bd["var"] == "k0") & (bd.group == grp)]
        ax.scatter(d.edge_azimuth_deg, d.asc_minus_desc, color=col, marker=mk, s=18,
                   label="pseido" if grp == "pseudo" else "mērķi (13)")
    ax.axhline(0, color="grey", lw=0.6)
    ax.axvline(180, color="grey", lw=0.6, ls=":")
    ax.set_xlabel("virziens uz tuvāko meža malu, ° (90 = A, 270 = R)")
    ax.set_ylabel("K0 bāze: ascending − descending, dB")
    ax.set_title("Malas virziens pret orbītu virzienu (K0)", fontsize=10)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out / "edge_diagnostics.png")
    plt.close(fig)

    pd.set_option("display.width", 250)
    print(units_t[units_t.kind == "target"][["uid", "n_px", "centre_dist_m", "edge_share_20m",
                                            "ctrl_centre_dist_m", "ctrl_edge_share_20m", "edge_side",
                                            "baseline_vv", "baseline_k0"]].round(2).to_string(index=False))
    print(units_t.groupby("group")[["centre_dist_m", "edge_share_20m", "ctrl_centre_dist_m",
                                    "ctrl_edge_share_20m", "baseline_vv", "baseline_k0"]].median().round(2).to_string())
    print(tests.round(4).to_string(index=False))
    print(dir_tab.round(2).to_string(index=False))


if __name__ == "__main__":
    main(sys.argv[1])
