"""Run report (Markdown, Latvian)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def md_table(df: pd.DataFrame, floatfmt: str = "{:.3f}") -> str:
    if df is None or df.empty:
        return "_(nav)_\n"

    def f(v):
        if isinstance(v, float):
            return "" if np.isnan(v) else floatfmt.format(v)
        return str(v)

    head = "| " + " | ".join(map(str, df.columns)) + " |\n|" + "---|" * len(df.columns) + "\n"
    return head + "".join("| " + " | ".join(f(v) for v in row) + " |\n" for row in df.itertuples(index=False))


def write_report(cfg, meta, table, results, s2, proxy, proxy_dropped, path: Path) -> Path:
    ev, w, thr = cfg.event, cfg.weather, cfg.detection.threshold
    pcol = f"precip_{w.wet_hours}h_mm"
    L = [f"# S1 vējgāžu skrīnings — {cfg.run_name}", "",
         f"Notikums: **{ev.name}**; logi: pirms {ev.pre_window[0]} … {ev.pre_window[1]}, "
         f"pēc {ev.post_window[0]} … {ev.post_window[1]}. AOI: `{Path(cfg.aoi).name}`, "
         f"{cfg.grid.crs} {cfg.grid.resolution:g} m. Avots: PC `{cfg.data.collection}` (VV, VH, lineārs γ⁰).", "",
         "## Metode (no šī skrējiena konfigurācijas)", "",
         f"- Metodes versija **{cfg.detection.version}**: normalizācija katram uzņēmumam "
         f"{'jā' if cfg.detection.normalize_per_acquisition else 'nē'}; telpiskā vidējošana "
         f"{cfg.detection.smoothing_window}×{cfg.detection.smoothing_window} (lineāri, tikai analizētajā mežā); "
         f"z statistika {'atsevišķi katrai HRL klasei' if cfg.detection.z_by_class else 'vienota visam mežam'}.",
         f"- Katrai relatīvajai orbītai atsevišķi: pirms un pēc vidējais **lineārajā skalā** → dB; "
         f"ΔVV, ΔVH = pēc − pirms. Nodata {cfg.data.nodata:g} un γ⁰ ≤ 0 → NaN pirms aprēķiniem.",
         "- ΔVV un ΔVH vidējais pāri orbītām, kas pikselim pieejamas (`n_orbits` slānis); "
         "indekss = ΔVH + ΔVV.",
         f"- Meža maska: HRL DLT 2018 klases {cfg.forest_mask.hrl_dlt_classes} mīnus OSM ceļi "
         f"{cfg.forest_mask.road_buffer_m:g} m (bez S2 NDVI precizējuma).",
         f"- Stabilais mežs = analizētais mežs mīnus S2 suspects poligoni ar {thr.exclude_buffer_m:g} m buferi.",
         f"- z = (indekss − mediāna_stabilais) / (1,4826 · MAD_stabilais). **windthrow**: z ≥ {thr.k:g} "
         f"(vienpusējs); **cut_like**: z ≤ −{thr.k:g} (netiek saukts par vējgāzi). MMU "
         f"{cfg.detection.min_area_ha:g} ha (8-kaimiņu).",
         f"- Variants **A**: visi uzņēmumi. Variants **B**: izslēgti uzņēmumi ar > {w.wet_precip_mm:g} mm "
         f"nokrišņu {w.wet_hours} h pirms uzņēmuma, ja orbītā/logā paliek ≥ {w.wet_min_remaining}.",
         f"- Nokrišņi: Open-Meteo vēsturiskais API, punkts {meta['weather'].get('latitude')} N, "
         f"{meta['weather'].get('longitude')} E (modelēts lielums).", ""]
    a = meta["areas_ha"]
    L += ["## Platības", "",
          f"AOI {a['aoi']} ha; HRL mežs (1+2) {a['forest_hrl_1_2']} ha; analizētais (bez ceļiem) "
          f"{a['analysis']} ha; stabilais {a['stable']} ha.", ""] + [f"- {n}" for n in meta["mask_notes"]] + [""]

    L += ["## Uzņēmumi", ""]
    used = table[table.used_A]
    L.append(f"Izmantoti (A): {len(used)}; B: {int(table.used_B.sum())}. Izslēgti B variantā:")
    exB = table[table.used_A & ~table.used_B]
    L.append("")
    L.append(md_table(exB[["rel_orbit", "window", "date", "platform", pcol, "reason_B"]], "{:.1f}"))
    kept_wet = table[table.used_B & table.reason_B.astype(str).str.startswith("slapjš")]
    if len(kept_wet):
        L += ["Slapji, bet paturēti (citādi orbītā/logā paliktu par maz):", "",
              md_table(kept_wet[["rel_orbit", "window", "date", pcol, "reason_B"]], "{:.1f}")]
    rejA = table[~table.used_A]
    if len(rejA):
        L += ["Neizmantoti (abos variantos):", "", md_table(rejA[["rel_orbit", "window", "date", "reason_A"]])]
    L += ["Visi uzņēmumi: `tables/acquisitions.csv`.", ""]

    L += ["## Slieksnis", ""]
    rows = []
    grp_name = {"all": "viss mežs", "1": "HRL 1 lapu koki", "2": "HRL 2 skujkoki"}
    for v, s in meta["stats"].items():
        for g, st in s["groups"].items():
            rows.append({"variants": v, "z grupa": grp_name.get(g, g),
                         "stabilā mediāna, dB": st["stable_median_db"], "MAD, dB": st["stable_mad_db"],
                         "stabilie pikseļi": st["stable_pixels"], "k": st["k"],
                         "slieksnis ↑, dB": st["threshold_db_up"], "slieksnis ↓, dB": st["threshold_db_down"],
                         "orbītas": ",".join(map(str, s["orbits"]))})
    L += [md_table(pd.DataFrame(rows)), ""]

    L += ["## Kandidāti", ""]
    for v, r in results.items():
        p = r.polygons
        if p.empty:
            L += [f"**{v}:** nav kandidātu.", ""]
            continue
        cols = ["id", "class", "area_ha", "mean_dVH", "mean_dVV", "index", "mean_z", "rel_orbit",
                "n_pre", "n_post", "tree_type", "conifer_share"]
        L += [f"**Variants {v}:** windthrow {int((p['class'] == 'windthrow').sum())} "
              f"({p.loc[p['class'] == 'windthrow', 'area_ha'].sum():.2f} ha), cut_like "
              f"{int((p['class'] == 'cut_like').sum())} ({p.loc[p['class'] == 'cut_like', 'area_ha'].sum():.2f} ha)", "",
              md_table(p[cols].sort_values(["class", "mean_z"], ascending=[False, False])), ""]
    L += ["### Jutīgums (pēc MMU)", "", md_table(pd.concat([r.sensitivity for r in results.values()]), "{:.2f}"), ""]
    L += ["### A pret B", ""]
    cmp_rows = [{"klase": k, **v} for k, v in meta["comparison_A_B"].items()]
    L += [md_table(pd.DataFrame(cmp_rows)), ""]

    L += ["## S2 vizuāla/indeksa pārbaude (NAV validācija)", "",
          "S2 indeksu mediāna kandidātā pirms un pēc vētras (no s2forest izvades, tikai lasot), "
          "mīnus tā pati izmaiņa stabilajā mežā (`d_rel`). Datumi ar < 50 % derīgu pikseļu netiek "
          "izmantoti. Stresa / bojājuma virziens: NDVI, NDRE, NDMI ↓, CRSWIR ↑.", ""]
    if not s2.empty:
        piv = s2.pivot_table(index=["id", "class"], columns="index", values="d_rel").reset_index()
        n = s2.groupby("id")[["n_pre", "n_post"]].min().reset_index()
        L += [md_table(piv.merge(n, on="id")), "", "Pa datumiem: `tables/s2_check_by_date.csv`.", ""]
    else:
        L += ["_(nav kandidātu vai S2 izvades)_", ""]

    L += ["## AIZVIETOTĀJS: S2 vasaras cirtes (tikai atpakaļizkliedes zīmei)", "",
          "Kailcirte nav vējgāze; šis salīdzinājums atbild tikai uz jautājumu, vai S1 redz audzi "
          "nomainošu izmaiņu un kādā virzienā mainās atpakaļizkliede. Katrai cirtei savi logi: pirms = "
          f"{cfg.checks.proxy_window_days} dienas līdz iepriekšējam skaidram S2 datumam, pēc = "
          f"{cfg.checks.proxy_window_days} dienas no `first_detected`. `_rel` = cirte − stabilā meža mediāna.", ""]
    if not proxy.empty:
        cols = [c for c in ["layer", "id", "area_ha", "first_detected", "prev_clear_s2", "rel_orbit",
                            "direction", "d_vv_cut", "d_vh_cut", "d_vv_rel", "d_vh_rel", "pre_dates",
                            "post_dates", "note"] if c in proxy.columns]
        L += [md_table(proxy[cols]), ""]
    if not proxy_dropped.empty:
        L += [f"Izslēgtas cirtes: {len(proxy_dropped)} — " +
              ", ".join(f"{k}: {v}" for k, v in proxy_dropped.reason.value_counts().items()), ""]
    L += ["## Izvades", "", "- `vectors/s1_windthrow.gpkg` (slāņi `candidates_A`, `candidates_B`)",
          "- `rasters/`: indekss, ΔVV, ΔVH, z, n_orbits, klases, katras orbītas Δ (A un B), maskas",
          "- `figures/preview_A.png`, `preview_B.png`, `stable_forest_series.png`",
          "- `tables/`: uzņēmumi, jutīgums, stabilā meža laika rinda, S2 pārbaude, aizvietotājs", ""]
    path.write_text("\n".join(L), encoding="utf-8")
    return path


def write_injection_report(cfg, rate, table, fa, sites, rec, path: Path) -> Path:
    inj, det = cfg.injection, cfg.detection
    L = [f"# Injekcijas tests — {cfg.run_name}", "",
         "> **PROVIZORISKS rezultāts** (izstrādes stāvoklis): metode un testa uzbūve vēl tiek pārbaudīta; "
         "skaitļus neizmantot kā galīgu jutības novērtējumu.", "",
         f"Metode: {det.version}; normalizācija katram uzņēmumam "
         f"{'jā' if det.normalize_per_acquisition else 'nē'}; z statistika "
         f"{'pa HRL klasēm' if det.z_by_class else 'vienota'}; MMU {det.min_area_ha:g} ha; uzņēmumi: variants A.",
         "",
         f"- Sintētiskas vējgāzes: kompakti diski {', '.join(f'{s:g}' for s in inj.sizes_ha)} ha; "
         f"stiprums × {', '.join(f'{s:g}' for s in inj.strengths)} no "
         f"+{inj.base_db['vv']:g} dB VV / +{inj.base_db['vh']:g} dB VH (Rüetschi u. c. 2019 vidējais).",
         f"- Ievietotas visos 'pēc' kompozītos (visas orbītas), reizinot lineāro γ⁰. {inj.n_per_combo} vietas "
         f"katrai platībai un HRL klasei (seed {inj.seed}); tās pašas vietas visiem stiprumiem un logiem.",
         f"- Vietas: stabilajā mežā, ≥ {inj.min_dist_suspects_m:g} m no S2 suspects, ≥ {inj.min_gap_m:g} m "
         f"viena no otras, ≥ {inj.class_purity:.0%} pikseļu mērķa klasē.",
         "- z statistika (mediāna, MAD) — no stabilā meža **bez** injicētajiem pikseļiem [pieņēmums: reāla "
         "vējgāze aizņem mazu meža daļu].",
         f"- Atklāta: ≥ {inj.detected_fraction:.0%} vietas platības ir windthrow poligonā ≥ {det.min_area_ha:g} ha.",
         "- Viltus trauksmes: windthrow poligoni bez injekcijas uz 1000 ha analizētā meža — **reālajos datos "
         "bez injekcijām** (ja AOI ir īstas vējgāzes, tās arī tiek skaitītas kā viltus).", "",
         "## Vietu skaits", "", md_table(sites), "",
         f"## Ieteikuma tabula ({inj.recommend_size_ha:g} ha, stiprums {inj.recommend_strength:g}×, abas klases)", "",
         md_table(table[["window", "k", "n", "n_detected", "rate", "n_false", "area_ha", "fa_per_1000ha",
                         "fa_per_1000ha_injection_runs"]], "{:.3f}"), ""]
    if rec:
        L += [f"**Ieteikums** (augstākais atklāšanas īpatsvars pie {inj.recommend_size_ha:g} ha un "
              f"{inj.recommend_strength:g}×, ja viltus trauksmes ≤ {inj.max_false_alarms_per_1000ha:g} / 1000 ha): "
              f"logs **{rec['window']}×{rec['window']}**, k = **{rec['k']:g}** — atklāti "
              f"{rec['rate_1ha_1x']:.0%}, viltus trauksmes {rec['fa_per_1000ha']:.2f} / 1000 ha.", ""]
        if len(rec["ties"]) > 1:
            L += ["Vienāds atklāšanas īpatsvars arī: " + "; ".join(
                f"{t['window']}×{t['window']}, k {t['k']:g} (FA {t['fa_per_1000ha']:.2f})" for t in rec["ties"]), ""]
    else:
        L += [f"**Nevienai kombinācijai** viltus trauksmes nav ≤ {inj.max_false_alarms_per_1000ha:g} / 1000 ha.", ""]
    piv = rate.pivot_table(index=["k", "window"], columns=["strength", "size_ha"], values="rate",
                           aggfunc="mean").round(2)
    piv.columns = [f"{s:g}×, {a:g} ha" for s, a in piv.columns]
    L += ["## Atklāšanas īpatsvars (abu klašu vidējais)", "", md_table(piv.reset_index(), "{:.2f}"), "",
          "Pa klasēm: `injection_rates.csv`; grafiks: `injection_detection_vs_area.png`.", "",
          "## Viltus trauksmes reālajos datos (bez injekcijām)", "",
          md_table(fa[fa.strength == 0.0][["window", "k", "n_false", "area_ha", "fa_per_1000ha"]], "{:.2f}")]
    path.write_text("\n".join(L), encoding="utf-8")
    return path
