"""Clean figures for a document: one image per panel, no titles or axes (300 dpi),
separate legend images and a caption file (paraksti.md, Latvian).

Maps contain no text; index / z maps keep a numeric colour bar. Charts keep axis
labels and a compact legend (needed to read them) but no title.
Visualization only - the frozen detection is not touched.

Usage: python scripts/export_clean_figures.py configs/test_kalsnava.yaml
       [target=F02 cloud_key=20260604_S2c haze_key=20260530_S2a]
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import geopandas as gpd
import matplotlib
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import geometry_mask
from rasterio.transform import from_origin

sys.path.insert(0, str(Path(__file__).parent))
from demo_multispectral import COMPOSITES, WAVELENGTH_NM, clearest, composite  # noqa: E402
from demo_processing import SCL_CLASSES, GREY, overlay, rgb  # noqa: E402

from s2forest import viz  # noqa: E402
from s2forest.config import load_config  # noqa: E402
from s2forest.fetch import build_grid, open_cube  # noqa: E402
from s2forest.indices import compute_indices  # noqa: E402
from s2forest.masking import valid_mask  # noqa: E402
from s2forest.temporal import harmonic_fit, harmonic_predict, time_info  # noqa: E402

plt = viz.plt
DPI = 300
CAPTIONS: list[tuple[str, str]] = []


def save_map(path: Path, img=None, arr=None, cmap=None, vmin=None, vmax=None, extent=None,
             draw=None, colorbar=False, caption=""):
    h, w = (img if img is not None else arr).shape[:2]
    fig_w = 6.0
    fig = plt.figure(figsize=(fig_w * (1.18 if colorbar else 1.0), fig_w * h / w))
    ax = fig.add_axes([0, 0, 0.84 if colorbar else 1, 1])
    if img is not None:
        ax.imshow(img, extent=extent, interpolation="nearest")
    else:
        im = ax.imshow(arr, cmap=cmap, vmin=vmin, vmax=vmax, extent=extent, interpolation="nearest")
        if colorbar:
            cax = fig.add_axes([0.87, 0.08, 0.035, 0.84])
            cb = fig.colorbar(im, cax=cax)
            cb.ax.tick_params(labelsize=9)
    if draw is not None:
        draw(ax)
    if extent is not None:
        ax.set_xlim(extent[0], extent[1]); ax.set_ylim(extent[2], extent[3])
    ax.set_axis_off()
    fig.savefig(path, dpi=DPI, facecolor="white")
    plt.close(fig)
    CAPTIONS.append((path.name, caption))


def save_legend(path: Path, items, kind="patch", ncol=1, caption=""):
    fig = plt.figure(figsize=(3, 0.3 * len(items) / ncol + 0.2))
    handles = []
    for it in items:
        if kind == "patch":
            handles.append(matplotlib.patches.Patch(facecolor=it[0], edgecolor="#808080", lw=0.4,
                                                    label=it[1]))
        else:
            c, lab, ls = it
            handles.append(matplotlib.lines.Line2D([], [], color=c, lw=2.2, ls=ls, label=lab))
    fig.legend(handles=handles, loc="center left", ncol=ncol, frameon=False, fontsize=9)
    fig.savefig(path, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    CAPTIONS.append((path.name, caption))


def main(config: str, target: str = "F02", cloud_key: str = "20260604_S2c",
         haze_key: str = "20260530_S2a") -> None:
    cfg = load_config(config)
    year = cfg.time.monitor_year
    out = cfg.run_dir / "figures" / "dokumentam"
    out.mkdir(parents=True, exist_ok=True)
    for f in out.glob("*.png"):
        f.unlink()
    grid = build_grid(cfg)
    cube = open_cube(cfg)
    idx = compute_indices(cube, ["ndvi", "ndre", "ndmi", "crswir"])
    ext = viz._extent(cube.B04.isel(time=0, drop=True))
    t1, t0 = clearest(cube, year), clearest(cube, year - 1)
    d1 = pd.Timestamp(cube.time.values[t1]).strftime("%d.%m.%Y")
    d0 = pd.Timestamp(cube.time.values[t0]).strftime("%d.%m.%Y")
    with rasterio.open(cfg.run_dir / "rasters" / "forest_mask.tif") as src:
        codes = src.read(1)
    forest = codes == 1
    area = "Kalsnavas testa teritorija (5 × 5 km)"

    # ---- A. multispectral composites and indices ------------------------------------------------
    comp_cap = {
        "B04_B03_B02": "dabiskajās krāsās (joslas B4-B3-B2)",
        "B08_B04_B03": "infrasarkanajā kombinācijā (B8-B4-B3; veselā veģetācija sarkanos toņos)",
        "B12_B8A_B04": "SWIR kombinācijā (B12-B8A-B4; mitruma un augsnes atšķirības)",
        "B8A_B05_B04": "sarkanās malas kombinācijā (B8A-B5-B4; hlorofila atšķirības)",
    }
    for n, (name, bands) in enumerate(COMPOSITES.items(), start=1):
        img, _, _ = composite(cube, t1, bands)
        key = "_".join(bands)
        save_map(out / f"A{n}_kompozits_{key}.png", img=img, extent=ext,
                 caption=f"Sentinel-2 attēls {comp_cap[key]}, {area}, {d1}. Izšķirtspēja 10–20 m.")
    idx_cap = {"ndvi": "NDVI (zaļā biomasa)", "ndre": "NDRE (hlorofila saturs, sarkanā mala)",
               "ndmi": "NDMI (lapotnes mitrums)",
               "crswir": "CRSWIR (lapotnes mitruma deficīts; augstāka vērtība = lielāks stress)"}
    for n, k in enumerate(["ndvi", "ndre", "ndmi", "crswir"], start=5):
        a = idx[k].isel(time=t1).values
        lo, hi = np.nanpercentile(a[forest], [2, 98])
        save_map(out / f"A{n}_indekss_{k}.png", arr=a, cmap=viz.SEQ, vmin=lo, vmax=hi, extent=ext,
                 colorbar=True, caption=f"Veģetācijas indekss {idx_cap[k]}, {area}, {d1}.")

    # ---- B. cloud and haze masking ------------------------------------------------------------
    raw_cfg = cfg.model_copy(deep=True)
    raw_cfg.masking.invalid_scl = [0]
    raw_cfg.masking.cloud_buffer_m = 0
    raw_cfg.masking.haze.enabled = False
    raw_cfg.data.min_valid_fraction = 0.0
    raw = open_cube(raw_cfg)
    m_cfg = cfg.model_copy(deep=True)
    m_cfg.data.min_valid_fraction = 0.0
    masked = open_cube(m_cfg)
    keys, mkeys = list(raw.acq_key.values), list(masked.acq_key.values)
    buf_px = int(round(cfg.masking.cloud_buffer_m / cfg.data.resolution))
    aoi = grid.aoi_mask
    for letter, key in (("B", cloud_key), ("C", haze_key)):
        t, tm = keys.index(key), mkeys.index(key)
        d = pd.Timestamp(raw.time.values[t]).strftime("%d.%m.%Y")
        base = rgb(raw, t)
        scl = raw.SCL.isel(time=t).values
        scl_ok = valid_mask(raw.SCL.isel(time=t), cfg.masking.invalid_scl, 0).values
        scl_buf = valid_mask(raw.SCL.isel(time=t), cfg.masking.invalid_scl, buf_px).values
        haze = masked.haze.isel(time=tm).values.astype(bool)
        final = masked.valid.isel(time=tm).values.astype(bool)
        kind = "ar gubu mākoņiem" if letter == "B" else "ar plānu dūmaku"
        save_map(out / f"{letter}1_{key}_neapstradats.png", img=base,
                 caption=f"Neapstrādāts Sentinel-2 attēls {kind}, {d}.")
        sc = np.zeros(scl.shape + (3,))
        for k, (c, _) in SCL_CLASSES.items():
            sc[scl == k] = matplotlib.colors.to_rgb(c)
        save_map(out / f"{letter}2_{key}_scl.png", img=sc,
                 caption=f"Sen2Cor ainas klasifikācija (SCL), {d}; krāsas — leģendā L1.")
        o = overlay(overlay(base, ~scl_ok, "#eb6834"), scl_ok & ~scl_buf, "#eda100")
        save_map(out / f"{letter}3_{key}_scl_maska.png", img=o,
                 caption=f"SCL mākoņu/ēnu maska (oranžs) ar {cfg.masking.cloud_buffer_m:.0f} m buferi "
                         f"(dzeltens), {d}; derīgi {np.mean(scl_buf[aoi]):.0%} pikseļu.")
        o = overlay(np.where(scl_buf[..., None], base, GREY), haze, "#e87ba4")
        save_map(out / f"{letter}4_{key}_dumaka.png", img=o,
                 caption=f"Laikrindu dūmakas tests (rozā = dūmaka, ko SCL nepamanīja), {d}; "
                         f"nomaskēti {np.mean(haze[aoi]):.0%} pikseļu.")
        ok = np.mean(final[aoi]) >= cfg.data.min_valid_fraction
        save_map(out / f"{letter}5_{key}_rezultats.png",
                 img=np.where(final[..., None], base, GREY),
                 caption=f"Analīzē izmantotie pikseļi (pelēks = nomaskēts), {d}: "
                         f"{np.mean(final[aoi]):.0%} — aina "
                         + ("izmantota." if ok else f"atmesta (< {cfg.data.min_valid_fraction:.0%})."))
    present = sorted(set(np.unique(raw.SCL.isel(time=keys.index(cloud_key)).values))
                     | set(np.unique(raw.SCL.isel(time=keys.index(haze_key)).values)))
    save_legend(out / "L1_leģenda_scl.png", [SCL_CLASSES[k] for k in present if k in SCL_CLASSES],
                caption="Leģenda: Sen2Cor ainas klasifikācijas (SCL) klases.")
    save_legend(out / "L2_leģenda_makonu_maska.png",
                [("#eb6834", "mākonis / ēna / cirruss (SCL)"), ("#eda100", "buferis ap mākoņiem"),
                 ("#e87ba4", "dūmaka (laikrindu tests)"), ("#d9d9d9", "nomaskēts")],
                caption="Leģenda: mākoņu un dūmakas maska.")

    # ---- D. forest mask ------------------------------------------------------------------------
    with rasterio.open(cfg.cache_dir / grid.key / "forest_hrl_dlt_2018.tif") as src:
        dlt = src.read(1)
    base = rgb(raw, keys.index(str(cube.acq_key.values[t1])))
    conifer = np.isin(dlt, cfg.forest_mask.classes) & aoi
    green = overlay(base, conifer, "#1baf7a", 0.35)
    lines = gpd.read_file(next((cfg.cache_dir / grid.key).glob("osm_lines_*.gpkg"))).to_crs(cfg.data.crs)
    ha = lambda m: f"{np.sum(m) / 100:.0f} ha"
    save_map(out / "D1_hrl_skujkoki.png", img=overlay(base, conifer, "#1baf7a", 0.55), extent=ext,
             caption=f"Copernicus HRL Dominant Leaf Type 2018 skujkoku klase (zaļš): {ha(conifer)}.")
    save_map(out / "D2_izslegts_ndvi.png", img=overlay(green, codes == 2, "#eda100", 0.9), extent=ext,
             caption=f"Izslēgts: izcirsts vai jaunaudze kopš 2018. gada (bāzes vasaras NDVI < "
                     f"{cfg.forest_mask.min_summer_ndvi:.2f}), dzeltens: {ha(codes == 2)}.")
    save_map(out / "D3_izslegts_celi.png", img=overlay(green, codes == 4, "#e34948", 0.9), extent=ext,
             draw=lambda ax: lines.plot(ax=ax, color="#ffffff", lw=0.6),
             caption=f"Izslēgts: OpenStreetMap ceļi ar {cfg.linear_features.buffer_m:.0f} m buferi "
                     f"(sarkans; balts — ceļu līnijas): {ha(codes == 4)}.")
    save_map(out / "D4_izslegts_amplituda.png", img=overlay(green, codes == 5, "#e87ba4", 0.9),
             extent=ext,
             caption=f"Izslēgts: liela sezonālā amplitūda — nav slēgta skujkoku audze (rozā): "
                     f"{ha(codes == 5)}.")
    save_map(out / "D5_analizetais_mezs.png", img=overlay(base, codes == 1, "#2a78d6", 0.6), extent=ext,
             caption=f"Analizētais skujkoku mežs (zils): {ha(codes == 1)} ({np.mean(forest[aoi]):.0%} "
                     f"teritorijas).")

    # ---- E. detection to drone missions -----------------------------------------------------------
    with rasterio.open(cfg.run_dir / "rasters" / "anomaly" / f"max_z_{cfg.anomaly.primary_index}_{year}.tif") as src:
        zmax = src.read(1)
    with rasterio.open(cfg.run_dir / "rasters" / "anomaly" / f"status_{year}.tif") as src:
        status = src.read(1)
    gpkg = cfg.run_dir / "vectors" / "suspects.gpkg"
    polys = gpd.read_file(gpkg, layer=f"suspects_{year}")
    targets = gpd.read_file(gpkg, layer="drone_targets")
    missions = gpd.read_file(gpkg, layer="drone_missions")
    stress, cuts = polys[polys["type"] == "stress"], polys[polys["type"] == "cut"]
    save_map(out / "E1_z_karte.png", arr=np.where(forest, zmax, np.nan), cmap=viz.DIV, vmin=-6,
             vmax=6, extent=ext, colorbar=True,
             caption=f"Maksimālā CRSWIR novirze (z) {year}. gadā salīdzinājumā ar katra pikseļa "
                     f"bāzi {cfg.time.baseline_year_list[0]}–{cfg.time.baseline_year_list[-1]} "
                     f"(sarkans = stresa virzienā).")
    img = overlay(overlay(overlay(base, status == 1, "#eb6834", 0.95), status == 2, "#2a78d6", 0.95),
                  status == 3, "#b9b8b3", 0.9)
    save_map(out / "E2_atzimetie_pikseli.png", img=img, extent=ext,
             caption="Atzīmētie pikseļi: stress (oranžs), cirte (zils), traucēts jau bāzes periodā "
                     "(pelēks, izslēgts).")

    def draw_polys(ax):
        if len(cuts):
            cuts.plot(ax=ax, color="#2a78d6", alpha=0.5, edgecolor="#2a78d6", lw=0.6)
        if len(stress):
            stress.boundary.plot(ax=ax, color="#ffffff", lw=3)
            stress.boundary.plot(ax=ax, color="#eb6834", lw=1.8)
    save_map(out / "E3_poligoni.png", img=base, extent=ext, draw=draw_polys,
             caption=f"Aizdomīgās vietas {year}: {len(stress)} stresa poligoni (oranža kontūra) un "
                     f"{len(cuts)} cirtes (zils), min. laukums {cfg.anomaly.min_area_ha:g} ha.")

    def draw_targets(ax):
        edges = targets[targets["kind"] == "cut_edge"]
        if len(edges):
            edges.plot(ax=ax, column="risk_score", cmap="YlOrRd", vmin=0.3, vmax=0.9, lw=0)
        if len(stress):
            stress.boundary.plot(ax=ax, color="#ffffff", lw=3)
            stress.boundary.plot(ax=ax, color="#eb6834", lw=1.8)
        missions.boundary.plot(ax=ax, color="#ffffff", lw=1.4, ls="--")
    save_map(out / "E4_drona_misijas.png", img=base, extent=ext, draw=draw_targets,
             caption=f"Drona mērķi un misijas: stresa vietas (oranžs), cirtes malas pēc riska "
                     f"(dzeltens → sarkans), top {len(missions)} misiju lidojuma laukumi "
                     f"(pārtraukta līnija, ≤ {cfg.targets.mission_max_area_ha:g} ha).")
    save_legend(out / "L3_leģenda_meza_maska.png",
                [("#1baf7a", "HRL skujkoki"), ("#eda100", "izcirsts / jaunaudze"),
                 ("#e34948", "ceļa buferis"), ("#e87ba4", "liela sezonālā amplitūda"),
                 ("#2a78d6", "analizētais mežs")], caption="Leģenda: meža maska.")
    save_legend(out / "L4_leģenda_detekcija.png",
                [("#eb6834", "stress"), ("#2a78d6", "cirte"), ("#b9b8b3", "traucēts bāzes periodā")],
                caption="Leģenda: atzīmētie pikseļi un poligoni.")
    save_legend(out / "L5_leģenda_misijas.png",
                [("#eb6834", "stresa vieta", "-"), ("#fd8d3c", "cirtes mala (krāsa = risks)", "-"),
                 ("#808080", "drona misija", "--")], kind="line",
                caption="Leģenda: drona mērķi un misijas.")

    # ---- F. close-up of the field-check target --------------------------------------------------
    fc = gpd.read_file(cfg.run_dir / "field_check" / f"field_check_{year}.gpkg", layer="targets")
    tgt = fc[fc["merka_id"] == target].iloc[0]
    minx, miny, maxx, maxy = tgt.geometry.buffer(250).bounds
    sub = cube.sel(x=slice(minx, maxx), y=slice(maxy, miny))
    subi = idx.sel(x=slice(minx, maxx), y=slice(maxy, miny))
    sext = viz._extent(sub.B04.isel(time=0, drop=True))
    outline = lambda ax: (gpd.GeoSeries([tgt.geometry]).boundary.plot(ax=ax, color="#ffffff", lw=2.6),
                          gpd.GeoSeries([tgt.geometry]).boundary.plot(ax=ax, color="#eb6834", lw=1.4))
    tc_ = COMPOSITES["dabiskās krāsas (B04-B03-B02)"]
    ci_ = COMPOSITES["infrasarkanā (NIR-sarkanā-zaļā, B08-B04-B03)"]
    _, lo_t, hi_t = composite(sub, t1, tc_)
    _, lo_c, hi_c = composite(sub, t0, ci_)
    cr = np.concatenate([subi.crswir.isel(time=t).values.ravel() for t in (t0, t1)])
    crlo, crhi = np.nanpercentile(cr, [2, 98])
    for t, d, yy in ((t0, d0, year - 1), (t1, d1, year)):
        img, _, _ = composite(sub, t, tc_, lo_t, hi_t)
        save_map(out / f"F_{target}_{yy}_dabiskas.png", img=img, extent=sext, draw=outline,
                 caption=f"Lauka pārbaudes mērķis {target} (oranža kontūra), dabiskās krāsas, {d}.")
        img, _, _ = composite(sub, t, ci_, lo_c, hi_c)
        save_map(out / f"F_{target}_{yy}_infrasarkana.png", img=img, extent=sext, draw=outline,
                 caption=f"Mērķis {target}, infrasarkanā kombinācija (B8-B4-B3), {d}.")
        save_map(out / f"F_{target}_{yy}_crswir.png", arr=subi.crswir.isel(time=t).values,
                 cmap=viz.SEQ, vmin=crlo, vmax=crhi, extent=sext, draw=outline, colorbar=True,
                 caption=f"Mērķis {target}, CRSWIR (tumšāks = lielāks mitruma deficīts), {d}.")

    # ---- G. charts (axis labels and legend, no title) ---------------------------------------------
    x, y = cube.x.values, cube.y.values
    tr = from_origin(float(x[0]) - 5, float(y[0]) + 5, 10, 10)
    t = pd.DatetimeIndex(cube.time.values)
    summer = np.flatnonzero((t.year == year) & np.isin(t.month, [7, 8]))
    cut = cuts.sort_values("area_ha", ascending=False).iloc[0]
    groups = {"vesels mežs (kontrole)": fc[fc["kind"] == "control"].geometry.iloc[0],
              f"stresa vieta ({target})": tgt.geometry, "cirte": cut.geometry}
    bands = list(WAVELENGTH_NM)
    fig, ax = plt.subplots(figsize=(7, 4))
    for k, (lab, geom) in enumerate(groups.items()):
        m = ~geometry_mask([geom], out_shape=(len(y), len(x)), transform=tr)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            vals = [float(np.nanmedian(cube[b].isel(time=summer).values[:, m])) for b in bands]
        ax.plot([WAVELENGTH_NM[b] for b in bands], vals, "-o", ms=5, lw=1.8, color=viz.SERIES[k],
                label=lab, mec=viz.SURFACE)
    ax.set_xlabel("viļņa garums, nm")
    ax.set_ylabel("atstarošanās")
    ax.legend(loc="upper right", fontsize=8.5)
    fig.savefig(out / "G1_spektralas_liknes.png", dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    CAPTIONS.append(("G1_spektralas_liknes.png",
                     f"Sentinel-2 spektrālās līknes (atstarošanās mediāna {year}. g. jūlijā–augustā): "
                     f"veselam mežam augsta NIR (~840–865 nm) un zema SWIR (1610, 2190 nm) "
                     f"atstarošanās; stresa vietai NIR zemāka un SWIR augstāka; cirtei — atklāta "
                     f"augsne un zemsedze."))

    # time series (regionally normalized values, as used by the detection)
    raw_crs = compute_indices(raw, ["crswir"]).crswir.values
    m_crs = compute_indices(masked, ["crswir"]).crswir.values
    inside = ~geometry_mask([tgt.geometry], out_shape=(len(y), len(x)), transform=tr)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        v_raw = np.nanmedian(raw_crs[:, inside], axis=1)
        v_ok = np.nanmedian(m_crs[:, inside], axis=1)
    scl_ok = valid_mask(raw.SCL, cfg.masking.invalid_scl, buf_px).values[:, inside]
    hz = masked.haze.values[:, inside].astype(bool)
    cloud = np.mean(~scl_ok, axis=1) >= 0.5
    hazy = (np.mean(hz, axis=1) >= 0.5) & ~cloud
    times = pd.DatetimeIndex(raw.time.values)
    doy, yrs = time_info(times)
    offs = pd.read_csv(cfg.run_dir / "tables" / "regional_offsets.csv", parse_dates=["time"])
    off = dict(zip(offs["time"].dt.round("s"), offs[f"offset_{cfg.anomaly.primary_index}"]))
    v_ok = v_ok - np.nan_to_num(np.array([off.get(tt.round("s"), np.nan) for tt in times], "float64"))
    used = np.isfinite(v_ok) & ~cloud & ~hazy
    bsel = np.isin(yrs, cfg.time.baseline_year_list) & used
    coef, scale, _ = harmonic_fit(v_ok[bsel][:, None], doy[bsel], cfg.anomaly.harmonics)
    sc = max(float(scale[0]), cfg.anomaly.mad_floor[cfg.anomaly.primary_index])
    fig, ax = plt.subplots(figsize=(10, 3.8))
    for yr in sorted(set(yrs)):
        dd = np.arange(121, 274)
        pred = harmonic_predict(coef, dd, cfg.anomaly.harmonics)[:, 0]
        tt = pd.to_datetime(f"{yr}-01-01") + pd.to_timedelta(dd - 1, unit="D")
        ax.fill_between(tt, pred - cfg.anomaly.z_threshold * sc, pred + cfg.anomaly.z_threshold * sc,
                        color=viz.SERIES[0], alpha=0.12, lw=0)
        ax.plot(tt, pred, color=viz.SERIES[0], lw=1.2, label="bāze (harmonisks modelis)" if yr == yrs.min() else None)
    ax.plot(times[cloud], v_raw[cloud], "x", color=viz.INK_2, ms=6, label="mākonis (nomaskēts)")
    ax.plot(times[hazy], v_raw[hazy], "+", color="#e87ba4", ms=8, mew=1.6, label="dūmaka (nomaskēts)")
    ax.plot(times[used & (yrs < year)], v_ok[used & (yrs < year)], "o", ms=4, color=viz.SERIES[0],
            mec=viz.SURFACE, label="bāzes gadi")
    ax.plot(times[used & (yrs == year)], v_ok[used & (yrs == year)], "o", ms=6, color=viz.SERIES[1],
            mec=viz.SURFACE, label=str(year))
    ax.set_ylabel("CRSWIR")
    viz._concise_dates(ax)
    ax.legend(loc="upper left", fontsize=8, ncol=3)
    fig.savefig(out / "G2_laika_rinda.png", dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    CAPTIONS.append(("G2_laika_rinda.png",
                     f"CRSWIR laika rinda mērķī {target} ({cfg.time.baseline_year_list[0]}–{year}, "
                     f"reģionāli normalizēta): bāzes gadu novērojumi (zils), harmoniskais bāzes "
                     f"modelis ar sliekšņa joslu (±{cfg.anomaly.z_threshold} mēroga), nomaskētie "
                     f"mākoņu (×) un dūmakas (+) novērojumi un {year}. gada novērojumi (oranžs), kas "
                     f"pastāvīgi pārsniedz bāzi."))

    lines_md = ["# Attēli dokumentam — ieteiktie paraksti", "",
                f"Avots: Sentinel-2 L2A (ESA Copernicus), apstrāde ar s2forest (iesaldētā versija "
                f"v0.2-kalsnava). {area}. Visi attēli 300 dpi; kartēs nav teksta — skaidrojums parakstā; "
                f"leģendas atsevišķos failos L1–L5.", ""]
    for name, cap in CAPTIONS:
        lines_md.append(f"- **{name}** — {cap}")
    (out / "paraksti.md").write_text("\n".join(lines_md) + "\n", encoding="utf-8")
    print(f"{len(CAPTIONS)} images -> {out}")


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0], *a[1:4])
