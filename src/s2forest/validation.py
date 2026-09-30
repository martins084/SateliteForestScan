"""Validation against reference polygons (e.g. sanitary cuts with dates).

Rules (agreed with the project team):

* A reference is IN SCOPE if its cut date is on/after the start of the
  monitoring season and not later than `reference.max_date` (default: 31 March
  of the following year - sanitary cuts often follow summer damage in autumn or
  winter). Earlier cuts cannot be detected "before the cut" in this run; they
  are listed as out of scope.
* A detection MATCHES a reference if the polygons intersect after buffering the
  reference by `reference.match_buffer_m` (default 10 m).
* A reference is a TRUE POSITIVE only if a `type == "stress"` polygon matches
  it with `first_detected` BEFORE the cut date. Detecting the cut itself is not
  a success for an early-warning screen; references found only as a cut (or as
  stress on/after the cut date) are reported separately.
* Lead time = cut date - first_detected, in days (positive = found before the cut).
* Precision = stress polygons matching an in-scope reference before its cut /
  all stress polygons (optionally only the statuses sent to the drone).
  Reference data are usually incomplete (not every damaged stand is cut or
  recorded), so precision is a pessimistic estimate.
"""

from __future__ import annotations

from dataclasses import dataclass

import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr
from rasterio.features import geometry_mask

from .aoi import read_vector
from .config import Config

OUTCOMES = ["stress_before_cut", "stress_on_or_after_cut", "cut_only", "missed"]


@dataclass
class ValidationResult:
    references: gpd.GeoDataFrame   # one row per reference with outcome and lead time
    polygons: pd.DataFrame         # one row per stress polygon with match info
    summary: pd.DataFrame          # metric table
    timeseries: pd.DataFrame       # per reference, per date, split at the cut


def load_references(cfg: Config) -> tuple[gpd.GeoDataFrame, dict]:
    rc = cfg.reference
    if rc.path is None:
        raise ValueError("No reference data configured (reference.path)")
    ref = read_vector(rc.path, cfg.data.crs)
    info = {"n_loaded": len(ref)}
    if rc.date_field not in ref:
        raise KeyError(f"reference.date_field '{rc.date_field}' not in {list(ref.columns)}")
    if rc.reason_field and rc.reason_values:
        if rc.reason_field not in ref:
            raise KeyError(f"reference.reason_field '{rc.reason_field}' not in {list(ref.columns)}")
        keep = ref[rc.reason_field].astype(str).isin([str(v) for v in rc.reason_values])
        info["n_filtered_by_reason"] = int((~keep).sum())
        ref = ref[keep].copy()
    ref["ref_date"] = pd.to_datetime(ref[rc.date_field], errors="coerce", dayfirst=True)
    info["n_bad_date"] = int(ref["ref_date"].isna().sum())
    ref = ref[ref["ref_date"].notna()].copy()
    ref["ref_id"] = ref[rc.id_field].astype(str) if rc.id_field and rc.id_field in ref else [
        f"R{i:03d}" for i in range(1, len(ref) + 1)]
    return ref.reset_index(drop=True), info


def _scope(cfg: Config, ref: gpd.GeoDataFrame) -> pd.Series:
    start, _ = cfg.time.season_range(cfg.time.monitor_year)
    max_date = (pd.Timestamp(cfg.reference.max_date) if cfg.reference.max_date
                else pd.Timestamp(f"{cfg.time.monitor_year + 1}-03-31"))
    d = ref["ref_date"]
    return pd.Series(np.select([d < pd.Timestamp(start), d > max_date],
                               ["before_season", "after_max_date"], "in_scope"), index=ref.index)


def match_references(cfg: Config, ref: gpd.GeoDataFrame, polygons: gpd.GeoDataFrame
                     ) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    rc = cfg.reference
    ref = ref.copy()
    ref["scope"] = _scope(cfg, ref)
    buf = ref.geometry.buffer(rc.match_buffer_m)
    polys = polygons.copy()
    polys["first_detected"] = pd.to_datetime(polys["first_detected"])

    rows = []
    poly_hits: dict[int, list[str]] = {int(i): [] for i in polys["id"]} if len(polys) else {}
    for i, r in ref.iterrows():
        hit = polys[polys.intersects(buf.loc[i])] if len(polys) else polys
        stress = hit[hit["type"] == "stress"] if len(hit) else hit
        before = stress[stress["first_detected"] < r["ref_date"]] if len(stress) else stress
        if r["scope"] == "in_scope":
            for pid in before["id"] if len(before) else []:
                poly_hits[int(pid)].append(r["ref_id"])
        if len(before):
            outcome = "stress_before_cut"
        elif len(stress):
            outcome = "stress_on_or_after_cut"
        elif len(hit):
            outcome = "cut_only"
        else:
            outcome = "missed"
        first = before["first_detected"].min() if len(before) else (
            hit["first_detected"].min() if len(hit) else pd.NaT)
        lead = (r["ref_date"] - first).days if pd.notna(first) else np.nan
        rows.append({"ref_id": r["ref_id"], "ref_date": r["ref_date"].date(), "scope": r["scope"],
                     "outcome": outcome, "first_detected": first.date() if pd.notna(first) else None,
                     "lead_days": lead,
                     "matched_ids": ",".join(str(int(x)) for x in hit["id"]) if len(hit) else "",
                     "matched_types": ",".join(sorted(set(hit["type"]))) if len(hit) else "",
                     "area_ha": round(r.geometry.area / 1e4, 3)})
    out_ref = gpd.GeoDataFrame(rows, geometry=list(ref.geometry), crs=ref.crs)

    prow = []
    for _, p in polys.iterrows():
        if p["type"] != "stress":
            continue
        prow.append({"id": int(p["id"]), "status": p.get("status"),
                     "first_detected": p["first_detected"].date(), "area_ha": p["area_ha"],
                     "confidence": p["confidence"], "matched_refs": ",".join(poly_hits[int(p["id"])]),
                     "true_positive": bool(poly_hits[int(p["id"])])})
    return out_ref, pd.DataFrame(prow)


