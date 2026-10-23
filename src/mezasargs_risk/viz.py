"""Stage 5 figures (PNG, Latvian labels). One y-axis per panel; two measures of different units
go to separate panels."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

from .describe import cell_geometry  # noqa: E402

S1, S2, S3 = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, GRID, AXIS, SURF = "#0b0b0b", "#52514e", "#e1e0d9", "#c3c2b7", "#fcfcfb"
SEQ = LinearSegmentedColormap.from_list("blue", ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"])
PX_HA = 0.09

plt.rcParams.update({"figure.facecolor": SURF, "axes.facecolor": SURF, "savefig.facecolor": SURF,
                     "axes.edgecolor": AXIS, "axes.labelcolor": INK2, "xtick.color": INK2,
                     "ytick.color": INK2, "text.color": INK, "axes.grid": True, "grid.color": GRID,
                     "grid.linewidth": 0.6, "axes.spines.top": False, "axes.spines.right": False,
                     "font.size": 9, "axes.titlesize": 10, "axes.titleweight": "bold",
                     "legend.frameon": False, "lines.linewidth": 2})


def _storms(ax, storms, label=True):
    for s in storms:
        ax.axvline(s.date.year, color=INK2, lw=0.8, ls=":", zorder=0)
        if label:
            ax.annotate(s.name.split(" (")[0], (s.date.year, 1), xycoords=("data", "axes fraction"),
                        xytext=(3, -10), textcoords="offset points", fontsize=7, color=INK2)


def annual(cfg, counts, cross, stats, path: Path) -> Path:
    c = counts[(counts.region > 0)].groupby(["version", "year", "agent"]).px.sum().unstack("agent").fillna(0)
    fig, axes = plt.subplots(3, 1, figsize=(9, 8.2), dpi=200, sharex=True)
    for ax, agent, title in ((axes[0], "wind_bark_beetle", "EFDA klase 1 (vējš / mizgrauži), ha gadā"),
                             (axes[1], "harvest", "EFDA klase 3 (cirte), ha gadā")):
        for v, col in ((cfg.efda.main.version, S1), (cfg.efda.crosscheck.version, S2)):
            s = c.loc[v][agent] * PX_HA
            ax.plot(s.index, s.values, color=col, label=f"EFDA {v}", marker="o", ms=3)
        ax.set_title(title, loc="left")
        ax.set_ylim(0, None)
        _storms(ax, cfg.storms, label=ax is axes[0])
    axes[0].legend(loc="upper left")
    m = stats.get("meb012")
    if m is not None:
        vol = m[m.indicator.str.contains("izcirstais")]
        for name, col, lab in (("Vējgāzes, snieglauzes", S1, "vējgāzes, snieglauzes"),
                               ("..kaitēkļu izraisīti stumbru bojājumi", S2, "kaitēkļu stumbru bojājumi")):
            s = vol[vol["Meža bojājumi"] == name].set_index("year")["value"]
            axes[2].plot(s.index, s.values, color=col, marker="o", ms=3, label=lab)
        axes[2].set_title("VMD: bojājumu rezultātā izcirstais apjoms, tūkst. m³ (CSP MEB012)", loc="left")
        axes[2].legend(loc="upper left")
        axes[2].set_ylim(0, None)
        _storms(axes[2], cfg.storms, label=False)
    axes[2].set_xlim(1984, 2025)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def efda_vs_vmd(counts, stats, path: Path, versions: list[str]) -> tuple[Path, pd.DataFrame]:
    m = stats["meb012"]
    vol = m[m.indicator.str.contains("izcirstais")].pivot(index="year", columns="Meža bojājumi", values="value")
    vol = vol[["Vējgāzes, snieglauzes", "..kaitēkļu izraisīti stumbru bojājumi"]]
    vol.columns = ["vmd_wind_km3", "vmd_stem_pest_km3"]
    c1 = counts[(counts.region > 0) & (counts.agent == "wind_bark_beetle")]
    c1 = (c1.groupby(["year", "version"]).px.sum() * PX_HA).unstack("version")
    df = vol.join(c1[versions].add_prefix("efda_c1_ha_"), how="inner")
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.9), dpi=200, sharey=True)
    for ax, col, lab in ((axes[0], "vmd_wind_km3", "VMD vējgāzes, snieglauzes, tūkst. m³"),
                         (axes[1], "vmd_stem_pest_km3", "VMD kaitēkļu stumbru bojājumi, tūkst. m³")):
        rhos = []
        for v, color in zip(versions, (S1, S2)):
            y = df[f"efda_c1_ha_{v}"].dropna()
            ax.scatter(df.loc[y.index, col], y, s=36, color=color, edgecolor=SURF, linewidth=1.5,
                       zorder=3, label=f"EFDA {v}")
            rhos.append(f"{v}: {df.loc[y.index, col].corr(y, method='spearman'):.2f} (n={len(y)})")
            if v == versions[0]:
                for yr, val in y.items():
                    ax.annotate(str(yr), (df.loc[yr, col], val), xytext=(4, 3), textcoords="offset points",
                                fontsize=6.5, color=INK2)
        ax.set_title("Spīrmena ρ  " + ";  ".join(rhos), loc="left", fontsize=8)
        ax.set_xlabel(lab)
    axes[0].set_ylabel("EFDA klase 1, ha")
    axes[0].legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path, df


def patches(p: pd.DataFrame, path: Path) -> Path:
    fig, axes = plt.subplots(3, 1, figsize=(9, 7.5), dpi=200, sharex=True)
    spec = [("median_ha", "Plankuma laukuma mediāna, ha"),
            ("share_area_ge1ha", "Platības daļa plankumos ≥ 1 ha"),
            ("si_area_weighted", "Formas indekss (laukumsvērts; 1 = kvadrāts)")]
    for ax, (col, title) in zip(axes, spec):
        for agent, color, lab in (("wind_bark_beetle", S1, "klase 1 (vējš / mizgrauži)"),
                                  ("harvest", S2, "klase 3 (cirte)")):
            s = p[p.agent == agent].set_index("year")[col]
            ax.plot(s.index, s.values, color=color, marker="o", ms=3, label=lab)
        ax.set_title(title, loc="left")
    axes[0].legend(loc="upper left")
    axes[1].set_ylim(0, 1)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def grid_map(cfg, regions, grid, forest_cells, path: Path, periods) -> Path:
    g = grid[grid.agent == "wind_bark_beetle"]
    f = forest_cells.set_index("cell")["forest_px"]
    fig, axes = plt.subplots(1, len(periods), figsize=(4.2 * len(periods), 3.6), dpi=200)
    vals = []
    for a, b in periods:
        s = g[(g.year >= a) & (g.year <= b)].groupby("cell").px.sum()
        vals.append((1000 * s / f.reindex(s.index)).where(f.reindex(s.index) >= 1000) / (b - a + 1))
    vmax = np.nanpercentile(pd.concat(vals).values, 98)
    for ax, (a, b), v in zip(np.atleast_1d(axes), periods, vals):
        v = v.dropna()
        cells = gpd.GeoDataFrame({"v": v.values}, geometry=cell_geometry(v.index.values, grid.attrs))
        cells.plot(ax=ax, column="v", cmap=SEQ, vmin=0, vmax=vmax, linewidth=0)
        regions.boundary.plot(ax=ax, color=INK2, linewidth=0.5)
        ax.set_title(f"{a}–{b}", loc="left")
        ax.set_axis_off()
    sm = plt.cm.ScalarMappable(cmap=SEQ, norm=plt.Normalize(0, vmax))
    cb = fig.colorbar(sm, ax=axes, shrink=0.8, pad=0.01)
    cb.set_label("EFDA klase 1: ha gadā uz 1000 ha meža\n(10 km šūnas ar ≥ 90 ha EFDA meža)", color=INK2)
    fig.text(0.01, 0.01, "Robežas: © EuroGeographics for the administrative boundaries (GISCO NUTS 2024)",
             fontsize=6, color=INK2)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def regions_heat(counts, forest_reg, path: Path, version: str) -> tuple[Path, pd.DataFrame]:
    c = counts[(counts.region > 0) & (counts.agent == "wind_bark_beetle") & (counts.version == version)]
    t = c.pivot_table(index="region_name", columns="year", values="px", aggfunc="sum")
    fr = forest_reg.set_index("region_name")["forest_px"]
    rate = 1000 * t.div(fr.reindex(t.index), axis=0)
    fig, ax = plt.subplots(figsize=(10, 2.8), dpi=200)
    im = ax.imshow(rate.values, aspect="auto", cmap=SEQ, vmin=0)
    ax.set_yticks(range(len(rate)), rate.index)
    ax.set_xticks(range(0, rate.shape[1], 5), rate.columns[::5])
    ax.grid(False)
    cb = fig.colorbar(im, ax=ax, pad=0.01)
    cb.set_label("ha uz 1000 ha meža", color=INK2)
    ax.set_title(f"EFDA {version} klase 1 pa NUTS 3 reģioniem (GISCO NUTS 2024)", loc="left")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path, rate


def harvest_conifer(cfg, grid, forest_cells, conifer, stats, path: Path) -> tuple[Path, pd.DataFrame]:
    h = grid[grid.agent == "harvest"].merge(conifer[["cell", "conifer_share"]], on="cell", how="left")
    f = forest_cells.merge(conifer[["cell", "conifer_share"]], on="cell", how="left")
    rows = []
    for thr in [cfg.conifer.min_share] + cfg.conifer.sensitivity:
        for grp, sel_h, sel_f in (("skujkoku", h.conifer_share >= thr, f.conifer_share >= thr),
                                  ("pārējās", h.conifer_share < thr, f.conifer_share < thr)):
            fy = f.loc[sel_f, "forest_px"].sum()
            s = h[sel_h].groupby("year").px.sum()
            for y, v in s.items():
                rows.append({"threshold": thr, "group": grp, "year": y, "harvest_ha": v * PX_HA,
                             "forest_ha": fy * PX_HA, "rate_pct": 100 * v / fy if fy else np.nan})
    t = pd.DataFrame(rows)
    main = t[t.threshold == cfg.conifer.min_share]
    m = stats.get("mez012")
    n = 3 if m is not None else 2
    fig, axes = plt.subplots(n, 1, figsize=(9, 2.6 * n + 0.6), dpi=200, sharex=True)
    for grp, col in (("skujkoku", S1), ("pārējās", S2)):
        s = main[main.group == grp].set_index("year")
        axes[0].plot(s.index, s.harvest_ha, color=col, marker="o", ms=3,
                     label=f"{grp} šūnas ({s.forest_ha.iloc[0]/1e3:.0f} tūkst. ha meža)")
        axes[1].plot(s.index, s.rate_pct, color=col, marker="o", ms=3)
    thr = cfg.conifer.min_share
    axes[0].set_title(f"EFDA klase 3 (cirte), ha gadā; skujkoku šūna: skujkoki ≥ {thr:.0%} HRL DLT 2018 koku seguma",
                      loc="left")
    axes[0].legend(loc="upper left")
    axes[1].set_title("EFDA klase 3, % no šūnu EFDA meža platības gadā", loc="left")
    if m is not None:
        a = m[m.indicator.str.contains("Platība") & (m["Valdošā suga"] == "Egle")]
        for cut, col, lab in (("Sanitārā vienlaidus cirte", S1, "sanitārā vienlaidus cirte"),
                              ("Sanitārā izlases cirte", S2, "sanitārā izlases cirte")):
            s = a[a["Cirte (veidi)"] == cut].set_index("year")["value"]
            axes[2].plot(s.index, s.values, color=col, marker="o", ms=3, label=lab)
        axes[2].set_title("Konteksts: VMD egļu audžu sanitārās cirtes, ha (CSP MEZ012; visa Latvija)", loc="left")
        axes[2].legend(loc="upper left")
    for ax in axes:
        ax.set_ylim(0, None)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path, t


def kalsnava_fig(per_year: pd.DataFrame, path: Path) -> Path:
    p = per_year.pivot(index="year", columns="agent", values="aoi_ha").fillna(0)
    fig, ax = plt.subplots(figsize=(9, 2.8), dpi=200)
    w = 0.4
    ax.bar(p.index - w / 2, p.get("wind_bark_beetle", 0), width=w, color=S1, label="klase 1 (vējš / mizgrauži)")
    ax.bar(p.index + w / 2, p.get("harvest", 0), width=w, color=S2, label="klase 3 (cirte)")
    ax.set_title("Kalsnavas testa teritorija (25 km²): EFDA v3.0 traucējumi, ha gadā", loc="left")
    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def harvest_official_fig(df: pd.DataFrame, follow: pd.DataFrame, versions: list[str], path: Path) -> Path:
    """Left: EFDA class 3 vs official stand-replacing cut area. Right: share of v2.1.1 disturbed
    pixels that v3.0 also marks as disturbed within +-1 year (end-of-series check)."""
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.9), dpi=200)
    ax = axes[0]
    ax.plot(df.index, df["csp_stand_replacing_ha"], color=INK2, marker="s", ms=3,
            label="CSP MEZ012: vienlaidus cirtes (VMD)")
    for v, col in zip(versions, (S1, S2)):
        s = df[f"efda_c3_ha_{v}"].dropna()
        rho = df.loc[s.index, "csp_stand_replacing_ha"].corr(s, method="spearman")
        ax.plot(s.index, s.values, color=col, marker="o", ms=3, label=f"EFDA {v} klase 3 (ρ={rho:.2f}, n={len(s)})")
    ax.set_title("Cirtes platība, ha gadā", loc="left")
    ax.set_ylim(0, None)
    ax.legend(loc="lower left", fontsize=7)
    ax = axes[1]
    for agent, col, lab in (("harvest", S3, "v2.1.1 klase 3"), ("wind_bark_beetle", S2, "v2.1.1 klase 1")):
        f = follow[follow.agent_other == agent].set_index("year")
        ax.plot(f.index, 100 * f["main_pm1"], color=col, marker="o", ms=3, label=lab)
    ax.set_title("v2.1.1 pikseļi, ko v3.0 arī rāda kā traucētus (±1 g.), %", loc="left")
    ax.set_ylim(0, 100)
    ax.legend(loc="lower left", fontsize=7)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def all_figures(cfg, fdir: Path, regions, counts, cross, p, grid, forest_cells, conifer, stats, kal) -> dict:
    out = {}
    v = cfg.efda.main.version
    out["annual"] = annual(cfg, counts, cross, stats, fdir / "rm5_efda_gadi.png")
    if "meb012" in stats:
        vers = [v] + ([cfg.efda.crosscheck.version] if cfg.efda.crosscheck else [])
        out["efda_vs_vmd"], df = efda_vs_vmd(counts, stats, fdir / "rm5_efda_pret_vmd.png", vers)
        df.to_csv(cfg.run_dir / "tables" / "efda_c1_vs_vmd.csv")
    out["patches"] = patches(p, fdir / "rm5_plankumi.png")
    out["map"] = grid_map(cfg, regions, grid, forest_cells, fdir / "rm5_karte_klase1.png",
                          [(1985, 2004), (2005, 2014), (2015, 2024)])
    fr = pd.read_csv(cfg.run_dir / "tables" / "efda_forest_px_by_region.csv")
    out["regions"], rate = regions_heat(counts, fr, fdir / "rm5_regioni.png", v)
    rate.to_csv(cfg.run_dir / "tables" / "efda_c1_rate_by_region.csv")
    out["harvest_conifer"], t = harvest_conifer(cfg, grid, forest_cells, conifer, stats,
                                                fdir / "rm5_cirtes_skujkoku.png")
    t.to_csv(cfg.run_dir / "tables" / "efda_harvest_conifer_cells.csv", index=False)
    if kal is not None:
        out["kalsnava"] = kalsnava_fig(kal[0], fdir / "rm5_kalsnava.png")
    return out


# --- stage 5a: LVM open damage polygons ------------------------------------------------------

def lvm_annual(cmp: pd.DataFrame, ann: pd.DataFrame, path: Path) -> Path:
    """LVM registered stem pests / wind vs CSP MEB012 state-forest stem-pest damage."""
    fig, axes = plt.subplots(2, 1, figsize=(9, 6), dpi=200, sharex=True)
    ax = axes[0]
    for code, col, lab in ((620, S2, "LVM: stumbra kaitēkļi (620)"), (100, S1, "LVM: vējgāze, snieglauze (100)")):
        s = ann[ann.subtype == code].set_index("year")["ha"]
        s = s[s.index.to_series().between(2008, 2024)]
        ax.plot(s.index, s.values, color=col, marker="o", ms=3, label=lab)
    ax.plot(cmp.index, cmp["csp_state_dead_stands_ha"], color=INK2, marker="s", ms=3, ls="--",
            label="CSP MEB012 valsts meži: bojā aizgājušās audzes, stumbra kaitēkļi")
    ax.set_title("Reģistrētā bojājumu platība, ha gadā (LVM pēc reģistrācijas gada)", loc="left")
    ax.legend(loc="upper left", fontsize=7)
    ax.set_ylim(0, None)
    ax = axes[1]
    ax.plot(cmp.index, cmp["lvm_n"], color=S2, marker="o", ms=3, label="LVM 620 poligonu skaits")
    ax.set_ylabel("poligoni")
    ax.set_title("LVM 620: poligonu skaits gadā (2025 – tikai līdz arhīva datumam 2025-04-27)", loc="left")
    ax.set_ylim(0, None)
    ax.set_xlim(2007.5, 2025.5)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def lvm_sizes(g, path: Path) -> Path:
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.4), dpi=200)
    bins = np.logspace(-2, 2, 41)
    for code, col, lab in ((620, S2, "620 stumbra kaitēkļi"), (100, S1, "100 vējgāze, snieglauze")):
        x = g[(g.subtype == code) & ~g["empty"]].ha
        axes[0].hist(x, bins=bins, color=col, alpha=0.6, label=f"{lab} (n={len(x):,})")
    axes[0].set_xscale("log")
    axes[0].axvline(0.5, color=INK2, ls=":", lw=1)
    axes[0].set_xlabel("poligona platība, ha (log)")
    axes[0].set_title("Poligonu izmērs", loc="left")
    axes[0].legend(fontsize=7)
    x = g[(g.subtype == 620) & ~g["empty"] & g.year.between(2013, 2025)]
    q = x.groupby("year").ha.quantile([0.25, 0.5, 0.75]).unstack()
    axes[1].fill_between(q.index.astype(int), q[0.25], q[0.75], color=S2, alpha=0.25, lw=0)
    axes[1].plot(q.index.astype(int), q[0.5], color=S2, marker="o", ms=3)
    axes[1].set_title("620: mediāna un kvartiles pa gadiem, ha", loc="left")
    axes[1].set_ylim(0, None)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def lvm_regions(regions, reg: pd.DataFrame, m11: pd.DataFrame, path: Path, years=(2023, 2024)) -> Path:
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.9), dpi=200, gridspec_kw={"width_ratios": [1.3, 1]})
    rate = 1000 * reg[list(years)].sum(axis=1) / reg["lvm_land_ha"] / len(years)
    r = regions.merge(rate.rename("rate"), left_on="NAME_LATN", right_index=True)
    r.plot(ax=axes[0], column="rate", cmap=SEQ, vmin=0, linewidth=0.5, edgecolor=INK2, legend=True,
           legend_kwds={"shrink": 0.7, "label": "ha gadā uz 1000 ha LVM zemes"})
    for _, row in r.iterrows():
        p = row.geometry.representative_point()
        axes[0].annotate(f"{row.NAME_LATN}\n{row.rate:.1f}", (p.x, p.y), ha="center", fontsize=7, color=INK)
    axes[0].set_axis_off()
    axes[0].set_title(f"LVM 620, {years[0]}–{years[-1]}", loc="left")
    ax = axes[1]
    d = m11.dropna(subset=["lvm_ha", "csp_state_dead_stands_ha"])
    for yr, mk in zip(sorted(d.year.unique()), "os^D"):
        x = d[d.year == yr]
        ax.scatter(x["csp_state_dead_stands_ha"], x["lvm_ha"], marker=mk, s=30, color=S2, edgecolor=SURF,
                   label=str(yr), zorder=3)
    rho = d["csp_state_dead_stands_ha"].corr(d["lvm_ha"], method="spearman")
    ax.set_xlabel("CSP MEB011 valsts meži: bojā aizgājušās audzes, ha")
    ax.set_ylabel("LVM 620, ha")
    ax.set_title(f"Reģions × gads, Spīrmena ρ = {rho:.2f} (n={len(d)})", loc="left", fontsize=8)
    ax.legend(fontsize=7)
    fig.text(0.01, 0.01, "Robežas: © EuroGeographics for the administrative boundaries (GISCO NUTS 2024)",
             fontsize=6, color=INK2)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def lvm_timing(t: pd.DataFrame, path: Path) -> Path:
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8), dpi=200, sharey=True)
    cols = {-1: INK2, 0: S1, 1: S2, 2: S3}
    for off, col in cols.items():
        x = t[t.offset == off].set_index("reg_year")
        axes[0].plot(x.index, 100 * x["harvest"], color=col, marker="o", ms=3, label=f"r{off:+d}" if off else "r")
    b = t[t.offset == 0].set_index("reg_year")
    axes[0].plot(b.index, 100 * b["base_harvest"], color=INK, ls=":", lw=1.2, label="bāze: visa LVM meža zeme (gads r)")
    axes[0].set_title("EFDA v3.0 cirte LVM 620 poligonos, % pikseļu", loc="left")
    axes[0].set_xlabel("reģistrācijas gads r")
    axes[0].legend(fontsize=7, title="EFDA gads", title_fontsize=7)
    s = t[t.reg_year.between(2019, 2022)].groupby("offset")[["harvest", "class1", "any"]].mean()
    w = 0.25
    for i, (k, col, lab) in enumerate((("harvest", S1, "klase 3"), ("class1", S2, "klase 1"), ("any", INK2, "jebkurš"))):
        axes[1].bar(s.index + (i - 1) * w, 100 * s[k], width=w, color=col, label=lab)
    axes[1].set_xticks(s.index, [f"r{o:+d}" if o else "r" for o in s.index])
    axes[1].set_title("Vidēji reģistrācijas gadiem 2019–2022", loc="left")
    axes[1].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def lvm_kalsnava(aoi, layers: dict, path: Path) -> Path:
    """Owner / data coverage in the Kalsnava AOI with s2forest polygons on top."""
    fig, ax = plt.subplots(figsize=(6.4, 6.4), dpi=200)
    aoi.boundary.plot(ax=ax, color=INK, lw=1)
    style = {"MPS nogabali": dict(color="#cde2fb", lw=0), "LVM zeme": dict(color="#86b6ef", lw=0),
             "MVR nogabali": dict(color="#f6c9b0", lw=0), "LVM bojājumi": dict(color=S2, lw=0)}
    handles = []
    for name, g in layers.items():
        if name in style and len(g):
            g.plot(ax=ax, **style[name])
            handles.append(plt.Rectangle((0, 0), 1, 1, color=style[name]["color"], label=f"{name}"))
    for lab, col in (("s2forest cirtes 2025+2026", INK2), ("s2forest stress 2025+2026", "#d03b3b")):
        g = layers.get(lab)
        if g is not None and len(g):
            g.boundary.plot(ax=ax, color=col, lw=0.6)
            handles.append(plt.Line2D([], [], color=col, label=lab))
    b = aoi.total_bounds
    ax.set_xlim(b[0], b[2]); ax.set_ylim(b[1], b[3])
    ax.set_axis_off()
    ax.legend(handles=handles, loc="lower left", fontsize=7, frameon=True, framealpha=0.9)
    ax.set_title("Kalsnavas AOI: kuru datu kopa aptver mežu", loc="left")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path
