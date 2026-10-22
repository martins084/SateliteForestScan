"""Golden regression snapshot of an s2forest run (detection outputs only).

Hashes (sha256) of:
  * every layer of vectors/suspects.gpkg (rows sorted, attributes + geometry WKB),
  * every GeoTIFF under rasters/ (pixel arrays, CRS, transform),
  * detection tables (CSV content, rows sorted).
Timestamps, run_metadata.json, figures and reports are not included.

    python scripts/golden_s2forest.py snapshot output/<run> tests/golden/kalsnava_v02.json
    python scripts/golden_s2forest.py compare  output/<run> tests/golden/kalsnava_v02.json
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import rasterio

TABLES = ["suspects_{y}.csv", "polygon_status_{y}.csv", "drone_targets_{y}.csv",
          "drone_missions_{y}.csv", "regional_offsets.csv", "ring_control_{y}.csv"]


def _h(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def frame_hash(df: pd.DataFrame) -> str:
    df = df.reindex(sorted(df.columns), axis=1)
    df = df.sort_values(list(df.columns)).reset_index(drop=True)
    return _h(df.to_csv(index=False, lineterminator="\n").encode())


def snapshot(run_dir: Path) -> dict:
    out: dict[str, dict] = {"vectors": {}, "rasters": {}, "tables": {}}
    gpkg = run_dir / "vectors" / "suspects.gpkg"
    for name, _ in pyogrio.list_layers(gpkg):
        g = gpd.read_file(gpkg, layer=name)
        df = pd.DataFrame(g.drop(columns="geometry"))
        df["_wkb"] = [geom.wkb_hex if geom is not None else "" for geom in g.geometry]
        out["vectors"][name] = {"rows": len(g), "sha256": frame_hash(df.astype(str))}
    for tif in sorted((run_dir / "rasters").rglob("*.tif")):
        with rasterio.open(tif) as s:
            a = s.read()
            meta = f"{s.crs}|{tuple(s.transform)}|{a.shape}|{a.dtype}|{s.descriptions}".encode()
        out["rasters"][str(tif.relative_to(run_dir)).replace("\\", "/")] = {
            "shape": list(a.shape), "sha256": _h(meta + np.ascontiguousarray(a).tobytes())}
    years = sorted({p.stem.split("_")[-1] for p in (run_dir / "tables").glob("suspects_*.csv")})
    for y in years:
        for t in TABLES:
            p = run_dir / "tables" / t.format(y=y)
            if p.exists():
                out["tables"][p.name] = {"sha256": frame_hash(pd.read_csv(p).astype(str))}
    return out


def compare(a: dict, b: dict) -> list[str]:
    diffs = []
    for sec in ("vectors", "rasters", "tables"):
        for k in sorted(set(a[sec]) | set(b[sec])):
            if k not in a[sec] or k not in b[sec]:
                diffs.append(f"{sec}/{k}: only in {'reference' if k in b[sec] else 'current'}")
            elif a[sec][k] != b[sec][k]:
                diffs.append(f"{sec}/{k}: differs {a[sec][k]} != {b[sec][k]}")
    return diffs


if __name__ == "__main__":
    mode, run, ref = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    snap = snapshot(run)
    if mode == "snapshot":
        ref.parent.mkdir(parents=True, exist_ok=True)
        ref.write_text(json.dumps(snap, indent=1, sort_keys=True), encoding="utf-8")
        print(f"snapshot: {sum(len(v) for v in snap.values())} items -> {ref}")
    else:
        d = compare(snap, json.loads(ref.read_text(encoding="utf-8")))
        print("IDENTICAL" if not d else "\n".join(d))
        sys.exit(1 if d else 0)
