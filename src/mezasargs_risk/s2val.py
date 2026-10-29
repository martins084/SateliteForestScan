"""Stage 5b: blind validation of s2forest (frozen v0.2 config, only AOI and years changed) against
LVM open damage polygons (LVM_BOJAJUMI, Wayback copy) on an AOI on LVM land.

* detection per object: LVM polygon registered in year r is "found" in year y if an s2forest suspect
  polygon of the run for monitoring year y lies within `match_buffer_m`; y = r + offset;
* precision: s2forest polygons inside LVM damage (any subtype) vs "unconfirmed" (the register is
  incomplete, so outside != false). Registrations after the archive snapshot are missing, the
  snapshot year is reported separately;
* lag: earliest s2forest first_detected vs registration year;
* placebo: the same detection / precision measures for LVM polygons moved at random (translation +
  rotation) inside the AOI conifer forest (HRL DLT class of the s2forest mask), `placebo_n` times.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize
from shapely import affinity

from .config import LvmConfig
from .lvm import SUBTYPES, _suspects, load_damage

STRICT_OVERLAP = 0.25   # informative: s2forest polygons cover >= this share of the LVM polygon
GROUPS = {"620": "stumbru kaitēkļi (620)", "100": "vējgāzes (100)", "other": "citi bojājumi"}
# s2forest forest mask codes (s2forest.forestmask FOREST_*)
MASK_CODES = {0: "nav HRL skujkoku klasē", 1: "analizēts", 2: "zems bāzes NDVI (jau nocirsts / jaunaudze)",
              3: "nav datu bāzē", 4: "ceļa buferī", 5: "liela sezonālā amplitūda"}


def group(subtype) -> str:
    return "620" if subtype == 620 else "100" if subtype == 100 else "other"


def load(c: LvmConfig) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, dict[tuple[str, int], gpd.GeoDataFrame]]:
    """AOI (LKS-92), LVM damage polygons whose representative point is in the AOI (clipped to it)
    and the s2forest suspect polygons per (variant, year)."""
    v = c.validation
    aoi = gpd.read_file(v.aoi).to_crs(3059)
    area = aoi.union_all()
    d = load_damage(c, bbox=tuple(aoi.total_bounds))
    d = d[~d["empty"] & d.representative_point().within(area)].copy()
    d["geometry"] = d.geometry.make_valid().intersection(area)
    d = d[~d.geometry.is_empty].copy()
    d["ha"] = d.area / 1e4
    d["group"] = d["subtype"].map(group)
    d["name"] = d["subtype"].map(SUBTYPES)
    d["lvm_id"] = range(len(d))
    runs = {(r.variant, r.year): _suspects(r).to_crs(3059) for r in c.s2forest}
    return aoi, d.reset_index(drop=True), runs


def _hits(polys: gpd.GeoDataFrame, s: gpd.GeoDataFrame, buf: float) -> pd.DataFrame:
    """Pairs (lvm_id, suspect id, type, first_detected) within `buf` metres, with the overlap
    area (m2) of the suspect polygon and the (unbuffered) LVM polygon."""
    if not len(polys) or not len(s):
        return pd.DataFrame(columns=["lvm_id", "id", "type", "first_detected", "onset_before_season", "overlap_m2"])
    j = gpd.sjoin(polys[["lvm_id", "geometry"]].assign(geometry=polys.buffer(buf)),
                  s[["id", "type", "first_detected", "onset_before_season", "geometry"]], predicate="intersects")
    own = gpd.GeoSeries(polys.set_index("lvm_id").geometry.loc[j["lvm_id"]].values, crs=polys.crs)
    other = gpd.GeoSeries(s.geometry.loc[j["index_right"]].values, crs=s.crs)
    j["overlap_m2"] = own.intersection(other).area.values
    return j.drop(columns=["geometry", "index_right"])


def detection(d: gpd.GeoDataFrame, runs: dict, variant: str, c: LvmConfig) -> pd.DataFrame:
    """One row per LVM polygon (registered in `reg_years`) x offset: found / by cut / by stress."""
    v = c.validation
    x = d[d["year"].isin(v.reg_years)]
    rows = []
    for off in v.offsets:
        for r in v.reg_years:
            s = runs.get((variant, r + off))
            xr = x[x["year"] == r]
            h = _hits(xr, s, c.match_buffer_m) if s is not None else None
            for p in xr.itertuples():
                row = {"lvm_id": p.lvm_id, "year": r, "subtype": p.subtype, "group": p.group, "ha": p.ha,
                       "offset": off, "run_year": r + off, "run_available": s is not None}
                if h is not None:
                    m = h[h["lvm_id"] == p.lvm_id]
                    row |= {"found": len(m) > 0,
                            "found_overlap25": m["overlap_m2"].sum() / (p.ha * 1e4) >= STRICT_OVERLAP,
                            "found_cut": (m["type"] == "cut").any(),
                            "found_stress": (m["type"] == "stress").any(),
                            "first_detected": m["first_detected"].min() if len(m) else None,
                            "onset_before_season": bool(m["onset_before_season"].any()) if len(m) else None}
                rows.append(row)
    return pd.DataFrame(rows)


SIZE_CLASSES = {"visi": 0.0, ">= 0,5 ha": 0.5, ">= 1 ha": 1.0}


def detection_summary(det: pd.DataFrame, extra: pd.Series | None = None) -> pd.DataFrame:
    """Share of polygons (and ha) found per group x size class x offset; plus 'any offset'.
    `extra` (bool per lvm_id) adds the rows restricted to it (e.g. >= 50 % in the analysed mask)."""
    out = []
    det = det[det["run_available"]].astype({"found": bool, "found_overlap25": bool, "found_cut": bool,
                                            "found_stress": bool})
    subsets = {k: det["ha"] >= v for k, v in SIZE_CLASSES.items()}
    if extra is not None:
        subsets[">= 0,5 ha, >= 50 % analizēts"] = (det["ha"] >= 0.5) & det["lvm_id"].map(extra).fillna(False)
    for g in GROUPS:
        for size, sel in subsets.items():
            x = det[sel & (det["group"] == g)]
            if len(x):
                out += _rates(x, g, size)
    return pd.DataFrame(out)


def _rates(x: pd.DataFrame, g: str, size: str) -> list[dict]:
    """Found shares per offset and for any offset (one polygon counted once)."""
    out = []
    per = x.groupby("offset")
    any_ = x.groupby("lvm_id").agg(found=("found", "any"), found_overlap25=("found_overlap25", "any"),
                                   cut=("found_cut", "any"),
                                   stress=("found_stress", "any"), ha=("ha", "first"))
    for off, y in list(per) + [("r-1..r+1", None)]:
        y = any_ if y is None else y.rename(columns={"found_cut": "cut", "found_stress": "stress"})
        out.append({"group": g, "size": size, "offset": off, "n": len(y), "ha": round(y["ha"].sum(), 1),
                    "found_n": int(y["found"].sum()), "found_share": round(y["found"].mean(), 3),
                    "found_ha_share": round(y.loc[y["found"], "ha"].sum() / y["ha"].sum(), 3),
                    "by_cut_n": int(y["cut"].sum()), "by_stress_n": int(y["stress"].sum()),
                    "found_overlap25_n": int(y["found_overlap25"].sum()),
                    "found_overlap25_share": round(y["found_overlap25"].mean(), 3)})
    return out


def precision(d: gpd.GeoDataFrame, runs: dict, variant: str, c: LvmConfig) -> pd.DataFrame:
    """s2forest polygons per run year x type: inside LVM damage (any subtype, any year / registered
    y-1..y+1) or unconfirmed. The snapshot year is flagged (register ends at the snapshot)."""
    rows = []
    buf_any = d.buffer(c.match_buffer_m)
    for (var, y), s in sorted(runs.items()):
        if var != variant:
            continue
        near = d["year"].between(y - 1, y + 1)
        hit_any = s.intersects(buf_any.union_all()) if len(d) else pd.Series(False, index=s.index)
        hit_win = s.intersects(buf_any[near].union_all()) if near.any() else pd.Series(False, index=s.index)
        hit_620 = s.intersects(buf_any[near & (d["group"] == "620")].union_all()) \
            if (near & (d["group"] == "620")).any() else pd.Series(False, index=s.index)
        for t in ("cut", "stress"):
            m = s["type"] == t
            rows.append({"run_year": y, "type": t, "n": int(m.sum()), "ha": round(s.loc[m, "area_ha"].sum(), 1),
                         "in_lvm_damage_any_year": int((m & hit_any).sum()),
                         "in_lvm_damage_reg_y-1..y+1": int((m & hit_win).sum()),
                         "in_lvm_620_reg_y-1..y+1": int((m & hit_620).sum()),
                         "unconfirmed": int((m & ~hit_any).sum()),
                         "share_in_lvm_damage_any_year": round((m & hit_any).sum() / max(m.sum(), 1), 3),
                         "register_incomplete": y >= c.damage_snapshot.year})
    return pd.DataFrame(rows)


def mask_cover(d: gpd.GeoDataFrame, mask_paths: dict[int, str], c: LvmConfig) -> tuple[pd.DataFrame, pd.Series]:
    """Area of LVM polygons (registered in `reg_years`) by s2forest mask code of the run for the
    registration year; and the analysed share per lvm_id."""
    rows, share = [], {}
    for r in c.validation.reg_years:
        x = d[d["year"] == r]
        with rasterio.open(mask_paths[r]) as src:
            codes, tr = src.read(1), src.transform
        for p in x.itertuples():
            lab = rasterize([(p.geometry, 1)], out_shape=codes.shape, transform=tr, fill=0, dtype="uint8").astype(bool)
            v = codes[lab]
            share[p.lvm_id] = float((v == 1).mean()) if v.size else 0.0
            for k, n in zip(*np.unique(v, return_counts=True)):
                rows.append({"year": r, "group": p.group, "code": int(k), "ha": n * 0.01})
    t = pd.DataFrame(rows).groupby(["group", "code"], as_index=False)["ha"].sum()
    t["mask"] = t["code"].map(MASK_CODES).fillna("ārpus rastra")
    t["share_of_group_ha"] = (t["ha"] / t.groupby("group")["ha"].transform("sum")).round(3)
    return t, pd.Series(share) >= 0.5


def relocate(d: gpd.GeoDataFrame, forest_xy: np.ndarray, area, rng: np.random.Generator,
             tries: int = 200) -> gpd.GeoDataFrame:
    """Move each polygon so its centroid lands on a random forest pixel, random rotation, fully
    inside the AOI (fallback: last try)."""
    geoms = []
    for g in d.geometry:
        cen = g.centroid
        for _ in range(tries):
            x, y = forest_xy[rng.integers(len(forest_xy))]
            ng = affinity.translate(affinity.rotate(g, rng.uniform(0, 360), origin=cen), x - cen.x, y - cen.y)
            if ng.within(area):
                break
        geoms.append(ng)
    return d.set_geometry(gpd.GeoSeries(geoms, index=d.index, crs=d.crs))


def placebo(d: gpd.GeoDataFrame, runs: dict, aoi: gpd.GeoDataFrame, forest_mask: str, c: LvmConfig,
            variant: str = "all") -> pd.DataFrame:
    """`placebo_n` random relocations of all LVM polygons; per permutation the detection shares
    (>= 0,5 ha, per offset and any) of the groups in `placebo_groups` and the share of s2forest
    polygons inside relocated damage."""
    v = c.validation
    with rasterio.open(forest_mask) as src:
        codes, tr = src.read(1), src.transform
    r_, c_ = np.nonzero((codes != 0) & (codes != 255))
    xy = np.column_stack([tr.c + (c_ + 0.5) * tr.a, tr.f + (r_ + 0.5) * tr.e])
    rng = np.random.default_rng(v.seed)
    area = aoi.union_all()
    rows = []
    for i in range(v.placebo_n):
        p = relocate(d, xy, area, rng)
        det = detection(p, runs, variant, c)
        summ = detection_summary(det)
        row = {"perm": i}
        for g in v.placebo_groups:
            row |= group_shares(summ, g)
        row |= precision_shares(precision(p, runs, variant, c))
        rows.append(row)
    return pd.DataFrame(rows)


def group_shares(summ: pd.DataFrame, g: str = "620") -> dict:
    """Detection shares (>= 0,5 ha) per offset of one group; keys of groups other than 620 get
    the prefix "<group>_"."""
    s = summ[(summ["group"] == g) & (summ["size"] == ">= 0,5 ha")]
    pre = "" if g == "620" else f"{g}_"
    return {f"{pre}{m}_{o}": val for m in ("found_share", "found_overlap25_share")
            for o, val in zip(s["offset"].astype(str), s[m])}


PREC_COLS = ["in_lvm_damage_any_year", "in_lvm_damage_reg_y-1..y+1", "in_lvm_620_reg_y-1..y+1"]


def precision_shares(pr: pd.DataFrame) -> dict:
    """Pooled share of s2forest polygons (years with a complete register) per type and measure."""
    out = {}
    for t in ("cut", "stress"):
        x = pr[(pr["type"] == t) & ~pr["register_incomplete"]]
        for col in PREC_COLS:
            out[f"{t}_{col}"] = x[col].sum() / max(x["n"].sum(), 1)
    return out


def placebo_compare(observed: dict, plac: pd.DataFrame) -> pd.DataFrame:
    """Observed vs placebo: mean, 2,5 / 97,5 % and one-sided p = (1 + #placebo >= observed) / (n + 1)."""
    rows = []
    for k, o in observed.items():
        if k not in plac:
            continue
        v = plac[k]
        rows.append({"measure": k, "observed": round(o, 3), "placebo_mean": round(v.mean(), 3),
                     "placebo_p2.5": round(v.quantile(0.025), 3), "placebo_p97.5": round(v.quantile(0.975), 3),
                     "p_one_sided": round((1 + (v >= o).sum()) / (len(v) + 1), 3)})
    return pd.DataFrame(rows)


def lag(det: pd.DataFrame, col: str = "found") -> pd.DataFrame:
    """Earliest s2forest first_detected (any run) per found 620 polygon vs registration year
    (`col` = "found" within the buffer, or "found_overlap25")."""
    x = det[(det[col] == True) & (det["group"] == "620")].copy()  # noqa: E712 (object column)
    x["first_detected"] = pd.to_datetime(x["first_detected"])
    e = x.sort_values("first_detected").groupby("lvm_id").first().reset_index()
    e["lag_years"] = e["first_detected"].dt.year - e["year"]
    e["month"] = e["first_detected"].dt.month
    return e[["lvm_id", "year", "ha", "first_detected", "lag_years", "month", "onset_before_season",
              "found_cut", "found_stress"]]
