# MežaSargs riska modelis — 1. posms: datu avotu pārbaude

Datums: 2026-10-22. Tikai mazas testa lejupielādes mapē `cache/rm_test/` (nav git), nekādas analīzes,
nekādas jaunas bibliotēkas. **[P]** = PĀRBAUDĪTS (atvērts URL / lejupielāde / komanda), **[N]** = PIEŅĒMUMS.
Licences un atsauces — [DATU_AVOTI.md](DATU_AVOTI.md).

**Brīvā RAM** (Win32_OperatingSystem): darba sākumā **6,7 GB** no 15,7 GB; beigās 5,0 GB [P].

## Kopsavilkuma tabula

| Avots | Pieejams | Formāts / izšķirtspēja | Laiks | Latvija / Kalsnava | Apjoms LV | Ierobežojumi |
|---|---|---|---|---|---|---|
| a) EFDA v3.0.0 | jā [P] | GeoTIFF, 30 m, EPSG:3035 | 1985–2024 | **jā, bet LV dati ir failā `Lithuania.zip`** [P] | 971,8 MB zip (no tā 784,5 MB varbūtības slānis) [P] | nav atslēgas; Zenodo |
| b1) Open-Meteo vēsturiskais | jā [P] | JSON, ERA5 0,25°, ERA5-Land 0,1° | ERA5 1940–, ERA5-Land 1950– [P docs] | jā (punktu vaicājumi) [P] | ~330 ERA5 šūnas LV [N aprēķins] | 10 000 izsaukumi/dienā, 600/min [P] |
| b2) ERA5-Land (CDS) | dokumentācija [P]; lejupielāde nav pārbaudīta [N] | GRIB, 0,1° (9 km) [P] | 1950– [P] | globāls [P] | nav novērtēts | konts + personīgais tokens + licences akcepts [P]; `cdsapi` nav instalēts |
| c1) LĢIA ortofoto 2022–2024 WMS | tikai pēc licences līguma [P] | WMS, 20 cm | 2022–2024 | visa LV [P] | — | WMS datus nedrīkst lejupielādēt [P] |
| c2) LĢIA DTM 20 m | jā [P HEAD] | TXT punkti 7z arhīvā | skenēšana 2013–2019 | visa LV [N no faila nosaukuma] | 399 MB 7z [P] | 7z atvēršanai vajag 7-Zip vai `py7zr` (nav) [P] |
| c3) LĢIA LiDAR LAS | jā [P galvenes] | LAS 1.2, 1 × 1 km flīzes | 2013–2019 [P lapa]; Kalsnavā galvenēs 2016 [P] | Kalsnavā 30 flīzes [P] | 65 918 flīzes; 78–261 MB flīze → ~5–17 TB [N] | `laspy` nav; flīze > 200 MB limits |
| d) Egle: Picea abies 30 m (Bonannella) | jā [P] | COG GeoTIFF 30 m, EPSG:3035, uint8 | 2000–2020 (6 periodi) | jā [P logs] | ~1,6 GB fails Eiropai; LV logs mazs [P/N] | varbūtība = sastopamība, Kalsnavā piesātināta (65 % pikseļu 98–99) [P] |
| e) Koku augstums CHMv2 (Meta/WRI) | jā [P] | COG, ~1,2 m, EPSG:3857, uint8 metri | attēli Kalsnavā 2018–2019 [P] | jā, 1 flīze [P] | ~140 flīzes × ~0,22 GB ≈ 30 GB [N aprēķins] | nav atslēgas (anonīms S3) |
| f1) Copernicus DEM GLO-30 | jā [P] | COG, 1″ (≈ 30 m), EPSG:4326 | — | jā [P] | — | **DSM (ietver kokus)** → TWI mežā nederīgs [P apraksts] |
| f2) LĢIA DTM 20 m | sk. c2 | | | | | |
| g) Fenoloģija | PHENIPS slēgts; RITY-2 un PHENIPS-Clim atvērti [P] | vienādojumi + parametri | — | Baltijas kalibrācijas nav atrasta [P meklēšana] | — | sk. g) sadaļu |
| h) Sausums (P − ET0, SPEI) | ET0 no Open-Meteo `era5` [P]; SPEI bibliotēkas nav instalētas | — | — | — | — | metodes raksta PDF HTTP 403 |

