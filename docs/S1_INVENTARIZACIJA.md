# Sentinel-1 vējgāžu modulis — 0. posms: inventarizācija

Datums: 2026-10-11. Zars `feat/s1-windthrow` (izveidots no `master` @ `76aea2f`).
Šajā posmā kods netika mainīts; vienīgā izmaiņa ir šis fails (bez commit).

Apzīmējumi: **[P]** = PĀRBAUDĪTS (norādīts fails vai komanda), **[N]** = PIEŅĒMUMS
(jāpārbauda nākamajos posmos).

---

## 1. Git stāvoklis

| Kas | Rezultāts | Avots |
|---|---|---|
| Aktīvais zars pirms darba | `master`, sinhronizēts ar `origin/master`, darba koks tīrs | [P] `git status --short --branch` |
| Pēdējais commit | `76aea2f docs: update commit hashes after history rewrite`; kopā 21 commit (30.09.–06.10.2026) | [P] `git log --oneline -30` |
| Tagi | `v0.2-kalsnava` (iesaldētā versija), `backup-v0.2` (lokāla rezerves kopija) | [P] `git tag` |
| Zari | `master`, `backup-before-rewrite` (lokāls), `feat/s1-windthrow` (jauns) | [P] `git branch -a` |
| Remote | `origin` = github.com/martins084/SateliteForestScan | [P] `git branch -a` |

Projekta nosaukums „MežaSargs“ repozitorijā nav atrodams; repozitorijs un pakotne
saucas `s2-forest-screening` / `s2forest`. **[P]** `git grep` (nav atrasts).

## 2. Repozitorija struktūra (līdz 3 līmeņiem, bez `.venv`, `cache`, `output`, `data/local`)

```
README.md  pyproject.toml  uv.lock  .python-version  .gitignore  .gitattributes
configs/   template_aoi.yaml  test_kalsnava.yaml  test_kalsnava_2025.yaml
data/      test_aoi_kalsnava.geojson
docs/      PROJEKTA_APRAKSTS.md  LAUKA_PARBAUDE.md  S1_INVENTARIZACIJA.md (jauns)
notebooks/ (tukša, nav git)
scripts/   14 kalibrēšanas / diagnostikas / attēlu skripti
src/s2forest/  aoi, anomaly, cli, config, diagnostics, fetch, fieldcheck, forestmask,
               haze, indices, io, linear, masking, pipeline, report, ringcontrol, stands,
               targets, temporal, validation, vectorize, viz
src/s2forest/sources/  base, earthsearch, planetary, stac_common
tests/     16 testu faili + conftest.py
```
[P] `find . -maxdepth 3 ...`. Izlasīti: `README.md`, `docs/PROJEKTA_APRAKSTS.md`,
`docs/LAUKA_PARBAUDE.md`, visi trīs `configs/*.yaml`, `pyproject.toml`.

## 3. Kā uzbūvēts s2forest

### 3.1 CLI un ieejas punkti [P]
- `pyproject.toml`: `[project.scripts] s2forest = "s2forest.cli:app"` (typer).
- Komandas (`src/s2forest/cli.py`): `fetch`, `indices`, `detect`, `validate`,
  `missions`, `stands`, `field-prepare`, `field-import`, `report`, `run`.
- Visu vada viens YAML fails; `config.load_config()` (`config.py:301`) ielādē to
  pydantic modeļos (`Config`, `TimeConfig`, `DataConfig`, `AnomalyConfig`, …),
  relatīvos ceļus izšķir pret konfigurācijas faila mapi.
- Soļu loģika `pipeline.py` (`index_stage`, `detect_stage`, `write_*_outputs`).

### 3.2 AOI un koordinātu sistēma [P]
- `data/test_aoi_kalsnava.geojson`: viens poligons CRS84, ~25,827–25,911 E,
  56,654–56,700 N (5 × 5 km; README: LKS-92 612000–617000, 280500–285500).
- `aoi.read_vector(path, crs)` → pārprojicē uz `data.crs`; `make_geobox()` veido
  režģi, kas piesaistīts izšķirtspējas daudzkārtņiem; `geobox_key()` — keša atslēga;
  `geometry_mask()` — rastrizācija.
- CRS: `EPSG:3059` (LKS-92 / Latvia TM), 10 m (`configs/test_kalsnava.yaml`).

### 3.3 STAC piekļuve [P]
- `sources/base.py`: abstrakcija `DataSource` + `SceneItem`; harmonizācija
  `reflectance_offset()` / `harmonize()` — **specifiska Sentinel-2** (BOA nobīde, DN).
