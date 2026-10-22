# 3. posms: S2 plūsmas uzlabojumi (2026-10-22/23)

Zars `feat/risk-model`. s2forest noklusējuma uzvedība nav mainīta: tā ir pārbaudīta ar zelta regresijas testu.
Jaunās iespējas ir tikai opcijas, kas pēc noklusējuma ir izslēgtas. **[P]** = pārbaudīts (palaists), **[N]** = pieņēmums.

## 1. Nestabilie testi (S1_INVENTARIZACIJA 9.)

- **Neizdevās atkārtot.** Pirms labojuma kļūme neparādījās 120 palaišanās [P]:
  - 12 pilnas;
  - 60 tikai abi testi;
  - 48 zem 4× paralēlas slodzes.

  Neparādījās arī 240 zarr rakstu stresa testā [P].
- **Atrasts un labots pierādāms defekts [P].** `fetch.py` izmantoja `with dask.config.set(scheduler="synchronous")`
  `ThreadPoolExecutor` pavedienos. Šis iestatījums ir globāls un nav pavedienu drošs: paralēlā testā 1 reizi no 1200
  plānotājs nebija `synchronous`. Tagad katrs aprēķins norāda plānotāju pats (`.compute(scheduler="synchronous")`).
- **Sākotnējās nestabilitātes cēlonis NAV pierādīts [N].** Labotais defekts ir ticams kandidāts, bet ne pierādīts.
  Abi testi tagad izdrukā katra neizdevušās ielādes kļūdas tekstu, lai nākamreiz cēloni varētu redzēt.
- **Pēc labojuma [P]:** 20 no 20 pilnām `pytest` palaišanām pēc kārtas ir zaļas (107 passed). Tās notika paralēli
  izpētes aprēķiniem, t. i., zem slodzes.

## 2. Zelta regresijas tests

- **Atsauce.** `tests/golden/kalsnava_v02.json` ir 38 objektu sha256: visi `suspects.gpkg` slāņi, 22 rastri un
  6 tabulas. Atsauce iegūta, palaižot taga `v0.2-kalsnava` kodu (atsevišķā git worktree) uz tā paša keša.
- **Tests.** `tests/test_golden_kalsnava.py` (marķieris `golden`, ~6 min) palaiž `indices` un `detect` ar v0.2
  konfigurāciju un salīdzina rezultātu ar atsauci.
- **Rezultāts [P]:** pašreizējais kods dod identisku izvadi visos 38 objektos. Tests palaists divreiz: pēc `fetch`
  un amplitūdas labojumiem, un vēlreiz ar visām 3. posma izmaiņām.

## 3. Amplitūdas maska tikai stresam (`forest_mask.amplitude_scope: stress_only`)

Kods 5 apzīmē lielu NDVI sezonālo amplitūdu. Ar šo opciju šādos pikseļos paliek tikai cirtes
(`flag == 1` un cirtes pazīme), bet stresa signāli tiek atmesti. Noklusējums `all` atbilst v0.2.

Kalsnava, abi varianti, pārējais kā `configs/test_kalsnava*.yaml` [P]:

| Gads | Tips | `all` (n / ha) | `stress_only` (n / ha) |
|---|---|---|---|
| 2025 | cirte | 70 / 77,10 | 70 / 78,34 |
| 2025 | stress | 12 / 2,58 | 12 / 2,58 |
| 2026 | cirte | 28 / 29,10 | 32 / 30,96 |
| 2026 | stress | 3 / 0,33 | 3 / 0,33 |

- **Jaunas cirtes.** Ar `stress_only` parādās jauni cirtes poligoni, kas nepārklājas ar `all` poligoniem:
  - 2026. gadā 4 poligoni (0,11–1,25 ha);
  - 2025. gadā 3 poligoni (0,11–0,73 ha). Kopskaits 2025. gadā paliek 70, tātad daļa poligonu, visticamāk,
    saplūst [N].
- **Pārbaudes gadījums: S1 cut_like #1** (56,6913 N, 25,8507 E):
  - `all`: 30 m attālumā nav neviena poligona;
  - `stress_only`: poligons **#24, cirte/persistent, 1,25 ha, pirmoreiz 2026-08-11**. Tas sakrīt ar S1 3b posmā
    redzēto S2 izmaiņu starp 07-29 un 08-11.
- **Stresa poligoni nemainās**, kā paredzēts.
- **Ierobežojums.** Jaunās cirtes nav pārbaudītas uz ortofoto vai lauka datiem. Nav zināms, vai tās visas ir īstas
  [N].

## 4. Meža malas atribūti (`diagnostics.forest_edge: true`)