## a) European Forest Disturbance Atlas (EFDA)

- **Versija [P]:** Zenodo jaunākā ir **v3.0.0 (2026-09-13)**, nevis v2.1.1 (2024-08-20), ko izmanto Besnard u. c. 2026.
  v3.0: 1985–2024, Landsat 4–9, 30 m, EPSG:3035, jauns dziļās mācīšanās traucējumu detektors; aģentu
  piešķiršana un meža maska — kā v2.1.1 (Viana-Soto & Senf 2025) (`efda_21722408.json`, `efda3_0_METADATA_EFDA_v3.0.txt`).
- **Slāņi v3.0 [P metadati]:** `annual_disturbance` (40 joslas, 1 = traucēts), `disturbance_probability` (0–100),
  `disturbance_severity` (dNBR × 1000), `disturbance_agent` (gada aģents: **1 = vējš / mizgrauži (viena klase)**,
  2 = uguns, 3 = cirte), `disturbance_agent_aggregated` (+ 4 = jaukti aģenti), `number_disturbances`,
  `latest_disturbance` (gads), `forestlanduse_mask`.
- **⚠ Kļūda datos [P]:** v3.0 `Latvia.zip` rastri aptver ~53,6–56,8° N (Lietuvas platuma grādi; Kalsnava un Rīga ārpus
  tiem), bet `Lithuania.zip` aptver ~55,3–58,5° N un **satur Latvijas datus** (Kalsnavas AOI pilnībā iekšā, 25 863
  meža pikseļi). v2.1.1 `latvia.zip` ir pareizs (55,1–58,7° N). Faili iekšā nosaukti attiecīgi `_latvia_` /
  `_lithuania_`. Ieteikums: ziņot autoriem; līdz tam lietot `Lithuania.zip` Latvijai vai v2.1.1 [N: vai tas ir tikai
  šo divu valstu sajaukums, citām valstīm nepārbaudīju].
- **Kalsnava [P, `efda3_kalsnava_*`]:** 1985–2024 traucēti 9 944 pikseļi (~895 ha); aģenti: vējš/mizgrauži **334 px
  (~30 ha)**, cirte 9 575, jaukti 35; pēdējā traucējuma gadi 1986…2024 (2020: 707 px, 2024: 605 px).
- **Precizitāte (ESSD 2025, v2.1.1; WebFetch kopsavilkums [P ar piezīmi: lasīts ~80 % raksta teksta]):**
  traucējumu F1 0,80 traucētajai klasei, kļūdas — 17,3 % (commission) un 22,5 % (omission); gada R² 0,73, MAE 1,91 gadi.
  Aģentu **modeļa** (ne kartes) kļūdas: vējš + mizgrauži — commission 10,5 %, omission 19,1 %; cirte 17,4 % / 8,7 %;
  autori: kartes precizitāti aģentiem nevar sniegt. Vējš un mizgrauži apvienoti, jo četru klašu modelis tos stipri jauca.
  Ierobežojumi: MMU 0,27 ha; zemas intensitātes (ne audzi nomainoši) traucējumi un **sanitārā / izlases cirte pēc
  vējgāzēm vai mizgraužiem tiek klasificēta kā cirte**; traucējumi pēc vasaras kompozīta datuma tiek atzīmēti nākamajā
  gadā. Ziemeļvalstīm augstāka commission kļūda. Baltijas valstis rakstā nav minētas atsevišķi.
- **v3.0 raksts (RSE 2026, in press)** — nav atvērts [N].
- **Faili [P]:** `efda3_Liechtenstein.zip` (2,9 MB, struktūrai); no `Latvia.zip` / `Lithuania.zip` ar HTTP range izvilkti
  tikai mazākie slāņi (sk. failu sarakstu); pilni valstu arhīvi NAV lejupielādēti.

## b) Laikapstākļi

- **Open-Meteo [P docs + tests]:** modeļi ERA5 (0,25°, 1940–, 5 d aizture), ERA5-Land (0,1°, 1950–), ERA5-Seamless,
  „best_match“ (jauc IFS no 2017 + ERA5 + ERA5-Land), CERRA (5 km, 1985–06.2021). Dienas mainīgie (API nosaukumi):
  `temperature_2m_max/min/mean`, `precipitation_sum`, `snowfall_sum`, `shortwave_radiation_sum`,
  `et0_fao_evapotranspiration`; `snow_depth` tikai stundas (ERA5-Land, CERRA). Vairākas koordinātas vienā izsaukumā — jā.
  Limiti: 600/min, 5 000/h, 10 000/dienā, 300 000/mēnesī; publiska pētniecība un izglītība = nekomerciāla.
