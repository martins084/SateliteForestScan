# MežaSargs riska modelis — 0. posms: stāvokļa pārbaude

Datums: 2026-10-22. Tikai lasīšana; vienīgā izmaiņa — šis fails (nav commitots; zara lēmums — 2. posmā).
**[P]** = PĀRBAUDĪTS (komanda / fails), **[N]** = PIEŅĒMUMS.

## 1. Git [P]

| | Stāvoklis | Avots |
|---|---|---|
| Aktīvais zars | `feat/s1-earlysignal` @ `47fb869`; darba koks tīrs (izņemot šo failu) | `git branch --show-current`, `git status --short` |
| `master` | `76aea2f` = `origin/master` (GitHub `martins084/SateliteForestScan`) | `git branch -a -vv` |
| `feat/s1-windthrow` | `0caeb79`, 7 commiti priekšā `master`, **nav apvienots** ar `master`, tikai lokāli | `git rev-list --count master..feat/s1-windthrow`, `git branch --merged master` |
| `feat/s1-earlysignal` | `47fb869`, 9 commiti priekšā `master` (ietver visus `feat/s1-windthrow`), **nav apvienots**, tikai lokāli | tas pats |
| Tagi | `v0.2-kalsnava` (iesaldētā S2 plūsma), `s1-windthrow-v3-k5.5` (`0caeb79`), `s1-earlysignal-kalsnava-v1` (`64fa9b4`), `backup-v0.2` | `git tag -n1` |
| Citi | lokāls zars `backup-before-rewrite` (`88dfa38`) un tags `backup-v0.2` — vēstures pārrakstīšanas rezerves kopijas (6.10.), nav GitHub | `git branch -a`, `git tag` |

Secība: `master` → `feat/s1-windthrow` → `feat/s1-earlysignal` (lineāra; `feat/s1-earlysignal` satur abus S1 darbus).

## 2. Izlasītā dokumentācija [P]

- `README.md`, `docs/PROJEKTA_APRAKSTS.md`, `docs/LAUKA_PARBAUDE.md` — kopš `master` nav mainīti
  (`git diff --stat master -- …` tukšs). S2 plūsma: STAC (Earth Search c1 + Planetary Computer), EPSG:3059 10 m,
  HRL DLT 2018 skujkoki + vasaras NDVI + NDVI amplitūda + OSM ceļi, harmoniska bāze, CRSWIR z ≥ 2,5 + 1 indekss,
  noturība ≥ 2 novērojumi / ≥ 7 dienas, poligoni ≥ 0,1 ha, drona mērķi un misijas, validācija (TP tikai stress
  pirms cirtes). Parametri iesaldēti `v0.2-kalsnava`.
- `docs/S1_KOPSAVILKUMS.md` (1.–8. sadaļa): S1 vējgāžu modulis (operatīvi v3 k 5,5), Kalsnavā vētras signāla nav;
  agrīnā signāla tests — neapstiprina, bet neatspēko; mērķi ~2× tuvāk meža malai nekā kontroles.
