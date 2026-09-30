"""Static figures (PNG) for diagnostics, maps and the report."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import xarray as xr  # noqa: E402

# Validated categorical palette (fixed order) and neutral inks.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e4e3df"
SURFACE = "#fcfcfb"
MUTED = "#b9b8b3"
FIG_DPI = 200  # figures are reused in the grant application and slides

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": MUTED, "axes.labelcolor": INK_2, "xtick.color": INK_2, "ytick.color": INK_2,
    "axes.titlecolor": INK, "axes.titlesize": 11, "axes.labelsize": 9,
    "xtick.labelsize": 8, "ytick.labelsize": 8, "legend.fontsize": 8, "legend.frameon": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.spines.top": False, "axes.spines.right": False, "font.size": 9,
})


def _concise_dates(ax) -> None:
    loc = matplotlib.dates.AutoDateLocator(minticks=3, maxticks=7)
    ax.xaxis.set_major_locator(loc)
    ax.xaxis.set_major_formatter(matplotlib.dates.ConciseDateFormatter(loc))


def _save(fig, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=FIG_DPI, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_valid_observations(table: pd.DataFrame, threshold: float, path: Path) -> Path:
    """Small multiples per year: clear-sky fraction over the AOI for every overpass."""
    t = table[table["status"].isin(["accepted", "rejected"])].copy()
    t["year"] = t["datetime"].dt.year
    t["doy_date"] = pd.to_datetime("2001-" + t["datetime"].dt.strftime("%m-%d"))
    years = sorted(t["year"].unique())
    fig, axes = plt.subplots(len(years), 1, figsize=(8, 1.6 * len(years) + 0.6), sharex=True,
                             squeeze=False)
    for ax, year in zip(axes[:, 0], years):
        d = t[t["year"] == year]
        acc = d[d["status"] == "accepted"]
        rej = d[d["status"] == "rejected"]
        ax.vlines(rej["doy_date"], 0, rej["valid_fraction"], color=MUTED, lw=2)
        ax.vlines(acc["doy_date"], 0, acc["valid_fraction"], color=SERIES[0], lw=2)
        ax.axhline(threshold, color=INK_2, lw=0.8, ls="--")
        ax.set_ylim(0, 1.05)
        ax.set_yticks([0, 0.5, 1])
        ax.text(0.005, 0.97, f"{year}: {len(acc)} derīgi / {len(d)} pārlidojumi",
                transform=ax.transAxes, va="top", color=INK, fontsize=8.5)
    axes[-1, 0].xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%d.%m"))
    axes[0, 0].set_title("Skaidro pikseļu daļa AOI katrā pārlidojumā "
                         "(zils = pieņemts, pelēks = atmests, svītra = slieksnis)", loc="left")
    fig.supylabel("derīgā daļa", color=INK_2, fontsize=9)
    return _save(fig, path)


def rgb_image(ds: xr.Dataset, t: int, gain: float = 3.5) -> np.ndarray:
    rgb = np.stack([ds[b].isel(time=t).values for b in ("B04", "B03", "B02")], axis=-1)
    rgb = np.clip(rgb * gain, 0, 1)
    rgb = np.where(np.isnan(rgb), 0.85, rgb)  # masked -> light grey
    return rgb


def plot_quicklooks(cube: xr.Dataset, aoi_outline, path: Path, max_panels: int = 12) -> Path:
    """RGB of the clearest acquisition per month (masked pixels shown light grey)."""
    df = pd.DataFrame({"time": pd.to_datetime(cube.time.values), "vf": cube.valid_fraction.values,
                       "i": np.arange(cube.sizes["time"])})
    df["month"] = df["time"].dt.to_period("M")
    pick = df.loc[df.groupby("month")["vf"].idxmax()].sort_values("time").tail(max_panels)
    n = len(pick)
    ncol = min(4, n)
    nrow = int(np.ceil(n / ncol))
    fig, axes = plt.subplots(nrow, ncol, figsize=(3 * ncol, 3 * nrow), squeeze=False)
    extent = [float(cube.x.min()) - 5, float(cube.x.max()) + 5, float(cube.y.min()) - 5,
              float(cube.y.max()) + 5]
    for ax in axes.ravel():
        ax.axis("off")
    for ax, (_, row) in zip(axes.ravel(), pick.iterrows()):
        ax.imshow(rgb_image(cube, int(row["i"])), extent=extent, interpolation="nearest")
        if aoi_outline is not None:
            aoi_outline.boundary.plot(ax=ax, color="#ffffff", lw=1.2)
            aoi_outline.boundary.plot(ax=ax, color=INK, lw=0.6)
        src = cube.source.values[int(row["i"])]
        ax.set_title(f"{row['time']:%Y-%m-%d}  {row['vf']:.0%}  ({src})", fontsize=8)
    fig.suptitle("Skaidrākā aina katrā mēnesī (pelēks = maskēts)", color=INK, fontsize=11,
                 x=0.01, ha="left")
    return _save(fig, path)


def plot_harmonization_check(series: pd.DataFrame, path: Path) -> Path:
    """Median reflectance of conifer-forest pixels per acquisition, per band, by source.

    If the baseline 04.00 offset were handled wrongly, one group of years/sources
    would sit ~0.1 above the others - most visible in the dark red band.
    """
    bands = [b for b in ("B04", "B08", "B11") if b in series]
    sources = sorted(series["source"].unique())
    fig, axes = plt.subplots(len(bands), 1, figsize=(8, 2.1 * len(bands) + 0.5), sharex=True,
                             squeeze=False)
    names = {"B04": "B04 sarkanais", "B08": "B08 NIR", "B11": "B11 SWIR1"}
    for ax, b in zip(axes[:, 0], bands):
        for k, s in enumerate(sources):
            d = series[series["source"] == s]
            ax.plot(d["time"], d[b], "o", ms=4, color=SERIES[k], label=s, mec=SURFACE, mew=0.8)
        ax.set_ylabel(names[b])
    axes[0, 0].legend(loc="upper right", ncol=len(sources))
    axes[0, 0].set_title("Harmonizācijas pārbaude: skujkoku meža pikseļu mediānā atstarošanās",
                         loc="left")
    return _save(fig, path)


# Sequential (single hue, light -> dark) and diverging (blue <-> grey <-> red) ramps.
SEQ = matplotlib.colors.LinearSegmentedColormap.from_list(
    "seq_blue", ["#cde2fb", "#86b6ef", "#3987e5", "#256abf", "#184f95", "#0d366b"])
DIV = matplotlib.colors.LinearSegmentedColormap.from_list(
    "div_blue_red", ["#184f95", "#6da7ec", "#f0efec", "#ec8a89", "#b8302f"])
FOREST_COLORS = {1: ("#1c5cab", "analizēts mežs"), 2: ("#eda100", "zems vasaras NDVI (cirte/jaunaudze)"),
                 3: ("#b9b8b3", "nav vasaras novērojumu"), 4: ("#e34948", "ceļa buferis (OSM)"),
                 5: ("#e87ba4", "liela sezonālā amplitūda (nav slēgta skujkoku audze)"),
                 0: ("#f0efec", "nav HRL skujkoku klasē")}


def plot_haze_diagnostics(df: pd.DataFrame, path: Path) -> Path:
    """Per date: share of SCL-valid AOI pixels masked by the haze test."""
    d = df.copy()
    d["time"] = pd.to_datetime(d["time"])
    d["year"] = d["time"].dt.year
    d["doy_date"] = pd.to_datetime("2001-" + d["time"].dt.strftime("%m-%d"))
    years = sorted(d["year"].unique())
    fig, axes = plt.subplots(len(years), 1, figsize=(8, 1.5 * len(years) + 0.7), sharex=True,
                             squeeze=False)
    for ax, year in zip(axes[:, 0], years):
        y = d[d["year"] == year]
        ax.vlines(y["doy_date"], 0, y["masked_frac"], color=SERIES[1], lw=3, label="maskēts (īslaicīgs)")
        u = y[y["unresolved_frac"] > 0]
        ax.plot(u["doy_date"], u["unresolved_frac"], "o", ms=5, color=SERIES[3], mec=SURFACE,
                label="neizšķirts (sezonas pēdējais, saglabāts)")
        for _, r in y[y["dropped"]].iterrows():
            ax.text(r["doy_date"], min(r["masked_frac"] + 0.05, 0.95), "atmesta", fontsize=7,
                    color=INK_2, ha="center")
        ax.set_ylim(0, 1)
        ax.set_yticks([0, 0.5, 1])
        ax.text(0.005, 0.95, str(year), transform=ax.transAxes, va="top", fontsize=8.5, color=INK)
    axes[0, 0].legend(loc="upper right", ncol=2)
    axes[-1, 0].xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%d.%m"))
    axes[0, 0].set_title("Dūmakas tests: nomaskētā daļa no SCL-derīgajiem AOI pikseļiem", loc="left")
    return _save(fig, path)


def _extent(template: xr.DataArray) -> list[float]:
    x, y = template.x.values, template.y.values
    r = abs(float(x[1] - x[0])) / 2
    return [float(x.min()) - r, float(x.max()) + r, float(y.min()) - r, float(y.max()) + r]


def plot_forest_mask(codes: np.ndarray, template: xr.DataArray, path: Path) -> Path:
    rgb = np.ones(codes.shape + (3,))
    for code, (hexcol, _) in FOREST_COLORS.items():
        rgb[codes == code] = matplotlib.colors.to_rgb(hexcol)
    fig, ax = plt.subplots(figsize=(6.5, 6))
    ax.imshow(rgb, extent=_extent(template), interpolation="nearest")
    handles = [matplotlib.patches.Patch(color=c, label=f"{lab} ({np.mean(codes[codes != 255] == k):.0%})")
               for k, (c, lab) in FOREST_COLORS.items()]
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.06), ncol=2)
    ax.set_title("Analīzes meža maska (HRL DLT 2018 + bāzes perioda vasaras NDVI)", loc="left")
    ax.grid(False)
    ax.ticklabel_format(style="plain")
    return _save(fig, path)


def plot_index_change_maps(maps: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]],
                           template: xr.DataArray, mask: np.ndarray, base_label: str,
                           mon_label: str, path: Path) -> Path:
    """Rows = indices; columns = baseline summer median, monitoring summer median,
    change oriented so that red = towards stress for every index."""
    n = len(maps)
    fig, axes = plt.subplots(n, 3, figsize=(11, 3.3 * n), squeeze=False)
    ext = _extent(template)
    for row, (name, (base, mon, chg)) in enumerate(maps.items()):
        vals = np.concatenate([base[mask], mon[mask]])
        vals = vals[np.isfinite(vals)]
        lo, hi = (np.percentile(vals, [2, 98]) if vals.size else (0, 1))
        for col, (arr, title) in enumerate([(base, f"{name.upper()} vasara, {base_label}"),
                                           (mon, f"{name.upper()} vasara, {mon_label}")]):
            ax = axes[row, col]
            im = ax.imshow(np.where(mask, arr, np.nan), cmap=SEQ, vmin=lo, vmax=hi, extent=ext,
                           interpolation="nearest")
            ax.set_title(title, loc="left", fontsize=9)
            fig.colorbar(im, ax=ax, fraction=0.046, pad=0.02)
        c = chg[mask]
        c = c[np.isfinite(c)]
        lim = float(np.percentile(np.abs(c), 98)) if c.size else 0.1
        ax = axes[row, 2]
        im = ax.imshow(np.where(mask, chg, np.nan), cmap=DIV, vmin=-lim, vmax=lim, extent=ext,
                       interpolation="nearest")
        ax.set_title(f"izmaiņa stresa virzienā (sarkans = stress)", loc="left", fontsize=9)
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.02)
        for ax in axes[row]:
            ax.set_xticks([])
            ax.set_yticks([])
            ax.grid(False)
    fig.suptitle("Indeksu vasaras mediānas (tikai analizētais mežs; balts = izslēgts)",
                 x=0.01, ha="left", color=INK, fontsize=11)
    return _save(fig, path)


TYPE_COLORS = {"stress": (SERIES[1], "stress (aizdomīgs)"), "cut": (SERIES[0], "cirte")}


def plot_suspects_map(cube: xr.Dataset, polygons, aoi_outline, year: int, path: Path,
                      label_top: int = 15) -> Path:
    """Suspect polygons over the clearest late-season RGB of the monitoring year."""
    t = pd.DatetimeIndex(cube.time.values)
    cand = np.flatnonzero((t.year == year) & (t.month >= 7))
    if cand.size == 0:
        cand = np.flatnonzero(t.year == year)
    i = int(cand[np.argmax(cube.valid_fraction.values[cand])])
    template = cube.B04.isel(time=0, drop=True)
    fig, ax = plt.subplots(figsize=(8.5, 8.5))
    ax.imshow(rgb_image(cube, i, gain=3.2), extent=_extent(template), interpolation="nearest")
    if aoi_outline is not None:
        aoi_outline.boundary.plot(ax=ax, color="#ffffff", lw=1.0)
    handles = []
    for typ, (col, lab) in TYPE_COLORS.items():
        sub = polygons[polygons["type"] == typ] if len(polygons) else polygons
        if len(sub):
            sub.boundary.plot(ax=ax, color="#ffffff", lw=2.2)
            sub.boundary.plot(ax=ax, color=col, lw=1.3)
        handles.append(matplotlib.lines.Line2D([], [], color=col, lw=2,
                                               label=f"{lab}: {len(sub)} ({sub.area.sum() / 1e4:.1f} ha)"))
    for _, r in polygons.head(label_top).iterrows():
        c = r.geometry.representative_point()
        ax.annotate(str(r["id"]), (c.x, c.y), xytext=(4, 4), textcoords="offset points",
                    fontsize=7.5, color=INK, bbox=dict(boxstyle="round,pad=0.15", fc="#ffffff",
                                                       ec="none", alpha=0.85))
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.04), ncol=2)
    ax.set_title(f"Aizdomīgās vietas {year} (fons: {t[i]:%Y-%m-%d}; numuri = id pēc ticamības)",
                 loc="left")
    ax.set_xlabel("")
    ax.set_ylabel("")
    ax.set_xticks([])
    ax.set_yticks([])
    ax.grid(False)
    return _save(fig, path)


def plot_regional_offsets(offsets: pd.DataFrame, names: list[str], path: Path) -> Path:
    d = offsets.copy()
    d["time"] = pd.to_datetime(d["time"])
    fig, axes = plt.subplots(len(names), 1, figsize=(8, 1.7 * len(names) + 0.6), sharex=True,
                             squeeze=False)
    for ax, n in zip(axes[:, 0], names):
        ax.axhline(0, color=MUTED, lw=0.8)
        ax.plot(d["time"], d[f"offset_{n}"], "o", ms=4, color=SERIES[0], mec=SURFACE)
        skipped = d[~d["normalized"]]
        ax.plot(skipped["time"], np.zeros(len(skipped)), "x", ms=5, color=INK_2)
        ax.set_ylabel(n.upper())
    axes[0, 0].set_title("Reģionālā nobīde katrā datumā (AOI + buferis, mežs; × = nav normalizēts)",
                         loc="left")
    return _save(fig, path)


def plot_polygon_chips(cube: xr.Dataset, indices: xr.Dataset, polygons, year: int, path: Path,
                       n: int = 8, pad_m: float = 150.0, index: str = "crswir") -> Path:
    """For the top-n polygons: RGB before (last clear date of the previous year),
    RGB in the monitoring year, and the polygon's median index time series."""
    t = pd.DatetimeIndex(cube.time.values)
    vf = cube.valid_fraction.values
    prev = np.flatnonzero((t.year == year - 1) & (t.month >= 7))
    cur = np.flatnonzero((t.year == year) & (t.month >= 7))
    i0 = int(prev[np.argmax(vf[prev] + prev * 1e-6)]) if prev.size else 0
    i1 = int(cur[np.argmax(vf[cur] + cur * 1e-6)]) if cur.size else len(t) - 1
    rows = polygons.head(n)
    fig, axes = plt.subplots(len(rows), 3, figsize=(11, 2.9 * len(rows)),
                             gridspec_kw={"width_ratios": [1, 1, 2.2]}, squeeze=False)
    from rasterio.features import geometry_mask as _gm
    from rasterio.transform import from_origin

    x, y = cube.x.values, cube.y.values
    res = float(abs(x[1] - x[0]))
    tr = from_origin(float(x[0]) - res / 2, float(y[0]) + res / 2, res, res)
    idx = indices[index]
    for r, (_, poly) in enumerate(rows.iterrows()):
        minx, miny, maxx, maxy = poly.geometry.buffer(pad_m).bounds
        sub = cube.sel(x=slice(minx, maxx), y=slice(maxy, miny))
        ext = [float(sub.x.min()) - 5, float(sub.x.max()) + 5, float(sub.y.min()) - 5,
               float(sub.y.max()) + 5]
        for c, ti in enumerate((i0, i1)):
            ax = axes[r, c]
            ax.imshow(rgb_image(sub, ti, gain=3.2), extent=ext, interpolation="nearest")
            gpd_boundary = polygons.iloc[[r]].boundary
            gpd_boundary.plot(ax=ax, color="#ffffff", lw=2)
            gpd_boundary.plot(ax=ax, color=SERIES[1], lw=1)
            ax.set_title(f"#{poly['id']}  {t[ti]:%Y-%m-%d}", loc="left", fontsize=8)
            ax.set_xlim(ext[0], ext[1])
            ax.set_ylim(ext[2], ext[3])
            ax.set_xlabel("")
            ax.set_ylabel("")
            ax.set_xticks([])
            ax.set_yticks([])
            ax.grid(False)
        inside = ~_gm([poly.geometry], out_shape=(len(y), len(x)), transform=tr)
        ts = idx.where(xr.DataArray(inside, dims=("y", "x"))).median(("y", "x")).compute()
        ok = np.isfinite(ts.values)
        ax = axes[r, 2]
        ax.plot(t[ok], ts.values[ok], "-o", ms=3, lw=1, color=SERIES[0], mec=SURFACE)
        ax.axvline(pd.Timestamp(poly["first_detected"]), color=SERIES[1], lw=1.2, ls="--")
        _concise_dates(ax)
        ax.set_title(f"{index.upper()} mediāna poligonā; {poly['type']}, {poly['area_ha']:.2f} ha, "
                     f"ticamība {poly['confidence']:.2f}", loc="left", fontsize=8)
    fig.tight_layout()
    return _save(fig, path)