- **Tests [P, `openmeteo_*_test.json`]:** ar `models=era5_land` dienas un stundas **nokrišņi, radiācija un ET0 ir tukši**
  (0/72 stundas), temperatūra un sniega dziļums ir. Ar `era5` un `era5_seamless` visi mainīgie ir. `best_match` dod
  citas vērtības (2018-07-02 nokrišņi 10,6 mm pret ERA5 2,5 mm) — jaukts avots, nehomogēns ilgām rindām.
- **ERA5-Land CDS [P docs]:** 0,1° (natīvi 9 km), stundas, 1950–, GRIB, CC-BY, doi:10.24381/cds.e2161bac; vajag kontu,
  personīgo tokenu `.cdsapirc` un licences akceptu; `cdsapi`. Faktiskā lejupielāde nav pārbaudīta [N]. GRIB lasīšanai
  vajadzētu `cfgrib` / `eccodes` [N].
- **Novērtējums plānam:** Open-Meteo `era5` / `era5_seamless` pietiek visiem vajadzīgajiem mainīgajiem bez atslēgas;
  ERA5-Land caur Open-Meteo der tikai temperatūrai / sniegam. Izvēle — 2. posmā.

## c) LĢIA

- **Licence [P]:** atvērtie dati — „Creative Commons Attiecinājums 4.0“ (licences PDF `Atverto datu licence CC BY_0.pdf`).
- **Ortofoto [P]:** atvērtie lejupielādējamie cikli lapā — 1.–6. (līdz 2016–2018). 8. cikls 2022–2024 (20 cm, RGBI/CIR) —
  WMS „Free data, authorized access after signing the license by the client“; pieteikšanās e-pieteikumi.lgia.gov.lv;
  WMS noteikumi: datus „cannot be modified, deleted or downloaded“. **Sekas 2.10 ortofoto rīkam:** izgriezumu
  saglabāšana var būt pretrunā noteikumiem → vajag LĢIA licences tekstu vai rīku, kas tikai rāda WMS (QGIS projekts).
  Brīvi pieejams metadatu WMS (fotografēšanas laiki): `https://wms.lgia.gov.lv/open/services/OPEN_METADATA/Ortofoto_metadata/MapServer/WMSServer` [P URL lapā; pats serviss nav testēts].
- **DTM [P]:** punkti ar 20 m soli, TXT 7z, `https://s3.storage.pub.lvdc.gov.lv/lgia-opendata/citi/dtm/DTM_Latvija_20m.7z`,
  399 MB; LKS-92 TM, LAS-2000,5. **1 m DTM rastra atvērtajos datos nav** [P: lapās nav minēts].
- **LiDAR [P]:** klasificēti punkti (zeme, veģetācija 3 klases, ēkas), LAS, ≥ 4 p/m² (zeme ≥ 1,5), 2013–2019;
  saraksts `LGIA_OpenData_las_saites.txt` (65 918 flīzes, 144 grupas pa 25 × 25 km). Kalsnava: grupa 3433, 30 flīzes,
  LAS 1.2 formāts 1, 6,8–14,2 p/m² (mediāna 9,3), faila izveides gads galvenē 2016 (ne obligāti skenēšanas gads [N]),
  flīzes 192–261 MB → AOI ~6,9 GB [P galvenes + HEAD]. Neviena flīze nav lejupielādēta.

## d) Koku sugas / egle

- **HRL DLT 2018** — jau izmanto (skujkoki / lapu koki, bez sugām).
- **Picea abies 30 m (Bonannella u. c. 2022) [P]:** Zenodo v3 (2022-07-25), CC BY 4.0, „realized distribution“ periodi
  2000–2020, COG ar pārskatiem (lasāms logs bez pilnas lejupielādes). Kalsnavas logs (`picea_p_2018_2020_kalsnava.tif`):
  65 % pikseļu vērtība 98–99; kontrolpunkti: Rīgas centrs 3, jūra 0, Bavārijas mežs 99. Tā ir **sastopamības varbūtība,
  nevis egles īpatsvars** [N interpretācija] — mežā gandrīz neatšķir audzes.
