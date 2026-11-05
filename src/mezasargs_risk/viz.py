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


def lvm_aoi_candidates(regions, cells: pd.DataFrame, cand: dict, kalsnava, path: Path, cell_m: float = 5000.0) -> Path:
    """Stage 5b: the densest stem-pest cells on a Latvia map + one panel per AOI candidate
    (LVM land, 2023-2024 stem-pest polygons, other damage)."""
    from shapely.geometry import box

    n = len(cand)
    fig, axs = plt.subplots(1, n + 1, figsize=(3.6 * (n + 1), 4.0), dpi=200)
    ax = axs[0]
    regions.plot(ax=ax, color="#eeede8", edgecolor=AXIS, lw=0.5)
    sq = gpd.GeoDataFrame(cells, geometry=[box(x, y, x + cell_m, y + cell_m) for x, y in zip(cells["x0"], cells["y0"])],
                          crs=regions.crs)
    sq.plot(ax=ax, color=AXIS, edgecolor=INK2, lw=0.4)
    sq[sq["rank"] <= n].plot(ax=ax, color=S2, edgecolor=INK, lw=0.6)
    for r in sq[sq["rank"] <= n].itertuples():
        ax.annotate(str(r.rank), (r.x0 + cell_m, r.y0 + cell_m), fontsize=8, fontweight="bold")
    kalsnava.boundary.plot(ax=ax, color=S1, lw=1.2)
    ax.set_axis_off()
    ax.set_title("10 blīvākās šūnas; kandidāti", loc="left")
    for ax, (rank, lay) in zip(axs[1:], cand.items()):
        b = lay["cell"].total_bounds
        lay["cell"].boundary.plot(ax=ax, color=INK, lw=1)
        if len(lay["land"]):
            lay["land"].plot(ax=ax, color="#cde2fb", lw=0)
        if len(lay["other"]):
            lay["other"].plot(ax=ax, color=INK2, lw=0)
        if len(lay["pest"]):
            lay["pest"].plot(ax=ax, color=S2, lw=0)
        ax.set_xlim(b[0], b[2]); ax.set_ylim(b[1], b[3])
        ax.set_axis_off()
        ax.set_title(f"Kandidāts {rank}", loc="left")
    axs[-1].legend(handles=[plt.Rectangle((0, 0), 1, 1, color=c, label=l) for c, l in
                            (("#cde2fb", "LVM zeme"), (S2, "LVM 620, 2023–2024"), (INK2, "citi bojājumi, 2023–2024"))],
                   loc="lower left", fontsize=7, frameon=True, framealpha=0.9)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def val5b_maps(aoi, d, runs: dict, path: Path) -> Path:
    """Stage 5b: one panel per monitoring year - LVM damage polygons registered in the monitored
    years (by group / registration year) and s2forest cut / stress polygons of that year's run."""
    years = sorted(y for v, y in runs if v == "all")
    d = d[d["year"].between(min(years), max(years))]          # registrations in the monitored years only
    fig, axs = plt.subplots(1, len(years), figsize=(3.6 * len(years), 4.2), dpi=200)
    style = [("620, reģ. 2023", (d["group"] == "620") & (d["year"] == 2023), "#f6b48f"),
             ("620, reģ. 2024", (d["group"] == "620") & (d["year"] == 2024), S2),
             ("620, reģ. 2022 / 2025", (d["group"] == "620") & ~d["year"].isin([2023, 2024]), "#f3dccd"),
             ("vējgāzes (100)", d["group"] == "100", "#86b6ef"),
             ("citi bojājumi", d["group"] == "other", AXIS)]
    for ax, y in zip(np.atleast_1d(axs), years):
        aoi.boundary.plot(ax=ax, color=INK, lw=1)
        for _, m, col in style:
            if m.any():
                d[m].plot(ax=ax, color=col, lw=0)
        s = runs[("all", y)]
        for t, col in (("cut", INK), ("stress", "#d03b3b")):
            if (s["type"] == t).any():
                s[s["type"] == t].boundary.plot(ax=ax, color=col, lw=0.6)
        b = aoi.total_bounds
        ax.set_xlim(b[0], b[2]); ax.set_ylim(b[1], b[3])
        ax.set_axis_off()
        ax.set_title(f"s2forest {y}" + (" (reģistrs beidzas 2025-04)" if y >= 2025 else ""), loc="left", fontsize=9)
    handles = [plt.Rectangle((0, 0), 1, 1, color=col, label=lab) for lab, _, col in style]
    handles += [plt.Line2D([], [], color=INK, label="s2forest cut"), plt.Line2D([], [], color="#d03b3b", label="s2forest stress")]
    fig.legend(handles=handles, loc="lower center", ncol=7, fontsize=7)
    fig.tight_layout(rect=(0, 0.07, 1, 0.97))
    fig.savefig(path)
    plt.close(fig)
    return path


