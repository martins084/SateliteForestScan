# 5b posms: s2forest aklā validācija uz LVM zemes

Statuss: **pabeigts (a–d).** Lietotājs izvēlējās 1. kandidātu (Vidzeme). Visi skaitļi b)–d) daļā ir no palaišanas. **[P]** = aprēķināts no datiem,
**[N]** = pieņēmums. Avoti kā 5a posmā (`docs/DATU_AVOTI.md`, 5a sadaļa): LVM_BOJAJUMI un LVM_ZEMES_VIENIBAS (Wayback
kopijas), HRL Dominant Leaf Type 2018 (100 m, tas pats kešs kā 5. posmā), GISCO NUTS 2024.

Reproducēšana: `mezasargs-risk lvm-aoi configs/rm_5b_lvm.yaml` → `output/rm5b_lvm/tables/lvm_5b_aoi_candidates.csv`,
AOI faili `output/rm5b_lvm/aoi/aoi_kandidats_<n>.geojson` (CRS84, kā Kalsnavas AOI).

## a) AOI izvēle [P]

Šūnas: 5 × 5 km LKS-92 režģis (kā 5a `target_cells`), 10 šūnas ar visvairāk LVM 620 poligoniem ≥ 0,5 ha, reģistrētiem
2023–2024 (poligons pieder šūnai pēc reprezentatīvā punkta). Kritēriji (lietotājs, 2026-10-23):

- LVM zeme ≥ 80 % šūnas platības (`LVM_ZEMES_VIENIBAS` ∩ šūna);
- HRL skujkoki ≥ 50 % — definēts kā DLT 2018 skujkoku pikseļi / koku segums (1 + 2), tāpat kā `ConiferConfig.min_share`;
- ≥ 30 LVM 620 poligoni ≥ 0,5 ha, reģistrēti 2023–2024;
- kārtojums: visi kritēriji izpildīti → Vidzeme → attālums līdz Kalsnavas AOI centram.

| Rangs | Centrs lon / lat | Reģions | km no Kalsnavas | LVM zeme | Koku segums | Skujkoki | 620 ≥ 0,5 ha (2023 / 2024) | ≥ 1 ha | 620 ha | Vējgāzes 2023–24 | Citi 2023–24 | Visi kritēriji |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **1** | 26,506 / 56,931 | Vidzeme | 48 | 100 % | 80 % | 80 % | 81 (47 / 34) | 59 | 145 | 67 | 66 | jā |
| **2** | 24,367 / 56,641 | Zemgale | 92 | 83 % | 80 % | 66 % | 80 (51 / 29) | 51 | 143 | 10 | 3 | jā |
| **3** | 24,123 / 56,731 | Rīga | 107 | 81 % | 79 % | 64 % | 102 (28 / 74) | 68 | 194 | 72 | 11 | jā |
| 4 | 23,795 / 56,776 | Rīga | 127 | 95 % | 73 % | 73 % | 101 (77 / 24) | 73 | 214 | 240 | 12 | jā |
| 5–7 | Kurzeme | Kurzeme | 252–289 | 86–95 % | 82–91 % | 72–83 % | 75–96 | 57–77 | | | | jā |
| 8 | 26,673 / 56,972 | Vidzeme | 59 | **72 %** | 80 % | 56 % | 72 (34 / 38) | 64 | 220 | 3 | 14 | nē (LVM zeme) |
| 9 | 24,041 / 56,732 | Rīga | 112 | **78 %** | 82 % | 52 % | 117 (63 / 54) | 88 | 309 | 107 | 6 | nē (LVM zeme) |
| 10 | 22,879 / 57,310 | Kurzeme | 195 | **66 %** | 69 % | 75 % | 79 (30 / 49) | 62 | 209 | 5 | 28 | nē (LVM zeme) |

Pilna tabula: `lvm_5b_aoi_candidates.csv`. „Vējgāzes” = `DAMAGESUBT 100`, „citi” = visi pārējie, izņemot 620.

![AOI kandidāti](rm_figures/rm5b_aoi_kandidati.png)

Piezīmes:

