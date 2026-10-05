"""Processing-step demonstration figures (visualization only; frozen detection untouched).

04 cloud masking: raw RGB -> SCL classes -> SCL mask + 20 m buffer -> temporal haze
   test -> valid pixels (two example dates: clouds, thin haze)
05 forest mask: HRL conifer -> minus felled since 2018 (low summer NDVI) -> minus OSM
   road buffer -> minus large seasonal amplitude -> analysed forest
06 from pixel to polygon: stress z map -> flagged pixels -> polygons (stress / cut)
   -> drone targets and missions
07 time series of one site: observations used by the detection (regionally
   normalized), masked observations, harmonic baseline and the threshold band

Usage: python scripts/demo_processing.py configs/test_kalsnava.yaml [cloud_key haze_key target]
       defaults: 20260604_S2c 20260530_S2a F02
"""

from __future__ import annotations

import sys
import warnings

import geopandas as gpd
import matplotlib
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import geometry_mask
from rasterio.transform import from_origin

from s2forest import viz
from s2forest.config import load_config
from s2forest.fetch import build_grid, open_cube
from s2forest.indices import compute_indices
from s2forest.masking import valid_mask
from s2forest.temporal import harmonic_fit, harmonic_predict, time_info

plt = viz.plt
SCL_CLASSES = {  # conventional SCL colours
    0: ("#000000", "nav datu"), 1: ("#ff0000", "defektīvs"), 2: ("#2f2f2f", "tumšs"),
    3: ("#643200", "mākoņa ēna"), 4: ("#00a000", "veģetācija"), 5: ("#ffe65a", "bez veģetācijas"),
    6: ("#0000ff", "ūdens"), 7: ("#808080", "neklasificēts"), 8: ("#c0c0c0", "mākonis (vid.)"),
    9: ("#ffffff", "mākonis (augsta)"), 10: ("#64c8ff", "cirruss"), 11: ("#ff96ff", "sniegs"),
}
GREY = 0.85


def rgb(ds, t, gain=3.2):
    a = np.stack([ds[b].isel(time=t).values for b in ("B04", "B03", "B02")], axis=-1)
    return np.where(np.isnan(a), GREY, np.clip(a * gain, 0, 1))


def overlay(base, mask, color, alpha=0.75):
    out = base.copy()
    c = np.array(matplotlib.colors.to_rgb(color))
    out[mask] = (1 - alpha) * out[mask] + alpha * c
    return out


def clean(ax, title):
    ax.set_title(title, loc="left", fontsize=8.5)
    ax.set_xticks([]); ax.set_yticks([]); ax.set_xlabel(""); ax.set_ylabel(""); ax.grid(False)


def legend_below(ax, items, ncol=2):
    ax.legend(handles=[matplotlib.patches.Patch(color=c, label=l) for c, l in items],
              loc="upper center", bbox_to_anchor=(0.5, -0.02), ncol=ncol, fontsize=7, frameon=False)