OUTCOME_LV = {"stress_before_cut": "stress pirms cirtes (TP)",
              "stress_on_or_after_cut": "stress cirtes dienā vai vēlāk",
              "cut_only": "noteikts tikai kā cirte", "missed": "nav noteikts"}


def plot_validation(refs, summary: pd.DataFrame, ts: pd.DataFrame, primary: str,
                    path: Path, max_series: int = 6) -> Path:
    inscope = refs[refs["scope"] == "in_scope"]
    counts = [int((inscope["outcome"] == o).sum()) for o in OUTCOME_LV]
    leads = inscope.loc[inscope["outcome"] == "stress_before_cut", "lead_days"].dropna()
    # most informative first: pre-cut stress, stress after cut, cut only, missed
    rank = {o: i for i, o in enumerate(OUTCOME_LV)}
    ids = list(inscope.assign(_r=inscope["outcome"].map(rank)).sort_values(["_r", "ref_id"])
               ["ref_id"][:max_series])
    nrow = 1 + int(np.ceil(len(ids) / 2))
    fig = plt.figure(figsize=(11, 3.0 * nrow))
    gs = fig.add_gridspec(nrow, 2)
    ax = fig.add_subplot(gs[0, 0])
    labels = list(OUTCOME_LV.values())
    ax.barh(labels[::-1], counts[::-1], color=SERIES[0], height=0.6)
    for yv, c in enumerate(counts[::-1]):
        ax.text(c, yv, f" {c}", va="center", fontsize=8, color=INK)
    ax.set_title(f"References darbības jomā: {len(inscope)} (ārpus: {len(refs) - len(inscope)})",
                 loc="left")
    ax.grid(axis="y", visible=False)
    ax = fig.add_subplot(gs[0, 1])
    row = summary.iloc[0]
    if len(leads) >= 8:
        ax.hist(leads, bins=min(12, len(leads)), color=SERIES[0], rwidth=0.9)
        ax.axvline(0, color=INK_2, lw=0.8)
        ax.set_xlabel("dienas pirms cirtes (pozitīvs = agrāk)")
    elif len(leads):
        # few values: show each reference as a labelled point
        lr = inscope.loc[leads.index]
        ys = np.arange(len(lr))
        ax.plot(lr["lead_days"], ys, "o", ms=8, color=SERIES[0], mec=SURFACE)
        for yv, (_, r) in zip(ys, lr.iterrows()):
            ax.annotate(f"{r['ref_id']}: {r['lead_days']:.0f} d", (r["lead_days"], yv),
                        xytext=(8, 0), textcoords="offset points", va="center", fontsize=8,
                        color=INK)
        ax.axvline(0, color=INK_2, lw=0.8)
        ax.set_yticks([])
        ax.set_ylim(-1, len(lr))
        ax.set_xlim(min(0, float(lr["lead_days"].min())) - 10, float(lr["lead_days"].max()) * 1.35 + 10)
        ax.set_xlabel("dienas pirms cirtes (pozitīvs = agrāk)")
    else:
        ax.text(0.5, 0.5, "Nav stresa noteikšanu pirms cirtes", ha="center", va="center",
                transform=ax.transAxes, color=INK_2)
        ax.set_xticks([])
        ax.set_yticks([])
    fmt = lambda v: "–" if pd.isna(v) else f"{v:.2f}"
    ax.set_title(f"Aizkave; precision {fmt(row['precision'])}, recall {fmt(row['recall'])}, "
                 f"F1 {fmt(row['f1'])}", loc="left")
    for k, rid in enumerate(ids):
        ax = fig.add_subplot(gs[1 + k // 2, k % 2])
        d = ts[ts["ref_id"] == rid] if len(ts) else ts
        r = inscope[inscope["ref_id"] == rid].iloc[0]
        if len(d):
            d = d.dropna(subset=[primary])
            dt = pd.to_datetime(d["date"])
            pre, post = d["phase"] == "pre_cut", d["phase"] == "post_cut"
            ax.plot(dt[pre], d.loc[pre, primary], "o", ms=3, color=SERIES[0], label="pirms cirtes")
            ax.plot(dt[post], d.loc[post, primary], "o", ms=3, color=SERIES[1], label="pēc cirtes")
        ax.axvline(pd.Timestamp(r["ref_date"]), color=INK, lw=1)
        if r["first_detected"] is not None:
            ax.axvline(pd.Timestamp(r["first_detected"]), color=SERIES[1], lw=1, ls="--")
        ax.set_title(f"{rid}: {OUTCOME_LV[r['outcome']]} (cirte {r['ref_date']})", loc="left",
                     fontsize=8.5)
        ax.set_ylabel(primary.upper())
        _concise_dates(ax)
        if k == 0:
            ax.legend(loc="upper left")
    fig.tight_layout()
    return _save(fig, path)


MONTHS_LV = {5: "maijs", 6: "jūnijs", 7: "jūlijs", 8: "augusts", 9: "septembris",
             4: "aprīlis", 10: "oktobris"}


def monthly_availability(table: pd.DataFrame, usable_times=None) -> pd.DataFrame:
    """Usable / all overpasses per year and month.

    `usable_times`: acquisition times actually used in the analysis (after the
    SCL and haze filters). If None, the SCL-based `accepted` status is used.
    """
    t = table[table["status"].isin(["accepted", "rejected", "failed"])].copy()
    t["datetime"] = pd.to_datetime(t["datetime"], utc=True)
    t["year"] = t["datetime"].dt.year
    t["month"] = t["datetime"].dt.month
    g = t.groupby(["year", "month"]).agg(total=("status", "size"),
                                         accepted=("status", lambda s: int((s == "accepted").sum())))
    g = g.reset_index()
    if usable_times is not None:
        u = pd.DatetimeIndex(usable_times)
        cnt = pd.Series(1, index=u).groupby([u.year, u.month]).sum()
        g["accepted"] = [int(cnt.get((y, m), 0)) for y, m in zip(g["year"], g["month"])]
    return g


def plot_monthly_availability(avail: pd.DataFrame, path: Path) -> Path:
    years = sorted(avail["year"].unique())
    months = sorted(avail["month"].unique())
    fig, axes = plt.subplots(1, len(years), figsize=(2.3 * len(years) + 0.6, 2.8), sharey=True,
                             squeeze=False)
    ymax = max(int(avail["accepted"].max()), 1)
    for ax, y in zip(axes[0], years):
        d = avail[avail["year"] == y].set_index("month").reindex(months, fill_value=0)
        xs = np.arange(len(months))
        ax.bar(xs, d["accepted"], color=SERIES[0], width=0.7)
        for x, (a, tot) in zip(xs, zip(d["accepted"], d["total"])):
            ax.text(x, a + 0.1, f"{a}/{tot}", ha="center", va="bottom", fontsize=7, color=INK_2)
        ax.set_xticks(xs, [MONTHS_LV.get(m, str(m))[:3] for m in months])
        ax.set_title(f"{y}: {int(d['accepted'].sum())} derīgi", loc="left", fontsize=9)
        ax.set_ylim(0, ymax + 1.5)
        ax.grid(axis="x", visible=False)
    axes[0, 0].set_ylabel("derīgi pārlidojumi")
    fig.suptitle("Datu pieejamība pa mēnešiem (derīgi / visi pārlidojumi virs AOI)", x=0.01,
                 ha="left", fontsize=10.5, color=INK)
    fig.tight_layout()
    return _save(fig, path)


def plot_overview_map(cube: xr.Dataset, polygons, missions, aoi_outline, year: int,
                      path: Path) -> Path:
    """RGB + cuts (filled) + stress polygons (outlined) + drone missions (dashed, labelled)."""
    t = pd.DatetimeIndex(cube.time.values)
    cand = np.flatnonzero((t.year == year) & (t.month >= 6))
    if cand.size == 0:
        cand = np.flatnonzero(t.year == year)
    i = int(cand[np.argmax(cube.valid_fraction.values[cand])])
    template = cube.B04.isel(time=0, drop=True)
    fig, ax = plt.subplots(figsize=(9, 9))
    ax.imshow(rgb_image(cube, i, gain=3.2), extent=_extent(template), interpolation="nearest")
    if aoi_outline is not None:
        aoi_outline.boundary.plot(ax=ax, color="#ffffff", lw=0.8)
    handles = []
    cuts = polygons[polygons["type"] == "cut"] if len(polygons) else polygons
    if len(cuts):
        cuts.plot(ax=ax, color=SERIES[0], alpha=0.45, edgecolor=SERIES[0], lw=0.6)
    handles.append(matplotlib.patches.Patch(facecolor=SERIES[0], alpha=0.6,
                                            label=f"cirtes: {len(cuts)} ({cuts['area_ha'].sum() if len(cuts) else 0:.1f} ha)"))
    stress = polygons[polygons["type"] == "stress"] if len(polygons) else polygons
    for status, ls in (("persistent", "-"), ("new", "-"), ("recovered", ":")):
        sub = stress[stress["status"] == status] if len(stress) else stress
        if len(sub):
            sub.boundary.plot(ax=ax, color="#ffffff", lw=3.0)
            sub.boundary.plot(ax=ax, color=SERIES[1], lw=1.8, ls=ls)
        lab = {"persistent": "stress, noturīgs", "new": "stress, jauns",
               "recovered": "stress, atkopies"}[status]
        handles.append(matplotlib.lines.Line2D([], [], color=SERIES[1], lw=2, ls=ls,
                                               label=f"{lab}: {len(sub)}"))
    if missions is not None and len(missions):
        missions.boundary.plot(ax=ax, color="#ffffff", lw=1.6, ls="--")
        for _, m in missions.iterrows():
            c = m.geometry.representative_point()
            ax.annotate(m["mission_id"], (c.x, c.y), fontsize=8, color=INK, ha="center",
                        bbox=dict(boxstyle="round,pad=0.2", fc="#ffffff", ec="none", alpha=0.9))
        handles.append(matplotlib.lines.Line2D([], [], color=INK_2, lw=1.5, ls="--",
                                               label=f"drona misijas (top {len(missions)})"))
    ext = _extent(template)
    ax.set_xlim(ext[0], ext[1])
    ax.set_ylim(ext[2], ext[3])
    ax.set_xlabel("")
    ax.set_ylabel("")
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.02), ncol=3)
    ax.set_title(f"Pārskata karte {year} (fons: Sentinel-2 {t[i]:%Y-%m-%d})", loc="left")
    ax.set_xticks([])
    ax.set_yticks([])
    ax.grid(False)
    return _save(fig, path)