def val5b_detection(summary: pd.DataFrame, plac: pd.DataFrame, path: Path) -> Path:
    """Stage 5b: (left) share of LVM 620 polygons >= 0,5 ha found per offset, observed vs placebo
    (mean and 2,5-97,5 %); (right) how s2forest marks each damage group (cut / stress, any offset)."""
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9.6, 3.8), dpi=200)
    s = summary[(summary["group"] == "620") & (summary["size"] == ">= 0,5 ha")]
    labs = [str(o) for o in s["offset"]]
    x = np.arange(len(labs))
    bars = [("found_share", -0.3, S2, "≤ 20 m, novērots"), ("found_share", -0.1, AXIS, "≤ 20 m, placebo"),
            ("found_overlap25_share", 0.1, INK2, "pārklāj ≥ 25 %, novērots"),
            ("found_overlap25_share", 0.3, "#e1e0d9", "pārklāj ≥ 25 %, placebo")]
    for col, dx, colr, lab in bars:
        if "novērots" in lab:
            a1.bar(x + dx, s[col], 0.2, color=colr, label=lab)
        else:
            q = [plac[f"{col}_{o}"] for o in labs]
            m = np.array([v.mean() for v in q])
            a1.bar(x + dx, m, 0.2, color=colr, edgecolor=AXIS, label=lab)
            a1.errorbar(x + dx, m, yerr=[m - [v.quantile(0.025) for v in q], [v.quantile(0.975) for v in q] - m],
                        fmt="none", ecolor=INK2, lw=1)
    a1.set_xticks(x, [{"-1": "r−1", "0": "r", "1": "r+1"}.get(l, "r−1..r+1") for l in labs])
    a1.set_ylabel("atrasto poligonu daļa")
    a1.set_title("LVM 620 ≥ 0,5 ha: atrasti pret placebo (95 %)", loc="left")
    a1.legend(fontsize=6.5)
    g = summary[(summary["size"] == ">= 0,5 ha") & (summary["offset"] == "r-1..r+1")].set_index("group")
    names = {"620": "620", "100": "vējgāzes", "other": "citi"}
    gi = [k for k in names if k in g.index]
    xi = np.arange(len(gi))
    a2.bar(xi - 0.2, [g.loc[k, "by_cut_n"] / g.loc[k, "n"] for k in gi], 0.4, color=INK2, label="atzīmēts kā cut")
    a2.bar(xi + 0.2, [g.loc[k, "by_stress_n"] / g.loc[k, "n"] for k in gi], 0.4, color="#d03b3b", label="atzīmēts kā stress")
    a2.set_xticks(xi, [f"{names[k]} (n={int(g.loc[k, 'n'])})" for k in gi])
    a2.set_ylabel("poligonu daļa (r−1..r+1)")
    a2.set_title("Ko s2forest atzīmē: cut vai stress", loc="left")
    a2.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def climate_point(name: str, ph: pd.DataFrame, wb: pd.DataFrame, years: tuple[int, int], path: Path,
                  check=None) -> Path:
    """Stage 4, one location: RITY-2 swarming / infestation DOY, filial generations, water balance
    anomaly. `ph`: one row per year (main + sensitivity columns), `wb`: seasonal table with cwb_z."""
    fig, axes = plt.subplots(3, 1, figsize=(8, 8.4), dpi=200)
    ax = axes[0]
    ax.plot(ph["year"], ph["swarming_doy"], "o-", color=S1, label="RITY-2 izlidošana (10)")
    ax.plot(ph["year"], ph["infestation_doy"], "s--", color=S1, alpha=0.6, ms=4, label="RITY-2 invāzija (11)")
    ax.plot(ph["year"], ph["phenips_clim_swarming_doy"], "^", color=S2,
            label="PHENIPS-Clim sliekšņi (apakšējā robeža)")
    if check is not None:
        ax.plot([check.year], [check.timetuple().tm_yday], "*", color=INK, ms=12,
                label=f"Silava: aktīva izlidošana {check:%d.%m.%Y}")
    ax.set_ylabel("gada diena (DOY)")
    ax.set_title(f"{name}: pavasara izlidošana (ERA5, RITY-2)")
    ax.legend(fontsize=7, loc="upper right")
    ax = axes[1]
    w = 0.25
    for k, (col, lab, colr) in enumerate((("n_filial_MIN", "MIN", S3), ("n_filial", "AVG (galvenais)", S1),
                                         ("n_filial_MAX", "MAX", S2))):
        ax.bar(ph["year"] + (k - 1) * w, ph[col], width=w, color=colr, label=lab)
    ax.plot(ph["year"], ph["n_filial_inca"], "k_", ms=12, mew=2, label="AVG ar INCA korekcijām (1)–(3)")
    ax.set_ylabel("paaudzes (F1–F3, Tsum ≥ 0,6)")
    ax.set_yticks([0, 1, 2, 3])
    ax.set_ylim(0, 3.9)
    ax.set_title("Pilnas paaudzes līdz 31. oktobrim")
    ax.legend(fontsize=7, ncol=4, loc="upper left")
    ax = axes[2]
    z = wb.dropna(subset=["cwb_z"])
    inside = (z["year"] >= years[0]) & (z["year"] <= years[1])
    ax.bar(z["year"], z["cwb_z"], color=np.where(inside, S2, AXIS), width=0.8)
    ax.axhline(0, color=INK2, lw=0.8)
    ax.set_ylabel("z (pret 1991–2020)")
    ax.set_title("Standartizēta klimatiskās ūdens bilances anomālija, P − ET0 IV–IX")
    for a in axes[:2]:
        a.set_xticks(ph["year"])
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def climate_maps(country, cells: pd.DataFrame, col: str, years: list[int], title: str, path: Path,
                 cmap="viridis", vmin=None, vmax=None, discrete: list | None = None, step: float = 0.25,
                 ncol: int = 3, marked: tuple = ()) -> Path:
    """Stage 4: one small map per year of a grid value (cells of `step` deg around lon / lat, EPSG:4326);
    years in `marked` get a `*` (incomplete)."""
    from matplotlib.collections import PatchCollection
    from matplotlib.colors import BoundaryNorm, ListedColormap
    from matplotlib.patches import Rectangle

    n = len(years)
    nrow = int(np.ceil(n / ncol))
    # panel ~3.0 x 2.15 in (Latvia extent 8 x 2.9 deg at 57 N); constrained layout, room at the bottom for the note
    fig, axes = plt.subplots(nrow, ncol, figsize=(3.0 * ncol + 0.9, 2.15 * nrow + 0.5), dpi=200, squeeze=False,
                             layout="constrained")
    fig.get_layout_engine().set(rect=(0, 0.035 * 3 / max(nrow, 3), 1, 1 - 0.035 * 3 / max(nrow, 3)), w_pad=0.02, h_pad=0.02)
    if discrete is not None:
        cm = ListedColormap([plt.get_cmap(cmap)(i / max(len(discrete) - 1, 1)) for i in range(len(discrete))])
        norm = BoundaryNorm(np.arange(len(discrete) + 1) - 0.5 + discrete[0], cm.N)
    else:
        cm = plt.get_cmap(cmap)
        norm = plt.Normalize(vmin if vmin is not None else cells[col].min(), vmax if vmax is not None else cells[col].max())
    for ax, y in zip(axes.flat, years):
        d = cells[cells["year"] == y]
        v = d[col].to_numpy(dtype=float)
        rects = [Rectangle((lo - step / 2, la - step / 2), step, step) for lo, la in zip(d["lon"], d["lat"])]
        ax.add_collection(PatchCollection(rects, lw=0, facecolors=[cm(norm(x)) if np.isfinite(x) else "#ffffff"
                                                                   for x in v]))
        country.boundary.plot(ax=ax, color=INK, lw=0.5)
        ax.set_xlabel("")
        ax.set_ylabel("")
        ax.set_xlim(20.6, 28.6)
        ax.set_ylim(55.4, 58.3)
        ax.set_aspect(1 / np.cos(np.radians(57)))
        ax.set_title(f"{y}*" if y in marked else str(y))
        ax.set_xticks([])
        ax.set_yticks([])
        ax.grid(False)
        for sp in ax.spines.values():
            sp.set_visible(False)
    for ax in list(axes.flat)[n:]:
        ax.axis("off")
    sm = plt.cm.ScalarMappable(norm=norm, cmap=cm)
    cb = fig.colorbar(sm, ax=axes, shrink=0.6, location="right")
    if discrete is not None:
        cb.set_ticks(discrete)
    fig.suptitle(title, fontweight="bold")
    note = "Robežas: © EuroGeographics for the administrative boundaries (GISCO NUTS 2024)"
    if any(y in marked for y in years):
        note += "; * nepilns gads"
    fig.text(0.01, 0.005, note, fontsize=7, color=INK2, va="bottom")
    fig.savefig(path, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)
    return path