- `sources/stac_common.py`: `stac_search()` vienmēr pievieno
  `query={"eo:cloud_cover": {"lte": ...}}` → **S1 vienumiem šīs īpašības nav**, tāpēc
  S1 meklēšanai šo funkciju nevar izmantot bez izmaiņām [N: jāpārbauda 1. posmā,
  vai PC filtrs vienumus bez `eo:cloud_cover` izmet].
- `sources/planetary.py`: `pystac_client.Client.open(PC_URL)`, URL parakstīšana
  `planetary_computer.sign` ielādes brīdī (anonīmi, bez atslēgas).
- `stac_common.odc_load()` balstās uz `odc.stac.load` ar S2 joslu karti un SCL
  apstrādi → S1 vajadzēs savu, vienkāršāku ielādi.

### 3.4 Meža maska [P]
- `forestmask.py`: HRL Dominant Leaf Type 2018 no EEA ImageServer
  (`DLT_URL`, kešots), klase 2 = skujkoki; precizēšana ar bāzes vasaras NDVI ≥ 0,65
  un NDVI sezonālo amplitūdu ≤ 0,22; `linear.linear_mask()` — OSM ceļi 20 m.
- Gatavs rastrs: `output/test_kalsnava/rasters/forest_mask.tif` (kodi 0–5, 1 =
  analizēts; nozīme `PROJEKTA_APRAKSTS.md` 6. sadaļā). [P] `ls output/test_kalsnava/rasters`.
- Ierobežojums: tikai **skujkoki**; vējgāzes skar arī lapu kokus. HRL ir 2018. gada
  stāvoklis, NDVI precizējums atkarīgs no S2 skrējiena.

### 3.5 Kontroles gredzens un bāzes līnija [P]
- `ringcontrol.ring_series()`: **katram poligonam** salīdzina indeksa mediānu
  poligonā ar 100 m gredzenu analizētā mežā. Tā ir diagnostika pēc detekcijas,
  **nevis** stabila meža sadalījums sliekšņa noteikšanai.
- `fieldcheck.control_site()`: izvēlas vienu 0,16 ha vesela meža kontroles vietu
  (z ≈ 0, ≥ 100 m no poligoniem, ≥ 50 m no ceļa) — arī nav sadalījums.
- S2 bāze: harmonisks modelis no 3 iepriekšējiem gadiem (`temporal.harmonic_fit`),
  z ar `mad_floor` (`anomaly.zscores`). S1 metodei (pirms/pēc vidējie) tieši nav
  piemērojams.
- **Secinājums:** prasība „slieksnis no stabila meža kontroles zonas sadalījuma“
  prasīs jaunu funkciju (piem., meža pikseļi bez S2 izmaiņām, ārpus poligoniem un
  ceļu buferiem → ΔVH+ΔVV procentile / robustais z). Esošās daļas (meža maska,
  ceļu maska, S2 poligoni izslēgšanai) var izmantot kā ievadi.

### 3.6 Izvades formāti un mapes [P]
- `output/<run_name>/`: `rasters/` (GeoTIFF, `io.write_geotiff`, deflate, 256 bloki),
  `vectors/suspects.gpkg` (slāņi pa gadiem), `tables/*.csv`, `figures/*.png`,
  `diagnostics/`, `config.yaml`, `run_metadata.json`, HTML atskaite.
- KML/GeoJSON WGS84 drona mērķiem (`targets.write_targets`).

### 3.7 Testi [P]
- `python -m uv run pytest` → 69 bezsaistes testi; `-m network` → 5 tīkla testi
  (`pyproject.toml`: `addopts = "-m 'not network'"`).
- **Konstatēts:** palaižot `.venv/Scripts/python.exe -m pytest -q` 5 reizes, 2 reizes
  pa vienam testam neizdevās, un katru reizi citam:
  `tests/test_haze.py::test_widespread_haze_on_last_date_is_masked_in_open_cube` un
  `tests/test_fetch.py::test_fetch_caches_filters_and_harmonizes`
  (`{'20240701_S2a': 'failed'} != {'20240701_S2a': 'accepted'}`, `test_fetch.py:45`).
  Atsevišķi palaists `tests/test_haze.py` → 6 passed. Tātad testi ir **nestabili**
  (iespējams, paralēlā ielāde ar `ThreadPoolExecutor`, `fetch.py:287`) [N: cēlonis nav
  pārbaudīts]. Kodu nelaboju (iesaldētā plūsma).

## 4. Esošs Sentinel-1 kods [P]

