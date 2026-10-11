"""Side-by-side comparison of S1 injection tests (e.g. v2b vs v3) with two detection criteria.

  "hit":     the candidate covers >= 25 % of the site OR the site centre is inside it;
  "area50":  >= 50 % of the site area is inside a windthrow candidate (original criterion).

False alarms come from the real data without injection (strength 0) of each run.

    python scripts/s1_compare_injection.py output/s1_kalsnava_2026-08_v2b output/s1_kalsnava_2026-08_v3
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

STRICT, OPERATIONAL = 1.0, 5.0
HIT_FRACTION, AREA_FRACTION = 0.25, 0.5


def load(run_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    d = pd.read_csv(run_dir / "injection" / "injection_sites_detection.csv")
    fa = pd.read_csv(run_dir / "injection" / "injection_false_alarms.csv")
    name = run_dir.name.split("_")[-1]
    d["hit"] = (d.detected_share >= HIT_FRACTION) | d.center_in.astype(bool)
    d["area50"] = d.detected_share >= AREA_FRACTION
    d["method"], fa["method"] = name, name
    return d, fa[fa.strength == 0.0], name


def main(dirs: list[str]) -> None:
    dets, fas = [], []
    for r in dirs:
        d, fa, _ = load(Path(r))
        dets.append(d)
        fas.append(fa)
    det = pd.concat(dets, ignore_index=True)
    fa = pd.concat(fas, ignore_index=True)[["method", "window", "k", "n_false", "area_ha", "fa_per_1000ha"]]
    long = det.melt(id_vars=["method", "window", "k", "size_ha", "strength", "class", "site"],
                    value_vars=["hit", "area50"], var_name="criterion", value_name="ok")
    rate = (long.groupby(["method", "window", "k", "criterion", "strength", "size_ha"]).ok.mean()
            .rename("rate").reset_index())
    out = Path(dirs[-1]) / "injection" / "comparison"
    out.mkdir(parents=True, exist_ok=True)
    rate.to_csv(out / "rates_by_method_criterion.csv", index=False)

    # main table: 1x strength, all sizes, both criteria, with false alarms
    t = rate[rate.strength == 1.0].pivot_table(index=["method", "window", "k"], columns=["criterion", "size_ha"],
                                               values="rate").round(2)
    t.columns = [f"{c} {s:g} ha" for c, s in t.columns]
    t = t.reset_index().merge(fa, on=["method", "window", "k"])
    t.to_csv(out / "table_1x.csv", index=False)

    # recommendation: best rate at 1 ha, 1x, per criterion and false-alarm limit
    r1 = rate[(rate.strength == 1.0) & (rate.size_ha == 1.0)].merge(fa, on=["method", "window", "k"])
    r2 = rate[(rate.strength == 2.0) & (rate.size_ha == 1.0)][["method", "window", "k", "criterion", "rate"]]
    r1 = r1.merge(r2.rename(columns={"rate": "rate_2x"}), on=["method", "window", "k", "criterion"])
    recs = []
    for crit in ("hit", "area50"):
        for lim_name, lim in (("strict ≤1", STRICT), ("operational ≤5", OPERATIONAL)):
            for meth in r1.method.unique():
                ok = r1[(r1.criterion == crit) & (r1.fa_per_1000ha <= lim) & (r1.method == meth)]
                if ok.empty:
                    recs.append({"criterion": crit, "fa_limit": lim_name, "method": meth})
                    continue
                b = ok.sort_values(["rate", "fa_per_1000ha", "k"], ascending=[False, True, False]).iloc[0]
                recs.append({"criterion": crit, "fa_limit": lim_name, "method": meth, "window": int(b.window),
                             "k": b.k, "rate_1ha_1x": round(b.rate, 3), "rate_1ha_2x": round(b.rate_2x, 3),
                             "fa_per_1000ha": round(b.fa_per_1000ha, 2)})
    recs = pd.DataFrame(recs)
    recs.to_csv(out / "recommendations.csv", index=False)

    # plot: rate vs size, 1x and 2x, best strict config of each method (hit criterion)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), dpi=150, sharey=True)
    for ax, crit in zip(axes, ("hit", "area50")):
        for _, rr in recs[(recs.criterion == crit) & (recs.fa_limit == "operational ≤5")].dropna().iterrows():
            for st, ls in ((1.0, "-"), (2.0, "--")):
                g = rate[(rate.method == rr.method) & (rate.window == rr.window) & (rate.k == rr.k)
                         & (rate.criterion == crit) & (rate.strength == st)].sort_values("size_ha")
                ax.plot(g.size_ha, g.rate, ls, marker="o",
                        label=f"{rr.method} ({int(rr.window)}×{int(rr.window)}, k {rr.k:g}), {st:g}×")
        ax.set_xscale("log")
        ax.minorticks_off()
        ax.set_xticks([0.5, 1, 2, 5])
        ax.set_xticklabels(["0.5", "1", "2", "5"])
        ax.set_title(f"kritērijs: {crit}", fontsize=10)
        ax.set_xlabel("platība, ha")
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("atklāšanas īpatsvars")
    axes[0].legend(fontsize=7)
    fig.suptitle("Injekcijas tests (PROVIZORISKS): operatīvā ieteikuma konfigurācijas", fontsize=11)
    fig.tight_layout()
    fig.savefig(out / "comparison_rate_vs_area.png")
    plt.close(fig)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    print(t.to_string(index=False))
    print(recs.to_string(index=False))


if __name__ == "__main__":
    main(sys.argv[1:])