# --- drought comparison (after stage 4) ------------------------------------------------------------------------------

DRY, WET = "#c4452f", "#2a78d6"          # diverging pair for the water balance anomaly (dry / wet)
EVENT_YEARS = (2018, 2023)


def _events(ax, years=EVENT_YEARS):
    for y in years:
        ax.axvspan(y - 0.5, y + 0.5, color=GRID, alpha=0.7, lw=0, zorder=0)


def drought_series(nat: pd.DataFrame, damage: dict, storms, path: Path) -> Path:
    """Annual series in one figure: drought on top (cwb_z bars, RITY-2 Tsum), damage below (one unit per panel)."""
    panels = [("CSP MEB012: izcirstais apjoms, tūkst. m³ (visi īpašnieki)",
               [("CSP MEB012 stumbra kaitēkļi, izcirsts tūkst. m3", S2, "stumbra kaitēkļi"),
                ("CSP MEB012 vējgāzes (kontrole), izcirsts tūkst. m3", INK2, "vējgāzes, snieglauzes (kontrole)")]),
              ("LVM 620 (stumbra kaitēkļi), ha pēc reģistrācijas gada", [("LVM 620, ha", S2, None)]),
              ("EFDA v3.0 klase 1 (vējš / mizgrauži, nav tīra mizgraužu etiķete), ha", [("EFDA v3.0 klase 1, ha", S3, None)]),
              ("EFDA v3.0 klase 3 (cirte), ha", [("EFDA v3.0 klase 3 (cirte), ha", INK2, None)])]
    fig, axes = plt.subplots(2 + len(panels), 1, figsize=(9, 2.0 * (2 + len(panels))), dpi=200, sharex=True,
                             layout="constrained")
    ax = axes[0]
    z = nat["cwb_z"].dropna()
    ax.bar(z.index, z.values, width=0.75, color=[DRY if v < 0 else WET for v in z.values], lw=0)
    ax.axhline(0, color=AXIS, lw=0.8)
    ax.set_title("Ūdens bilances anomālija z (P − ET0, IV–IX, Latvijas vidējais; bāze 1991–2020; < 0 = sausāks)",
                 loc="left")
    ax = axes[1]
    for col, c, lab in (("tsum_F1", S2, "Tsum_F1"), ("tsum_F2", S1, "Tsum_F2")):
        s = nat[col].dropna()
        ax.plot(s.index, s.values, color=c, marker="o", ms=3, label=lab)
        ax.annotate(lab, (s.index[-1], s.values[-1]), xytext=(4, 0), textcoords="offset points", fontsize=7,
                    color=INK2, va="center")
    ax.set_title("RITY-2 relatīvā termālā summa (AVG, Latvijas vidējais; tikai 2018–2026, 2026* līdz 27.10)",
                 loc="left")
    ax.legend(loc="upper left", fontsize=7, ncol=2)
    for ax, (title, series) in zip(axes[2:], panels):
        for key, c, lab in series:
            s = damage[key].dropna()
            ax.plot(s.index, s.values, color=c, marker="o", ms=3, label=lab, ls="-" if c != INK2 or lab is None else "--")
        if any(lab for _, _, lab in series):
            ax.legend(loc="upper left", fontsize=7)
        ax.set_title(title, loc="left")
        ax.set_ylim(0, None)
    _storms(axes[4], storms)
    for ax in axes:
        _events(ax)
    for y in EVENT_YEARS:
        axes[-1].annotate(str(y), (y, 0.03), xycoords=("data", "axes fraction"), ha="center", va="bottom", fontsize=7,
                          color=INK2)
    axes[-1].set_xlim(1984.5, 2026.5)
    fig.savefig(path)
    plt.close(fig)
    return path


