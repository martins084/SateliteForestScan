"""Run, figures and report of the S1 early-signal test (see earlysignal.py)."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from .earlysignal import (VAR_NAMES, VARS, EarlyConfig, acquisition_series, analyse,  # noqa: E402
                          differences, group_median_ci, null_group_band, smooth_trailing, superposed)
from .report import md_table  # noqa: E402


def run(cfg: EarlyConfig, progress=print, reuse: bool = True) -> dict:
    from .earlysignal import build_units
    from .pipeline import build_grid, build_masks

    rd = cfg.run_dir
    for sub in ("tables", "figures"):
        (rd / sub).mkdir(parents=True, exist_ok=True)
    grid = build_grid(cfg)
    masks = build_masks(cfg, grid)
    units, targets = build_units(cfg, grid, masks)
    progress(f"units: {sum(u.kind == 'target' for u in units)} targets, "
             f"{sum(u.kind == 'control' for u in units)} controls, {sum(u.kind == 'pseudo' for u in units)} "
             f"pseudo, {sum(u.kind == 'pseudo_control' for u in units)} pseudo controls")
    sp = rd / "tables" / "series.csv.gz"
    ap = rd / "tables" / "acquisitions.csv"
    mp = rd / "series_meta.json"
    if reuse and sp.exists() and ap.exists() and mp.exists():
        series = pd.read_csv(sp, parse_dates=["time"])
        acq = pd.read_csv(ap, parse_dates=["time"])
        smeta = json.loads(mp.read_text(encoding="utf-8"))
    else:
        series, acq, smeta = acquisition_series(cfg, grid, masks, units, progress)
        series.to_csv(sp, index=False)
        acq.to_csv(ap, index=False)
        mp.write_text(json.dumps(smeta, indent=1, default=str), encoding="utf-8")
    diffs = differences(series, units, cfg.min_controls)
    res = analyse(cfg, diffs, units)
    diffs.to_csv(rd / "tables" / "differences.csv.gz", index=False)
    res.to_csv(rd / "tables" / "signals.csv", index=False)
    targets.to_csv(rd / "tables" / "targets.csv", index=False)
    pd.DataFrame([{"uid": u.uid, "kind": u.kind, "parent": u.parent, "n_px": len(u.rows),
                   **{k: v for k, v in u.attrs.items() if k in ("source", "t_first", "t_last_normal")}}
                  for u in units]).to_csv(rd / "tables" / "units.csv", index=False)

    main = targets[targets.main_group].uid.tolist()
    alln = targets.uid.tolist()
    pseudo = [u.uid for u in units if u.kind == "pseudo"]
    rng = np.random.default_rng(cfg.seed)
    edges, v_all, c_all = superposed(cfg, diffs, res, units, alln + pseudo)
    nt = len(alln)
    v_t, v_p, c_t = v_all[:, :nt], v_all[:, nt:], c_all[:, :nt]
    imain = [alln.index(u) for u in main]
    sea = {}
    for i, var in enumerate(VARS):
        m, lo, hi = group_median_ci(v_t[i][imain], cfg.bootstrap, rng)
        m15, _, _ = group_median_ci(v_t[i], cfg.bootstrap, rng)
        pm, plo, phi = null_group_band(v_p[i], len(imain), cfg.bootstrap, rng)
        sea[var] = {"main": m, "main_lo": lo, "main_hi": hi, "all15": m15, "placebo": pm,
                    "placebo_lo": plo, "placebo_hi": phi}
    centers = (edges[:-1] + edges[1:]) / 2
    sea_tab = pd.concat([pd.DataFrame({"var": var, "bin_center_days": centers, **sea[var],
                                       "acq_per_target_median": np.median(c_t[i][imain], axis=0)})
                         for i, var in enumerate(VARS)], ignore_index=True)
    sea_tab.to_csv(rd / "tables" / "superposed_epochs.csv", index=False)

    single = [u for u in cfg.single if u in alln]
    plot_sea(cfg, centers, sea, c_t, imain, v_t, [alln.index(u) for u in single], single,
             rd / "figures" / "superposed_epochs.png")
    for var in ("k0", "vh"):
        plot_targets(cfg, diffs, res, units, alln, var, rd / "figures" / f"targets_{var}.png")
    summary = summarize(res, targets, pseudo)
    summary.to_csv(rd / "tables" / "summary.csv", index=False)
    write_report(cfg, targets, res, summary, sea_tab, acq, smeta, rd / f"atskaite_{cfg.run_name}.md")
    return {"targets": targets, "res": res, "summary": summary, "sea": sea_tab, "acq": acq, "meta": smeta}


def summarize(res: pd.DataFrame, targets: pd.DataFrame, pseudo: list[str]) -> pd.DataFrame:
    rows = []
    for var in VARS:
        r = res[res["var"] == var]
        p = r[r.uid.isin(pseudo)]
        p95 = float(np.nanpercentile(p.max_sustained_drop_db, 95)) if len(p) else np.nan
        for grp, uids in (("galvenā (13)", targets[targets.main_group].uid), ("visi (15)", targets.uid),
                          ("placebo (pseudo)", pd.Series(pseudo))):
            g = r[r.uid.isin(uids)]
            rows.append({"var": var, "group": grp, "n": len(g),
                         "n_signal": int(g.signal_date.notna().sum()),
                         "share_signal": g.signal_date.notna().mean() if len(g) else np.nan,
                         "n_before_t_last_normal": int(g.before_t_last_normal.sum()),
                         "share_before_t_last_normal": g.before_t_last_normal.mean() if len(g) else np.nan,
                         "n_drop_above_placebo_p95": int((g.max_sustained_drop_db > p95).sum()),
                         "placebo_p95_drop_db": p95})
    return pd.DataFrame(rows)


def plot_sea(cfg, centers, sea, c_t, imain, v_t, isingle, single, path: Path) -> None:
    fig, axes = plt.subplots(len(VARS) + 1, 1, figsize=(10, 2.6 * len(VARS) + 1.8), dpi=150, sharex=True,
                             gridspec_kw={"height_ratios": [3] * len(VARS) + [1.2]})
    for ax, var in zip(axes, VARS):
        s = sea[var]
        ax.fill_between(centers, s["placebo_lo"], s["placebo_hi"], color="#bbbbbb", alpha=0.6,
                        label="placebo: 13 nejaušu pseido-mērķu mediāna, 5–95 %")
        ax.plot(centers, s["placebo"], color="#777777", lw=1)
        ax.fill_between(centers, s["main_lo"], s["main_hi"], color="#d62728", alpha=0.2,
                        label="mērķi (13): bootstrap 90 %")
        ax.plot(centers, s["main"], color="#d62728", marker="o", ms=3, label="mērķi (13): mediāna")
        ax.plot(centers, s["all15"], color="#d62728", ls="--", lw=1, label="visi 15")
        for j, uid in zip(isingle, single):
            ax.plot(centers, v_t[VARS.index(var), j], ls=":", marker="x", ms=4, color="#1f77b4", label=uid)
        ax.axvline(0, color="k", lw=0.8)
        ax.axhline(0, color="grey", lw=0.5)
        ax.axhline(-cfg.drop_db, color="grey", lw=0.6, ls="--")
        ax.set_ylabel(f"{VAR_NAMES[var]}\nΔ pret bāzi, dB", fontsize=8)
        ax.grid(alpha=0.3)
    axes[0].legend(fontsize=7, ncol=2, loc="lower left")
    ax = axes[-1]
    ax.bar(centers, np.median(c_t[2][imain], axis=0), width=24, color="#4c72b0")
    ax.set_ylabel("uzņēmumi\nmērķim tvertnē", fontsize=8)
    ax.set_xlabel("dienas līdz t_last_normal (pēdējais S2 novērojums bez anomālijas)")
    ax.grid(alpha=0.3)
    fig.suptitle("S1 agrīnā signāla tests: superponētās epohas (mērķis − kontroles, mīnus bāze)", fontsize=11)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def plot_targets(cfg, diffs, res, units, uids, var, path: Path) -> None:
    info = {u.uid: u for u in units}
    n = len(uids)
    cols = 3
    rows = int(np.ceil(n / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(5 * cols, 2.4 * rows), dpi=130, sharey=True, squeeze=False)
    rr = res[res["var"] == var].set_index("uid")
    for ax, uid in zip(axes.ravel(), uids):
        g = diffs[(diffs.uid == uid) & (diffs["var"] == var)].sort_values("time")
        t = pd.DatetimeIndex(g.time)
        v = g["diff"].to_numpy(float)
        sm = smooth_trailing(t, v, cfg.smooth_days)
        r = rr.loc[uid]
        ax.plot(t, v, ".", ms=2, color="#bbbbbb")
        ax.plot(t, sm, color="#333333", lw=1)
        ax.axhline(r.baseline_db, color="#2ca02c", lw=0.8)
        ax.axhline(r.baseline_db - cfg.drop_db, color="#2ca02c", lw=0.8, ls="--")
        a = info[uid].attrs
        ax.axvline(pd.Timestamp(a["t_first"]), color="#d62728", lw=1)
        if a.get("t_last_normal") is not None:
            ax.axvline(pd.Timestamp(a["t_last_normal"]), color="#ff7f0e", lw=1)
        if pd.notna(r.signal_date):
            ax.axvline(pd.Timestamp(r.signal_date), color="#1f77b4", lw=1, ls=":")
        tag = "" if a.get("main_group", True) else " (ārpus galvenās kopas)"
        ax.set_title(f"{uid}{tag}", fontsize=8)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%y-%m"))
        ax.tick_params(labelsize=7)
        ax.grid(alpha=0.3)
    for ax in axes.ravel()[n:]:
        ax.axis("off")
    fig.suptitle(f"{VAR_NAMES[var]}: mērķis − kontroles (pelēks), 30 d izlīdzināts (melns); bāze un −0,5 dB (zaļš); "
                 "t_first (sarkans), t_last_normal (oranžs), signāls (zils)", fontsize=9)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def write_report(cfg, targets, res, summary, sea_tab, acq, smeta, path: Path) -> None:
    used = acq[acq.used]
    excl = acq[~acq.used]
    L = [f"# S1 agrīnā signāla tests — {cfg.run_name}", "",
         "Hipotēze (Hechtl u. c. 2025, Forests 16(8):1272): pirms optiski redzama mizgraužu bojājuma "
         "atpakaļizkliede samazinās ~1 dB. Mērķi ir **S2 aizdomas** (s2forest stresa poligoni), nevis "
         "apstiprināti mizgrauži. RTC GRD datiem pilnos Kennaugh elementus (K5, K8) nevar aprēķināt; "
         "izmantoti VV, VH, K0-līdzīgā 10·log10(VV+VH) un VH − VV.", "",
         "## Metode (no šīs palaišanas konfigurācijas)", "",
         f"- Periods {cfg.period[0]} … {cfg.period[1]}, visas orbītas; uzņēmumi atrasti {smeta['n_acq_found']}, "
         f"izmantoti {smeta['n_acq_used']}. Izslēgti: temperatūra < {cfg.freeze_temp_c:g} °C uzņēmuma stundā "
         f"vai sniega sega > 0 (Open-Meteo; sniega dati {'ir' if smeta['snow_available'] else 'NAV — tikai temperatūra'}).",
         "- Katrs uzņēmums normalizēts pret stabilā meža mediānu (VV, VH atsevišķi); vienības vērtība = "
         f"mediāna pikseļos (≥ {cfg.min_valid_share:.0%} derīgu).",
         f"- Kontroles: {cfg.n_controls} stabilā meža diski katram mērķim, tāda pati platība (≥ {cfg.min_px} px), "
         f"tā pati HRL klase, {cfg.control_dist_m[0]:g}–{cfg.control_dist_m[1]:g} m, ārpus visiem suspects + "
         f"{cfg.suspects_buffer_m:g} m. Atšķirība = mērķis − kontroļu mediāna (≥ {cfg.min_controls} kontroles).",
         f"- Izlīdzināšana: **atpakaļvērsta** {cfg.smooth_days} dienu slīdošā mediāna (vērtība datumā t izmanto tikai "
         "(t − 30 d, t], lai vēlāks kritums neparādītos agrāk). Visas orbītas kopā; orbītu skaits ar signālu "
         "savā rindā — atsevišķa kolonna.",
         f"- Bāze: atšķirības mediāna {cfg.baseline_months[0]}–{cfg.baseline_months[1]} mēnešus pirms t_first.",
         f"- Agrīnais signāls: pirmais datums pirms t_first, kad izlīdzinātā atšķirība ≤ bāze − {cfg.drop_db:g} dB "
         f"visā {cfg.persist_days} dienu logā (≥ {cfg.persist_min_obs} vērtības, ≥ {cfg.persist_min_span_days} dienas). "
         "`max_sustained_drop` = lielākais šāds noturīgs kritums pirms t_first.",
         "- t_last_normal (mana operacionālā definīcija no s2forest izvades, tikai lasot): pēdējais S2 datums "
         "pirms t_first ar ≥ 50 % derīgu pikseļu, kurā poligona mediānais CRSWIR z < 2,5 (tā pati sezona) "
         "vai < 1,25 (iepriekšējā sezona, ja z rastri ir); ja iepriekšējās sezonas z rastru nav — iepriekšējās "
         "sezonas pēdējais derīgais S2 datums (s2forest `onset_prev_autumn` = nē) [N].",
         f"- Placebo: {cfg.n_pseudo} nejauši stabilā skujkoku meža diski ar galvenās kopas mērķu platībām un "
         "datumiem (cikliski), katram 5 kontroles; superponētajās epohās placebo josla = 13 nejauši izvēlētu "
         "pseido-mērķu mediānas 5–95 % (bootstrap).", ""]
    L += ["## Uzņēmumi", "", f"Izslēgti {len(excl)} no {len(acq)}: " +
          ", ".join(f"{k} {v}" for k, v in excl.reason.str.extract(r"^(\w+)")[0].value_counts().items()) + ".", ""]
    per_year = used.assign(year=used.time.dt.year).groupby(["year", "rel_orbit"]).size().unstack(fill_value=0)
    L += [md_table(per_year.reset_index(), "{:.0f}"), ""]
    L += ["## Mērķi un signāli", ""]
    tt = targets[["uid", "area_ha", "status", "t_first", "t_last_normal", "t_last_normal_rule", "main_group",
                  "n_controls"]].copy()
    tt["t_first"] = pd.to_datetime(tt.t_first).dt.date
    tt["t_last_normal"] = pd.to_datetime(tt.t_last_normal).dt.date
    L += [md_table(tt, "{:.2f}"), ""]
    for var in VARS:
        r = res[(res["var"] == var) & res.uid.isin(targets.uid)].merge(targets[["uid", "main_group"]], on="uid")
        p95 = summary[(summary["var"] == var)].placebo_p95_drop_db.iloc[0]
        r["> placebo P95"] = r.max_sustained_drop_db > p95
        r["signal_date"] = pd.to_datetime(r.signal_date).dt.date
        L += [f"### {VAR_NAMES[var]} (placebo P95 noturīgam kritumam: {p95:.2f} dB)", "",
              md_table(r[["uid", "main_group", "baseline_db", "baseline_n", "signal_date", "lead_vs_t_first_months",
                          "lead_vs_t_last_normal_months", "before_t_last_normal", "max_sustained_drop_db",
                          "> placebo P95", "orbits_with_signal", "n_orbits"]], "{:.2f}"), ""]
    L += ["## Kopsavilkums", "", md_table(summary, "{:.2f}"), "",
          "Attēli: `figures/superposed_epochs.png`, `figures/targets_k0.png`, `figures/targets_vh.png`. "
          "Tabulas: `tables/`.", ""]
    path.write_text("\n".join(L), encoding="utf-8")
