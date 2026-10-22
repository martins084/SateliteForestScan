"""Orthophoto desk check in QGIS: project, marking form, form import.

`prepare`: suspect polygons and drone targets of the run -> desk_check_<year>.gpkg (layers
`suspects`, `targets`, each with a `merka_id` and empty marking fields), a CSV marking form
(one row per object) and a QGIS project desk_check_<year>.qgs (plain XML, relative paths).

The orthophoto is NOT fetched or stored by this tool: LĢIA WMS data "cannot be modified,
deleted or downloaded" (WMS terms, see docs/RM_1_DATU_PARBAUDE.md). If `desk_check.wms_url`
is set, the project contains a WMS layer pointing to it (no user name / password - those are
entered in QGIS authentication after signing the LĢIA licence); otherwise the project only
has an empty group as a placeholder. QGIS only displays the WMS.

`import`: reads the filled form (CSV, ';' or ',' separated, or the edited GeoPackage) and
cross-tabulates detector type / status against the desk verdict.

The .qgs is plain XML in the QGIS 3 project format; checked headless with QGIS 3.44 (layers
valid, CRS EPSG:3059, value-map widget on `vertejums`), not yet used interactively.
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

import geopandas as gpd
import pandas as pd

from .config import Config

def _srs(epsg: str) -> str:
    """<spatialrefsys> with WKT: QGIS 3.44 did not resolve a bare <authid> (project CRS stayed empty)."""
    from pyproj import CRS

    wkt = CRS.from_user_input(epsg).to_wkt()
    return f"<spatialrefsys><wkt>{escape(wkt)}</wkt><authid>{epsg}</authid></spatialrefsys>"


VERDICTS = {"koki_stav": "koki stāv", "koki_gulus": "koki gulus", "izcirsts": "izcirsts",
            "nav_skaidrs": "nav skaidrs"}
FORM_COLUMNS = ["merka_id", "vertejums", "piezimes", "datums", "vertetajs"]


def _parse_date(v: str):
    """ISO (2026-10-15) or Latvian day-first (15.10.2026)."""
    v = str(v).strip()
    fmt = "%Y-%m-%d" if len(v) >= 10 and v[4] == "-" else "%d.%m.%Y"
    return pd.to_datetime(v, format=fmt, errors="coerce")


def desk_objects(polys: gpd.GeoDataFrame, targets: gpd.GeoDataFrame | None
                 ) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame | None]:
    """Add `merka_id` (P<id> for suspect polygons, D<target_id> for drone targets) and the
    empty marking fields."""
    p = polys.copy()
    p.insert(0, "merka_id", [f"P{int(i)}" for i in p["id"]])
    t = None
    if targets is not None and len(targets):
        t = targets.copy()
        t.insert(0, "merka_id", [f"D{v}" for v in t["target_id"]])
    for g in (p, t):
        if g is not None:
            for c in FORM_COLUMNS[1:]:
                g[c] = ""
    return p, t


# --- QGIS project XML -----------------------------------------------------------------------

def _value_map() -> str:
    opts = "".join(f'<Option type="Map"><Option name={quoteattr(lbl)} value={quoteattr(code)} '
                   f'type="QString"/></Option>' for code, lbl in VERDICTS.items())
    return ('<field name="vertejums"><editWidget type="ValueMap"><config><Option type="Map">'
            f'<Option name="map" type="List">{opts}</Option></Option></config></editWidget></field>')


def _vector_layer(lid: str, name: str, source: str, geom: str, symbol: str) -> str:
    return f"""  <maplayer type="vector" geometry="{geom}">
   <id>{lid}</id>
   <datasource>{escape(source)}</datasource>
   <layername>{escape(name)}</layername>
   <srs>{_srs("EPSG:3059")}</srs>
   <provider encoding="UTF-8">ogr</provider>
   <renderer-v2 type="singleSymbol" symbollevels="0" enableorderby="0" forceraster="0">
    <symbols>{symbol}</symbols>
   </renderer-v2>
   <fieldConfiguration>{_value_map()}</fieldConfiguration>
  </maplayer>
"""


def _outline(name: str, rgb: str, width: float) -> str:
    return (f'<symbol type="fill" name="{name}" alpha="1" clip_to_extent="1" force_rhr="0">'
            '<layer class="SimpleFill" enabled="1" locked="0" pass="0"><Option type="Map">'
            '<Option name="style" value="no" type="QString"/>'
            f'<Option name="outline_color" value="{rgb},255" type="QString"/>'
            f'<Option name="outline_width" value="{width}" type="QString"/>'
            '<Option name="outline_width_unit" value="MM" type="QString"/>'
            '</Option></layer></symbol>')


def qgis_project(gpkg_name: str, year: int, has_targets: bool, wms_url: str | None,
                 wms_layers: str | None, wms_crs: str = "EPSG:3059",
                 wms_format: str = "image/jpeg") -> str:
    layers = [("suspects", f"Aizdomīgie poligoni {year}", _outline("0", "227,26,28", 0.6))]
    if has_targets:
        layers.append(("targets", "Drona mērķi", _outline("0", "31,120,180", 0.4)))
    maps, tree = [], []
    for lyr, name, sym in layers:
        lid = f"desk_{lyr}"
        src = f"./{gpkg_name}|layername={lyr}"
        maps.append(_vector_layer(lid, name, src, "Polygon", sym))
        tree.append(f'  <layer-tree-layer id="{lid}" name={quoteattr(name)} '
                    f'source={quoteattr(src)} providerKey="ogr" checked="Qt::Checked" expanded="0"/>')
    wms_name = "LĢIA ortofoto (WMS, pēc licences)"
    if wms_url:
        src = (f"crs={wms_crs}&dpiMode=7&format={wms_format}&layers={wms_layers or ''}"
               f"&styles=&url={wms_url}")
        maps.append(f"""  <maplayer type="raster">
   <id>desk_orthophoto_wms</id>
   <datasource>{escape(src)}</datasource>
   <layername>{escape(wms_name)}</layername>
   <srs>{_srs(wms_crs)}</srs>
   <provider>wms</provider>
  </maplayer>