def drought_regions(feat: pd.DataFrame, dens: pd.DataFrame, years: tuple[int, int], path: Path) -> Path:
    """Per NUTS 2024 region: water balance anomaly (top row) and LVM 620 ha per 1000 ha LVM land (bottom row)."""
    regs = sorted(dens["region"].unique())
    fig, axes = plt.subplots(2, len(regs), figsize=(2.2 * len(regs), 4.6), dpi=200, sharex=True, sharey="row",
                             layout="constrained")
    fig.get_layout_engine().set(rect=(0, 0.05, 1, 0.95))
    top = float(dens["lvm_620_ha_per_1000ha"].max()) * 1.05
    for j, r in enumerate(regs):
        f = feat[(feat["region"] == r) & feat["year"].between(years[0] - 2, years[1])]
        ax = axes[0, j]
        ax.bar(f["year"], f["cwb_z"], width=0.75, color=[DRY if v < 0 else WET for v in f["cwb_z"]], lw=0)
        ax.axhline(0, color=AXIS, lw=0.8)
        ax.set_title(r, loc="left")
        g = dens[dens["region"] == r]
        ax = axes[1, j]
        ax.plot(g["year"], g["lvm_620_ha_per_1000ha"], color=S2, marker="o", ms=3)
        ax.set_ylim(0, top)
        for a in axes[:, j]:
            _events(a)
            a.set_xticks([years[0] - 2, 2018, 2023])
    axes[0, 0].set_ylabel("cwb_z")
    axes[1, 0].set_ylabel("LVM 620, ha / 1000 ha")
    fig.suptitle("Reģioni (NUTS 2024): ūdens bilances anomālija un LVM 620 bojājumu blīvums", fontweight="bold")
    fig.text(0.01, 0.005, "Reģionu robežas: © EuroGeographics for the administrative boundaries (GISCO NUTS 2024)",
             fontsize=6, color=INK2, va="bottom")
    fig.savefig(path, bbox_inches="tight", pad_inches=0.08)
    plt.close(fig)
    return path