`git grep -niE "sentinel-1|sentinel1|sentinel_1|\brtc\b|\bgrd\b|backscatter|\bVV\b|\bVH\b|\bsar\b|\bs1\b"`
(bez `uv.lock`): **nav S1 koda.** Vienīgās sakritības ir viltus:
`config.py:35` (`s1{i}` = nogabalu sugu lauki s10…s14) un `tests/test_targets.py:140`
(mērķa ID „S1“).

## 5. Vide [P]

- Pārvaldība: **uv** (`pyproject.toml` + `uv.lock`, `.venv`); `.python-version` = 3.12.
  `uv` nav PATH bash vidē, darbojas kā `python -m uv` (uv 0.12.21).
- Python 3.12.14 (`.venv/Scripts/python.exe --version`).

| Bibliotēka | Versija |
|---|---|
| pystac-client | 0.9.0 |
| planetary-computer | 1.0.0 |
| odc-stac | 0.5.3 |
| stackstac | **nav** |
| rioxarray | 0.23.0 |
| xarray | 2026.9.0 |
| geopandas | 1.2.0 |
| rasterio | 1.5.2 |
| scipy | 1.18.1 |
| numpy | 2.5.3 |
| dask | 2026.8.0 |
| zarr | 3.4.0 |
| requests | 2.34.2 |
| openeo, sarsen, scikit-image | **nav** |

`stackstac` nav vajadzīgs — `odc-stac` jau ir. Laikapstākļu datu klienta nav;
`requests` pietiek Open-Meteo vēsturiskajam API [N: Open-Meteo archive darbojas bez
atslēgas — jāpārbauda 3. posmā].

## 6. Lokāli pieejamie validācijas dati [P]

| Fails | Objekti | Kolonnas | Datumi | Piezīme |
|---|---|---|---|---|
| `data/local/test_kalsnava_demo_references.gpkg` | 28 poligoni, EPSG:3059 | nr, cirtes_datums, iemesls, piezime | 04.06.–28.08.2026 | **sintētiskas** (no S2 paša cirtēm) |
| `data/local/test_kalsnava_2025_winter_cut_references.gpkg` | 24 poligoni | nr, cirtes_datums, datums_no, datums_lidz, iemesls, piezime, platiba_ha | cirtes_datums 30.09.2025; intervāls 2025-09-29…2026-05-05 | iemesls „nezināms“; 0,12–4,2 ha (mediāna 0,62) |
| `output/test_kalsnava/vectors/suspects.gpkg`, slānis `suspects_2026` | 31 (28 cut, 3 stress) | id, first_detected, area_ha, type, delta_*, z_*, … | first_detected 05.05.–28.08.2026 | cirtes 0,12–4,2 ha; **14 ≥ 0,5 ha** |
| `output/test_kalsnava_2025/vectors/suspects.gpkg`, `suspects_2025` | 82 (70 cut, 12 stress) | tāpat | 02.05.–25.09.2025 | cirtes 0,1–6,2 ha; **35 ≥ 0,5 ha** |
| `data/local/mvr_kalsnava.gpkg` | 73 nogabali | objectid, kadastrs, kvart, nog, mt, s10…, a10… | — | tikai privātie meži, 1,2 % analizētā meža |
| `output/test_kalsnava/field_check/field_check_2026.gpkg` | 5 mērķi (F01–F05) | merka_id, kind, … | — | lauka pārbaude vēl nav veikta |

**LVM vējgāžu poligonu nav. Sanitāro ciršu ar zināmu iemeslu nav. Neviena datu kopa
nesatur vējgāzes kā iemeslu.** S2 „cut“ poligoni ir audzi nomainošas izmaiņas
(kailcirtes / cirtes) ar neprecīzu datumu (pirmā skaidrā S2 aina pēc notikuma).

## 7. Kopsavilkums

### Ko var izmantot atkārtoti (importējot, nemainot s2forest)
- `aoi.read_vector`, `make_geobox`, `geobox_key`, `geometry_mask` — AOI un režģis EPSG:3059.
- `config.py` pydantic + YAML modelis (S1 modulim — sava līdzīga konfigurācija).
- `planetary_computer.sign` + `pystac_client` + `odc.stac.load` (bez S2 specifiskās `odc_load`).
- Meža maska: `forestmask.forest_mask` (HRL) un `linear.linear_mask` (ceļi) vai gatavais
  `rasters/forest_mask.tif`.
- `io.write_geotiff`; `ringcontrol.ring_series` kā pēcdetekcijas diagnostika;
  S2 `suspects_<gads>` izslēgšanai no stabilā meža un kā aizvietotājs validācijai;
  `validation.match_references` loģika (pārklāšanās + buferis) kā paraugs.