def metrics(refs: gpd.GeoDataFrame, polys: pd.DataFrame, statuses: list[str] | None = None
            ) -> dict:
    inscope = refs[refs["scope"] == "in_scope"]
    n_ref = len(inscope)
    n_tp_ref = int((inscope["outcome"] == "stress_before_cut").sum())
    p = polys if statuses is None or polys.empty else polys[polys["status"].isin(statuses)]
    n_poly = len(p)
    n_tp_poly = int(p["true_positive"].sum()) if n_poly else 0
    precision = n_tp_poly / n_poly if n_poly else np.nan
    recall = n_tp_ref / n_ref if n_ref else np.nan
    f1 = (2 * precision * recall / (precision + recall)
          if n_poly and n_ref and (precision + recall) > 0 else np.nan)
    leads = inscope.loc[inscope["outcome"] == "stress_before_cut", "lead_days"]
    out = {"references_in_scope": n_ref, "references_out_of_scope": int(len(refs) - n_ref),
           "stress_polygons": n_poly, "tp_polygons": n_tp_poly, "tp_references": n_tp_ref,
           "precision": precision, "recall": recall, "f1": f1,
           "lead_days_median": float(leads.median()) if len(leads) else np.nan,
           "lead_days_min": float(leads.min()) if len(leads) else np.nan,
           "lead_days_max": float(leads.max()) if len(leads) else np.nan}
    for o in OUTCOMES:
        out[f"refs_{o}"] = int((inscope["outcome"] == o).sum())
    return out


def reference_timeseries(refs: gpd.GeoDataFrame, indices: xr.Dataset, names: list[str],
                         max_refs: int = 200) -> pd.DataFrame:
    """Median index values inside each reference polygon per date, labelled
    pre_cut / post_cut relative to the reference date."""
    from rasterio.transform import from_origin

    refs = refs.head(max_refs)
    if refs.empty:
        return pd.DataFrame()
    # Load once, cropped to the references' extent (reading per reference is slow).
    minx, miny, maxx, maxy = refs.total_bounds
    sub = indices[names].sel(x=slice(minx - 20, maxx + 20), y=slice(maxy + 20, miny - 20)).load()
    x, y = sub.x.values, sub.y.values
    if len(x) < 2 or len(y) < 2:
        return pd.DataFrame()
    res = float(abs(x[1] - x[0]))
    tr = from_origin(float(x[0]) - res / 2, float(y[0]) + res / 2, res, res)
    times = pd.DatetimeIndex(sub.time.values)
    arrays = {n: sub[n].transpose("time", "y", "x").values for n in names}
    rows = []
    for _, r in refs.iterrows():
        inside = ~geometry_mask([r.geometry], out_shape=(len(y), len(x)), transform=tr)
        if not inside.any():
            continue
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            vals = {n: np.nanmedian(arrays[n][:, inside], axis=1) for n in names}
        cut = pd.Timestamp(r["ref_date"])
        for t_i, t in enumerate(times):
            row = {"ref_id": r["ref_id"], "date": t.date(),
                   "phase": "pre_cut" if t < cut else "post_cut",
                   "days_to_cut": (cut - t).days}
            row.update({n: (float(vals[n][t_i]) if np.isfinite(vals[n][t_i]) else None)
                        for n in names})
            rows.append(row)
    return pd.DataFrame(rows)


def validate(cfg: Config, polygons: gpd.GeoDataFrame, indices: xr.Dataset | None = None
             ) -> tuple[ValidationResult, dict]:
    ref, info = load_references(cfg)
    refs, polys = match_references(cfg, ref, polygons)
    rows = [{"subset": "all stress polygons", **metrics(refs, polys)},
            {"subset": f"drone statuses ({', '.join(cfg.targets.statuses)})",
             **metrics(refs, polys, cfg.targets.statuses)}]
    summary = pd.DataFrame(rows)
    ts = (reference_timeseries(refs, indices, list(cfg.indices)) if indices is not None
          else pd.DataFrame())
    return ValidationResult(references=refs, polygons=polys, summary=summary, timeseries=ts), info