# --- stage 6a pilot -------------------------------------------------------------------------------------------------

def pilot_overview(py: pd.DataFrame, path: Path) -> Path:
    """Positives (LVM 620 cells) per year in the pilot block and their share of the training cells."""
    fig, axes = plt.subplots(2, 1, figsize=(8, 4.6), dpi=200, sharex=True, layout="constrained")
    axes[0].bar(py["year"], py["positives"], color=S2, width=0.7, lw=0)
    axes[0].set_title("Pozitīvās šūnas (LVM 620 pēc reģistrācijas gada), skaits", loc="left")
    axes[1].bar(py["year"], py["share_pos"] * 100, color=S2, width=0.7, lw=0)
    axes[1].set_title("Pozitīvo daļa apmācības kopā, %", loc="left")
    axes[1].set_xticks(py["year"])
    fig.savefig(path)
    plt.close(fig)
    return path


def pilot_features(tab: pd.DataFrame, feats: list[tuple[str, str, bool]], path: Path) -> Path:
    """ECDF of each feature: positives vs other training cells (no model). feats: (column, title, log x)."""
    d = tab[tab["in_set"] == 1]
    n = len(feats)
    ncol = 4
    nrow = int(np.ceil(n / ncol))
    fig, axes = plt.subplots(nrow, ncol, figsize=(11, 2.4 * nrow), dpi=200, layout="constrained", squeeze=False)
    for ax, (c, title, logx) in zip(axes.flat, feats):
        for lab, col, name in ((0, INK2, "pārējās"), (1, S2, "pozitīvās")):
            x = np.sort(d.loc[d["label"] == lab, c].dropna().to_numpy())
            if len(x):
                ax.plot(x, np.arange(1, len(x) + 1) / len(x), color=col, lw=1.6, label=f"{name} (n={len(x):,})")
        if logx:
            ax.set_xscale("symlog", linthresh=1)
        ax.set_title(title, loc="left", fontsize=8)
        ax.set_ylim(0, 1)
        ax.legend(fontsize=6, loc="best")
    for ax in list(axes.flat)[n:]:
        ax.axis("off")
    fig.suptitle("Pilota bloks: pazīmju sadalījums (ECDF), pozitīvās pret pārējām šūnām, 2013–2024", fontweight="bold")
    fig.savefig(path)
    plt.close(fig)
    return path