- `docs/S1_INVENTARIZACIJA.md` atvērtie uzdevumi:
  - **9. sadaļa:** nestabilie testi `test_haze.py::test_widespread_haze_on_last_date_is_masked_in_open_cube` un
    `test_fetch.py::test_fetch_caches_filters_and_harmonizes` (~2 no 5 pilnajām palaišanām; cēlonis [N] —
    `ThreadPoolExecutor`, `fetch.py:287`).
  - **10. sadaļa:** s2forest amplitūdas maska (NDVI p90−p10 > 0,22) izslēdza 62 no 66 pikseļiem audzi nomainošai
    izmaiņai jauktā audzē (S1 cut_like #1, 56,6913 N, 25,8507 E).

## 3. Izvades, ko riska modelis varētu izmantot [P]

Visas tikai Kalsnavas 5 × 5 km AOI (`data/test_aoi_kalsnava.geojson`, EPSG:3059 režģis 500 × 500, 10 m).

| Izvade | Saturs | Ceļš |
|---|---|---|
| S2 suspects 2026 | 31 poligons (28 cut, 3 stress), atribūti `first_detected`, `type`, `status`, z, delta, `dist_to_road_m`, … | `output/test_kalsnava/vectors/suspects.gpkg` (`suspects_2026`) |
| S2 suspects 2025 | 82 poligoni (70 cut, 12 stress) | `output/test_kalsnava_2025/vectors/suspects.gpkg` (`suspects_2025`) |
| S2 meža maska | kodi 0–5 (1 = analizēts) | `output/test_kalsnava/rasters/forest_mask.tif` |
| S2 indeksu laika rindas | NDVI, NDRE, NDMI, CRSWIR, 2023–2026 (64 joslas) un 2022–2025 (58 joslas); vasaras mediānas pa gadiem | `output/test_kalsnava*/rasters/indices/` |
| S2 anomāliju rastri | z, statuss, pirmā noteikšana — tikai monitoringa gadam (2025, 2026) | `output/test_kalsnava*/rasters/anomaly/` |
| HRL DLT 2018 | klases uz AOI režģa (kešs) | `cache/0cb4ee74d8b3_891ae0/forest_hrl_dlt_2018.tif`, `cache/s1/0cb4ee74d8b3/hrl_dlt_2018.tif` |
| OSM ceļi | kešs (Overpass) | `cache/*/osm_lines_53071ed950.gpkg` |
| S1 uzņēmumi | 530 AOI izgriezumi (VV, VH, lineārs γ⁰, EPSG:3059 10 m), 2023-01 … 2026-10 | `cache/s1/0cb4ee74d8b3/acq/*.npz` |
| S1 vējgāžu rezultāti | kandidāti, rastri, injekcijas un null kalibrācija | `output/s1_kalsnava_2026-08_*`, `output/s1_null_calibration/` |
| S1 agrīnais signāls | laika rindas mērķiem / kontrolēm / placebo, signāli, malu diagnostika | `output/s1_earlysignal_kalsnava/` |
| Laikapstākļi | Open-Meteo stundu dati (temperatūra, nokrišņi, sniegs) 2023-01-01 … 2026-10-11 vienā punktā | `cache/s1/0cb4ee74d8b3/openmeteo_*.json` |
| Nogabali | MVR atvērtie dati, 73 privāto mežu nogabali (1,2 % analizētā meža) | `data/local/mvr_kalsnava.gpkg` |

**Nav pieejams lokāli:** jebkuri dati ārpus Kalsnavas AOI; EFDA; koku augstums; DEM/TWI; ortofoto; fenoloģija;
Latvijas mēroga laikapstākļi; LVM dati.

## 4. Vide [P]

| | Vērtība |
|---|---|
| Python | 3.12.14 (`.venv`, pārvaldība `uv`; `python -m uv`, uv 0.12.21) |
| Dators | Intel i5-13450HX, 10 kodoli / 16 pavedieni; RAM 15,7 GB (brīvi pārbaudes brīdī 1,4 GB) |
| Disks C: | 952 GB, brīvi 573 GB; projekts: `cache/` 1,2 GB, `output/` 1,1 GB, `data/` 230 MB |

Instalēts: numpy 2.5.3, scipy 1.18.1, pandas 3.0.6, xarray 2026.9.0, rioxarray 0.23.0, rasterio 1.5.2,
geopandas 1.2.0, shapely 2.1.2, pyproj 3.8.0, dask 2026.8.0, odc-stac 0.5.3, pystac-client 0.9.0,
planetary-computer 1.0.0, zarr 3.4.0, matplotlib 3.11.2, requests 2.34.2.

**Nav instalēts:** scikit-learn, lightgbm, xgboost, shap, statsmodels, spei, climate-indices, xclim, pyet,
richdem, whitebox, pdal, laspy, owslib, netCDF4, h5netcdf, cdsapi. Modelēšanai (loģistiskā regresija,
krosvalidācija, permutation importance) būs vajadzīga vismaz scikit-learn — tikai pēc jūsu apstiprinājuma.

## 5. Novērojumi un riski [N, ja nav norādīts citādi]

1. Visas esošās S2/S1 izvades aptver tikai 25 km² — riska modeļa apmācībai reģionālā mērogā tās nav etiķešu avots;
   Kalsnavā tās der demonstrācijai un detalizācijai.
2. S1 darbs ir divos neapvienotos lokālos zaros; riska modeļa zara izvēle (no `master` vai no `feat/s1-earlysignal`)
   ir 2. posma lēmums.
3. [P] Brīvā RAM pārbaudes brīdī bija tikai 1,4 GB no 15,7 GB (citi procesi); lielu rastru apstrāde jāplāno pa blokiem.
4. [P] Nestabilie s2forest testi joprojām ir atvērti (S1_INVENTARIZACIJA.md 9. sadaļa); jebkurš regresijas tests pret
   `v0.2-kalsnava` vispirms jāpadara stabils.
5. [P] Lokāli ir pirms-pārrakstīšanas vēstures rezerves (`backup-before-rewrite`, `backup-v0.2`); tās nav GitHub. Vai
   tās paturēt — jūsu lēmums (nav steidzami).

## 6. Kas NAV izdarīts

- Nav lejupielādēti nekādi jauni dati, nav instalētas bibliotēkas, nav mainīts kods.
- Nav pārbaudīti ārējie datu avoti (tas ir 1. posms).
- Šis fails nav commitots.