- Vidzemē kritērijus izpilda **tikai 1. kandidāts**. Otra Vidzemes šūna (8., 59 km) neiztur LVM zemes kritēriju (72 %).
- Kandidātam 4 ir visvairāk vējgāžu poligonu (240) — der atsevišķai vējgāžu pārbaudei, ja to vajag [N].
- HRL DLT ir 2018. gada; kopš tā skujkoku segums bojājumu dēļ var būt mazāks [N]. s2forest meža maska ir tā pati
  DLT 2018 klase 2, tāpēc 620 poligoni ārpus tās netiks analizēti.

**Lēmums (lietotājs, 2026-10-23):** 1. kandidāts → `data/aoi_lvm5b_vidzeme.geojson`.

## b) s2forest palaišana [P]

Iesaldētā v0.2 konfigurācija (`configs/test_kalsnava_2025.yaml` tagā `v0.2-kalsnava`). Mainīts **tikai** `run_name`, `aoi`,
`time.monitor_year`; noņemts Kalsnavas `reference` bloks (`stands` v0.2 konfigurācijā vēl nebija). Neviens detekcijas,
maskas, bāzes vai noturības parametrs nemainās. Bāze = 3 iepriekšējās sezonas (1. maijs – 30. septembris), kā v0.2.

Diff pret v0.2 (2023. gads; pārējie gadi atšķiras tikai ar gadu un nosaukumu):

```diff
@@ -1,12 +1,14 @@
-# Same AOI as test_kalsnava.yaml, monitoring 2025 with baseline 2022-2024.
-# Exercises the 2022 gap in sentinel-2-c1-l2a (filled from Planetary Computer).
-run_name: test_kalsnava_2025
-aoi: ../data/test_aoi_kalsnava.geojson
+# Stage 5b: s2forest blind validation on LVM land (AOI candidate 1, Vidzeme, 5 x 5 km).
+# Frozen v0.2-kalsnava config (configs/test_kalsnava_2025.yaml at the tag); changed ONLY:
+# run_name, aoi, time.monitor_year (2023, baseline = 3 previous seasons as in v0.2);
+# `reference` (Kalsnava winter cuts) removed.
+run_name: lvm5b_vidzeme_2023
+aoi: ../data/aoi_lvm5b_vidzeme.geojson
 output_dir: ../output
 cache_dir: ../cache
 
 time:
-  monitor_year: 2025
+  monitor_year: 2023
   baseline_years: 3
   season_start: "05-01"
   season_end: "09-30"
@@ -42,12 +44,3 @@
   normalization:
     enabled: true
     buffer_m: 5000
-
-# Winter cuts 2025/26 found by the 2026 run (scripts/make_winter_cut_references.py).
-# Cut reason UNKNOWN (mostly regular fellings); cut date = earliest possible, so
-# lead times are lower bounds. Question: was stress visible in 2025 before the cut?
-reference:
-  path: ../data/local/test_kalsnava_2025_winter_cut_references.gpkg
-  id_field: nr
-  date_field: cirtes_datums
-  description: "2025./2026. gada ziemas cirtes, ko atrada 2026. gada analīze. Cirtes iemesls NAV zināms (visticamāk, galvenokārt kārtējās cirtes, nevis mizgraužu bojājumi). Cirtes datums ir agrākais iespējamais (2025-09-30), tāpēc aizkave ir apakšējā robeža."
```

`stress_only` variants (informatīvi) pievieno tikai `forest_mask.amplitude_scope: stress_only`.
Konfigurācijas: `configs/lvm5b_vidzeme_<gads>[_stress_only].yaml`. Palaišana: `s2forest run <config>`.

| Monitoringa gads | Bāze | Lietojamās ainas (bāze → monitorings) | Analizēts mežs | Cirtes (cut) | Stress |
|---|---|---|---|---|---|
| 2022 | 2019–2021 | 20 / 13 / 12 → 11 | 1 299 ha (54,0 % AOI) | 57 (47,0 ha) | 7 (1,1 ha) |
| 2023 | 2020–2022 | 13 / 12 / 11 → 21 | 1 143 ha (47,1 %) | 38 (21,2 ha) | 20 (10,2 ha) |
| 2024 | 2021–2023 | 12 / 11 / 22 → 15 | 1 340 ha (55,2 %) | 41 (42,4 ha) | 3 (0,7 ha) |
| 2025 | 2022–2024 | 11 / 22 / 15 → 13 | 1 341 ha (55,5 %) | 53 (32,4 ha) | 11 (5,6 ha) |