- **Cita atvērta Eiropas egles daļas / sugu karte ar LV pārklājumu** — nav atrasta un pārbaudīta [N]. Egļu īpatsvaram
  līdz LVM taksācijai paliek: HRL skujkoki + Picea varbūtība + MVR (privātie meži, 1,2 % Kalsnavā).

## e) Koku augstums

- **CHMv2 (Meta/WRI, 2026) [P]:** anonīms S3 `dataforgood-fb-data/forests/v2/global/dinov3_global_chm_v2_ml3/`, flīzes
  pēc quadkey (zoom 10), COG ~1,2 m EPSG:3857 uint8 metros + GeoJSON ar attēlu datumiem. Kalsnava = flīze `1201223023`
  (222 MB, nolasīts tikai AOI logs): augstums p10 0 m, p50 9 m, p90 20 m, max 36 m; attēli 2018-05-20, 2018-05-27,
  2019-05-21. Precizitāte v2 nav pārbaudīta [N]; v1 (Tolan u. c. 2024, RSE 300) raksts nav atvērts.
- **LĢIA LiDAR** (c3) — precīzāks, bet 2013–2019 un TB apjomā; vajag `laspy` vai PDAL.
- Citi globālie produkti (ETH 10 m 2020, GLAD 30 m) — nav pārbaudīti [N].

## f) Reljefs / TWI

- **Copernicus DEM GLO-30 [P]:** Planetary Computer, flīze `Copernicus_DSM_COG_10_N56_00_E025_00_DEM`, Kalsnavā
  86–153 m (mediāna 105 m). **Tas ir DSM** (radara virsma ar kokiem) — mežā TWI būtu kropļots.
- **LĢIA DTM 20 m** (c2) — kails reljefs, CC BY; vajag 7z atarhivētāju.
- TWI aprēķinam (plūsmas akumulācija) bibliotēkas nav (`richdem`, `whitebox`, `pysheds` — nav) [P]; iespējama arī
  pašu D8 implementācija numpy/scipy [N].

## g) Mizgraužu fenoloģija

- **PHENIPS (Baier, Pennerstorfer, Schopf 2007, FEM 249:171–186):** **slēgta piekļuve** [P: OpenAlex `closed`; BOKU
  lapā PDF nav]. Vērtības no oriģināla NAV izrakstītas.
- **RITY-2 (Ogris 2020, MethodsX 7:100845, CC BY, PMC7076557) [P, pilns teksts `rity_ogris2020.txt`]:** balstīts uz
  PHENIPS, kalibrēts Slovēnijai (INCA dati). Vienādojumi:
  - meža gaisa t° no INCA: ATmin = 1,44 + 0,82·Imin; ATmean = 0,50 + 0,81·Imean; ATmax = 1,03 + 0,86·Imax (1–3);
  - mizas t°: BTmin = 0,56 + 0,99·ATmin; BTmean = −0,48 + 1,03·ATmean; BTmax = 0,03 + 0,99·ATmax (4–6);
  - efektīvā mizas t°: DT_L = 8,3 °C, T_O = 30,4 °C, DT_U = 38,9 °C; lineāri BT − 8,3 starp DT_L un T_O (7);
    virs T_O nelineāri ar α = 0,02876507, β = 3,5922336, γ = 1,24657367, Tmax = 40,9958913 (8); citādi 0 (9);
  - izlidošana: Imax > 14,5 °C un Σ(Imax − 8,3) ≥ 53,0 dd no 7. marta (10); invāzija ≥ 155,6 dd (11);
  - paaudze: K = 557 dd (12); māsu perējumi un F2/F3 — ja Imax > 14,5 °C un dienas garums ≥ 14,5 h (13–15);
  - pārziemošana: paaudze tiek skaitīta, ja relatīvā termālā summa ≥ 0,6 līdz 31. oktobrim.
  - Rakstā minētās **PHENIPS** vērtības (sekundārs avots): izlidošana 60,5 dd, invāzija 140,3 dd, termālā summa no
    1. aprīļa, ATmax slieksnis 16,5 °C; PHENIPS mizas t° — regresija ar gaisa t° un radiāciju.
