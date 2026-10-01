"""Single-file HTML report (Latvian) with embedded figures.

Figures are also written as separate PNG files (200 dpi) to
`figures/report/` for reuse in the grant application and slides.
The report is built from the run's output files, so it can be regenerated
without recomputing the detection.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from jinja2 import Environment, select_autoescape

from . import viz
from .aoi import read_vector
from .config import Config

STATUS_LV = {"new": "jauns", "persistent": "noturīgs", "recovered": "atkopies"}
TYPE_LV = {"stress": "stress", "cut": "cirte"}


def _img(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def _fmt(v, nd=2, dash="–"):
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return dash
    if isinstance(v, (int, np.integer)):
        return f"{int(v)}"
    if isinstance(v, (float, np.floating)):
        return f"{v:.{nd}f}".replace(".", ",")
    return str(v)


def _read_layer(gpkg: Path, layer: str) -> gpd.GeoDataFrame | None:
    import pyogrio

    if not gpkg.exists() or layer not in [l[0] for l in pyogrio.list_layers(gpkg)]:
        return None
    return gpd.read_file(gpkg, layer=layer)


def method_lines(cfg: Config) -> list[str]:
    """Method description generated from the EFFECTIVE configuration of the run."""
    a, m, fm, lf, n = cfg.anomaly, cfg.masking, cfg.forest_mask, cfg.linear_features, cfg.anomaly.normalization
    f = lambda v, nd=2: _fmt(v, nd)
    lines = [
        "Dati: " + ", ".join(f"{s.name}/{s.collection}" for s in cfg.data.sources)
        + " (STAC, bez autentifikācijas); atstarošanās harmonizēta pēc processing baseline "
        "(BOA_ADD_OFFSET).",
        f"Mākoņu maska: SCL klases {', '.join(map(str, m.invalid_scl))}, buferis {m.cloud_buffer_m:.0f} m"
        + (f"; laikrindu dūmakas tests (B02 > bāze + {f(m.haze.b02_threshold, 3)})" if m.haze.enabled
           else "; dūmakas tests izslēgts")
        + f"; aina tiek izmantota, ja ≥ {cfg.data.min_valid_fraction:.0%} AOI pikseļu ir derīgi.",
        f"Režģis {cfg.data.crs}, {cfg.data.resolution:g} m; indeksi {', '.join(i.upper() for i in cfg.indices)}.",
        "Meža maska: HRL Dominant Leaf Type 2018 (klases " + ", ".join(map(str, fm.classes)) + ")"
        + (f"; izslēgts, ja bāzes vasaras NDVI < {f(fm.min_summer_ndvi)}" if fm.min_summer_ndvi is not None else "")
        + (f"; izslēgts, ja bāzes {fm.seasonal_range_index.upper()} sezonālais diapazons (p90−p10) > "
           f"{f(fm.max_seasonal_range)}" if fm.max_seasonal_range is not None else "")
        + (f"; izslēgts ≤ {lf.buffer_m:.0f} m no OSM ceļiem" if lf.enabled else "; ceļu maska izslēgta")
        + ".",
    ]
    if a.baseline_method == "harmonic":
        lines.append(f"Bāze ({cfg.time.baseline_year_list[0]}–{cfg.time.baseline_year_list[-1]}): harmonisks "
                     f"sezonālais modelis katram pikselim (brīvais loceklis + {a.harmonics} harmonika(s)), robusta "
                     f"pielāgošana (IRLS, Huber k = {f(a.huber_k, 3)}, {a.robust_iterations} iterācijas); mērogs = "
                     f"atlikumu MAD × 1,4826, ne mazāks par mad_floor; ≥ {a.min_baseline_obs} bāzes novērojumi.")
    else:
        lines.append(f"Bāze ({cfg.time.baseline_year_list[0]}–{cfg.time.baseline_year_list[-1]}): mediāna un MAD "
                     f"±{a.doy_window} dienu logā; ≥ {a.min_baseline_obs} bāzes novērojumi.")
    if n.enabled:
        lines.append(f"Reģionālā normalizācija: katra datuma nobīde = meža pikseļu mediānā novirze AOI + "
                     f"{n.buffer_m / 1000:g} km buferī ({cfg.data.context_resolution:g} m), divos soļos.")
    else:
        lines.append("Reģionālā normalizācija izslēgta.")
    span = getattr(a, "persistence_min_days", 0)
    lines.append(f"Anomālija: {a.primary_index.upper()} z ≥ {f(a.z_threshold, 1)} un vismaz {a.min_confirming} "
                 f"cits indekss; noturība ≥ {a.persistence} secīgi derīgi novērojumi"
                 + (f", kas aptver ≥ {span} dienas" if span else "")
                 + f"; min. laukums {f(a.min_area_ha, 1)} ha; cirtes pazīme: NDVI ≤ {f(a.cut_ndvi_max)} un "
                 f"kritums ≥ {f(a.cut_ndvi_drop)}, vai NDMI kritums ≥ {f(a.cut_ndmi_drop)}.")
    return lines


def build_report(cfg: Config, n_series: int = 5) -> Path:
    from .pipeline import index_stage

    year = cfg.time.monitor_year
    run = cfg.run_dir
    fig_dir = run / "figures" / "report"
    fig_dir.mkdir(parents=True, exist_ok=True)
    meta = json.loads((run / "run_metadata.json").read_text(encoding="utf-8"))
    gpkg = run / "vectors" / "suspects.gpkg"
    polys = _read_layer(gpkg, f"suspects_{year}")
    if polys is None:
        raise FileNotFoundError(f"{gpkg} (layer suspects_{year}) not found - run `detect` first")
    missions = _read_layer(gpkg, "drone_missions")
    targets = _read_layer(gpkg, "drone_targets")
    acq = pd.read_csv(run / "diagnostics" / "acquisitions.csv")
    aoi = read_vector(cfg.aoi, cfg.data.crs)

    st = index_stage(cfg)
    figs: dict[str, Path] = {}
    avail = viz.monthly_availability(acq, st.cube.time.values)
    figs["availability"] = viz.plot_monthly_availability(avail, fig_dir / "01_datu_pieejamiba.png")
    figs["overview"] = viz.plot_overview_map(st.cube, polys, missions, aoi, year,
                                             fig_dir / "02_parskata_karte.png")
    # 3-5 time series: stress polygons first (persistent, new, recovered), then largest cuts
    order = {"persistent": 0, "new": 1, "recovered": 2}
    stress = polys[polys["type"] == "stress"].copy()
    stress["_o"] = stress["status"].map(order)
    stress = stress.sort_values(["_o", "confidence"], ascending=[True, False]).drop(columns="_o")
    cuts = polys[polys["type"] == "cut"].sort_values("area_ha", ascending=False)
    series_polys = pd.concat([stress.head(n_series), cuts.head(max(3 - len(stress), 0))])
    series_polys = gpd.GeoDataFrame(series_polys.head(n_series), crs=polys.crs)
    if len(series_polys):
        figs["timeseries"] = viz.plot_polygon_chips(st.cube, st.indices, series_polys, year,
                                                    fig_dir / "03_laika_rindas.png",
                                                    n=len(series_polys))
    val_summary = val_refs = None
    vs = run / "tables" / f"validation_summary_{year}.csv"
    if vs.exists():
        val_summary = pd.read_csv(vs)
        val_refs = pd.read_csv(run / "tables" / f"validation_references_{year}.csv")
        src = run / "figures" / f"validation_{year}.png"
        if src.exists():
            figs["validation"] = fig_dir / "04_validacija.png"
            figs["validation"].write_bytes(src.read_bytes())

    # --- numbers ------------------------------------------------------------------
    acq["dt"] = pd.to_datetime(acq["datetime"], utc=True)
    in_years = acq["dt"].dt.year.isin(cfg.time.years)
    usable = meta.get("fetch", {}).get("usable_per_year", {})
    det = meta.get("detect", {})
    status_tab = (polys.groupby(["type", "status"])["area_ha"].agg(["size", "sum"]).reset_index()
                  if len(polys) else pd.DataFrame(columns=["type", "status", "size", "sum"]))
    def _n(t, s=None):
        d = polys[polys["type"] == t]
        return int(len(d) if s is None else (d["status"] == s).sum())

    months = sorted(avail["month"].unique())
    avail_rows = []
    for y in sorted(avail["year"].unique()):
        d = avail[avail["year"] == y].set_index("month")
        avail_rows.append({"year": y, "cells": [
            f"{int(d.loc[m, 'accepted'])}/{int(d.loc[m, 'total'])}" if m in d.index else "0/0"
            for m in months]})

    top_stress = []
    prim = cfg.anomaly.primary_index
    for _, r in stress.head(10).iterrows():
        top_stress.append({"id": r["id"], "status": STATUS_LV.get(r["status"], r["status"]),
                           "first": r["first_detected"], "area": _fmt(r["area_ha"]),
                           "delta": _fmt(r.get(f"delta_{prim}"), 3), "conf": _fmt(r["confidence"]),
                           "before": "jā" if bool(r.get("onset_before_season")) else "nē",
                           "linear": "jā" if bool(r.get("linear_feature", False)) else "",
                           "near_road": "jā" if bool(r.get("near_road", False)) else "",
                           "autumn": "jā" if bool(r.get("onset_prev_autumn", False)) else "nē",
                           "road": _fmt(r.get("dist_to_road_m"), 0)})
    mission_rows = []
    if missions is not None:
        for _, m in missions.iterrows():
            mission_rows.append({"id": m["mission_id"], "stress": int(m["n_stress"]),
                                 "edges": int(m["n_cut_edge"]), "area": _fmt(m["flight_area_ha"], 1),
                                 "lat": f"{m['centroid_lat']:.5f}", "lon": f"{m['centroid_lon']:.5f}",
                                 "targets": m["target_ids"]})
    val_rows = []
    if val_summary is not None:
        for _, r in val_summary.iterrows():
            subset = ("visi stresa poligoni" if r["subset"].startswith("all")
                      else "tikai drona statusi (" + ", ".join(
                          STATUS_LV.get(x, x) for x in cfg.targets.statuses) + ")")
            val_rows.append({"subset": subset, "inscope": int(r["references_in_scope"]),
                             "out": int(r["references_out_of_scope"]),
                             "tp": int(r["refs_stress_before_cut"]),
                             "after": int(r["refs_stress_on_or_after_cut"]),
                             "cut": int(r["refs_cut_only"]), "missed": int(r["refs_missed"]),
                             "p": _fmt(r["precision"]), "r": _fmt(r["recall"]), "f1": _fmt(r["f1"]),
                             "lead": _fmt(r["lead_days_median"], 0)})
    val_detail = []
    if val_refs is not None:
        tp = val_refs[(val_refs["scope"] == "in_scope") & (val_refs["outcome"] == "stress_before_cut")]
        by_id = polys.set_index("id")
        for _, r in tp.iterrows():
            ids = [int(float(x)) for x in str(r["matched_ids"]).split(",") if x and x != "nan"]
            st_txt = ", ".join(f"#{i} {STATUS_LV.get(by_id.at[i, 'status'], by_id.at[i, 'status'])}"
                               for i in ids if i in by_id.index and by_id.at[i, "type"] == "stress")
            val_detail.append({"id": r["ref_id"], "date": r["ref_date"], "first": r["first_detected"],
                               "lead": _fmt(r["lead_days"], 0), "ids": r["matched_ids"],
                               "stress": st_txt})

    ctx = {
        "title": f"Meža stresa skrīnings — {cfg.run_name}",
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "version": version("s2forest"),
        "year": year, "baseline": f"{cfg.time.baseline_year_list[0]}–{cfg.time.baseline_year_list[-1]}",
        "season": f"{cfg.time.season_start} … {cfg.time.season_end}",
        "aoi_ha": _fmt(aoi.to_crs(cfg.data.crs).area.sum() / 1e4, 0),
        "analysed_ha": _fmt(det.get("analysed_ha"), 0),
        "excluded_ha": _fmt(det.get("baseline_disturbed_ha"), 0),
        "n_acq": int(in_years.sum()), "n_acc": int((in_years & (acq["status"] == "accepted")).sum()),
        "n_usable": int(st.cube.sizes["time"]),
        "usable_mon": usable.get(str(year), usable.get(year, "–")),
        "n_stress": _n("stress"), "n_stress_p": _n("stress", "persistent"),
        "n_stress_n": _n("stress", "new"), "n_stress_r": _n("stress", "recovered"),
        "stress_ha": _fmt(polys.loc[polys["type"] == "stress", "area_ha"].sum()),
        "n_cut": _n("cut"), "cut_ha": _fmt(polys.loc[polys["type"] == "cut", "area_ha"].sum(), 1),
        "n_targets": 0 if targets is None else len(targets),
        "n_missions": len(mission_rows),
        "months": [viz.MONTHS_LV.get(m, str(m)) for m in months], "avail_rows": avail_rows,
        "status_rows": [{"type": TYPE_LV.get(r["type"], r["type"]),
                         "status": STATUS_LV.get(r["status"], r["status"]),
                         "n": int(r["size"]), "ha": _fmt(r["sum"])} for _, r in status_tab.iterrows()],
        "top_stress": top_stress, "prim": prim.upper(), "missions": mission_rows,
        "val_rows": val_rows, "val_detail": val_detail,
        "val_description": cfg.reference.description,
        "method_lines": method_lines(cfg),
        "k": _fmt(cfg.anomaly.z_threshold, 1), "N": cfg.anomaly.persistence,
        "min_area": _fmt(cfg.anomaly.min_area_ha, 1),
        "sources": ", ".join(f"{s.name}/{s.collection}" for s in cfg.data.sources),
        "figs": {k: _img(v) for k, v in figs.items()},
        "fig_files": {k: v.name for k, v in figs.items()},
    }
    env = Environment(autoescape=select_autoescape(["html"]))
    html = env.from_string(TEMPLATE).render(**ctx)
    out = run / f"atskaite_{cfg.run_name}_{year}.html"
    out.write_text(html, encoding="utf-8")
    return out


TEMPLATE = r"""<!doctype html>
<html lang="lv">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }}</title>
<style>
  :root { --ink:#0b0b0b; --ink2:#52514e; --muted:#8a8984; --line:#e4e3df; --bg:#fcfcfb;
          --card:#ffffff; --accent:#2a78d6; --warn:#eb6834; }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--ink);
         font: 15px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif; }
  main { max-width: 1100px; margin: 0 auto; padding: 32px 20px 64px; }
  h1 { font-size: 26px; margin: 0 0 4px; }
  h2 { font-size: 19px; margin: 40px 0 10px; padding-top: 8px; border-top: 1px solid var(--line); }
  .sub { color: var(--ink2); margin: 0 0 20px; }
  .note { color: var(--ink2); font-size: 13.5px; }
  .callout { background: #fff7f2; border-left: 4px solid var(--warn); padding: 10px 14px;
             margin: 14px 0; font-size: 14px; }
  .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; }
  .tile { background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 12px 14px; }
  .tile .v { font-size: 24px; font-weight: 600; }
  .tile .l { color: var(--ink2); font-size: 13px; }
  figure { margin: 12px 0 4px; }
  figure img { width: 100%; height: auto; border: 1px solid var(--line); border-radius: 6px; background:#fff; }
  figcaption { color: var(--ink2); font-size: 13px; margin-top: 4px; }
  .tablewrap { overflow-x: auto; }
  table { border-collapse: collapse; width: 100%; font-size: 14px; background: var(--card); }
  th, td { border-bottom: 1px solid var(--line); padding: 6px 8px; text-align: left; vertical-align: top; }
  th { color: var(--ink2); font-weight: 600; background: #f6f5f2; }
  td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
  ul { padding-left: 20px; }
  footer { margin-top: 48px; color: var(--muted); font-size: 12.5px; }
  @media print { h2 { break-after: avoid; } figure { break-inside: avoid; } }
</style>
</head>
<body><main>

<h1>{{ title }}</h1>
<p class="sub">Sentinel-2 skrīnings (1. līmenis) · monitoringa gads {{ year }}, bāze {{ baseline }},
sezona {{ season }} · sagatavots {{ generated }} · s2forest {{ version }}</p>

<div class="callout"><b>Kā lasīt šo atskaiti.</b> Šis ir <b>skrīninga</b> slānis, kas norāda,
kur sūtīt dronu verifikācijai. Sentinel-2 izšķirtspēja ir 10–20 m: rīks nosaka izmaiņas koku
grupu vai nogabala daļu līmenī, nevis atsevišķus kokus, un <b>nav</b> droša "zaļā uzbrukuma"
(agrīnās, vizuāli neredzamās) stadijas noteikšana.</div>

<h2>Kopsavilkums</h2>
<div class="tiles">
  <div class="tile"><div class="v">{{ analysed_ha }} ha</div><div class="l">analizētais skujkoku mežs (no {{ aoi_ha }} ha AOI)</div></div>
  <div class="tile"><div class="v">{{ usable_mon }}</div><div class="l">derīgi novērojumi {{ year }}. gadā</div></div>
  <div class="tile"><div class="v">{{ n_stress_p + n_stress_n }}</div><div class="l">stresa vietas drona pārbaudei (noturīgas {{ n_stress_p }}, jaunas {{ n_stress_n }})</div></div>
  <div class="tile"><div class="v">{{ n_cut }}</div><div class="l">cirtes, {{ cut_ha }} ha</div></div>
  <div class="tile"><div class="v">{{ n_missions }}</div><div class="l">drona misijas ({{ n_targets }} mērķi kopā)</div></div>
</div>
<p class="note">Kopā {{ n_acq }} Sentinel-2 pārlidojumi virs AOI periodā; {{ n_acc }} pietiekami
skaidri pēc SCL mākoņu maskas (≥ 60 % derīgu pikseļu), un {{ n_usable }} izmantoti analīzē pēc
papildu dūmakas testa. Stresa poligoni: {{ n_stress }} ({{ stress_ha }} ha), no tiem
{{ n_stress_r }} ar statusu "atkopies" (izmaiņa atgriezusies normā, visticamāk, fenoloģijas artefakts).
No analīzes izslēgti {{ excluded_ha }} ha, kas jau bāzes periodā bija nocirsti vai noturīgi anomāli.</p>

<h2>Datu pieejamība</h2>
<figure><img src="{{ figs.availability }}" alt="Derīgie pārlidojumi pa mēnešiem">
<figcaption>Analīzē izmantoto (pēc SCL maskas un dūmakas testa) / visu pārlidojumu skaits pa mēnešiem. Fails: figures/report/{{ fig_files.availability }}</figcaption></figure>
<div class="tablewrap"><table>
<tr><th>Gads</th>{% for m in months %}<th class="num">{{ m }}</th>{% endfor %}</tr>
{% for r in avail_rows %}<tr><td>{{ r.year }}</td>{% for c in r.cells %}<td class="num">{{ c }}</td>{% endfor %}</tr>{% endfor %}
</table></div>

<h2>Pārskata karte</h2>
<figure><img src="{{ figs.overview }}" alt="Pārskata karte">
<figcaption>Stresa poligoni (oranža kontūra; punktēta = atkopies), cirtes (zils laukums) un
prioritārās drona misijas (pārtraukta līnija). Fails: figures/report/{{ fig_files.overview }}</figcaption></figure>

<h2>Poligonu statuss</h2>
<div class="tablewrap"><table>
<tr><th>Tips</th><th>Statuss</th><th class="num">Skaits</th><th class="num">Platība, ha</th></tr>
{% for r in status_rows %}<tr><td>{{ r.type }}</td><td>{{ r.status }}</td><td class="num">{{ r.n }}</td><td class="num">{{ r.ha }}</td></tr>{% endfor %}
</table></div>
<p class="note"><b>Jauns</b>: pēc pirmās noteikšanas vēl par maz novērojumu lēmumam.
<b>Noturīgs</b>: izmaiņa saglabājas. <b>Atkopies</b>: atgriezies normā. Poligoni netiek dzēsti.</p>
{% if top_stress %}
<div class="tablewrap"><table>
<tr><th>ID</th><th>Statuss</th><th>Pirmoreiz</th><th class="num">Platība, ha</th><th class="num">{{ prim }} izmaiņa</th><th class="num">Ticamība</th><th>Pirms sezonas</th><th>Sācies iepr. rudenī</th><th>Iegarens</th><th>Pie ceļa</th><th class="num">Līdz ceļam, m</th></tr>
{% for r in top_stress %}<tr><td>#{{ r.id }}</td><td>{{ r.status }}</td><td>{{ r.first }}</td><td class="num">{{ r.area }}</td><td class="num">{{ r.delta }}</td><td class="num">{{ r.conf }}</td><td>{{ r.before }}</td><td>{{ r.autumn }}</td><td>{{ r.linear }}</td><td>{{ r.near_road }}</td><td class="num">{{ r.road }}</td></tr>{% endfor %}
</table></div>
<p class="note">Ticamība ir heuristisks 0–1 rādītājs (z lielums, indeksu saskaņa, noturība,
bāzes novērojumu skaits), nevis varbūtība.</p>
{% endif %}

{% if figs.timeseries %}
<h2>Laika rindas</h2>
<figure><img src="{{ figs.timeseries }}" alt="Laika rindas">
<figcaption>RGB pirms (iepriekšējā gada vasara) un {{ year }}. gadā, un {{ prim }} mediāna poligonā
visā periodā; pārtrauktā līnija = pirmā noteikšana. Fails: figures/report/{{ fig_files.timeseries }}</figcaption></figure>
{% endif %}

<h2>Drona misijas</h2>
{% if missions %}
<div class="tablewrap"><table>
<tr><th>Misija</th><th class="num">Stresa mērķi</th><th class="num">Cirtes malas</th><th class="num">Laukums, ha</th><th>Centrs (WGS84)</th><th>Mērķi</th></tr>
{% for m in missions %}<tr><td>{{ m.id }}</td><td class="num">{{ m.stress }}</td><td class="num">{{ m.edges }}</td><td class="num">{{ m.area }}</td><td>{{ m.lat }}, {{ m.lon }}</td><td>{{ m.targets }}</td></tr>{% endfor %}
</table></div>
<p class="note">Prioritāte: 1 — noturīgs stress, 2 — jauns stress, 3 — stress pie ceļa
(≤ 30 m) vai iegarens (iespējami ceļmalas darbi / lineāri objekti), 4 — cirtes malas. Cirtes malas (30 m skujkoku josla gar
pēdējo 2 gadu cirtēm) ir sakārtotas pēc riska: malas orientācija (D–DR–R vērstas malas), cirtes svaigums
un skujkoku īpatsvars. KML: vectors/drone_missions_{{ year }}.kml, vectors/drone_targets_{{ year }}.kml.</p>
{% else %}<p>Nav drona misiju.</p>{% endif %}

<h2>Validācija</h2>
{% if val_rows %}
{% if val_description %}<div class="callout">{{ val_description }}</div>{% endif %}
<div class="tablewrap"><table>
<tr><th>Poligonu kopa</th><th class="num">References</th><th class="num">Ārpus</th><th class="num">Stress pirms cirtes (TP)</th><th class="num">Stress pēc cirtes</th><th class="num">Tikai cirte</th><th class="num">Nav noteikts</th><th class="num">Precision</th><th class="num">Recall</th><th class="num">F1</th><th class="num">Aizkave, d (mediāna)</th></tr>
{% for r in val_rows %}<tr><td>{{ r.subset }}</td><td class="num">{{ r.inscope }}</td><td class="num">{{ r.out }}</td><td class="num">{{ r.tp }}</td><td class="num">{{ r.after }}</td><td class="num">{{ r.cut }}</td><td class="num">{{ r.missed }}</td><td class="num">{{ r.p }}</td><td class="num">{{ r.r }}</td><td class="num">{{ r.f1 }}</td><td class="num">{{ r.lead }}</td></tr>{% endfor %}
</table></div>
{% if val_detail %}
<p><b>References ar stresu pirms cirtes:</b></p>
<div class="tablewrap"><table>
<tr><th>Reference</th><th>Cirtes datums</th><th>Pirmā noteikšana</th><th class="num">Aizkave, d</th><th>Stresa poligons (statuss)</th><th>Visi atbilstošie poligoni</th></tr>
{% for r in val_detail %}<tr><td>{{ r.id }}</td><td>{{ r.date }}</td><td>{{ r.first }}</td><td class="num">{{ r.lead }}</td><td>{{ r.stress }}</td><td>{{ r.ids }}</td></tr>{% endfor %}
</table></div>
{% endif %}
<p class="note">TP ir tikai stresa noteikšana <b>pirms</b> cirtes (atbilstība: pārklāšanās ar 10 m
buferi). Aizkave = cirtes datums − pirmā noteikšana (pozitīvs = agrāk). References dati parasti
nav pilnīgi, tāpēc precision ir pesimistisks novērtējums.</p>
{% if figs.validation %}<figure><img src="{{ figs.validation }}" alt="Validācija">
<figcaption>Validācijas iznākumi, aizkave un references laika rindas, sadalītas pie cirtes datuma.
Fails: figures/report/{{ fig_files.validation }}</figcaption></figure>{% endif %}
{% else %}
<p>References dati nav norādīti, tāpēc validācija nav veikta.</p>
{% endif %}

<h2>Ierobežojumi</h2>
<ul>
<li><b>Izšķirtspēja.</b> 10 m (NDVI) un 20 m (NDRE, NDMI, CRSWIR) — koku grupu / nogabala daļu līmenis.
Mazākā atzīmētā vieta: {{ min_area }} ha. Atsevišķi koki netiek noteikti.</li>
<li><b>Nav "zaļā uzbrukuma" noteikšanas.</b> Rīks reaģē uz vainaga mitruma un krāsas izmaiņām, kas
parasti parādās nedēļas līdz mēnešus pēc uzbrukuma. Rezultāti ir jāpārbauda ar dronu vai uz vietas.</li>
<li><b>Mākoņainība.</b> Derīgu novērojumu ir maz (skat. "Datu pieejamība"); garos mākoņainos periodos
noteikšana aizkavējas. Plānus mākoņus un dūmaku daļēji kompensē laikrindu dūmakas tests.</li>
<li><b>Meža maska.</b> Copernicus HRL Dominant Leaf Type 2018: "skujkoki" ietver arī priedi; egli
no priedes neatšķir. Kopš 2018. gada izcirstās vietas izslēdz ar bāzes perioda vasaras NDVI slieksni.</li>
<li><b>Cirtes vs. stress.</b> Tips "cirte" nozīmē audzi nomainošu izmaiņu (kailcirte, sanitārā cirte vai
pilnībā atmirusi audze); nošķiršana ir heuristiska.</li>
<li><b>Sliekšņi kalibrēti vienā teritorijā.</b> Parametri (dūmaka, MAD grīda, meža maska, cirtes pazīme)
kalibrēti Kalsnavas testa teritorijā; jaunām teritorijām tie jāpārbauda ar kalibrēšanas skriptiem.</li>
<li><b>Ticamības rādītājs</b> ir heuristisks un nav varbūtība.</li>
</ul>

<h2>Metode un parametri</h2>
<p class="note">Ģenerēts no šī skrējiena faktiskās konfigurācijas (pilna konfigurācija:
config.yaml un run_metadata.json). Pilns apraksts: README.</p>
<ul class="note">{% for l in method_lines %}<li>{{ l }}</li>{% endfor %}</ul>

<footer>Sagatavots ar s2forest {{ version }} · LBTU Studentu inovāciju programma, sadarbībā ar LVM.
Sentinel-2 dati: Copernicus (ESA), izplatīti ar Element84 Earth Search un Microsoft Planetary Computer.</footer>
</main></body></html>
"""