- AOI daļa, kas nav HRL skujkoku klasē: 36,7 %. 2023. gadā „liela sezonālā amplitūda” izslēdz 14,2 % AOI (citos gados
  4,5–7,0 %).
- `stress_only`: 2023. gadā 59 cirtes (33,5 ha) pret 38; citos gados ±1 poligons.
- **s2forest atskaites kļūda (nav detekcijas kļūda):** 2022. un 2023. gada (abu variantu) palaišanās HTML atskaite
  neizdevās. Cēlonis: `viz.monthly_availability` → `pd.to_datetime` ar jauktiem datuma formātiem 2020. gada ainās
  (`2020-07-13 09:44:34+00:00`). Detekcijas izvade (`suspects.gpkg`, rastri, maska) ir pilnīga. s2forest kods nav
  mainīts (iesaldēts).

## c) Validācija pret LVM bojājumiem [P]

`mezasargs-risk lvm-validate configs/rm_5b_lvm.yaml` → `output/rm5b_lvm/tables/val_*.csv`.

- **AOI LVM bojājumi:** 549 poligoni, kuru reprezentatīvais punkts ir AOI (apgriezti pēc AOI). Reģistrēti 2023–2024:
  - 620: 88 (147,8 ha);
  - vējgāzes (100): 67 (106,6 ha);
  - citi: 66 (89,7 ha) — galvenokārt sausums (900; 23 + 18) un slimības (500; 16 2024. gadā).
- **Saskaņošana:** s2forest poligons ≤ 20 m no LVM poligona (lietotāja definīcija). Papildus informatīvi stingrāka:
  s2forest poligoni pārklāj **≥ 25 %** LVM poligona platības.