- **Atklāta vieta** ir jebkas no šī: HRL DLT nav klase 1/2; OSM ceļa buferis; bāzes gadu cirte; monitoringa gada
  cirte.
- **Atribūti.** Katram poligonam un drona mērķim tiek aprēķināti `edge_dist_m` (attālums līdz atklātai vietai
  ārpus paša poligona, logā ±1 km) un `edge_share_20m`. Papildus tiek izveidota tabula
  `tables/edge_diagnostics_<gads>.csv`.
- **Labota kļūda [P].** Pirmajā versijā cirtes pikseļi paši skaitījās par atklātu vietu, tāpēc visiem poligoniem
  attālums bija 0. Tagad poligona paša pikseļi netiek skaitīti.

Kalsnava, `all` [P]:

| | Analizētā meža pikseļi | Stresa poligoni | Cirtes poligoni |
|---|---|---|---|
| 2025: mediāna, m / daļa ≤ 20 m | 40 / 32 % | 17 / 58 % (n = 12) | 10 / 81 % (n = 70) |
| 2026: mediāna, m / daļa ≤ 20 m | 50 / 24 % | 10 / 67 % (n = 3) | 10 / 89 % (n = 28) |

**Svarīgi [N]: rādītāji nav tieši salīdzināmi.**
- Poligonam izmanto minimālo attālumu pār visiem tā pikseļiem, bet pikselim — tā paša attālumu. Lielākiem
  poligoniem minimums ir mazāks.
- Stresa poligonu ir maz (3 un 12).

Tāpēc tabula tikai norāda, ka aizdomas ir pie meža malām. Godīgai salīdzināšanai vajadzīgi vienāda izmēra
nejauši kontroles poligoni. Tas nav izdarīts.

## 5. Ortofoto galda pārbaude (QGIS)

- **Komandas:** `s2forest desk-prepare` un `s2forest desk-import`; modulis `deskcheck.py`.
- **`desk-prepare` izveido** `desk_check/` mapi ar trim failiem:
  - GPKG ar poligoniem (`P<id>`) un drona mērķiem (`D<target_id>`), kuros ir tukši marķējuma lauki;
  - CSV veidlapu;
  - `.qgs` projektu.
- **WMS slānis.** Projektā tas ir tikai tad, ja konfigurācijā ir `desk_check.wms_url` un `wms_layers`. Projektā nav
  ne lietotājvārda, ne paroles. Bez URL projektā ir tukša grupa kā vietturis. Rīks WMS neizsauc un attēlus
  nesaglabā.
- **Vērtējumi:** `koki_stav`, `koki_gulus`, `izcirsts`, `nav_skaidrs`. QGIS formā tie ir izkrītošā sarakstā.
- **`desk-import`** pieņem gan aizpildītu CSV, gan QGIS rediģētu GPKG. Rezultāts ir tabula, kas krustojumā rāda
  detektora klasi pret galda vērtējumu.
- **Pārbaudīts QGIS 3.44 bez GUI [P]:**
  - projekts atveras;
  - vektoru slāņi ir derīgi, projekta un slāņu CRS ir EPSG:3059;
  - `vertejums` laukam ir ValueMap;
  - labojums QGIS → `read_form` → krustojuma tabula strādā.
- **Nav pārbaudīts:**
  - interaktīvs darbs QGIS;
  - īsts LĢIA WMS: vajag licenci un URL. Pārbaudē WMS slānis ar `example.invalid` bija nederīgs, kā gaidīts.

## 6. HRL Water & Wetness (TWI aizstājējs, 7. lēmums)

Detaļas ir `DATU_AVOTI.md`. Kalsnavā [P]: 97,3 % sauss, 1,8 % īslaicīgi mitrs, 0,9 % pastāvīgs ūdens. Slānis ir
kategorisks un vājš kā TWI aizstājējs. **Ieteikums:**
- slīpums + TPI no LĢIA DTM;
- WAW mitro klašu īpatsvars — tikai kā papildu pazīme.

Licences teksts nav izlasīts [N].

## Kas NAV izdarīts

- Nestabilitātes sākotnējais cēlonis nav pierādīts (sk. 1.).
- `stress_only` jaunās cirtes nav pārbaudītas ar neatkarīgiem datiem.
- `stress_only` nav padarīts par noklusējumu: tas būtu jauna versija ar jaunu validāciju.
- Malas diagnostikai nav vienāda izmēra kontroles poligonu.
- QGIS projekts nav lietots interaktīvi; nav pārbaudīts ar īstu LĢIA WMS.
- HRL WAW licences teksts nav izlasīts.
