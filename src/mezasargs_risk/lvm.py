"""Stage 5a: LVM open damage polygons (LVM_BOJAJUMI, CC0, state forest) - inventory, official
statistics, timing against EFDA harvest, and an independent check of s2forest in Kalsnava.

Fields [P: lvm_bojajumi_shp.docx, data.gov.lv]: DISTRBYEAR = year the damage was *registered*
(text, 4), DAMAGESUBT = damage subtype (codes below). There is no severity and no date.
The analysis set is LVM land (LVM_ZEMES_VIENIBAS, land units managed by LVM) - polygons outside
it are counted, not dropped.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize

from .config import LvmConfig, RiskConfig
from .efda import layer

# DAMAGESUBT classifier [P: lvm_bojajumi_shp.docx]
SUBTYPES = {0: "Nav ievadīts", 100: "Vējgāze, snieglauze", 200: "Ūdens", 400: "Uguns", 500: "Slimības",
            610: "Kaitēkļi - skuju, lapu grauzēji", 620: "Kaitēkļi - stumbru kaitēkļi",
            630: "Kaitēkļi - jaunaudžu kaitēkļi", 700: "Saimnieciskā darbība", 800: "Cits",
            900: "Sausums", 3000: "Dzīvnieki - cits", 3001: "Dzīvnieki - alnis",
            3002: "Dzīvnieki - staltbriedis", 3003: "Dzīvnieki - meža cūka", 3004: "Dzīvnieki - stirna",
            3006: "Dzīvnieki - mednis", 3007: "Dzīvnieki - alnis un staltbriedis",
            3008: "Dzīvnieki - alnis un stirna", 3009: "Dzīvnieki - staltbriedis un stirna",
            30010: "Dzīvnieki - bebrs"}
PX_HA = 0.09


def _zip(path, member) -> str:
    return f"zip://{path.resolve()}!{member}"


def load_damage(c: LvmConfig, bbox=None) -> gpd.GeoDataFrame:
    g = gpd.read_file(_zip(c.damage, c.damage_member), bbox=bbox)
    g["year_raw"] = g["DISTRBYEAR"]
    g["year"] = pd.to_numeric(g["DISTRBYEAR"], errors="coerce").astype("Int64")
    g["subtype"] = pd.to_numeric(g["DAMAGESUBT"], errors="coerce").astype("Int64")
    g["empty"] = g.geometry.isna() | g.geometry.is_empty
    g["valid"] = ~g["empty"] & g.geometry.is_valid
    g["ha"] = np.where(g["empty"], np.nan, g.area / 1e4)
    return g


def load_land(c: LvmConfig, bbox=None) -> gpd.GeoDataFrame:
    return gpd.read_file(_zip(c.land_units, c.land_units_member), bbox=bbox)


def inventory(g: gpd.GeoDataFrame, land: gpd.GeoDataFrame, c: LvmConfig) -> pd.DataFrame:
    """Field / code / year / geometry checks, one row per check."""
    ok_year = g["year"].between(2000, c.damage_snapshot.year)
    known = g["subtype"].isin(list(SUBTYPES))
    geo = g[~g["empty"]]
    inside = gpd.sjoin(geo[["geometry"]].assign(geometry=geo.representative_point()),
                       land[["geometry"]], predicate="within", how="left")
    in_land = inside["index_right"].notna().groupby(level=0).any()
    rows = [("fields", ", ".join(c for c in g.columns if c in ("DISTRBYEAR", "DAMAGESUBT")) or "-"),
            ("records", len(g)),
            ("geometry null/empty", int(g["empty"].sum())),
            ("geometry invalid (non-empty)", int((~g["empty"] & ~g["valid"]).sum())),
            ("multipolygons", int((geo.geom_type == "MultiPolygon").sum())),
            ("crs", str(g.crs)),
            ("DISTRBYEAR non-numeric", int(g["year"].isna().sum())),
            (f"DISTRBYEAR outside 2000-{c.damage_snapshot.year}", int((g["year"].notna() & ~ok_year).sum())),
            ("DISTRBYEAR values outside range", ", ".join(sorted({str(v) for v in g.loc[g["year"].notna() & ~ok_year, "year_raw"]}))),
            ("year range (plausible)", f"{int(g.loc[ok_year, 'year'].min())}-{int(g.loc[ok_year, 'year'].max())}"),
            ("DAMAGESUBT not in classifier", int((~known).sum())),
            ("polygon point inside LVM land units", f"{in_land.mean():.3f}"),
            ("LVM land units", len(land)),
            ("LVM land area, ha", round(float(land.area.sum() / 1e4)))]
    return pd.DataFrame(rows, columns=["check", "value"])


def annual(g: gpd.GeoDataFrame, c: LvmConfig) -> pd.DataFrame:
    """Polygons and ha per registration year x subtype (plausible years only)."""
    x = g[~g["empty"] & g["year"].between(2000, c.damage_snapshot.year)]
    t = x.groupby(["year", "subtype"]).ha.agg(n="count", ha="sum").reset_index()
    t["name"] = t["subtype"].map(SUBTYPES)
    return t


def sizes(g: gpd.GeoDataFrame) -> pd.DataFrame:
    x = g[~g["empty"]]
    q = x.groupby("subtype").ha.describe(percentiles=[0.1, 0.25, 0.5, 0.75, 0.9]).reset_index()
    q["share_ge_0_5ha"] = x.groupby("subtype").ha.apply(lambda s: (s >= 0.5).mean()).values
    q["name"] = q["subtype"].map(SUBTYPES)
    return q


def by_region(g: gpd.GeoDataFrame, land: gpd.GeoDataFrame, regions: gpd.GeoDataFrame,
              code: int, c: LvmConfig) -> pd.DataFrame:
    """ha of subtype `code` per NUTS 3 region and year, and per 1000 ha of LVM land."""
    r = regions.to_crs(g.crs)[["NUTS_ID", "NAME_LATN", "geometry"]]
    x = g[(g["subtype"] == code) & ~g["empty"] & g["year"].between(*c.years)]
    pts = gpd.sjoin(x.assign(geometry=x.representative_point())[["year", "ha", "geometry"]], r,
                    predicate="within")
    t = pts.groupby(["NAME_LATN", "year"]).ha.sum().unstack("year").fillna(0)
    lp = gpd.overlay(land[["geometry"]], r, how="intersection", keep_geom_type=True)
    land_ha = lp.assign(ha=lp.area / 1e4).groupby("NAME_LATN").ha.sum()
    t.insert(0, "lvm_land_ha", land_ha.reindex(t.index))
    return t


def csp_compare(ann: pd.DataFrame, meb012: pd.DataFrame, code: int) -> pd.DataFrame:
    """LVM subtype `code` per year vs CSP MEB012 stem-pest damage, state forest and total."""
    lv = ann[ann.subtype == code].set_index("year")[["n", "ha"]].add_prefix("lvm_")
    m = meb012[meb012["Meža bojājumi"] == "..kaitēkļu izraisīti stumbru bojājumi"]
    out = lv.copy()
    for owner, tag in (("Valsts meži", "state"), ("Pavisam", "total")):
        mm = m[m["Meža īpašuma forma"] == owner]
        for ind, short in (("Bojā aizgājušās audzes, ha", "dead_stands_ha"),
                           ("Bojājumu rezultātā izcirstais apjoms, tūkst. m³", "harvested_km3")):
            out[f"csp_{tag}_{short}"] = mm[mm.indicator == ind].set_index("year")["value"].reindex(out.index)
    return out


# CSP MEB011 territorial units matching the NUTS 2024 level-3 regions
MEB011_REGIONS = {"Kurzemes statistiskais reģions (no 01.01.2024.)": "Kurzeme",
                  "Latgales statistiskais reģions": "Latgale",
                  "Rīgas statistiskais reģions (no 01.01.2024.)": "Rīga",
                  "Vidzemes statistiskais reģions (no 01.01.2024.)": "Vidzeme",
                  "Zemgales statistiskais reģions": "Zemgale"}


def meb011_compare(reg: pd.DataFrame, meb011: pd.DataFrame) -> pd.DataFrame:
    """Region x year: LVM stem-pest ha vs CSP MEB011 state-forest stem-pest damage."""
    m = meb011[(meb011["Meža bojājumi"] == "..kaitēkļu izraisīti stumbru bojājumi")
               & (meb011["Meža īpašuma forma"] == "Valsts meži")
               & meb011["Teritoriālā vienība"].isin(list(MEB011_REGIONS))].copy()
    m["region"] = m["Teritoriālā vienība"].map(MEB011_REGIONS)
    m = m.pivot_table(index=["region", "year"], columns="indicator", values="value")
    m.columns = ["csp_state_dead_stands_ha" if "ha" in c else "csp_state_harvested_km3" for c in m.columns]
    lv = reg.drop(columns="lvm_land_ha").stack().rename("lvm_ha")
    lv.index.names = ["region", "year"]
    out = m.join(lv, how="left").reset_index()
    out["lvm_land_ha"] = out["region"].map(reg["lvm_land_ha"])
    return out


def efda_timing(g: gpd.GeoDataFrame, land: gpd.GeoDataFrame, cfg: RiskConfig) -> pd.DataFrame:
    """Share of polygon pixels (EFDA v3.0 grid) that EFDA marks as harvest / class 1 / any in
    years r + offset (r = registration year). Base rate: the same shares for all EFDA forest
    pixels on LVM land."""
    c, v = cfg.lvm, cfg.efda.main
    x = g[(g["subtype"] == c.stem_pest) & ~g["empty"] & g["year"].between(*c.years)].to_crs(3035)
    rows = []
    with rasterio.open(layer(v, "agent")) as s, rasterio.open(layer(v, "forest")) as fm:
        last = v.first_year + s.count - 1
        lvm_px = rasterize(((geom, 1) for geom in land.to_crs(3035).geometry), out_shape=s.shape,
                           transform=s.transform, fill=0, dtype="uint8") == 1
        base = lvm_px & (fm.read(1) == 1)
        bands = {}

        def band(y):
            if y not in bands:
                bands[y] = s.read(y - v.first_year + 1)
            return bands[y]

        for y, grp in x.groupby("year"):
            m = rasterize(((geom, 1) for geom in grp.geometry), out_shape=s.shape,
                          transform=s.transform, fill=0, dtype="uint8") == 1
            for off in c.timing_offsets:
                yy = int(y) + off
                if not v.first_year <= yy <= last:
                    continue
                a, b = band(yy)[m], band(yy)[base]
                rows.append({"reg_year": int(y), "offset": off, "efda_year": yy, "polygons": len(grp),
                             "poly_px": int(m.sum()), "harvest": float((a == 3).mean()),
                             "class1": float((a == 1).mean()), "any": float(np.isin(a, (1, 2, 3)).mean()),
                             "base_harvest": float((b == 3).mean()), "base_any": float(np.isin(b, (1, 2, 3)).mean())})
    t = pd.DataFrame(rows)
    t["harvest_lift"] = t["harvest"] / t["base_harvest"]
    return t


def _suspects(run) -> gpd.GeoDataFrame:
    s = gpd.read_file(run.path, layer=f"suspects_{run.year}")
    s["run"], s["variant"], s["run_year"] = run.label, run.variant, run.year
    return s


def kalsnava_check(cfg: RiskConfig) -> dict[str, pd.DataFrame]:
    """LVM damage polygons in the Kalsnava AOI vs s2forest runs (match = overlap within
    `match_buffer_m`). Registrations after the archive snapshot are missing by construction."""
    c = cfg.lvm
    aoi = gpd.read_file(cfg.kalsnava.aoi).to_crs(3059)
    area = aoi.union_all()
    land = load_land(c, bbox=tuple(aoi.total_bounds))
    dmg = load_damage(c, bbox=tuple(aoi.total_bounds))
    dmg = dmg[~dmg["empty"] & dmg.intersects(area)].copy()
    dmg["name"] = dmg["subtype"].map(SUBTYPES)
    runs = pd.concat([_suspects(r) for r in c.s2forest]).to_crs(3059)
    summary = pd.DataFrame([
        {"item": "AOI, ha", "value": round(area.area / 1e4, 1)},
        {"item": "LVM land in AOI, ha", "value": round(land.intersection(area).area.sum() / 1e4, 1)},
        {"item": "LVM damage polygons in AOI (all subtypes, all years)", "value": len(dmg)},
        {"item": f"... subtype {c.stem_pest}", "value": int((dmg["subtype"] == c.stem_pest).sum())},
        {"item": f"... subtype {c.stem_pest} >= {c.min_target_ha} ha", "value":
            int(((dmg["subtype"] == c.stem_pest) & (dmg["ha"] >= c.min_target_ha)).sum())},
        {"item": "LVM archive snapshot", "value": str(c.damage_snapshot)},
    ])
    # LVM polygons -> s2forest matches
    rows = []
    for i, d in dmg.iterrows():
        near = runs[runs.intersects(d.geometry.buffer(c.match_buffer_m))]
        rows.append({"lvm_index": i, "year": d["year"], "subtype": d["subtype"], "name": d["name"],
                     "ha": round(d["ha"], 2),
                     "matched_runs": ";".join(sorted(set(near["run"]))),
                     "matched": ";".join(f"{r.run}#{r.id}:{r.type}:{r.first_detected}" for r in near.itertuples())})
    lvm_side = pd.DataFrame(rows)
    # s2forest polygons -> LVM damage / LVM land
    buf = dmg.buffer(c.match_buffer_m).union_all() if len(dmg) else None
    land_u = land.union_all() if len(land) else None
    s2 = runs.assign(in_lvm_damage=runs.intersects(buf) if buf is not None else False,
                     on_lvm_land=runs.intersects(land_u) if land_u is not None else False)
    s2_side = (s2.groupby(["run", "variant", "type"])
                 .agg(n=("id", "count"), ha=("area_ha", "sum"), on_lvm_land=("on_lvm_land", "sum"),
                      in_lvm_damage=("in_lvm_damage", "sum")).reset_index())
    if c.mps:
        mps = gpd.read_file(_zip(c.mps, c.mps_member), bbox=tuple(aoi.total_bounds))
        summary.loc[len(summary)] = {"item": "Meža pētīšanas stacija (MPS) land in AOI, ha",
                                     "value": round(mps.intersection(area).area.sum() / 1e4, 1)}
    out = {"summary": summary, "lvm_polygons": lvm_side, "s2forest": s2_side,
           "s2forest_polygons": s2.drop(columns="geometry")}
    if c.mvr_kalsnava:
        mvr = gpd.read_file(c.mvr_kalsnava, bbox=tuple(aoi.total_bounds),
                            columns=["kadastrs", "kvart", "nog", "nog_plat", "p_cirp", "p_cirg", "bv10", "bv11", "bv12"])
        mvr = mvr.set_crs(3059, allow_override=True)   # LKS-2020 TM .prj, same grid as LKS-92 TM here [N]
        mvr = mvr[mvr.intersects(area)].copy()
        mvr["p_cirg"] = pd.to_numeric(mvr["p_cirg"], errors="coerce").astype("Int64")
        summary.loc[len(summary)] = {"item": "MVR compartments in AOI (n / ha)",
                                     "value": f"{len(mvr)} / {mvr.area.sum() / 1e4:.1f}"}
        rows = []
        for _, d in mvr[mvr["p_cirg"] >= 2024].iterrows():
            near = runs[runs.intersects(d.geometry.buffer(c.match_buffer_m))]
            rows.append({"kvart": d["kvart"], "nog": d["nog"], "ha": round(d.geometry.area / 1e4, 2),
                         "p_cirp": d["p_cirp"], "p_cirg": d["p_cirg"],
                         "matched": ";".join(f"{r.run}#{r.id}:{r.type}:{r.first_detected}" for r in near.itertuples())})
        out["mvr_recent_cuts"] = pd.DataFrame(rows)
    if c.s1_targets:
        t = pd.read_csv(c.s1_targets)
        t["year"], t["id"] = t["uid"].str.split("#").str[0].astype(int), t["uid"].str.split("#").str[1].astype(int)
        base = s2[s2["variant"] == "all"][["run_year", "id", "on_lvm_land", "in_lvm_damage"]]
        out["s1_targets"] = t.merge(base, left_on=["year", "id"], right_on=["run_year", "id"], how="left")
    return out


def target_cells(g: gpd.GeoDataFrame, c: LvmConfig, regions: gpd.GeoDataFrame | None = None,
                 ref_point=None, years=(2023, 2024), cell_m: float = 5000.0, top: int = 10) -> pd.DataFrame:
    """5 x 5 km cells (LKS-92 grid) with the most stem-pest polygons >= min_target_ha registered
    in `years` - candidates for an S1 / s2forest test AOI on LVM land (only proposed, not run)."""
    x = g[(g["subtype"] == c.stem_pest) & ~g["empty"] & g["year"].isin(list(years)) & (g["ha"] >= c.min_target_ha)]
    p = x.representative_point()
    cx, cy = (p.x // cell_m * cell_m).astype(int), (p.y // cell_m * cell_m).astype(int)
    t = x.assign(x0=cx.values, y0=cy.values).groupby(["x0", "y0"]).agg(n=("ha", "size"), ha=("ha", "sum"))
    t = t.sort_values("n", ascending=False).head(top).reset_index()
    t["x1"], t["y1"] = t["x0"] + cell_m, t["y0"] + cell_m
    cen = gpd.GeoSeries(gpd.points_from_xy(t["x0"] + cell_m / 2, t["y0"] + cell_m / 2), crs=g.crs)
    ll = cen.to_crs(4326)
    t["lon"], t["lat"] = ll.x.round(3).values, ll.y.round(3).values
    if regions is not None:
        r = regions.to_crs(g.crs)[["NAME_LATN", "geometry"]]
        t["region"] = gpd.sjoin(gpd.GeoDataFrame(geometry=cen), r, how="left")["NAME_LATN"].values
    if ref_point is not None:
        t["km_from_ref"] = (cen.distance(ref_point) / 1000).round(0).values
    return t


def aoi_check(cells: pd.DataFrame, g: gpd.GeoDataFrame, land: gpd.GeoDataFrame, dlt_path, c: LvmConfig,
              cell_m: float = 5000.0) -> pd.DataFrame:
    """Stage 5b AOI criteria for the densest target cells (`target_cells` output): LVM land share,
    HRL DLT 2018 conifer share of tree cover, stem-pest target counts. Ranked: all criteria met,
    preferred region, distance to the reference point."""
    from rasterio.mask import mask
    from shapely.geometry import box

    a = c.aoi
    x = g[~g["empty"]]
    pts = x.representative_point()
    rows = []
    with rasterio.open(dlt_path) as src:
        for r in cells.head(a.top_cells).itertuples():
            cell = box(r.x0, r.y0, r.x0 + cell_m, r.y0 + cell_m)
            lvm_ha = land[land.intersects(cell)].intersection(cell).union_all().area / 1e4
            geom = gpd.GeoSeries([cell], crs=g.crs).to_crs(src.crs).iloc[0]
            d, _ = mask(src, [geom], crop=True, filled=False)
            v = d[0].compressed()
            n0, n1, n2 = (int((v == k).sum()) for k in (0, 1, 2))
            inside = x[pts.within(cell)]
            y = inside[inside["year"].between(*a.years)]
            sp = y[y["subtype"] == c.stem_pest]
            row = {"x0": r.x0, "y0": r.y0, "lon": r.lon, "lat": r.lat, "region": getattr(r, "region", None),
                   "km_from_kalsnava": getattr(r, "km_from_ref", None),
                   "lvm_land_share": round(lvm_ha / (cell_m ** 2 / 1e4), 3),
                   "tree_cover_share": round((n1 + n2) / max(n0 + n1 + n2, 1), 3),
                   "conifer_share": round(n2 / max(n1 + n2, 1), 3)}
            for yr in range(a.years[0], a.years[1] + 1):
                row[f"n{c.stem_pest}_{yr}_ge{c.min_target_ha}ha"] = int(((sp["year"] == yr) & (sp["ha"] >= c.min_target_ha)).sum())
            row["targets"] = int((sp["ha"] >= c.min_target_ha).sum())
            row["targets_ge1ha"] = int((sp["ha"] >= 1.0).sum())
            row["targets_ha"] = round(sp.loc[sp["ha"] >= c.min_target_ha, "ha"].sum(), 1)
            row[f"n{c.stem_pest}_all_sizes"] = len(sp)
            row["n_wind_100"] = int((y["subtype"] == 100).sum())
            row["n_other_damage"] = int((~y["subtype"].isin([c.stem_pest, 100])).sum())
            rows.append(row)
    t = pd.DataFrame(rows)
    t["ok_lvm_land"] = t["lvm_land_share"] >= a.min_lvm_share
    t["ok_conifer"] = t["conifer_share"] >= a.min_conifer_share
    t["ok_targets"] = t["targets"] >= a.min_targets
    t["all_ok"] = t["ok_lvm_land"] & t["ok_conifer"] & t["ok_targets"]
    t["preferred_region"] = t["region"] == a.prefer_region
    t = t.sort_values(["all_ok", "preferred_region", "km_from_kalsnava"], ascending=[False, False, True])
    t["rank"] = range(1, len(t) + 1)
    return t.reset_index(drop=True)


def aoi_geojson(x0: float, y0: float, crs, path, name: str, cell_m: float = 5000.0) -> None:
    """Write a 5 x 5 km LKS-92 cell as a CRS84 GeoJSON AOI (same format as the Kalsnava AOI)."""
    from shapely.geometry import box

    gpd.GeoDataFrame({"name": [name]}, geometry=[box(x0, y0, x0 + cell_m, y0 + cell_m)], crs=crs) \
        .to_crs(4326).to_file(path, driver="GeoJSON")