MODEL_STYLE = {"random": ("nejaušs", "#9a9890", ":"), "dist_t1": ("tikai 620 t−1 attālums", INK2, "--"),
               "dist_t23": ("tikai 620 t−2..t−3 (L3)", "#a3a29a", "-."), "A": ("A spiediens", S1, "-"),
               "A_mono": ("A monotons (jutīgums)", "#86b6ef", "--"),
               "B": ("B + audze", S3, "-"), "B_chm": ("B + CHMv2", "#8a5cd1", "-"), "C": ("C + klimats", S2, "-")}


def model_metrics(met: pd.DataFrame, path: Path, title_suffix: str = "") -> Path:
    """Per test year: PR-AUC / share of positives, hit share in the top 5 % and 10 % of the area; all cells (top row)
    and new foci (bottom row); 95 % cluster-bootstrap CI as error bars."""
    panels = [("ap_ratio", "PR-AUC / pozitīvo daļa (1 = nejaušs)"), ("hit5", "Trāpījumi augšējos 5 % platības, %"),
              ("hit10", "Trāpījumi augšējos 10 % platības, %")]
    subs = [("visi", "VISAS ŠŪNAS"), ("jaunie", "JAUNIE PERĒKĻI\n(> 500 m no 620 t−1)")]
    models = [m for m in MODEL_STYLE if m in set(met["model"])]
    fig, axes = plt.subplots(2, 3, figsize=(11, 6.4), dpi=200, layout="constrained", sharex=True)
    off = np.linspace(-0.3, 0.3, len(models))
    for i, (sub, sname) in enumerate(subs):
        for j, (col, ptitle) in enumerate(panels):
            ax = axes[i, j]
            k = 100 if col.startswith("hit") else 1
            gs = met[met["subset"] == sub]
            # y range from the point estimates; a CI longer than that (few tiles -> very wide) is cut and marked ^
            pt = float(np.nanmax(gs[col].to_numpy())) * k if gs[col].notna().any() else 1.0
            cap = min(float(np.nanmax(gs[f"{col}_hi"].to_numpy())) * k, pt * 1.6) if gs[f"{col}_hi"].notna().any() else pt
            cut = False
            for o, m in zip(off, models):
                g = gs[gs["model"] == m].sort_values("year")
                if g.empty:
                    continue
                lab, c, ls = MODEL_STYLE[m]
                yv, lo, hi = g[col] * k, g[f"{col}_lo"] * k, g[f"{col}_hi"] * k
                hic = hi.clip(upper=cap)
                ax.errorbar(g["year"] + o, yv, yerr=[(yv - lo).clip(lower=0), (hic - yv).clip(lower=0)], color=c, ls=ls,
                            lw=1.3, marker="o", ms=3.5, elinewidth=0.8, capsize=0, label=lab)
                over = (hi > cap).to_numpy()
                if over.any():
                    cut = True
                    ax.plot((g["year"] + o).to_numpy()[over], np.full(over.sum(), cap), "^", ms=3.5, color=c, lw=0)
            if col == "ap_ratio":
                ax.axhline(1, color=INK2, lw=0.8, ls=":", zorder=0)
            ax.set_ylim(0, cap * 1.05 if cap > 0 else 1)
            if cut:
                ax.text(0.99, 0.98, "▲ TI augšējā robeža ārpus ass", transform=ax.transAxes, ha="right", va="top",
                        fontsize=6, color=INK2)
            if i == 0:
                ax.set_title(ptitle, loc="left", fontsize=8)
            if j == 0:
                ax.set_ylabel(sname, fontsize=8, fontweight="bold")
            ax.set_xticks(sorted(met["year"].unique()))
    h, lab = axes[0, 0].get_legend_handles_labels()
    fig.legend(h, lab, loc="outside lower center", ncol=len(lab), fontsize=7, frameon=False)
    fig.suptitle("7a pilots: tests gadā t, apmācība ≤ t−1" + title_suffix + "; 95 % TI — bootstrap pa ~5 km blokiem",
                 fontsize=10, x=0.01, ha="left")
    fig.savefig(path)
    plt.close(fig)
    return path


