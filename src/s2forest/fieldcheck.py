"""Field / drone check: targets, healthy control site, form template, form import.

`prepare`: selected stress polygons, the highest-risk cut edge and one healthy
control site -> field_check_<year>.gpkg (polygons + centroid points), KML and a
CSV field form template with one row per target.

Control site: a compact 4 x 4 pixel (0.16 ha) block of analysed conifer forest with
no anomaly (status 0), monitoring-year CRSWIR z close to 0 (|median| < 0.5, max
< 1.5), >= 100 m from any suspect polygon or cut-edge zone and >= 50 m from roads.
Among candidates the one whose baseline summer NDVI / CRSWIR level is closest to
the mean of the checked stress polygons is chosen (a spectral stand-type proxy:
species / age data are not available for state forest), preferring sites close
to the stress targets (logistics).

`import`: reads a filled form (CSV, ';' or ',' separated, UTF-8 with or without
BOM), validates values and turns it into reference polygons for `validate`
(event date = inspection date) plus a predicted-vs-observed table.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize
from scipy import ndimage
from shapely.geometry import box

from .config import Config

FORM_COLUMNS = [
    "merka_id", "datums", "laiks", "gps_platums", "gps_garums", "gps_precizitate_m",
    "apsekotajs", "apskatito_koku_skaits", "koki_ar_urbumu_miltiem", "koki_ar_sveku_tecem",
    "koki_ar_ieejas_atverem", "koki_ar_mizas_lobisanos", "vainaga_krasa", "foto_numuri",
    "secinajums", "cita_bojajuma_veids", "piezimes",
]
CROWN_VALUES = ["zala", "dzeltenzala", "sarkanbruna", "peleka", "jaukta"]
CONCLUSIONS = ["mizgrauzi", "cits_bojajums", "vesels", "nav_skaidrs"]
COUNT_COLUMNS = ["apskatito_koku_skaits", "koki_ar_urbumu_miltiem", "koki_ar_sveku_tecem",
                 "koki_ar_ieejas_atverem", "koki_ar_mizas_lobisanos"]


def _read(path: Path) -> tuple[np.ndarray, object]:
    with rasterio.open(path) as src:
        return src.read(), src.transform


def control_site(cfg: Config, stress: gpd.GeoDataFrame, avoid: gpd.GeoDataFrame,
                 roads: gpd.GeoDataFrame | None, block_px: int = 4,
                 min_dist_m: float = 100.0, road_dist_m: float = 50.0) -> gpd.GeoDataFrame:
    year = cfg.time.monitor_year
    r = cfg.run_dir / "rasters"
    codes, tr = _read(r / "forest_mask.tif")
    codes = codes[0]
    status = _read(r / "anomaly" / f"status_{year}.tif")[0][0]
    z = _read(r / "anomaly" / f"z_{cfg.anomaly.primary_index}_{year}.tif")[0]
    ndvi_b = _read(r / "ndvi_summer_median_baseline.tif")[0][0]
    crs_b = np.nanmedian(np.stack([_read(r / "indices" / f"crswir_summer_median_{y}.tif")[0][0]
                                   for y in cfg.time.baseline_year_list]), axis=0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        zmed = np.nanmedian(z, axis=0)
        zmax = np.nanmax(z, axis=0)
    res = abs(tr.a)
    shape = codes.shape
    ok = (codes == 1) & (status == 0) & (np.abs(zmed) < 0.5) & (zmax < 1.5)
    ok &= np.isfinite(ndvi_b) & np.isfinite(crs_b)
    if len(avoid):
        near = rasterize([(g.buffer(min_dist_m), 1) for g in avoid.geometry], out_shape=shape,
                         transform=tr, fill=0, dtype="uint8").astype(bool)
        ok &= ~near
    if roads is not None and len(roads):
        rmask = rasterize([(g.buffer(road_dist_m), 1) for g in roads.to_crs(cfg.data.crs).geometry],
                          out_shape=shape, transform=tr, fill=0, dtype="uint8").astype(bool)
        ok &= ~rmask
    # block_px x block_px windows fully inside `ok`
    full = ndimage.uniform_filter(ok.astype("float32"), size=block_px, mode="constant") >= 0.999
    cand = np.argwhere(full)
    if cand.size == 0:
        raise RuntimeError("No control site candidate found")
    # target levels: mean baseline values inside the stress polygons
    smask = rasterize([(g, 1) for g in stress.geometry], out_shape=shape, transform=tr, fill=0,
                      dtype="uint8").astype(bool)
    t_ndvi, t_crs = float(np.nanmean(ndvi_b[smask])), float(np.nanmean(crs_b[smask]))
    sd_ndvi = float(np.nanstd(ndvi_b[codes == 1])) or 1.0
    sd_crs = float(np.nanstd(crs_b[codes == 1])) or 1.0
    win_ndvi = ndimage.uniform_filter(np.nan_to_num(ndvi_b), size=block_px, mode="constant")
    win_crs = ndimage.uniform_filter(np.nan_to_num(crs_b), size=block_px, mode="constant")
    centre = np.array(stress.geometry.union_all().centroid.coords[0])
    rows, cols = cand[:, 0], cand[:, 1]
    xs, ys = rasterio.transform.xy(tr, rows, cols)
    dist_km = np.hypot(np.asarray(xs) - centre[0], np.asarray(ys) - centre[1]) / 1000
    score = (np.abs(win_ndvi[rows, cols] - t_ndvi) / sd_ndvi
             + np.abs(win_crs[rows, cols] - t_crs) / sd_crs + 0.25 * dist_km)
    k = int(np.argmin(score))
    rr, cc = rows[k], cols[k]
    h = block_px // 2
    r0, c0 = rr - h, cc - h          # uniform_filter window centred at (rr, cc)
    x0, y0 = tr * (c0, r0)
    geom = box(x0, y0 - block_px * res, x0 + block_px * res, y0)
    sl = (slice(r0, r0 + block_px), slice(c0, c0 + block_px))
    return gpd.GeoDataFrame([{
        "kind": "control", "source_id": None, "area_ha": round(geom.area / 1e4, 2),
        "ndvi_baseline": round(float(np.nanmean(ndvi_b[sl])), 3),
        "crswir_baseline": round(float(np.nanmean(crs_b[sl])), 3),
        "target_ndvi_baseline": round(t_ndvi, 3), "target_crswir_baseline": round(t_crs, 3),
        "z_median": round(float(np.nanmean(zmed[sl])), 2), "z_max": round(float(np.nanmax(zmax[sl])), 2),
        "dist_to_stress_km": round(float(dist_km[k]), 2),
        "description": ("Kontroles vieta: analizēts skujkoku mežs bez anomālijas (z ≈ 0), "
                        "bāzes vasaras NDVI/CRSWIR tuvs pārbaudāmajiem stresa poligoniem; "
                        "uz vietas pārliecināties, ka audze ir līdzīga (suga, vecums)."),
        "geometry": geom}], geometry="geometry", crs=cfg.data.crs)


def prepare(cfg: Config, stress_ids: list[int], out_dir: Path) -> dict[str, Path]:
    year = cfg.time.monitor_year
    gpkg = cfg.run_dir / "vectors" / "suspects.gpkg"
    polys = gpd.read_file(gpkg, layer=f"suspects_{year}")
    targets = gpd.read_file(gpkg, layer="drone_targets")
    stress = polys[polys["id"].isin(stress_ids)].copy()
    missing = set(stress_ids) - set(stress["id"])
    if missing:
        raise KeyError(f"polygon ids not found in suspects_{year}: {sorted(missing)}")
    rows = []
    for _, p in stress.set_index("id").loc[stress_ids].reset_index().iterrows():
        rows.append({"kind": "stress", "source_id": int(p["id"]), "area_ha": p["area_ha"],
                     "description": (f"Stresa poligons #{p['id']} ({p['status']}), pirmoreiz "
                                     f"{p['first_detected']}"
                                     + (", izmaiņa sākusies iepr. rudenī"
                                        if bool(p.get("onset_prev_autumn", False)) else "")
                                     + f"; ticamība {p['confidence']:.2f}"),
                     "geometry": p.geometry})
    edges = targets[targets["kind"] == "cut_edge"].sort_values("risk_score", ascending=False)
    if len(edges):
        e = edges.iloc[0]
        rows.append({"kind": "cut_edge", "source_id": e["target_id"], "area_ha": e["area_ha"],
                     "description": f"Augsta riska cirtes mala {e['target_id']} (risks "
                                    f"{e['risk_score']:.2f}): {e['description']}",
                     "geometry": e.geometry})
    sel = gpd.GeoDataFrame(rows, geometry="geometry", crs=cfg.data.crs)
    from .linear import fetch_osm_lines
    from .fetch import build_grid

    grid = build_grid(cfg)
    try:
        roads = fetch_osm_lines(grid.geobox, cfg.linear_features, cfg.cache_dir / grid.key)
        roads = roads[roads["kind"] == "road"]
    except Exception:  # noqa: BLE001 - control site can be chosen without roads
        roads = None
    avoid = pd.concat([polys[["geometry"]], targets[["geometry"]]], ignore_index=True)
    ctrl = control_site(cfg, stress, gpd.GeoDataFrame(avoid, crs=cfg.data.crs), roads)
    allt = gpd.GeoDataFrame(pd.concat([sel, ctrl], ignore_index=True), crs=cfg.data.crs)
    allt.insert(0, "merka_id", [f"F{i:02d}" for i in range(1, len(allt) + 1)])
    c = allt.geometry.centroid.to_crs(4326)
    allt["centroid_lat"], allt["centroid_lon"] = c.y.round(6), c.x.round(6)
    pt = allt.geometry.representative_point().to_crs(4326)
    allt["point_lat"], allt["point_lon"] = pt.y.round(6), pt.x.round(6)

    out_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    g = out_dir / f"field_check_{year}.gpkg"
    allt.to_file(g, layer="targets", driver="GPKG", engine="pyogrio")
    pts = allt.copy()
    pts["geometry"] = allt.geometry.representative_point()
    pts.to_file(g, layer="points", driver="GPKG", engine="pyogrio")
    out["gpkg"] = g
    for layer, gdf in (("targets", allt), ("points", pts)):
        k = out_dir / f"field_check_{year}_{layer}.kml"
        if k.exists():
            k.unlink()
        gdf.to_crs(4326).rename(columns={"merka_id": "Name", "description": "Description"})[
            ["Name", "Description", "kind", "centroid_lat", "centroid_lon", "geometry"]
        ].to_file(k, driver="KML", engine="pyogrio")
        out[f"kml_{layer}"] = k
    form = pd.DataFrame({c: [""] * len(allt) for c in FORM_COLUMNS})
    form["merka_id"] = allt["merka_id"]
    f = out_dir / f"lauka_veidlapa_{year}.csv"
    form.to_csv(f, index=False, sep=";", encoding="utf-8-sig")
    out["form"] = f
    allt.drop(columns="geometry").to_csv(out_dir / f"field_check_{year}.csv", index=False,
                                         sep=";", encoding="utf-8-sig")
    return out


def _parse_date(v: str):
    """ISO (2026-10-15) or Latvian day-first (15.10.2026)."""
    v = str(v).strip()
    fmt = "%Y-%m-%d" if len(v) >= 10 and v[4] == "-" else "%d.%m.%Y"
    return pd.to_datetime(v, format=fmt, errors="coerce")


def read_form(path: Path) -> tuple[pd.DataFrame, list[str]]:
    """Read and validate a filled form. Returns (rows, list of problems)."""
    raw = Path(path).read_text(encoding="utf-8-sig")
    sep = ";" if raw.splitlines()[0].count(";") >= raw.splitlines()[0].count(",") else ","
    from io import StringIO

    df = pd.read_csv(StringIO(raw), sep=sep, dtype=str).fillna("")
    problems = []
    miss = [c for c in FORM_COLUMNS if c not in df]
    if miss:
        problems.append(f"trūkst kolonnu: {miss}")
        return df, problems
    df = df[df["merka_id"].str.strip() != ""].copy()
    for i, r in df.iterrows():
        tag = f"rinda {r['merka_id']}"
        if r["secinajums"] not in CONCLUSIONS:
            problems.append(f"{tag}: secinajums '{r['secinajums']}' nav no {CONCLUSIONS}")
        if r["vainaga_krasa"] and r["vainaga_krasa"] not in CROWN_VALUES:
            problems.append(f"{tag}: vainaga_krasa '{r['vainaga_krasa']}' nav no {CROWN_VALUES}")
        d = _parse_date(r["datums"])
        if pd.isna(d):
            problems.append(f"{tag}: nederīgs datums '{r['datums']}'")
        for c in COUNT_COLUMNS:
            if r[c] and not str(r[c]).strip().isdigit():
                problems.append(f"{tag}: {c} nav vesels skaitlis ('{r[c]}')")
        for c in ("gps_platums", "gps_garums"):
            if r[c]:
                try:
                    float(str(r[c]).replace(",", "."))
                except ValueError:
                    problems.append(f"{tag}: {c} nav skaitlis ('{r[c]}')")
    df["datums"] = [None if pd.isna(d := _parse_date(v)) else d.date() for v in df["datums"]]
    return df, problems


def form_to_references(form: pd.DataFrame, targets: gpd.GeoDataFrame
                       ) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    """Join the form to the field-check targets -> references (all rows; filter on
    `secinajums` with reference.reason_values) and a predicted-vs-observed table."""
    t = targets.set_index("merka_id")
    unknown = sorted(set(form["merka_id"]) - set(t.index))
    if unknown:
        raise KeyError(f"merka_id not in field_check targets: {unknown}")
    ref = gpd.GeoDataFrame(form.merge(targets[["merka_id", "kind", "source_id", "geometry"]],
                                      on="merka_id"), geometry="geometry", crs=targets.crs)
    table = pd.crosstab(ref["kind"], ref["secinajums"]).reindex(
        columns=CONCLUSIONS, fill_value=0)
    return ref, table