- **Placebo:** visi 549 LVM poligoni 100 reizes nejauši pārvietoti (centroids uz nejauša HRL skujkoku pikseļa AOI,
  nejauša rotācija, poligons pilnībā AOI; seed 42). p = (1 + #placebo ≥ novērotais) / 101; mazākā iespējamā p = 0,010.

### c1) Detekcija pēc objekta — LVM 620 ≥ 0,5 ha (n = 81, 145 ha)

| Gads attiecībā pret reģistrāciju | ≤ 20 m | placebo (95 %) | p | pārklāj ≥ 25 % | placebo (95 %) | p |
|---|---|---|---|---|---|---|
| r−1 | 29,6 % | 16,0 % (7,4–24,7) | 0,010 | **2,5 %** | 2,6 % (0–6,2) | 0,61 |
| r | 29,6 % | 14,4 % (8,6–22,2) | 0,010 | 12,3 % | 2,6 % (0–6,2) | 0,010 |
| r+1 | 42,0 % | 16,6 % (9,2–25,3) | 0,010 | 19,8 % | 3,4 % (0–8,6) | 0,010 |
| **jebkurā (r−1..r+1)** | **69,1 %** | 36,2 % (25,9–46,9) | 0,010 | **32,1 %** | 8,2 % (2,5–13,6) | 0,010 |

- **Platība:** atrasti 66,7 % no 620 ha (≤ 20 m).
- **Lielumu klases (jebkurā gadā, ≤ 20 m / ≥ 25 %):**
  - visi 620 (n = 88): 70,5 % / 30,7 %;
  - ≥ 1 ha (n = 59): 69,5 % / 23,7 %;
  - ≥ 0,5 ha un ≥ 50 % platības analizētajā maskā (n = 74): 68,9 % / 31,1 %.
- **Kā atrasti:** 55 no 56 kā **cut**, 8 (arī) kā stress. Atrastie ir gandrīz tikai cirtes, ne stresa signāls.
- **r−1 signāls ir blakus esošas cirtes:** ≤ 20 m rādītājs r−1 ir virs placebo, bet pārklāšanās ≥ 25 % ir tieši
  placebo līmenī. Tātad gadā pirms reģistrācijas s2forest atrod cirtes **blakus** vēlāk reģistrētajiem bojājumiem, nevis
  pašos bojātajos nogabalos [P]. Vai tās ir ciršu malas, kurās uzbrūk mizgrauži, ir pieņēmums [N].

### c2) Precizitāte — s2forest poligoni LVM bojājumos (jebkurš veids)

„Ārpus” = **neapstiprināts** (LVM reģistrs nav pilnīgs; regulārās cirtes tajā nav). 2022–2024 kopā (`all`):

| | n | jebkura gada bojājumos | placebo | p | reģ. y−1..y+1 | placebo | p | 620, reģ. y−1..y+1 | placebo | p |
|---|---|---|---|---|---|---|---|---|---|---|
| cut | 136 | 94,1 % | 76,1 % | 0,010 | 66,9 % | 44,9 % | 0,010 | 48,5 % | 24,3 % | 0,010 |
| stress | 30 | 73,3 % | 70,7 % | 0,52 | 50,0 % | 39,8 % | 0,14 | 23,3 % | 21,0 % | 0,48 |

- **Pa gadiem:**
  - cut jebkura gada bojājumos: 98 % (2022), 97 % (2023), 85 % (2024); neapstiprināti attiecīgi 1, 1, 6;
  - stress: 5/7, 15/20, 2/3 (tabula `val_precision_all.csv`).
- **AOI ir ļoti blīvi bojājumu poligoni:** pat nejauši novietoti poligoni aptver 76 % s2forest ciršu. Tāpēc „jebkura gada
  bojājumos” bez placebo neko neizsaka.
- **Cirtes** ir būtiski biežāk LVM bojājumos nekā nejauši. **Stresa poligoni nav** (p 0,14–0,52; n = 30).
- **2025 atsevišķi — neapstiprinātas (reģistrs beidzas 2025-04):**
  - cut 53, no tām 28 jebkura gada bojājumos, **25 neapstiprinātas**;
  - stress 11, no tiem 3 bojājumos, **8 neapstiprināti**.

  2025. gada reģistrācijas Wayback kopijā ir tikai līdz 2025-04-27, tāpēc šos skaitļus ar 2022–2024 nesalīdzina.

### c3) Laika nobīde — s2forest `first_detected` pret reģistrācijas gadu (620)

| | n | r−1 | r | r+1 | `onset_before_season` | mēnesis |
|---|---|---|---|---|---|---|
| ≤ 20 m | 62 | 28 | 18 | 16 | 40 / 62 | 41 maijā, 21 jūl.–sept. |
| pārklāj ≥ 25 % | 27 | 3 | 10 | 14 | 19 / 27 | 19 maijā, 8 jūn.–sept. |

- **Pēc reģistrācijas gada (≥ 25 %):** 2023. gada poligoni visbiežāk atrasti gadā r+1 (11 no 15), 2024. gada poligoni — gadā
  r (8 no 12).
- Lielākā daļa sakritību ir cirtes, kuru sākums ir **pirms sezonas** (pirmais datums = sezonas sākums maijā). Tātad tā ir
  ziemas cirte pēc reģistrācijas; precīzu cirtes datumu S2 sezona nedod [P].
- Agrīna stresa signāla pirms reģistrācijas šeit nav redzams: stingrajā variantā r−1 = 3 (placebo līmenis).

### c4) Vējgāzes un citi bojājumi — vai s2forest tos atzīmē kā cut vai stress

≥ 0,5 ha, jebkurā gadā r−1..r+1:

| | n | ≤ 20 m | kā cut | kā stress | pārklāj ≥ 25 % |
|---|---|---|---|---|---|
| 620 | 81 | 69,1 % | 55 | 8 | 32,1 % |
| vējgāzes (100) | 59 | 54,2 % | 28 | 5 | 8,5 % |
| citi | 57 | 68,4 % | 38 | 3 | 22,8 % |

- **Atšķiršanas spēja nav [P]:** visas trīs grupas s2forest atzīmē galvenokārt kā **cut**, stress ir 5–10 %.
  s2forest tips norāda uz izmaiņas veidu (audzi nomainoša vai pakāpeniska), nevis uz cēloni.
- **Vējgāzes:** stingrā pārklāšanās ir zema (8,5 %). Tās ir ≤ 20 m no ciršu poligoniem, bet reti pašas atrastas [P].
  Placebo vējgāzēm un citiem nav rēķināts.
- **Citi** (sausums / slimības) atrasti galvenokārt gadā **r−1** (≥ 25 %: visi 13 gadā r−1).
  - Tikai 7 no 57 ir ≥ 50 % analizētajā maskā: 50 % platības ir „liela sezonālā amplitūda”, 12 % „zems bāzes NDVI”.
  - Visticamāk, tās ir jaunaudzes uz iepriekšējām cirtēm [N].

### c5) `stress_only` (informatīvi)

- **620 ≥ 0,5 ha jebkurā gadā:** 70,4 % (≤ 20 m) un 32,1 % (≥ 25 %), praktiski kā `all` (69,1 % / 32,1 %).
- **Vējgāzes:** 57,6 % / 8,5 %. **Citi:** 73,7 % / 29,8 %.
- **Precizitāte:** 2023. gada cirtes 89,8 % jebkura gada bojājumos (pret 97,4 %).
- Placebo `stress_only` variantam nav rēķināts.

![Kartes](rm_figures/rm5b_kartes.png)

![Detekcija](rm_figures/rm5b_detekcija.png)

## Ierobežojumi

- **(a) 2023. gada bojājumi ir 2024. gada bāzē** (v0.2 metodes īpašība, nemainīta). 2024. gada palaišanā ir tikai
  3 stresa poligoni (0,7 ha) pret 20 2023. gadā; tas atbilst šim ierobežojumam, bet cēlonis nav pierādīts [N].
- **(b) 620 poligoni ārpus s2forest analizētās maskas** (reģistrācijas gada palaišanas maska, visi 620 2023–2024,
  148 ha): **26,8 ha = 18,1 %** nav analizēti:

  | Maskas kods | ha | % no 620 |
  |---|---|---|
  | analizēts | 121,2 | 81,9 % |
  | nav HRL DLT 2018 skujkoku klasē | 11,7 | 7,9 % |
  | liela sezonālā amplitūda | 11,5 | 7,8 % |
  | ceļa buferī | 3,4 | 2,3 % |
  | zems bāzes NDVI | 0,2 | 0,1 % |

  Vējgāzēm ārpus maskas 27,7 %, citiem 81,2 % (`val_lvm_mask_cover.csv`).
- LVM poligoniem ir tikai reģistrācijas gads. Ja cirte notikusi ziemā, s2forest sezona cirtes datumu nedod.
- Viens AOI (25 km²), n = 81. Rezultāts nav vispārināms uz visu Latviju bez citiem AOI [N].
- Placebo pārvieto visus bojājumu veidus kopā un tikai HRL skujkoku mežā. Ja LVM bojājumi ir tuvāk cirtēm nekā
  nejauši (ciršu malas), placebo var nenovērtēt fona līmeni; stingrais rādītājs to mazina [N].

## Fakti pret pieņēmumiem

- **[P]:**
  - visi skaitļi tabulās (no palaišanas);
  - konfigurācijas diff;
  - placebo sadalījumi;
  - maskas kodu platības;
  - s2forest atskaites kļūdas cēlonis.
- **[N]:**
  - r−1 sakritības ir ciršu malas, kurās uzbrūk mizgrauži;
  - „citi” bojājumi ir jaunaudzēs;
  - 2024. gada mazais stresa skaits ir no 2023. gada bojājumiem bāzē;
  - vispārināmība ārpus šī AOI.

## Kas NAV izdarīts

- s2forest kods nav mainīts. Atskaites datuma kļūda (`viz.monthly_availability`) nav labota; detekciju tā neietekmē.
- Placebo nav rēķināts vējgāzēm, citiem bojājumiem un `stress_only` variantam (tikai 620 un precizitāte, `all`).
- Nav pārbaudīti citi AOI kandidāti (2, 3).
- Nav salīdzināts ar MVR vai ortofoto (bez attēlu lejupielādes).
- Nav S1 testa ar šiem mērķiem.