def model_importance(pm: pd.DataFrame, path: Path) -> Path:
    """Permutation importance (drop in average precision on the test year) of model C: bar = mean over test years,
    dots = single years; all cells and new foci."""
    subs = [("visi", "visas šūnas"), ("jaunie", "jaunie perēkļi")]
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.2), dpi=200, layout="constrained", sharey=True)
    order = pm[pm["subset"] == "visi"].groupby("feature")["importance_mean"].mean().sort_values().index.tolist()
    for ax, (sub, sname) in zip(axes, subs):
        g = pm[pm["subset"] == sub]
        mean = g.groupby("feature")["importance_mean"].mean().reindex(order)
        ax.barh(range(len(order)), mean.to_numpy(), color=S2, height=0.6, lw=0)
        for k, f in enumerate(order):
            v = g.loc[g["feature"] == f, "importance_mean"].to_numpy()
            ax.plot(v, np.full(len(v), k), "o", ms=2.5, color=INK, alpha=0.6, lw=0)
        ax.axvline(0, color=AXIS, lw=0.8)
        ax.set_yticks(range(len(order)), order, fontsize=7)
        ax.set_title(f"C modelis: PR-AUC kritums, permutējot pazīmi — {sname}", loc="left", fontsize=8)
        ax.set_xlabel("PR-AUC kritums (stabiņš: vidēji 2020–2024; punkti: gadi)", fontsize=7)
    fig.savefig(path)
    plt.close(fig)
    return path