### Kas trūkst
- S1 kods (meklēšana bez `eo:cloud_cover`, ielāde, lineāra ↔ dB, orbītu grupēšana).
- Laikapstākļu (temperatūra / sniegs) avots sasaluma un slapja sniega izslēgšanai.
- Stabila meža kontroles zonas sadalījuma funkcija sliekšņa noteikšanai.
- Vienkārša poligonizācija ar 0,5 ha MMU (esošā `vectorize.polygonize` ir saistīta ar S2 pazīmēm).
- Vētras datums, skartā teritorija un LVM vējgāžu poligoni (2. posms — jautājums jums).

### Riski
1. **Notikuma nav Kalsnavas AOI** [N]: nav zināms, vai 5 × 5 km testa teritorijā 2023–2026
   bija vējgāzes; bez notikuma modulis atradīs tikai cirtes un troksni.
2. **Aizvietotājs (S2 cut) nav vējgāze:** kailcirte noņem stumbrus, vējgāzē tie paliek uz
   zemes — atpakaļizkliedes izmaiņa var būt citāda. **[P — avots: lietotājs, 2026-10-11]**
   Rüetschi u. c. 2019 vējgāzēm konstatēja atpakaļizkliedes pieaugumu ~0,5 dB
   (VV 0,45 dB, VH 0,68 dB). Turklāt S2 cirtes datums ir neprecīzs, un tikai 14 (2026) /
   35 (2025) cirtes ir ≥ 0,5 ha.
3. **Sezonalitāte:** vētras Latvijā bieži ir rudenī–ziemā; sasalums un slapjš sniegs maina
   atpakaļizkliedi → maz derīgu „pēc“ uzņēmumu.
4. **Orbītas:** Sentinel-1B nedarbojas kopš 2021. gada beigām; 1C un 1D pievienojās vēlāk
   [N: precīzi datumi un pārklājums jāpārbauda 1. posmā katalogā] → 2023–2024 retāki uzņēmumi.
5. **Meža maska tikai skujkokiem** (HRL klase 2) — lapu koku vējgāzes netiks analizētas,
   ja neizmanto plašāku masku (lēmums jums 3. posmā).
6. **Nestabili esošie testi** (2/5 palaišanās) — jāņem vērā, vērtējot jaunos testus; labot
   s2forest nedrīkst bez jūsu atļaujas.
7. **Jaunas atkarības** (ja vajadzēs) mainīs `pyproject.toml` / `uv.lock` — tas skar kopīgo
   vidi, tāpēc katru pievienošu tikai pēc saskaņošanas.
8. **Kur ievietot moduli** (lēmums 3. posmā): (a) atsevišķa pakotne `src/s1windthrow/` ar
   savu CLI ierakstu `pyproject.toml`, (b) apakšpakotne `s2forest/s1/` ar jaunu komandu
   `s2forest windthrow` (prasa izmainīt `cli.py`). (a) neskar s2forest kodu.

## 8. Lēmumi pēc 0. posma (lietotājs, 2026-10-11)

- **Modulis:** atsevišķa pakotne `src/s1windthrow/` ar savu CLI ierakstu `pyproject.toml`;
  s2forest kods netiek mainīts.
- **Meža maska S1 modulim:** HRL DLT klases 1 un 2 (lapu koki un skujkoki) + ceļu maska,
  **bez** S2 NDVI precizējuma. Katram poligonam atribūts ar dominējošo koku tipu.
- **Nestabilie testi** netiek laboti šajā darbā — atsevišķs uzdevums (9. sadaļa).
- **Risks 2** atzīmēts kā pārbaudīts (lietotāja sniegtās Rüetschi u. c. 2019 vērtības).
- **Jaunas atkarības** — tikai pēc saskaņošanas.

## 9. Atsevišķs uzdevums: nestabilie s2forest testi

Ārpus S1 darba (s2forest ir iesaldēts; labot tikai ar atsevišķu atļauju).
`tests/test_haze.py::test_widespread_haze_on_last_date_is_masked_in_open_cube` un
`tests/test_fetch.py::test_fetch_caches_filters_and_harmonizes` (`test_fetch.py:45`,
pārlidojuma statuss `failed` nevis `accepted`) pilnajā palaišanā neizdodas aptuveni
2 reizes no 5, atsevišķi iziet. Iespējamais cēlonis — paralēlā ielāde
(`ThreadPoolExecutor`, `fetch.py:287`) [N]. Uzdevums: atkārtot pilno `pytest` palaišanu cilpā,
noteikt cēloni, labot tā, lai detekcijas rezultāti nemainās.
