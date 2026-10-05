"""Sentinel-2 multispectral demonstration figures (visualization only; does not
touch the frozen detection).

1. Whole AOI, one clear summer scene: true colour, colour infrared (NIR-R-G),
   SWIR composite (SWIR2-NIR-R), red-edge composite (NIR-RE-R) and index maps
   (NDVI, NDRE, NDMI, CRSWIR).
2. Close-up of a field-check target: true colour, colour infrared and CRSWIR in the
   previous and the monitoring year.
3. Spectral signatures (median reflectance per band) of healthy forest (control
   site), a stress polygon and a cut.

Also writes the composites as 8-bit RGB GeoTIFFs for QGIS.

Usage: python scripts/demo_multispectral.py configs/test_kalsnava.yaml F02
"""

from __future__ import annotations

import sys
import warnings

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import geometry_mask
from rasterio.transform import from_origin

from s2forest import viz
from s2forest.config import load_config
from s2forest.fetch import open_cube
from s2forest.indices import compute_indices

plt = viz.plt
WAVELENGTH_NM = {"B02": 490, "B03": 560, "B04": 665, "B05": 705, "B08": 842, "B8A": 865,
                 "B11": 1610, "B12": 2190}
COMPOSITES = {
    "dabiskās krāsas (B04-B03-B02)": ("B04", "B03", "B02"),
    "infrasarkanā (NIR-sarkanā-zaļā, B08-B04-B03)": ("B08", "B04", "B03"),
    "SWIR (B12-B8A-B04)": ("B12", "B8A", "B04"),
    "sarkanā mala (B8A-B05-B04)": ("B8A", "B05", "B04"),
}
INDEX_LABELS = {"ndvi": "NDVI (zaļā biomasa)", "ndre": "NDRE (hlorofils, sarkanā mala)",
                "ndmi": "NDMI (mitrums)", "crswir": "CRSWIR (mitruma deficīts; ↑ = stress)"}


def clearest(cube, year: int, months=(6, 7, 8)) -> int:
    t = pd.DatetimeIndex(cube.time.values)
    sel = np.flatnonzero((t.year == year) & np.isin(t.month, months))
    if sel.size == 0:
        sel = np.flatnonzero(t.year == year)
    return int(sel[np.argmax(cube.valid_fraction.values[sel])])


