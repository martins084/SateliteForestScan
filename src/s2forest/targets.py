"""Drone target layer: where to send the DJI Mavic 3M for multispectral verification.

Two kinds of targets:

* ``stress`` - suspect stress polygons whose status is in `targets.statuses`
  (default: new, persistent; "recovered" ones are left out);
* ``cut_edge`` - high-risk zone: a band (default 30 m) of analysed conifer
  forest along cuts of the monitoring year and the previous year. Newly exposed
  spruce edges are a known preferred attack site of Ips typographus.

Every target gets its centroid in WGS84 and a short Latvian description for
the flight planner. Exported to the run's GeoPackage and as GeoJSON / KML.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr
from rasterio.features import rasterize, shapes
from rasterio.transform import from_origin
from scipy import ndimage
from shapely.geometry import shape

from .config import Config

STATUS_LV = {"new": "jauns", "persistent": "noturīgs", "recovered": "atkopies"}


def _transform(template: xr.DataArray):
    x, y = template.x.values, template.y.values
    res = float(abs(x[1] - x[0]))
    return from_origin(float(x[0]) - res / 2, float(y[0]) + res / 2, res, res), res


def _disk(r: int) -> np.ndarray:
    yy, xx = np.ogrid[-r:r + 1, -r:r + 1]
    return xx * xx + yy * yy <= r * r


def cut_edge_zones(cfg: Config, polygons: gpd.GeoDataFrame, feats: xr.Dataset,
                   conifer: np.ndarray, template: xr.DataArray) -> gpd.GeoDataFrame:
    """Band of conifer forest around recent cuts (monitoring-year cut polygons plus
    baseline-period cuts of the last `cut_edge_years - 1` years).

    One zone per cut (>= cut_edge_min_cut_ha); band fragments split by
    non-conifer pixels are kept together as one multipolygon target.
    """
    tcfg = cfg.targets
    tr, res = _transform(template)
    shape_ = template.shape
    cut_year = np.full(shape_, np.nan, dtype="float32")
    if len(polygons):
        cp = polygons[polygons["type"] == "cut"]
        if len(cp):
            m = rasterize([(g, 1) for g in cp.geometry], out_shape=shape_, transform=tr,
                          fill=0, dtype="uint8").astype(bool)
            cut_year[m] = cfg.time.monitor_year
    first_year = cfg.time.monitor_year - tcfg.cut_edge_years + 1
    if "baseline_cut_year" in feats and "baseline_disturbed" in feats:
        cy = feats["baseline_cut_year"].values
        with np.errstate(invalid="ignore"):
            # only coherent patches (the area-filtered baseline_disturbed mask)
            b = (cy >= first_year) & (np.nan_to_num(feats["baseline_disturbed"].values) > 0)
        cut_year = np.where(b & np.isnan(cut_year), cy, cut_year)
    cuts = np.isfinite(cut_year)

    empty = gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs=cfg.data.crs)
    lab, n = ndimage.label(cuts, structure=np.ones((3, 3), dtype=int))
    if n == 0:
        return empty
    r = max(1, int(round(tcfg.cut_edge_width_m / res)))
    disk = _disk(r)
    px_ha = res * res / 1e4
    min_cut_px = int(np.ceil(tcfg.cut_edge_min_cut_ha / px_ha))
    min_band_px = int(np.ceil(tcfg.cut_edge_min_area_ha / px_ha))
    rows = []
    for k, sl in enumerate(ndimage.find_objects(lab), start=1):
        if sl is None:
            continue
        ys = slice(max(sl[0].start - r, 0), min(sl[0].stop + r, shape_[0]))
        xs = slice(max(sl[1].start - r, 0), min(sl[1].stop + r, shape_[1]))
        comp = lab[ys, xs] == k
        n_cut = int(comp.sum())
        if n_cut < min_cut_px:
            continue
        band = ndimage.binary_dilation(comp, structure=disk) & ~cuts[ys, xs] & conifer[ys, xs]
        n_band = int(band.sum())
        if n_band < min_band_px:
            continue
        sub_tr = tr * tr.translation(xs.start, ys.start)
        geoms = [shape(g) for g, v in shapes(band.astype("uint8"), mask=band, transform=sub_tr,
                                             connectivity=8)]
        rows.append({"area_ha": round(n_band * px_ha, 3), "cut_area_ha": round(n_cut * px_ha, 2),
                     "cut_year": int(np.nanmax(cut_year[ys, xs][comp])),
                     "geometry": gpd.GeoSeries(geoms).union_all()})
    if not rows:
        return empty
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=cfg.data.crs)


def build_targets(cfg: Config, polygons: gpd.GeoDataFrame, feats: xr.Dataset,
                  conifer: np.ndarray, template: xr.DataArray) -> gpd.GeoDataFrame:
    tcfg = cfg.targets
    prim = cfg.anomaly.primary_index
    parts = []
    if len(polygons) and "status" in polygons:
        s = polygons[(polygons["type"] == "stress") & polygons["status"].isin(tcfg.statuses)]
        for _, p in s.iterrows():
            desc = (f"Stress ({STATUS_LV.get(p['status'], p['status'])}), {p['area_ha']:.2f} ha; "
                    f"pirmoreiz {p['first_detected']}; {prim.upper()} izmaiņa "
                    f"{p.get(f'delta_{prim}', float('nan')):+.3f}; ticamība {p['confidence']:.2f}; "
                    f"poligons #{p['id']}")
            parts.append({"kind": "stress", "status": p["status"], "source_id": int(p["id"]),
                          "area_ha": p["area_ha"], "first_detected": p["first_detected"],
                          "confidence": p["confidence"], "priority": 1 if p["status"] == "persistent" else 2,
                          "description": desc, "geometry": p.geometry})
    if tcfg.cut_edge_enabled:
        edges = cut_edge_zones(cfg, polygons, feats, conifer, template)
        for _, e in edges.iterrows():
            desc = (f"Cirtes mala: {tcfg.cut_edge_width_m:.0f} m josla skujkoku mežā gar "
                    f"{e['cut_year']}. g. cirti ({e['cut_area_ha']:.1f} ha), josla {e['area_ha']:.2f} ha; "
                    f"augsta riska zona, anomālija nav noteikta")
            parts.append({"kind": "cut_edge", "status": "risk_zone", "source_id": None,
                          "area_ha": e["area_ha"], "first_detected": None, "confidence": None,
                          "priority": 3, "description": desc, "geometry": e.geometry})
    if not parts:
        return gpd.GeoDataFrame(columns=["target_id", "geometry"], geometry="geometry",
                                crs=cfg.data.crs)
    gdf = gpd.GeoDataFrame(parts, geometry="geometry", crs=cfg.data.crs)
    gdf = gdf.sort_values(["priority", "confidence", "area_ha"],
                          ascending=[True, False, False], na_position="last").reset_index(drop=True)
    gdf.insert(0, "target_id", [f"T{i:03d}" for i in range(1, len(gdf) + 1)])
    cent = gdf.geometry.centroid.to_crs(4326)
    gdf["centroid_lon"] = cent.x.round(6)
    gdf["centroid_lat"] = cent.y.round(6)
    # For ring-shaped zones the centroid can fall outside; give a point on the target too.
    pt = gdf.geometry.representative_point().to_crs(4326)
    gdf["point_lon"] = pt.x.round(6)
    gdf["point_lat"] = pt.y.round(6)
    return gdf


def write_targets(cfg: Config, targets: gpd.GeoDataFrame, gpkg: Path) -> dict[str, Path]:
    year = cfg.time.monitor_year
    vdir = gpkg.parent
    out: dict[str, Path] = {}
    targets.to_file(gpkg, layer="drone_targets", driver="GPKG", engine="pyogrio")
    out["drone_targets_gpkg"] = gpkg
    wgs = targets.to_crs(4326)
    gj = vdir / f"drone_targets_{year}.geojson"
    wgs.to_file(gj, driver="GeoJSON", engine="pyogrio")
    out["drone_targets_geojson"] = gj
    kml = vdir / f"drone_targets_{year}.kml"
    k = wgs.rename(columns={"target_id": "Name", "description": "Description"})
    k = k[["Name", "Description", "kind", "priority", "centroid_lon", "centroid_lat", "geometry"]]
    if kml.exists():
        kml.unlink()
    k.to_file(kml, driver="KML", engine="pyogrio")
    out["drone_targets_kml"] = kml
    pd.DataFrame(targets.drop(columns="geometry")).to_csv(
        cfg.run_dir / "tables" / f"drone_targets_{year}.csv", index=False)
    return out