- **PHENIPS-Clim (Jakoby, Lischke, Wermelinger 2019, GCB) [P, autora manuskripts WSL DORA, teksts izvilkts ar zlib]:**
  1. tabula (Bayes kalibrācija Šveicei): Tfly_min 16,11 °C, Tfly_max 31,29 °C, Tsw_sum 100 dd (no 1. janvāra, virs
  Tdev_min 5,12 °C), DOYfirst 210, DOYlast 232, Tdia_min 16,45 °C, pfly_max 0,01, ν 1,36, psb 0,30, slotsb 4, k 0,03,
  Briere ρ_dev 0,0000789, ρ_mat 0,0000101, ρ_rep 0,0000255, T_lo dev/mat/rep 4,76 / −4,43 / −12,98 °C, T_up 40,03 /
  39,99 / 36,00 °C, n_dev 71, n_mat 8, n_rep 11. Vienādojumu (Eq. 1–4) formulas PDF teksta slānī nav nolasāmas
  (iegultas rakstzīmes) [P] → vajag publicētāja HTML (Wiley — Cloudflare pārbaude, neapiets) vai `pypdf` / poppler.
- **Ziemeļeiropa / Baltija [P meklēšana]:** Tikkanen & Lehtonen 2023 (Silva Fennica 57(3):23003) — Igaunija, Somija,
  Zviedrija; fenoloģijas modeli nedarbina, lieto termālās summas sliekšņus (1500 dd ~ 2 paaudzes; 625–750 dd vienai
  paaudzei, citējot Jönsson u. c. 2007 un Annila 1969); **Latvija nav iekļauta**. Baltijas / Latvijas PHENIPS kalibrācija
  nav atrasta. Öhrn 2012 (SLU, Zviedrija, OA) — nav atvērts.
- **Latvijas monitorings [P, Silava prezentācijas un ziņas]:** Silava — 26 parauglaukumi × 3 feromonu slazdi svaigās
  cirsmās, 1. maijs–1. septembris, reizi nedēļā (2017. g. prezentācija); 2023. g. „aktīva izlidošana sākusies
  20. aprīlī“ (lvportals 2023); 2024. g. aktivitāte no aprīļa (LSM 28.05.2024). **Atvērta slazdu datu kopa nav atrasta** —
  jāprasa Silava / VMD [N].

## h) Sausums

- **ET0:** Open-Meteo `et0_fao_evapotranspiration` (FAO-56) ar `era5` / `era5_seamless` [P tests]; ERA5-Land caur
  Open-Meteo to nedod [P].
- **Klimatiskā ūdens bilance P − ET0** — tiešs aprēķins, bibliotēka nav vajadzīga [N].
- **SPEI:** Vicente-Serrano u. c. 2010 (J. Climate 23:1696) — OpenAlex „bronze OA“, PDF lejupielāde HTTP 403 [P] →
  metodes detaļas no oriģināla nav izlasītas. Bibliotēkas (licences PyPI, nav instalētas): `spei` 0.8.2 (MIT),
  `climate-indices` 3.0.0 (BSD), `xclim` 0.62.0 (Apache-2.0); ET alternatīvai `pyet` 1.5.0 (MIT). Iespējams arī
  log-logistiskā sadalījuma pielāgojums ar `scipy` (jau ir) [N].

## Lejupielādētie / izveidotie faili (`cache/rm_test/`, kopā 73 MB)