def stretch(stack: np.ndarray, lo: np.ndarray | None = None, hi: np.ndarray | None = None):
    """Per-band 2-98 % stretch -> 0..1; returns (image, lo, hi) so the same stretch can
    be reused for another date."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        if lo is None:
            lo = np.nanpercentile(stack, 2, axis=(0, 1))
            hi = np.nanpercentile(stack, 98, axis=(0, 1))
    img = np.clip((stack - lo) / np.maximum(hi - lo, 1e-6), 0, 1)
    return np.where(np.isnan(img), 0.85, img), lo, hi


def composite(cube, t: int, bands, lo=None, hi=None):
    s = np.stack([cube[b].isel(time=t).values for b in bands], axis=-1)
    return stretch(s, lo, hi)


def write_rgb_tif(img: np.ndarray, cube, path) -> None:
    x, y = cube.x.values, cube.y.values
    tr = from_origin(float(x[0]) - 5, float(y[0]) + 5, 10, 10)
    arr = (np.clip(img, 0, 1) * 255).astype("uint8").transpose(2, 0, 1)
    with rasterio.open(path, "w", driver="GTiff", width=arr.shape[2], height=arr.shape[1], count=3,
                       dtype="uint8", crs=str(cube.rio.crs), transform=tr, compress="deflate",
                       photometric="RGB") as dst:
        dst.write(arr)


def main(config: str, target_id: str = "F02") -> None:
    cfg = load_config(config)
    year = cfg.time.monitor_year
    out = cfg.run_dir / "figures" / "demo_multispektralais"
    out.mkdir(parents=True, exist_ok=True)
    cube = open_cube(cfg)
    idx = compute_indices(cube, ["ndvi", "ndre", "ndmi", "crswir"])
    t1 = clearest(cube, year)
    t0 = clearest(cube, year - 1)
    d1 = pd.Timestamp(cube.time.values[t1]).strftime("%Y-%m-%d")
    d0 = pd.Timestamp(cube.time.values[t0]).strftime("%Y-%m-%d")
    ext = viz._extent(cube.B04.isel(time=0, drop=True))
    with rasterio.open(cfg.run_dir / "rasters" / "forest_mask.tif") as src:
        forest = src.read(1) == 1

    # ---- 1. whole AOI: composites + indices --------------------------------------------
    fig, axes = plt.subplots(2, 4, figsize=(17, 9))
    for ax, (name, bands) in zip(axes[0], COMPOSITES.items()):
        img, _, _ = composite(cube, t1, bands)
        ax.imshow(img, extent=ext, interpolation="nearest")
        ax.set_title(name, loc="left", fontsize=9)
        write_rgb_tif(img, cube, out / f"kompozits_{'_'.join(bands)}_{d1}.tif")
    for ax, n in zip(axes[1], ["ndvi", "ndre", "ndmi", "crswir"]):
        a = idx[n].isel(time=t1).values
        lo, hi = np.nanpercentile(a[forest], [2, 98])
        im = ax.imshow(a, cmap=viz.SEQ, vmin=lo, vmax=hi, extent=ext, interpolation="nearest")
        ax.set_title(INDEX_LABELS[n], loc="left", fontsize=9)
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.02)
    for ax in axes.ravel():
        ax.set_xticks([]); ax.set_yticks([]); ax.grid(False)
    fig.suptitle(f"Sentinel-2 multispektrālie dati, Kalsnava (5 × 5 km), {d1}: joslu kombinācijas "
                 f"un veģetācijas indeksi (10 m; sarkanā mala un SWIR 20 m)",
                 x=0.01, ha="left", fontsize=11, color=viz.INK)
    fig.tight_layout()
    p1 = viz._save(fig, out / "01_teritorija_kompoziti_indeksi.png")

    # ---- 2. close-up of a field-check target ---------------------------------------------
    fc = gpd.read_file(cfg.run_dir / "field_check" / f"field_check_{year}.gpkg", layer="targets")
    tgt = fc[fc["merka_id"] == target_id].iloc[0]
    minx, miny, maxx, maxy = tgt.geometry.buffer(250).bounds
    sub = cube.sel(x=slice(minx, maxx), y=slice(maxy, miny))
    subi = idx.sel(x=slice(minx, maxx), y=slice(maxy, miny))
    sext = viz._extent(sub.B04.isel(time=0, drop=True))
    fig, axes = plt.subplots(2, 3, figsize=(12, 8.2))
    _, lo_t, hi_t = composite(sub, t1, COMPOSITES["dabiskās krāsas (B04-B03-B02)"])
    _, lo_c, hi_c = composite(sub, t0, COMPOSITES["infrasarkanā (NIR-sarkanā-zaļā, B08-B04-B03)"])
    cr = np.concatenate([subi.crswir.isel(time=t).values.ravel() for t in (t0, t1)])
    crlo, crhi = np.nanpercentile(cr, [2, 98])
    for row, (t, d) in enumerate([(t0, d0), (t1, d1)]):
        img, _, _ = composite(sub, t, COMPOSITES["dabiskās krāsas (B04-B03-B02)"], lo_t, hi_t)
        axes[row, 0].imshow(img, extent=sext, interpolation="nearest")
        axes[row, 0].set_title(f"{d}: dabiskās krāsas", loc="left", fontsize=9)
        img, _, _ = composite(sub, t, COMPOSITES["infrasarkanā (NIR-sarkanā-zaļā, B08-B04-B03)"],
                              lo_c, hi_c)
        axes[row, 1].imshow(img, extent=sext, interpolation="nearest")
        axes[row, 1].set_title(f"{d}: infrasarkanā (vesela veģetācija sarkana)", loc="left", fontsize=9)
        im = axes[row, 2].imshow(subi.crswir.isel(time=t).values, cmap=viz.SEQ, vmin=crlo, vmax=crhi,
                                 extent=sext, interpolation="nearest")
        axes[row, 2].set_title(f"{d}: CRSWIR (tumšāks = lielāks mitruma deficīts)", loc="left",
                               fontsize=9)
        fig.colorbar(im, ax=axes[row, 2], fraction=0.046, pad=0.02)
    for ax in axes.ravel():
        gpd.GeoSeries([tgt.geometry]).boundary.plot(ax=ax, color="#ffffff", lw=2.2)
        gpd.GeoSeries([tgt.geometry]).boundary.plot(ax=ax, color=viz.SERIES[1], lw=1.2)
        ax.set_xlim(sext[0], sext[1]); ax.set_ylim(sext[2], sext[3])
        ax.set_xlabel(""); ax.set_ylabel("")
        ax.set_xticks([]); ax.set_yticks([]); ax.grid(False)
    fig.suptitle(f"Lauka pārbaudes mērķis {target_id} ({tgt['description'][:70]}…): "
                 f"{year - 1} pret {year}", x=0.01, ha="left", fontsize=10.5, color=viz.INK)
    fig.tight_layout()
    p2 = viz._save(fig, out / f"02_tuvplans_{target_id}.png")

    # ---- 3. spectral signatures ---------------------------------------------------------
    x, y = cube.x.values, cube.y.values
    tr = from_origin(float(x[0]) - 5, float(y[0]) + 5, 10, 10)
    polys = gpd.read_file(cfg.run_dir / "vectors" / "suspects.gpkg", layer=f"suspects_{year}")
    cut = polys[polys["type"] == "cut"].sort_values("area_ha", ascending=False).iloc[0]
    groups = {
        "vesels mežs (kontrole F05)": fc[fc["kind"] == "control"].geometry.iloc[0],
        f"stresa vieta ({target_id})": tgt.geometry,
        f"cirte (#{cut['id']})": cut.geometry,
    }
    t = pd.DatetimeIndex(cube.time.values)
    summer = np.flatnonzero((t.year == year) & np.isin(t.month, [7, 8]))
    bands = list(WAVELENGTH_NM)
    fig, ax = plt.subplots(figsize=(9, 5))
    rows = []
    for k, (lab, geom) in enumerate(groups.items()):
        m = ~geometry_mask([geom], out_shape=(len(y), len(x)), transform=tr)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            vals = [float(np.nanmedian(cube[b].isel(time=summer).values[:, m])) for b in bands]
        ax.plot([WAVELENGTH_NM[b] for b in bands], vals, "-o", ms=5, lw=1.8, color=viz.SERIES[k],
                label=lab, mec=viz.SURFACE)
        rows.append({"grupa": lab, **{b: round(v, 4) for b, v in zip(bands, vals)}})
    for k, b in enumerate(bands):
        # stagger labels of neighbouring bands (B04/B05, B08/B8A)
        dy = 4 if b not in ("B05", "B8A") else 14
        ax.annotate(b, (WAVELENGTH_NM[b], ax.get_ylim()[0]), xytext=(0, dy),
                    textcoords="offset points", ha="center", fontsize=7, color=viz.INK_2)
    ax.axvspan(690, 760, color=viz.GRID, alpha=0.6, lw=0)
    ax.text(725, ax.get_ylim()[1] * 0.97, "sarkanā\nmala", ha="center", va="top", fontsize=7.5,
            color=viz.INK_2)
    ax.set_xlabel("viļņa garums, nm")
    ax.set_ylabel("atstarošanās")
    ax.set_title(f"Spektrālās līknes, {year}. g. jūlijs–augusts (mediāna pa datumiem un pikseļiem)",
                 loc="left")
    ax.legend(loc="upper right")
    p3 = viz._save(fig, out / "03_spektralas_liknes.png")
    pd.DataFrame(rows).to_csv(out / "spektralas_liknes.csv", index=False)
    print("\n".join(str(p) for p in (p1, p2, p3)))
    print(f"scenes: {d0} (previous year), {d1} (monitoring year); summer dates for spectra: "
          f"{len(summer)}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "F02")
