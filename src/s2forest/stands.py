"""Forest stand (nogabals) attributes from the State Forest Register (Meža valsts reģistrs).

Source: VMD open data (data.gov.lv, CC0), SHP per head forestry. The open data
have NO species share coefficient; per first-storey element (s10..s14) they give
species, age, height, diameter, basal area g (m2/ha) and tree count. Composition
is therefore computed from the BASAL AREA (fallback: tree count):

    spruce_share = sum(g of spruce elements) / sum(g of all elements)

Spruce = species codes 3 (Egle) and 15 (Citas egles) in the VMD classifier.

INFORMATIVE ONLY in the frozen version v0.2-kalsnava: the attributes are added to
the suspect polygons and drone targets but are NOT used in detection, confidence
or priority.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio

from .config import StandsConfig

# VMD classifier "S_klasifikators" (most common codes) and "MT_klasifikators".
SPECIES = {1: "priede", 3: "egle", 4: "bērzs", 6: "melnalksnis", 8: "apse", 9: "baltalksnis",
           10: "ozols", 11: "osis", 12: "liepa", 13: "lapegle", 14: "citas priedes",
           15: "citas egles", 16: "goba, vīksna", 19: "papele", 20: "vītols", 21: "blīgzna",
           24: "kļava", 28: "duglāzija", 32: "pīlādzis", 35: "ieva", 68: "hibrīdā apse"}
FOREST_TYPES = {1: "sils", 2: "mētrājs", 3: "lāns", 4: "damaksnis", 5: "vēris", 6: "gārša",
                7: "grīnis", 8: "slapjais mētrājs", 9: "slapjais damaksnis", 10: "slapjais vēris",
                11: "slapjā gārša", 12: "purvājs", 14: "niedrājs", 15: "dumbrājs", 16: "liekņa",
                17: "viršu ārenis", 18: "mētru ārenis", 19: "šaurlapju ārenis",
                21: "platlapju ārenis", 22: "viršu kūdrenis", 23: "mētru kūdrenis",
                24: "šaurlapju kūdrenis", 25: "platlapju kūdrenis"}


def clip_stands(src: str | Path, aoi: gpd.GeoDataFrame, out: Path, pad_m: float = 200.0) -> Path:
    """Read only the stands intersecting the AOI (+pad) from a large SHP / zip and
    save them as GeoPackage. `src` may be a .zip with one or more shapefiles."""
    src = str(src)
    layers = []
    paths = [src]
    if src.lower().endswith(".zip"):
        import zipfile

        with zipfile.ZipFile(src) as z:
            paths = [f"/vsizip/{src}/{n}" for n in z.namelist() if n.lower().endswith(".shp")]
    for pth in paths:
        info = pyogrio.read_info(pth)
        crs = info["crs"]
        bbox = tuple(aoi.to_crs(crs).buffer(pad_m).total_bounds)
        g = pyogrio.read_dataframe(pth, bbox=bbox)
        if len(g):
            layers.append(g.to_crs(aoi.crs))
    if not layers:
        raise ValueError("No stands intersect the AOI")
    gdf = gpd.GeoDataFrame(pd.concat(layers, ignore_index=True), crs=aoi.crs)
    out.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(out, driver="GPKG")
    return out


def _num(df: pd.DataFrame, col: str) -> np.ndarray:
    if col not in df:
        return np.full(len(df), np.nan)
    return pd.to_numeric(df[col], errors="coerce").to_numpy(dtype="float64")


def composition(stands: gpd.GeoDataFrame, cfg: StandsConfig) -> gpd.GeoDataFrame:
    """Add per-stand composition columns (spruce share, dominant species, age, forest type)."""
    s = stands.copy()
    sp = np.column_stack([_num(s, c) for c in cfg.species_fields])
    g = np.column_stack([_num(s, c) for c in cfg.basal_area_fields])
    n = np.column_stack([_num(s, c) for c in cfg.tree_count_fields])
    age = np.column_stack([_num(s, c) for c in cfg.age_fields])
    w = np.where(np.nansum(np.nan_to_num(g), axis=1, keepdims=True) > 0, np.nan_to_num(g),
                 np.nan_to_num(n))
    valid = np.isfinite(sp) & (sp > 0)
    w = np.where(valid, w, 0.0)
    tot = w.sum(axis=1)
    spruce = np.isin(sp, [float(v) for v in cfg.spruce_values]) & valid
    with np.errstate(invalid="ignore", divide="ignore"):
        s["spruce_share"] = np.where(tot > 0, (w * spruce).sum(axis=1) / tot, np.nan).round(2)
    dom = np.argmax(w, axis=1)
    rows = np.arange(len(s))
    has = tot > 0
    s["dom_species_code"] = np.where(has, sp[rows, dom], np.nan)
    s["dom_species"] = [SPECIES.get(int(c), f"kods {int(c)}") if np.isfinite(c) else None
                        for c in s["dom_species_code"]]
    s["dom_age"] = np.where(has, age[rows, dom], np.nan)
    s["composition_basis"] = np.where(np.nansum(np.nan_to_num(g), axis=1) > 0, "g",
                                      np.where(has, "n", None))
    mt = _num(s, cfg.forest_type_field)
    s["forest_type_code"] = mt
    s["forest_type"] = [FOREST_TYPES.get(int(c), f"kods {int(c)}") if np.isfinite(c) else None
                        for c in mt]
    return s


def stand_id(row, cfg: StandsConfig) -> str:
    """`id_field` if present, else cadastre-quarter-stand(-substand) (MVR shapefiles
    have no `id` field although the open-data description lists one)."""
    v = row.get(cfg.id_field)
    if v is not None and pd.notna(v) and str(v):
        return str(v)
    parts = [row.get("kadastrs"), row.get("kvart"), row.get("nog")]
    sid = "-".join(str(int(p)) if isinstance(p, float) and p.is_integer() else str(p)
                   for p in parts if p is not None and pd.notna(p))
    anog = row.get("anog")
    if anog is not None and pd.notna(anog) and str(anog).strip() not in ("", "0"):
        sid += f"-{anog}"
    return sid


def load_stands(cfg: StandsConfig, crs: str) -> gpd.GeoDataFrame | None:
    if cfg.path is None or not Path(cfg.path).exists():
        return None
    return composition(gpd.read_file(cfg.path).to_crs(crs), cfg)


STAND_COLUMNS = ["stand_id", "stand_kvart_nog", "stand_dom_species", "stand_dom_age",
                 "stand_forest_type", "stand_spruce_share", "spruce_share_weighted",
                 "stand_cover_share"]


def annotate_outputs(cfg_all, polygons: gpd.GeoDataFrame, targets: gpd.GeoDataFrame | None
                     ) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame | None, dict]:
    """Annotate suspect polygons and drone targets with stand attributes."""
    st = load_stands(cfg_all.stands, cfg_all.data.crs)
    info = {"stands_loaded": 0 if st is None else int(len(st))}
    if st is None:
        return polygons, targets, info
    polygons = annotate(polygons, st, cfg_all.stands)
    if targets is not None and len(targets):
        targets = annotate(targets.drop(columns=[c for c in STAND_COLUMNS if c in targets]),
                           st, cfg_all.stands)
    s = polygons[polygons["type"] == "stress"] if len(polygons) else polygons
    info.update({"stress_polygons": int(len(s)),
                 "stress_with_stand": int((s["stand_cover_share"] > 0).sum()) if len(s) else 0,
                 "stress_spruce_dominated": int((s["stand_spruce_share"] >= 0.5).sum()) if len(s) else 0})
    return polygons, targets, info


def annotate(polygons: gpd.GeoDataFrame, stands: gpd.GeoDataFrame, cfg: StandsConfig
             ) -> gpd.GeoDataFrame:
    """Per polygon: the stand with the largest overlap (ID, species, age, forest type,
    its spruce share), the area-weighted spruce share over all overlapping stands and
    the share of the polygon covered by register stands."""
    out = polygons.copy()
    cols = {"stand_id": None, "stand_kvart_nog": None, "stand_dom_species": None,
            "stand_dom_age": np.nan, "stand_forest_type": None, "stand_spruce_share": np.nan,
            "spruce_share_weighted": np.nan, "stand_cover_share": 0.0}
    for c, v in cols.items():
        out[c] = v
    if out.empty or stands.empty:
        return out
    st = stands.reset_index(drop=True)
    sidx = st.sindex
    for i, geom in zip(out.index, out.geometry):
        cand = list(sidx.query(geom, predicate="intersects"))
        if not cand:
            continue
        inter = st.iloc[cand].geometry.intersection(geom).area.to_numpy()
        keep = inter > 0
        if not keep.any():
            continue
        cand = np.asarray(cand)[keep]
        inter = inter[keep]
        main = st.iloc[cand[np.argmax(inter)]]
        kv, ng = main.get("kvart"), main.get("nog")
        out.at[i, "stand_id"] = stand_id(main, cfg)
        out.at[i, "stand_kvart_nog"] = f"{kv}-{ng}" if pd.notna(kv) and pd.notna(ng) else None
        out.at[i, "stand_dom_species"] = main["dom_species"]
        out.at[i, "stand_dom_age"] = main["dom_age"]
        out.at[i, "stand_forest_type"] = main["forest_type"]
        out.at[i, "stand_spruce_share"] = main["spruce_share"]
        sh = st.iloc[cand]["spruce_share"].to_numpy(dtype="float64")
        ok = np.isfinite(sh)
        if ok.any():
            out.at[i, "spruce_share_weighted"] = round(float(np.sum(sh[ok] * inter[ok]) / np.sum(inter[ok])), 2)
        out.at[i, "stand_cover_share"] = round(float(inter.sum() / geom.area), 2)
    return out
