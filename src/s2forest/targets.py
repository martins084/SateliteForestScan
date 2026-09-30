"""Drone target layer: where to send the DJI Mavic 3M for multispectral verification.

Two kinds of targets:

* ``stress`` - suspect stress polygons whose status is in `targets.statuses`
  (default: new, persistent; "recovered" ones are left out);
* ``cut_edge`` - high-risk zone: a band (default 30 m) of analysed conifer
  forest along cuts of the monitoring year and the previous year. Newly exposed
  spruce edges are a known preferred attack site of Ips typographus.

Every target gets its centroid in WGS84 and a short Latvian description for
the flight planner. Stress targets always rank first (persistent, then new);
cut-edge zones follow, ordered by `risk_score` (edge orientation, cut
freshness, conifer share; see TargetsConfig).

Targets are then grouped into MISSIONS: greedily, starting from the highest
priority unassigned target, the nearest targets (within `mission_max_gap_m`)
are added while the convex hull of the buffered members stays below
`mission_max_area_ha`. Missions are ranked by their best target priority, then
their highest target value (risk / confidence), then total value; the top `max_missions` are exported. Exported to the run's
GeoPackage and as GeoJSON / KML.
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
    # For every pixel: offset to the nearest cut pixel -> direction the forest wall faces.
    _, (near_r, near_c) = ndimage.distance_transform_edt(~cuts, return_indices=True)
    rr, cc = np.indices(shape_)
    east = (near_c - cc).astype("float32")
    north = -(near_r - rr).astype("float32")
    face = (np.degrees(np.arctan2(east, north)) + 360) % 360
    orient_px = (1 + np.cos(np.radians(face - tcfg.risk_peak_azimuth))) / 2
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
        ring = ndimage.binary_dilation(comp, structure=disk) & ~cuts[ys, xs]
        band = ring & conifer[ys, xs]
        n_band = int(band.sum())
        if n_band < min_band_px:
            continue
        year = int(np.nanmax(cut_year[ys, xs][comp]))
        o = orient_px[ys, xs][band]
        f = face[ys, xs][band]
        comps = {
            "orientation": float(o.mean()),
            "freshness": float(max(0.0, 1 - (cfg.time.monitor_year - year) / tcfg.cut_edge_years)),
            "conifer": float(n_band / max(int(ring.sum()), 1)),
        }
        w = tcfg.risk_weights
        wsum = sum(w.get(c, 0.0) for c in comps) or 1.0
        risk = sum(w.get(c, 0.0) * v for c, v in comps.items()) / wsum
        sub_tr = tr * tr.translation(xs.start, ys.start)
        geoms = [shape(g) for g, v in shapes(band.astype("uint8"), mask=band, transform=sub_tr,
                                             connectivity=8)]
        rows.append({"area_ha": round(n_band * px_ha, 3), "cut_area_ha": round(n_cut * px_ha, 2),
                     "cut_year": year, "risk_score": round(risk, 3),
                     "risk_orientation": round(comps["orientation"], 3),
                     "risk_freshness": round(comps["freshness"], 3),
                     "risk_conifer": round(comps["conifer"], 3),
                     # share of the band whose wall faces S..W (157.5-292.5 deg)
                     "sw_exposed_share": round(float(np.mean((f >= 157.5) & (f <= 292.5))), 2),
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
                    f"poligons #{p['id']}"
                    + ("; IEGARENS - iespējams lineārs objekts (ceļš, grāvis)"
                       if bool(p.get("linear_feature", False)) else "")
                    + (f"; {p['dist_to_road_m']:.0f} m no ceļa"
                       if pd.notna(p.get("dist_to_road_m", np.nan)) and p["dist_to_road_m"] < 60 else ""))
            parts.append({"kind": "stress", "status": p["status"], "source_id": int(p["id"]),
                          "linear_feature": bool(p.get("linear_feature", False)),
                          "area_ha": p["area_ha"], "first_detected": p["first_detected"],
                          "confidence": p["confidence"], "risk_score": None,
                          "priority": 1 if p["status"] == "persistent" else 2,
                          # stress targets always outrank cut edges (risk_score <= 1)
                          "value": 1.0 + float(p["confidence"]),
                          "description": desc, "geometry": p.geometry})
    if tcfg.cut_edge_enabled:
        edges = cut_edge_zones(cfg, polygons, feats, conifer, template)
        for _, e in edges.iterrows():
            desc = (f"Cirtes mala: {tcfg.cut_edge_width_m:.0f} m josla skujkoku mežā gar "
                    f"{e['cut_year']}. g. cirti ({e['cut_area_ha']:.1f} ha), josla {e['area_ha']:.2f} ha; "
                    f"risks {e['risk_score']:.2f} (D-R vērsta mala {e['sw_exposed_share']:.0%}); "
                    f"anomālija nav noteikta")
            parts.append({"kind": "cut_edge", "status": "risk_zone", "source_id": None,
                          "area_ha": e["area_ha"], "first_detected": None, "confidence": None,
                          "risk_score": e["risk_score"], "risk_orientation": e["risk_orientation"],
                          "risk_freshness": e["risk_freshness"], "risk_conifer": e["risk_conifer"],
                          "sw_exposed_share": e["sw_exposed_share"], "cut_year": e["cut_year"],
                          "priority": 3, "value": float(e["risk_score"]),
                          "description": desc, "geometry": e.geometry})
    if not parts:
        return gpd.GeoDataFrame(columns=["target_id", "geometry"], geometry="geometry",
                                crs=cfg.data.crs)
    gdf = gpd.GeoDataFrame(parts, geometry="geometry", crs=cfg.data.crs)
    gdf = gdf.sort_values(["priority", "value", "area_ha"],
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


def build_missions(cfg: Config, targets: gpd.GeoDataFrame
                   ) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Group targets into flight missions. Returns (missions, targets with mission_id)."""
    from shapely.ops import unary_union

    tcfg = cfg.targets
    t = targets.copy()
    t["mission_id"] = None
    empty = gpd.GeoDataFrame(columns=["mission_id", "geometry"], geometry="geometry",
                             crs=targets.crs)
    if t.empty:
        return empty, t
    max_area = tcfg.mission_max_area_ha * 1e4
    buf = tcfg.mission_buffer_m
    order = list(t.sort_values(["priority", "value"], ascending=[True, False]).index)
    unassigned = set(order)
    groups = []
    while unassigned:
        seed = next(i for i in order if i in unassigned)
        members = [seed]
        unassigned.discard(seed)
        hull = t.geometry[seed].buffer(buf).convex_hull
        while True:
            cand = [i for i in order if i in unassigned
                    and t.geometry[i].distance(hull) <= tcfg.mission_max_gap_m]
            # prefer higher priority, then the nearest
            cand.sort(key=lambda i: (t.at[i, "priority"], t.geometry[i].distance(hull)))
            added = False
            for i in cand:
                new_hull = unary_union([t.geometry[j] for j in members + [i]]).buffer(buf).convex_hull
                if new_hull.area <= max_area:
                    members.append(i)
                    unassigned.discard(i)
                    hull = new_hull
                    added = True
                    break
            if not added:
                break
        groups.append((members, hull))

    rows = []
    for members, hull in groups:
        sub = t.loc[members]
        n_stress = int((sub["kind"] == "stress").sum())
        rows.append({"members": members, "priority": int(sub["priority"].min()),
                     "max_value": float(sub["value"].max()),
                     "value": float(sub["value"].sum()), "n_targets": len(members),
                     "n_stress": n_stress, "n_cut_edge": len(members) - n_stress,
                     "flight_area_ha": round(hull.area / 1e4, 2),
                     "oversize": bool(hull.area > max_area), "geometry": hull})
    m = gpd.GeoDataFrame(rows, geometry="geometry", crs=targets.crs)
    # Best target first (a mission is worth flying for its riskiest target), then total value.
    m = m.sort_values(["priority", "max_value", "value"],
                      ascending=[True, False, False]).reset_index(drop=True)
    m.insert(0, "mission_id", [f"M{i:02d}" for i in range(1, len(m) + 1)])
    m.insert(1, "rank", np.arange(1, len(m) + 1))
    for _, r in m.iterrows():
        t.loc[r["members"], "mission_id"] = r["mission_id"]
    m["target_ids"] = [",".join(t.loc[mem, "target_id"]) for mem in m["members"]]
    m = m.drop(columns="members")
    c = m.geometry.centroid.to_crs(4326)
    m["centroid_lon"] = c.x.round(6)
    m["centroid_lat"] = c.y.round(6)
    m["description"] = [
        (f"Misija {r['mission_id']}: {r['n_stress']} stresa mērķi, {r['n_cut_edge']} cirtes malas; "
         f"lidojuma laukums {r['flight_area_ha']:.1f} ha"
         + (" (pārsniedz ieteikto, var būt vajadzīgas vairākas baterijas)" if r["oversize"] else "")
         + f"; mērķi {r['target_ids']}")
        for _, r in m.iterrows()]
    return m, t