""")
        tree.append(f'  <layer-tree-layer id="desk_orthophoto_wms" name={quoteattr(wms_name)} '
                    f'source={quoteattr(src)} providerKey="wms" checked="Qt::Checked" expanded="0"/>')
    else:
        tree.append(f'  <layer-tree-group name={quoteattr(wms_name + " - pievienot QGIS")} '
                    'checked="Qt::Checked" expanded="1"/>')
    return f"""<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis projectname={quoteattr(f"Ortofoto galda pārbaude {year}")} version="3.34.0">
 <title>{escape(f"Ortofoto galda pārbaude {year}")}</title>
 <projectCrs>{_srs("EPSG:3059")}</projectCrs>
 <layer-tree-group>
{chr(10).join(tree)}
 </layer-tree-group>
 <projectlayers>
{"".join(maps)} </projectlayers>
 <properties>
  <Paths><Absolute type="bool">false</Absolute></Paths>
  <SpatialRefSys><ProjectionsEnabled type="int">1</ProjectionsEnabled><ProjectCrs type="QString">EPSG:3059</ProjectCrs></SpatialRefSys>
 </properties>
</qgis>
"""


def prepare(cfg: Config, out_dir: Path) -> dict[str, Path]:
    year = cfg.time.monitor_year
    gpkg = cfg.run_dir / "vectors" / "suspects.gpkg"
    polys = gpd.read_file(gpkg, layer=f"suspects_{year}")
    try:
        targets = gpd.read_file(gpkg, layer="drone_targets")
    except Exception:  # noqa: BLE001 - runs without drone targets
        targets = None
    p, t = desk_objects(polys, targets)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    g = out_dir / f"desk_check_{year}.gpkg"
    if g.exists():
        g.unlink()
    p.to_file(g, layer="suspects", driver="GPKG", engine="pyogrio")
    if t is not None:
        t.to_file(g, layer="targets", driver="GPKG", engine="pyogrio")
    out["gpkg"] = g
    ids = list(p["merka_id"]) + ([] if t is None else list(t["merka_id"]))
    form = pd.DataFrame({c: [""] * len(ids) for c in FORM_COLUMNS})
    form["merka_id"] = ids
    f = out_dir / f"galda_veidlapa_{year}.csv"
    form.to_csv(f, index=False, sep=";", encoding="utf-8-sig")
    out["form"] = f
    dc = cfg.desk_check
    q = out_dir / f"desk_check_{year}.qgs"
    q.write_text(qgis_project(g.name, year, t is not None, dc.wms_url, dc.wms_layers,
                              dc.wms_crs, dc.wms_format), encoding="utf-8")
    out["qgis"] = q
    return out


# --- import --------------------------------------------------------------------------------

def read_form(path: Path) -> tuple[pd.DataFrame, list[str]]:
    """Filled form (CSV or the edited desk_check GeoPackage) -> (rows with a verdict, problems)."""
    path = Path(path)
    if path.suffix.lower() == ".gpkg":
        import pyogrio

        parts = [pd.DataFrame(gpd.read_file(path, layer=n).drop(columns="geometry"))
                 for n, _ in pyogrio.list_layers(path)]
        df = pd.concat(parts, ignore_index=True)
        df = df[[c for c in FORM_COLUMNS if c in df]].astype(str).replace({"None": "", "nan": ""})
    else:
        raw = path.read_text(encoding="utf-8-sig")
        first = raw.splitlines()[0]
        sep = ";" if first.count(";") >= first.count(",") else ","
        df = pd.read_csv(StringIO(raw), sep=sep, dtype=str).fillna("")
    problems = []
    miss = [c for c in FORM_COLUMNS if c not in df]
    if miss:
        return df, [f"trūkst kolonnu: {miss}"]
    df = df[(df["merka_id"].str.strip() != "") & (df["vertejums"].str.strip() != "")].copy()
    for _, r in df.iterrows():
        tag = f"rinda {r['merka_id']}"
        if r["vertejums"] not in VERDICTS:
            problems.append(f"{tag}: vertejums '{r['vertejums']}' nav no {list(VERDICTS)}")
        if r["datums"] and pd.isna(_parse_date(r["datums"])):
            problems.append(f"{tag}: nederīgs datums '{r['datums']}'")
    df["datums"] = [None if not v or pd.isna(d := _parse_date(v)) else d.date() for v in df["datums"]]
    return df, problems


def results(form: pd.DataFrame, suspects: pd.DataFrame, targets: pd.DataFrame | None
            ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Join verdicts to the desk objects -> (joined rows, crosstab detector class x verdict)."""
    parts = [pd.DataFrame({"merka_id": suspects["merka_id"], "area_ha": suspects["area_ha"],
                           "detektors": "poligons " + suspects["type"].astype(str) + "/"
                                        + suspects["status"].astype(str)})]
    if targets is not None and len(targets):
        parts.append(pd.DataFrame({"merka_id": targets["merka_id"], "area_ha": targets["area_ha"],
                                   "detektors": "mērķis " + targets["kind"].astype(str)}))
    obj = pd.concat(parts, ignore_index=True)
    j = form.merge(obj, on="merka_id", how="left")
    j["detektors"] = j["detektors"].fillna("nezināms merka_id")
    tab = pd.crosstab(j["detektors"], j["vertejums"], margins=True, margins_name="kopā")
    return j, tab
