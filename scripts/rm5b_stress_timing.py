"""Stage 5b (diagnostic): s2forest stress polygons 2022-2024 vs LVM damage polygons that they
intersect directly (no buffer): registration year relative to the run year, a cut <= 20 m away in
the same run, and overlap with a cut of the next run. Both validation AOIs.

    python scripts/rm5b_stress_timing.py configs/rm_5b_lvm.yaml configs/rm_5b_lvm_aoi3.yaml
"""

import sys

import pandas as pd

from mezasargs_risk import s2val
from mezasargs_risk.config import load_config


def stress_timing(config: str) -> pd.DataFrame:
    c = load_config(config).lvm
    _, d, runs = s2val.load(c)
    rows = []
    for y in (2022, 2023, 2024):
        s = runs[("all", y)]
        cuts = s[s["type"] == "cut"]
        nxt = runs[("all", y + 1)]
        nxt_cuts = nxt[nxt["type"] == "cut"]
        for p in s[s["type"] == "stress"].itertuples():
            dd = d[d.intersects(p.geometry)]
            win = dd[(dd["year"] - y).between(-1, 1)]
            rows.append({"config": config, "run_year": y, "id": p.id, "area_ha": p.area_ha,
                         "in_damage_window": len(win) > 0, "in_620_window": bool((win["group"] == "620").any()),
                         "reg_minus_run_year": ",".join(map(str, sorted(set((win["year"] - y).astype(int))))),
                         "cut_le20m_same_run": bool(len(cuts)) and bool(cuts.distance(p.geometry).min() <= 20),
                         "cut_next_run_overlap": bool(nxt_cuts.intersects(p.geometry).any())})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    out = pd.concat([stress_timing(a) for a in sys.argv[1:]], ignore_index=True)
    out.to_csv("output/rm5b_lvm_aoi3/tables/stress_timing_both_aoi.csv", index=False)
    for cfg, r in out.groupby("config"):
        w = r[r["in_damage_window"]]
        print(f"{cfg}: stress n={len(r)}, in window {len(w)}, in 620 window {int(r['in_620_window'].sum())}")
        print("  reg - run year:", w["reg_minus_run_year"].value_counts().to_dict())
        print(f"  in window: cut <= 20 m same run {int(w['cut_le20m_same_run'].sum())}, "
              f"overlapped by next-run cut {int(w['cut_next_run_overlap'].sum())}")