def _write_kml(gdf: gpd.GeoDataFrame, path: Path, name_col: str, cols: list[str]) -> Path:
    k = gdf.to_crs(4326).rename(columns={name_col: "Name", "description": "Description"})
    k = k[["Name", "Description", *cols, "geometry"]]
    if path.exists():
        path.unlink()
    k.to_file(path, driver="KML", engine="pyogrio")
    return path


def write_targets(cfg: Config, targets: gpd.GeoDataFrame, gpkg: Path,
                  missions: gpd.GeoDataFrame | None = None) -> dict[str, Path]:
    """Write drone targets (all) and missions (top `max_missions`)."""
    year = cfg.time.monitor_year
    vdir = gpkg.parent
    tdir = cfg.run_dir / "tables"
    tdir.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path] = {}
    targets.to_file(gpkg, layer="drone_targets", driver="GPKG", engine="pyogrio")
    out["drone_targets_gpkg"] = gpkg
    gj = vdir / f"drone_targets_{year}.geojson"
    targets.to_crs(4326).to_file(gj, driver="GeoJSON", engine="pyogrio")
    out["drone_targets_geojson"] = gj
    out["drone_targets_kml"] = _write_kml(targets, vdir / f"drone_targets_{year}.kml", "target_id",
                                          ["kind", "priority", "centroid_lon", "centroid_lat"])
    pd.DataFrame(targets.drop(columns="geometry")).to_csv(tdir / f"drone_targets_{year}.csv",
                                                          index=False)
    if missions is not None:
        top = missions.head(cfg.targets.max_missions)
        top.to_file(gpkg, layer="drone_missions", driver="GPKG", engine="pyogrio")
        out["drone_missions_gpkg"] = gpkg
        top.to_crs(4326).to_file(vdir / f"drone_missions_{year}.geojson", driver="GeoJSON",
                                 engine="pyogrio")
        out["drone_missions_kml"] = _write_kml(
            top, vdir / f"drone_missions_{year}.kml", "mission_id",
            ["rank", "n_stress", "n_cut_edge", "flight_area_ha", "centroid_lon", "centroid_lat"])
        pd.DataFrame(missions.drop(columns="geometry")).to_csv(
            tdir / f"drone_missions_{year}.csv", index=False)
    return out