| Fails | Avots (URL) | Izmērs | Licence | Kam |
|---|---|---|---|---|
| `efda_13333034.json`, `efda_21722408.json` | https://zenodo.org/api/records/13333034, …/21722408 | 15 kB, 17 kB | — (metadati) | versijas, faili |
| `efda3_0_METADATA_EFDA_v3.0.txt` | https://zenodo.org/records/21722408/files/0_METADATA_EFDA_v3.0.txt | 3,8 kB | CC BY 4.0 | slāņu definīcijas |
| `efda3_Liechtenstein.zip` | …/21722408/files/Liechtenstein.zip | 2,9 MB | CC BY 4.0 | zip / GeoTIFF struktūra |
| `efda3_disturbance_agent_aggregated_latvia_v30.tif`, `efda3_latest_disturbance_latvia_v30.tif`, `efda3_forestlanduse_mask_latvia_v30.tif` | `Latvia.zip` (v3.0), HTTP range, 15,7 MB pārsūtīti | 3,8 / 8,6 / 3,1 MB | CC BY 4.0 | atklāja, ka tie ir Lietuvas dati |
| `efda3_forestlanduse_mask_lithuania_v30.tif`, `efda3_disturbance_agent_aggregated_lithuania_v30.tif`, `efda3_latest_disturbance_lithuania_v30.tif` | `Lithuania.zip` (v3.0), HTTP range, ~26 MB pārsūtīti | 3,7 / 6,3 / 16,1 MB | CC BY 4.0 | Latvijas dati, Kalsnavas izgriezumi |
| `efda211_latvia_forestmask.tif` | `latvia.zip` (v2.1.1), HTTP range | 5,5 MB | CC BY 4.0 | v2.1.1 pārklājuma salīdzinājums |
| `efda3_kalsnava_*.tif` (2) | izgriezti no iepriekšējiem | 5 kB, 12 kB | CC BY 4.0 | Kalsnavas aģenti / gadi |
| `openmeteo_*_test.json` (5) | https://archive-api.open-meteo.com/v1/archive | 2–5 kB | CC BY 4.0 | modeļu un mainīgo tests |
| `lgia_las_saites.txt` | https://s3.storage.pub.lvdc.gov.lv/lgia-opendata/las/LGIA_OpenData_las_saites.txt | 4,9 MB | CC BY 4.0 | flīžu saraksts |
| `lgia_las_group_headers.json`, `lgia_las_kalsnava_headers.json` | LAS galvenes (375 B katra, HTTP range; 144 + 625 flīzes) | 30 kB, 9 kB | CC BY 4.0 | flīžu robežas, blīvums |
| `copdem30_kalsnava.tif` | Planetary Computer `cop-dem-glo-30` (COG logs) | 115 kB | sk. DATU_AVOTI | DEM tests |
| `chmv2_kalsnava_1201223023.tif`, `chmv2_metadata_1201223023.geojson` | https://dataforgood-fb-data.s3.amazonaws.com/forests/v2/global/dinov3_global_chm_v2_ml3/ (COG logs + metadati) | 10,5 MB, 8,4 MB | CC BY 4.0 | koku augstums Kalsnavā |
| `picea_5881700.json`, `picea_6961187.json`, `picea_p_2018_2020_kalsnava.tif` | https://zenodo.org/api/records/…; COG logs no `veg_picea.abies_anv.eml_p_30m_0..0cm_2018..2020_eumap_epsg3035_v0.3.tif` | 17 kB ×2, 14 kB | CC BY 4.0 | egles karte |
| `rity_ogris2020_PMC7076557.xml`, `rity_ogris2020.txt` | https://www.ebi.ac.uk/europepmc/webservices/rest/PMC7076557/fullTextXML | 60 kB, 20 kB | CC BY 4.0 | RITY vienādojumi |
| `phenips_clim_jakoby2019.txt` | izvilkts no https://www.dora.lib4ri.ch/wsl/dload/wsl:21181/PDF3/view (PDF 2,4 MB WebFetch kešā, ne `cache/rm_test`) | 1,6 MB | autora manuskripts [N: licence nav pārbaudīta] | PHENIPS-Clim parametri |
| `efda_extract.py`, `pdf_text.py` | mani palīgskripti (nav pakotnē) | 3 kB | — | izvilkšana |

## Kas NAV izdarīts

- Nav lejupielādēti pilni Latvijas faili (EFDA arhīvi, DTM 7z, LAS flīzes, CHMv2 flīzes).
- Nav pārbaudīta faktiskā ERA5-Land lejupielāde no CDS (vajag jūsu kontu / tokenu).
- Nav izlasīti: PHENIPS oriģināls (slēgts), PHENIPS-Clim vienādojumu formulas, SPEI oriģinālraksts (403), EFDA v3 RSE
  raksts, CHMv2 / Tolan precizitātes raksti, LĢIA licences PDF pilnais teksts, Copernicus DEM licences pielikums.
- Nav testēts LĢIA metadatu WMS; nav pieteikta LĢIA ortofoto WMS piekļuve (jūsu lēmums / darbība).
- Nav pārbaudīts, vai EFDA v3 failu sajaukums skar arī citas valstis.
- Nav instalēta neviena bibliotēka; šie dokumenti nav commitoti.