def main(config, cloud_key="20260604_S2c", haze_key="20260530_S2a", target="F02"):
    cfg = load_config(config)
    year = cfg.time.monitor_year
    out = cfg.run_dir / "figures" / "demo_apstrade"
    out.mkdir(parents=True, exist_ok=True)
    grid = build_grid(cfg)

    raw_cfg = cfg.model_copy(deep=True)
    raw_cfg.masking.invalid_scl = [0]
    raw_cfg.masking.cloud_buffer_m = 0
    raw_cfg.masking.haze.enabled = False
    raw_cfg.data.min_valid_fraction = 0.0
    raw = open_cube(raw_cfg)                      # reflectance without cloud masks
    m_cfg = cfg.model_copy(deep=True)
    m_cfg.data.min_valid_fraction = 0.0
    masked = open_cube(m_cfg)                     # with all masks, all dates kept
    keys = list(raw.acq_key.values)
    buf_px = int(round(cfg.masking.cloud_buffer_m / cfg.data.resolution))

    # ---- 04 cloud masking -----------------------------------------------------------
    fig, axes = plt.subplots(2, 5, figsize=(19, 8.6))
    for row, key in enumerate([cloud_key, haze_key]):
        t = keys.index(key)
        tm = list(masked.acq_key.values).index(key)
        scl = raw.SCL.isel(time=t).values
        base = rgb(raw, t)
        d = pd.Timestamp(raw.time.values[t]).strftime("%Y-%m-%d")
        scl_ok = valid_mask(raw.SCL.isel(time=t), cfg.masking.invalid_scl, 0).values
        scl_buf = valid_mask(raw.SCL.isel(time=t), cfg.masking.invalid_scl, buf_px).values
        haze = masked.haze.isel(time=tm).values.astype(bool)
        final = masked.valid.isel(time=tm).values.astype(bool)
        aoi = grid.aoi_mask
        f = lambda m: f"{np.mean(m[aoi]):.0%}"
        ax = axes[row]
        ax[0].imshow(base); clean(ax[0], f"{d}: dabiskās krāsas (neapstrādāts)")
        sc = np.zeros(scl.shape + (3,))
        for k, (c, _) in SCL_CLASSES.items():
            sc[scl == k] = matplotlib.colors.to_rgb(c)
        ax[1].imshow(sc); clean(ax[1], "Sen2Cor ainas klasifikācija (SCL)")
        present = [k for k in SCL_CLASSES if (scl == k).any()]
        legend_below(ax[1], [SCL_CLASSES[k] for k in present], ncol=3)
        o = overlay(base, ~scl_ok, "#eb6834")
        o = overlay(o, scl_ok & ~scl_buf, "#eda100")
        ax[2].imshow(o); clean(ax[2], f"SCL maska + {cfg.masking.cloud_buffer_m:.0f} m buferis: "
                                       f"derīgi {f(scl_buf)}")
        legend_below(ax[2], [("#eb6834", "mākonis / ēna / cirruss (SCL)"),
                             ("#eda100", "buferis ap mākoņiem")])
        o = overlay(np.where(scl_buf[..., None], base, GREY), haze, "#e87ba4")
        ax[3].imshow(o); clean(ax[3], f"laikrindu dūmakas tests: nomaskēti {np.mean(haze[aoi]):.0%}")
        legend_below(ax[3], [("#e87ba4", "dūmaka (B02 > bāze + 0,02, īslaicīga)")], ncol=1)
        ax[4].imshow(np.where(final[..., None], base, GREY))
        ok = np.mean(final[aoi]) >= cfg.data.min_valid_fraction
        clean(ax[4], f"izmantotie pikseļi: {f(final)} → aina "
                     + ("IZMANTOTA" if ok else f"ATMESTA (< {cfg.data.min_valid_fraction:.0%})"))
    fig.suptitle("1. solis — mākoņu, ēnu un dūmakas maska (pelēks = nomaskēts)", x=0.01, ha="left",
                 fontsize=12, color=viz.INK)
    fig.tight_layout()
    p4 = viz._save(fig, out / "04_makonu_maska.png")

    # ---- 05 forest mask ---------------------------------------------------------------
    with rasterio.open(cfg.run_dir / "rasters" / "forest_mask.tif") as src:
        codes = src.read(1)
    with rasterio.open(cfg.cache_dir / grid.key / "forest_hrl_dlt_2018.tif") as src:
        dlt = src.read(1)
    tc = keys.index("20260717_S2c") if "20260717_S2c" in keys else int(np.argmax(raw.valid_fraction.values))
    base = rgb(raw, tc)
    conifer = np.isin(dlt, cfg.forest_mask.classes) & grid.aoi_mask
    lines = gpd.read_file(next((cfg.cache_dir / grid.key).glob("osm_lines_*.gpkg"))).to_crs(cfg.data.crs)
    ext = viz._extent(raw.B04.isel(time=0, drop=True))
    green = overlay(base, conifer, "#1baf7a", 0.35)
    steps = [  # (title, image, lines to draw, area mask)
        ("HRL Dominant Leaf Type 2018: skujkoki", overlay(base, conifer, "#1baf7a", 0.55), None, conifer),
        ("− izcirsts / jaunaudze kopš 2018 (vasaras NDVI < 0,65)",
         overlay(green, codes == 2, "#eda100", 0.9), None, codes == 2),
        ("− OSM ceļi, 20 m buferis", overlay(green, codes == 4, "#e34948", 0.9), lines, codes == 4),
        ("− liela sezonālā amplitūda (NDVI p90−p10 > 0,22)",
         overlay(green, codes == 5, "#e87ba4", 0.9), None, codes == 5),
        ("= analizētais skujkoku mežs", overlay(base, codes == 1, "#2a78d6", 0.6), None, codes == 1),
    ]
    fig, axes = plt.subplots(1, 5, figsize=(21, 5.2))
    for ax, (title, img, ln, area) in zip(axes, steps):
        ax.imshow(img, extent=ext, interpolation="nearest")
        if ln is not None:
            ln.plot(ax=ax, color="#ffffff", lw=0.6)
        ax.set_xlim(ext[0], ext[1]); ax.set_ylim(ext[2], ext[3])
        clean(ax, f"{title}\n{np.sum(area) / 100:.0f} ha ({np.mean(area[grid.aoi_mask]):.0%} AOI)")
    fig.suptitle("2. solis — meža maska: kur analīze tiek veikta", x=0.01, ha="left", fontsize=12,
                 color=viz.INK)
    fig.tight_layout()
    p5 = viz._save(fig, out / "05_meza_maska.png")

    # ---- 06 from pixel to polygon ---------------------------------------------------------
    with rasterio.open(cfg.run_dir / "rasters" / "anomaly" / f"max_z_{cfg.anomaly.primary_index}_{year}.tif") as src:
        zmax = src.read(1)
    with rasterio.open(cfg.run_dir / "rasters" / "anomaly" / f"status_{year}.tif") as src:
        status = src.read(1)
    gpkg = cfg.run_dir / "vectors" / "suspects.gpkg"
    polys = gpd.read_file(gpkg, layer=f"suspects_{year}")
    targets = gpd.read_file(gpkg, layer="drone_targets")
    missions = gpd.read_file(gpkg, layer="drone_missions")
    fig, axes = plt.subplots(1, 4, figsize=(21, 6))
    zshow = np.where(codes == 1, zmax, np.nan)
    im = axes[0].imshow(zshow, cmap=viz.DIV, vmin=-6, vmax=6, extent=ext, interpolation="nearest")
    fig.colorbar(im, ax=axes[0], fraction=0.046, pad=0.02)
    clean(axes[0], f"maks. CRSWIR z {year} (sarkans = stresa virzienā)\nsalīdzinājums ar katra pikseļa bāzi")
    img = base.copy()
    img = overlay(img, status == 1, "#eb6834", 0.95)
    img = overlay(img, status == 2, "#2a78d6", 0.95)
    img = overlay(img, status == 3, "#b9b8b3", 0.9)
    axes[1].imshow(img, extent=ext, interpolation="nearest")
    clean(axes[1], "atzīmētie pikseļi: z ≥ 2,5 + cits indekss,\n≥ 2 novērojumi un ≥ 7 dienas")
    legend_below(axes[1], [("#eb6834", "stress"), ("#2a78d6", "cirte (NDVI/NDMI kritums)"),
                           ("#b9b8b3", "traucēts jau bāzē (izslēgts)")], ncol=3)
    axes[2].imshow(base, extent=ext, interpolation="nearest")
    cuts = polys[polys["type"] == "cut"]
    stress = polys[polys["type"] == "stress"]
    if len(cuts):
        cuts.plot(ax=axes[2], color="#2a78d6", alpha=0.5, edgecolor="#2a78d6", lw=0.6)
    if len(stress):
        stress.boundary.plot(ax=axes[2], color="#ffffff", lw=3)
        stress.boundary.plot(ax=axes[2], color="#eb6834", lw=1.8)
        for _, r in stress.iterrows():
            c = r.geometry.representative_point()
            axes[2].annotate(f"#{r['id']}", (c.x, c.y), xytext=(5, 5), textcoords="offset points",
                             fontsize=8, bbox=dict(boxstyle="round,pad=0.15", fc="#ffffff", ec="none"))
    clean(axes[2], f"poligoni ≥ 0,1 ha: {len(stress)} stress, {len(cuts)} cirtes")
    axes[3].imshow(base, extent=ext, interpolation="nearest")
    edges = targets[targets["kind"] == "cut_edge"]
    if len(edges):
        edges.plot(ax=axes[3], column="risk_score", cmap="YlOrRd", vmin=0.3, vmax=0.9, lw=0)
    if len(stress):
        stress.boundary.plot(ax=axes[3], color="#eb6834", lw=2)
    missions.boundary.plot(ax=axes[3], color="#ffffff", lw=1.4, ls="--")
    for _, m in missions.iterrows():
        c = m.geometry.representative_point()
        axes[3].annotate(m["mission_id"], (c.x, c.y), fontsize=7.5, ha="center",
                         bbox=dict(boxstyle="round,pad=0.15", fc="#ffffff", ec="none", alpha=0.9))
    clean(axes[3], "drona mērķi un misijas: stress (oranžs),\ncirtes malas pēc riska (dzeltens→sarkans)")
    for ax in axes:
        ax.set_xlim(ext[0], ext[1]); ax.set_ylim(ext[2], ext[3])
    fig.suptitle("3. solis — no pikseļa līdz drona misijai", x=0.01, ha="left", fontsize=12,
                 color=viz.INK)
    fig.tight_layout()
    p6 = viz._save(fig, out / "06_no_pikseļa_lidz_misijai.png")

    # ---- 07 time series of one site -----------------------------------------------------------
    fc = gpd.read_file(cfg.run_dir / "field_check" / f"field_check_{year}.gpkg", layer="targets")
    geom = fc[fc["merka_id"] == target].geometry.iloc[0]
    x, y = raw.x.values, raw.y.values
    tr = from_origin(float(x[0]) - 5, float(y[0]) + 5, 10, 10)
    inside = ~geometry_mask([geom], out_shape=(len(y), len(x)), transform=tr)
    ri = compute_indices(raw, ["crswir"]).crswir.values[:, inside]
    mi = compute_indices(masked, ["crswir"]).crswir.values[:, inside]
    scl_ok = valid_mask(raw.SCL, cfg.masking.invalid_scl, buf_px).values[:, inside]
    hz = masked.haze.values[:, inside].astype(bool)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        v_raw = np.nanmedian(ri, axis=1)
        v_ok = np.nanmedian(np.where(np.isfinite(mi), mi, np.nan), axis=1)
    cloud = np.mean(~scl_ok, axis=1) >= 0.5
    hazy = (np.mean(hz, axis=1) >= 0.5) & ~cloud
    used = np.isfinite(v_ok) & ~cloud & ~hazy
    times = pd.DatetimeIndex(raw.time.values)
    doy, yrs = time_info(times)
    # the detection compares regionally normalized values: subtract the per-date offset
    offs = pd.read_csv(cfg.run_dir / "tables" / "regional_offsets.csv", parse_dates=["time"])
    # exact acquisition time (two platforms can image the same day)
    off = dict(zip(offs["time"].dt.round("s"), offs[f"offset_{cfg.anomaly.primary_index}"]))
    o = np.array([off.get(t.round("s"), np.nan) for t in times], dtype="float64")
    v_ok = v_ok - np.nan_to_num(o)
    base_sel = np.isin(yrs, cfg.time.baseline_year_list) & used
    coef, scale, _ = harmonic_fit(v_ok[base_sel][:, None], doy[base_sel], cfg.anomaly.harmonics)
    sc = max(float(scale[0]), cfg.anomaly.mad_floor[cfg.anomaly.primary_index])
    fig, ax = plt.subplots(figsize=(12, 4.6))
    for yr in sorted(set(yrs)):
        dd = np.arange(121, 274)
        pred = harmonic_predict(coef, dd, cfg.anomaly.harmonics)[:, 0]
        tt = pd.to_datetime(f"{yr}-01-01") + pd.to_timedelta(dd - 1, unit="D")
        ax.fill_between(tt, pred - cfg.anomaly.z_threshold * sc, pred + cfg.anomaly.z_threshold * sc,
                        color=viz.SERIES[0], alpha=0.12, lw=0)
        ax.plot(tt, pred, color=viz.SERIES[0], lw=1.2,
                label="bāze (harmonisks modelis, 2023–2025)" if yr == yrs.min() else None)
    ax.plot(times[cloud], v_raw[cloud], "x", color=viz.INK_2, ms=6, label="mākonis / ēna (SCL) — nomaskēts")
    ax.plot(times[hazy], v_raw[hazy], "+", color="#e87ba4", ms=8, mew=1.6, label="dūmaka — nomaskēts")
    bl = used & (yrs < year)
    mon = used & (yrs == year)
    ax.plot(times[bl], v_ok[bl], "o", ms=4, color=viz.SERIES[0], mec=viz.SURFACE, label="izmantots (bāzes gadi)")
    ax.plot(times[mon], v_ok[mon], "o", ms=6, color=viz.SERIES[1], mec=viz.SURFACE, label=f"izmantots ({year})")
    ax.set_ylabel("CRSWIR − reģionālā nobīde\n(mediāna mērķī)")
    viz._concise_dates(ax)
    ax.legend(loc="upper left", fontsize=7.5, ncol=2)
    ax.set_title(f"4. solis — laika rinda mērķī {target}: maskēšana, reģionālā normalizācija un bāze "
                 f"(josla = ±{cfg.anomaly.z_threshold} mēroga; nomaskētie — nenormalizēti)",
                 loc="left", fontsize=10)
    p7 = viz._save(fig, out / "07_laika_rinda.png")
    print("\n".join(map(str, (p4, p5, p6, p7))))


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0], *(a[1:4]))
