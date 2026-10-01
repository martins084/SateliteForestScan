# s2-forest-screening

Sentinel-2 meža stresa un mizgraužu (*Ips typographus*) bojājumu **skrīninga** rīks —
1. līmenis divlīmeņu sistēmā (satelīts → drons). Rīks atrod aizdomīgas vietas
nogabala / koku grupu līmenī, lai zinātu, kur sūtīt dronu (DJI Mavic 3M)
multispektrālai verifikācijai.

> **Svarīgi par iespējām.** Sentinel-2 izšķirtspēja ir 10–20 m. Rīks nosaka
> izmaiņas koku grupu vai nogabala daļu līmenī, **nevis atsevišķus kokus**.
> Tas **nav** droša "zaļā uzbrukuma" (agrīnās, vizuāli neredzamās) stadijas
> noteikšana — tas ir skrīninga slānis, kura rezultāti jāpārbauda uz vietas.

LBTU Studentu inovāciju programma, sadarbībā ar LVM.

---

## Uzstādīšana

Nepieciešams: Windows / Linux / macOS, interneta pieslēgums datu ieguvei.
API atslēgas vai paroles **nav vajadzīgas**.

```bash
python -m pip install --user uv
python -m uv sync
```

`uv` pats uzstāda projekta Python versiju (3.12) un visas atkarības mapē `.venv`.

## Lietošana

Visu vada viens YAML konfigurācijas fails (piemērs: `configs/test_kalsnava.yaml`).

### Jauna teritorija

1. Nokopē `configs/template_aoi.yaml` (piem., `configs/lvm_meza_masivs.yaml`).
2. Ievieto ievaddatus mapē `data/local/` (tā netiek iekļauta git): AOI, pēc
   vajadzības nogabalus un references (sanitārās cirtes).
3. Aizpildi laukus, kas atzīmēti ar `TODO` (AOI ceļš, monitoringa gads,
   references lauku nosaukumi un cirtes iemesla vērtības).
4. Palaid visu procesu ar vienu komandu:

```bash
python -m uv run s2forest run configs/lvm_meza_masivs.yaml
```

Pirmā palaišana jaunai 5×5 km teritorijai ilgst ~40–60 min (datu ieguve,
4 sezonas); atkārtota palaišana izmanto kešu un ilgst ~10 min.

### Atsevišķi soļi

```bash
python -m uv run s2forest fetch    configs/test_kalsnava.yaml   # datu ieguve + diagnostika
python -m uv run s2forest indices  configs/test_kalsnava.yaml   # indeksi, meža maska, GeoTIFF
python -m uv run s2forest detect   configs/test_kalsnava.yaml   # anomālijas, poligoni, drona mērķi
python -m uv run s2forest validate configs/test_kalsnava.yaml   # salīdzinājums ar references datiem
```

`detect --no-closeups` izlaiž poligonu tuvplānu attēlus (ātrāk).

```bash
python -m uv run s2forest report   configs/test_kalsnava.yaml   # HTML atskaite
python -m uv run s2forest missions configs/test_kalsnava.yaml   # pārgrupēt misijas (pēc targets.mission_* maiņas)
```

Atskaite: `output/<run_name>/atskaite_<run_name>_<gads>.html` (viens fails ar
iegultiem attēliem). Visi atskaites attēli ir arī atsevišķi PNG failos (200 dpi)
mapē `figures/report/` — izmantošanai granta pieteikumā un prezentācijā.

Rezultāti: `output/<run_name>/`

| Mape | Saturs |
|---|---|
| `diagnostics/` | pārlidojumu tabula, derīgo novērojumu grafiks, RGB priekšskatījumi, harmonizācijas un dūmakas testa pārbaude |
| `rasters/` | meža maska, indeksu laika rindas (viena josla = viens datums), vasaras mediānas pa gadiem |
| `rasters/anomaly/` | statusa rastrs, pirmās noteikšanas diena, z-vērtības |
| `vectors/suspects.gpkg` | slāņi `suspects_<gads>` (visi poligoni), `drone_targets` (drona mērķi), `validation_references_<gads>`; atverami QGIS un QField |
| `vectors/drone_targets_<gads>.kml` / `.geojson` | drona mērķi WGS84 lidojuma plānošanai |
| `tables/` | poligonu atribūti un statusu kopsavilkums, drona mērķi, validācijas rezultāti, reģionālās nobīdes (CSV) |
| `figures/` | PNG kartes prezentācijai |
| `run_metadata.json` | izmantotie pārlidojumi, pakotņu versijas (reproducējamībai) |

Testi (bez interneta): `python -m uv run pytest`.
Kataloga pieņēmumu pārbaude (ar internetu): `python -m uv run pytest -m network`.

## Metode īsumā

1. **Datu ieguve.** STAC katalogi bez autentifikācijas: galvenais — Element84
   Earth Search `sentinel-2-c1-l2a` (ESA Collection-1, vienota apstrāde visiem
   gadiem); otrais — Microsoft Planetary Computer `sentinel-2-l2a`, kas aizpilda
   datumus, kuru nav galvenajā avotā. Tiek lasīts tikai AOI izgriezums no COG
   failiem. Vispirms tiek nolasīts tikai SCL slānis un novērtēta skaidrā daļa
   AOI; pārējās joslas tiek lejupielādētas tikai pieņemtajiem pārlidojumiem.
   Viena pārlidojuma MGRS flīzes tiek apvienotas. Kešs: `cache/`.
2. **Harmonizācija.** DN → atstarošanās katrai ainai atsevišķi pēc tās
   processing baseline un metadatiem (BOA_ADD_OFFSET = −0,1 no baseline 04.00).
3. **Maskēšana.** SCL klases 0, 1, 3, 8, 9, 10, 11 (+20 m buferis ap mākoņiem un
   ēnām) un **laikrindu dūmakas tests** (skat. zemāk). Pārlidojumi ar < 60 %
   derīgu pikseļu AOI tiek atmesti.
4. **Režģis.** LKS-92 / Latvia TM (EPSG:3059), 10 m. 20 m joslas (B05, B8A, B11,
   B12) tiek pārveidotas uz 10 m ar **bilineāro interpolāciju** vienā solī ar
   pārprojicēšanu. NDRE, NDMI un CRSWIR tāpēc faktiski ir 20 m produkti 10 m
   režģī.
5. **Indeksi.** NDVI (B08, B04), NDRE (B8A, B05), NDMI (B8A, B11), CRSWIR
   (B11 / lineārs kontinuums starp B8A un B12 pie 1610 nm).
6. **Anomālijas.** Katram pikselim un indeksam bāzes līnija no iepriekšējiem 3
   gadiem: **harmonisks sezonālais modelis** (brīvais loceklis + 1 gada harmonika,
   `anomaly.harmonics`), pielāgots robusti (IRLS ar Huber svariem, 5 iterācijas).
   Novirzes mērogs = modeļa atlikumu MAD × 1,4826 (ne mazāks par `mad_floor`);
   pikseļiem ar < 5 bāzes novērojumiem bāzes nav. Alternatīva
   (`anomaly.baseline_method: window`): mediāna un MAD ±30 dienu logā.
   Harmoniskais modelis izvēlēts, jo loga mediāna sezonas malās ir nobīdīta
   (logs tur ir vienpusējs): Kalsnavā veselā mežā agrā pavasarī (≤ 30.05)
   z ≥ 2,5 īpatsvars samazinājās no 0,42 % līdz 0,15 %, un vidējā |z mediāna|
   no 0,12 līdz 0,08 (`scripts/diagnose_seasonal_bias.py`, grafiks
   `diagnostics/seasonal_bias.png`). 2. harmonika uzlabojumu nedeva.
   Novērojums ir anomāls, ja CRSWIR z ≥ 2,5 un vismaz viens cits indekss arī
   pārsniedz 2,5; pikselis tiek atzīmēts, ja tas atkārtojas ≥ 2 secīgos
   derīgos novērojumos **un** skrējiens aptver ≥ 7 dienas (`persistence_min_days`;
   divas ainas dažu dienu attālumā ir vienos laikapstākļos un nav neatkarīgas).
   Skrējiens, kas sezonas beigās vēl nav sasniedzis 7 dienas, netiek izmests —
   poligons saņem statusu `new`. Poligoni < 0,1 ha tiek atmesti.
   Reģionālā normalizācija: katram datumam no novērojumiem atņem AOI + 5 km
   bufera meža pikseļu mediāno novirzi (sausuma gadi, fenoloģijas nobīde);
   buferis tiek lasīts 60 m izšķirtspējā no COG pārskatiem (overviews).
   No bāzes izslēdz pikseļus, kas bāzes periodā jau bija nocirsti vai noturīgi
   anomāli (≥ 0,1 ha laukumi); katrs bāzes gads tiek pārbaudīts pret
   iepriekšējiem bāzes gadiem (pirmais — pret pārējiem), lai noķertu arī
   traucējumu, kas turpinās vairākus gadus.
   **Ceļi:** no analīzes izslēdz pikseļus ≤ 20 m no OpenStreetMap ceļiem
   (`linear_features`; ieskaitot meža ceļus `track`), jo ceļmalas ir jaukti
   pikseļi, kas mainās ar putekļiem, pļaušanu un ceļa darbiem. Dati no publiskā
   Overpass API (bez atslēgas, ODbL licence), kešoti. Kalsnavā tas ir 58 ceļi un
   6,8 % skujkoku meža. Grāvjus un elektrolīnijas var ieslēgt konfigurācijā
   (noklusēti izslēgti: grāvju Latvijas mežos ir ļoti daudz). Ja OSM dati nav
   pieejami, analīze turpinās bez ceļu maskas un CLI par to brīdina.
7. **Poligonu atribūti.** `first_detected`, `area_ha`, `type` (`stress` vai
   `cut` — cirte / audzi nomainoša izmaiņa), `delta_<indekss>` (izmaiņa pret
   bāzi), `z_<indekss>`, `persistence_len`, `n_indices_agree`, `confidence`
   (heuristisks 0–1 rādītājs, **nav varbūtība**), `onset_before_season`
   (izmaiņa notikusi jau pirms sezonas pirmā novērojuma, piem., ziemas cirte),
   `prev_autumn_z` un `onset_prev_autumn` (poligona mediānais z iepriekšējā gada
   novērojumos no 15.08.; ≥ 1,25 → izmaiņa sākusies jau iepriekšējā rudenī),
   `elongation` (minimālā pagrieztā taisnstūra garā/īsā mala), `dist_to_road_m`,
   `near_road` (stresa poligona mala ≤ 30 m no ceļa),
   `linear_feature` (stresa poligons ar iegarenību ≥ 3 — iespējams lineārs
   objekts; netiek dzēsts, bet atzīmēts arī drona mērķa aprakstā) un
   `status`:
   - `new` — pēc pirmās noteikšanas ir < 2 derīgi novērojumi, vēl nevar izlemt;
   - `persistent` — izmaiņa saglabājas (mediānā primārā z ≥ k/2);
   - `recovered` — atgriezies normā (piem., pavasara fenoloģijas artefakts).
   Poligoni netiek dzēsti; statusu skaits redzams `tables/polygon_status_<gads>.csv`.
8. **Drona mērķi** (`drone_targets`): stresa poligoni ar statusu `new` vai
   `persistent` — 1. prioritāte noturīgi, 2. jauni, 3. stress pie ceļa (`near_road`)
   vai iegarens (`linear_feature`), jo tie biežāk ir ceļmalu / grāvju darbi, nevis
   stress; 4. prioritāte — 30 m skujkoku meža josla gar pēdējo 2 gadu cirtēm
   ≥ 0,3 ha (augsta riska zona, kur anomālija nav noteikta), sakārtota pēc `risk_score`. Katram mērķim: ID
   (T001…), centroīda un punkta uz mērķa koordinātas WGS84, īss apraksts latviski.

   **Cirtes malas riska rādītājs** `risk_score` (0–1) = svērta summa (svari
   `targets.risk_weights`, noklusēti):

   | Komponente | Svars | Aprēķins |
   |---|---|---|
   | orientācija (`risk_orientation`) | 0,4 | Katram joslas pikselim — virziens uz tuvāko cirtes pikseli, t. i., kurp vērsta atsegtā meža siena. Pikseļa vērtība (1 + cos(virziens − 225°)) / 2: maksimums DR (225°), D un R ≈ 0,93, Z ≈ 0,07; vidējais pa joslu. D, DR un R vērstas malas saņem visvairāk saules → pārkaršana → mizgraužu uzbrukumu risks. |
   | svaigums (`risk_freshness`) | 0,3 | Monitoringa gada cirte = 1, iepriekšējā gada = 0,5 (lineāri pa `cut_edge_years`). |
   | skujkoku īpatsvars (`risk_conifer`) | 0,3 | Cik liela daļa no pilnās 30 m joslas ap cirti ir analizētais skujkoku mežs. |

   Papildus: `sw_exposed_share` — joslas daļa, kuras siena vērsta D…R (157,5–292,5°).
   Maksimuma virzienu var mainīt ar `targets.risk_peak_azimuth`.

   **Misijas** (`drone_missions`): mērķi tiek grupēti pēc attāluma. Sākot ar
   augstākās prioritātes nepiešķirto mērķi, tiek pievienoti tuvākie mērķi
   (≤ 500 m), kamēr buferēto (20 m) mērķu izliektās čaulas laukums nepārsniedz
   30 ha (~1–2 Mavic 3M baterijas zemā augstumā). Misijas sakārtotas pēc labākā
   mērķa prioritātes, tad pēc augstākā mērķa riska / ticamības misijā, tad pēc kopējās vērtības; eksportētas top 10 (`targets.max_missions`)
   GPKG slānī un KML/GeoJSON (`vectors/drone_missions_<gads>.kml`). Visi mērķi
   (arī ārpus top 10) paliek `drone_targets` slānī ar `mission_id`.
9. **Validācija** (ja ir references dati, piem., sanitārās cirtes ar datumiem):
   - references darbības jomā ir cirtes no monitoringa sezonas sākuma līdz
     nākamā gada 31. martam; agrākās cirtes nevar noteikt "pirms cirtes";
   - atbilstība: jebkura pārklāšanās ar referenci, kas paplašināta par 10 m;
   - **TP ir tikai stresa noteikšana pirms cirtes**; atsevišķi uzskaitītas
     references, kas noteiktas tikai kā cirte vai kā stress pēc cirtes;
   - aizkave = cirtes datums − `first_detected` dienās (pozitīvs = agrāk);
   - precision, recall, F1; katras references indeksu laika rinda, sadalīta
     pie cirtes datuma;
   - references lauku nosaukumi (ID, datums, iemesls) un iemesla filtrs ir
     konfigurējami. Datumi tiek lasīti arī formātā `dd.mm.gggg`.
   - Precision ir pesimistisks novērtējums, jo references dati parasti nav pilnīgi.

   Kalsnavas konfigurācijā validācija tiek demonstrēta ar **sintētiskām**
   referencēm (`scripts/make_demo_references.py`), kas izveidotas no paša rīka
   atrastajām cirtēm. Tās pārbauda tikai moduļa darbību un **neko neliecina par
   precizitāti**.

## Kalibrētie parametri (Kalsnavas testa teritorija, 2026)

Visi sliekšņi ir konfigurējami; kalibrēšanas skripti ir mapē `scripts/`, un tie
jāpārpalaiž jaunai teritorijai.

| Parametrs | Vērtība | Pamatojums |
|---|---|---|
| Dūmakas tests, B02 pārsniegums (`masking.haze.b02_threshold`) | 0,02 | Skaidrās dienās meža pikseļu B02 novirze no bāzes: p95 = 0,017, p99 = 0,025. Ar 0,02 tiek aptverti 2026-09-15 mākoņu svītru kodoli (atbilst RGB). Ar 0,015 skaidrās dienās maskētu cirsmu malas, ar 0,03 izkrīt svītru malas. `scripts/calibrate_haze.py` |
| Sezonas pēdējais novērojums (`last_obs_scene_share`) | 10 % | Pēdējam novērojumam nav nākamā, tāpēc to pēc noklusējuma saglabā. Izņēmums: ja neizšķirtie pikseļi aizņem ≥ 10 % no AOI, to uzskata par atmosfēras efektu. Skaidrās pēdējās dienās tie bija 0,1–1,5 %, dūmakainajās 12–24 %. |
| Meža maska, bāzes vasaras NDVI (`forest_mask.min_summer_ndvi`) | 0,65 | HRL skujkoku pikseļu vasaras NDVI mediānas virsotne ir ~0,78 (σ ≈ 0,04); izcirtumi un jaunaudzes veido asti 0,35–0,65. 0,65 ≈ virsotne − 3σ; izslēdz ~4 % HRL pikseļu (cirsmas, ceļus, grāvjus). `scripts/calibrate_forest_ndvi.py` |
| Meža maska, sezonālā amplitūda (`forest_mask.max_seasonal_range`, NDVI) | 0,22 | Bāzes perioda NDVI sezonālais diapazons (p90−p10) katram pikselim: slēgtām skujkoku audzēm virsotne ~0,10, jauktām audzēm, jaunaudzēm un mitrām vietām gara aste. Robeža = mediāna + 3 robustās σ (0,21 bāzei 2022–24, 0,22 bāzei 2023–25); izslēdz ~10–12 % analizētā meža. Poligons #65 (2025), ko redzējām kā jauktu audzi: 0,30. NDVI izvēlēts CRSWIR vietā, jo #65 bāzes periodā CRSWIR diapazons (0,31) bija zem CRSWIR robežas (0,33) — lielā svārstība bija tikai 2025. gadā; lapu koku / pameža zaļošana labāk redzama NDVI. `scripts/calibrate_amplitude.py` |
| Minimālā z mēroga grīda (`anomaly.mad_floor`) | NDVI 0,035, NDRE 0,034, NDMI 0,047, CRSWIR 0,061 | No ~10–15 bāzes novērojumiem ±30 dienu logā MAD bieži ir par mazu, un z tiek uzpūsts (bāzes gados 5–11 % novērojumu pārsniedza z ≥ 2,5). Grīda = pikseļu robustā mēroga (1,4826·MAD) 75. procentile analizētajā mežā. `scripts/calibrate_mad_floor.py` |
| Cirtes pazīme (`cut_ndmi_drop`) | NDMI kritums ≥ 0,15 | Vizuāli apstiprinātām ziemas kailcirtēm NDMI izmaiņa −0,16…−0,28, bet NDVI paliek ~0,6 (zemsedze). Tāpēc tikai NDVI noteikums tās neatpazina. |
| Bāzes traucējumu izslēgšana | tikai laukumi ≥ 0,1 ha | Izolēti trokšņaini pikseļi netiek uzskatīti par traucētiem (citādi tika izslēgti 39 % meža). |

## Pārbaudītie datu avotu fakti (2026-09-30)

- **Earth Search `sentinel-2-c1-l2a` robs:** nav datu no ~2022. gada aprīļa
  līdz novembrim. Šos datumus aizpilda Planetary Computer (lielākoties
  pārapstrādātā baseline 05.10, dažiem datumiem 04.00). Katra novērojuma avots
  un baseline ir saglabāts rezultātos.
- **BOA nobīde c1 kolekcijā** attiecas uz *visiem* gadiem (arī 2018–2021, jo tie
  ir pārapstrādāti ar baseline 05.00), tāpēc lēmums tiek pieņemts pēc ainas
  baseline, nevis pēc datuma (25.01.2022).
- **Earth Search vecā kolekcija `sentinel-2-l2a`:** ja
  `earthsearch:boa_offset_applied = true`, pikseļu vērtības jau ir nobīdītas,
  lai gan metadati (`raster:bands.offset = −0.1`) to neatspoguļo. Rīks nobīdi
  otrreiz nepiemēro (pārbaudīts, salīdzinot vienas ainas DN abās kolekcijās:
  starpība tieši 1000).
- **Planetary Computer** nesniedz `raster:bands`; nobīde tiek noteikta pēc
  baseline (≥ 04.00 → −0,1).
- Harmonizācijas pārbaudes grafiks (`diagnostics/harmonization_check.png`)
  rāda konsekventus skujkoku meža atstarošanās līmeņus 2022–2026 abos avotos.

## Ceļu bagātinājuma tests (Kalsnava)

`scripts/road_enrichment.py`: stresa pikseļu daļa attāluma joslās līdz OSM ceļam,
dalīta ar analizētā meža daļu tajās pašās joslās (1 = nav ceļa efekta).

| Josla | 2025 stress | 2025 cirtes | 2026 stress |
|---|---|---|---|
| 20–30 m | 1,8 | 1,1 | 0 |
| 30–50 m | 1,5 | 1,1 | 0 |
| 50–100 m | 1,9 | 1,1 | 0,8 |
| > 100 m | 0,65 | 0,95 | 1,2 |

2025. gadā bagātinājums nenokrīt līdz ~1 pēc 30 m, tātad tas nav lokāls
ceļmalas pikseļu efekts, ko atrisinātu plašāks buferis (paraugs mazs: 16 poligoni).
Tāpēc buferis paliek 20 m, bet poligoni ≤ 30 m no ceļa tiek atzīmēti ar
`near_road` un saņem zemāku drona prioritāti. Cirtēm ceļu efekta nav (~1).

## Starpgadu un platformu saskaņotība (Kalsnava, 2022–2026)

`scripts/check_platform_trend.py`: vasaras (15.06.–31.08.) CRSWIR un NDVI mediāna
stabilā veselā mežā pa gadiem un platformām.

- Vasaras CRSWIR pieauga 0,78 (2022) → 0,84 (2025), 2026. gadā 0,76; NDVI tajā pašā
  laikā arī pieauga (0,79 → 0,83). Vienlaicīgs pieaugums nav stresa pazīme —
  visticamāk, reģionāls laikapstākļu signāls, ko noņem reģionālā normalizācija.
- Nenormalizētās vērtībās S2A CRSWIR bija par 0,02–0,04 augstāks nekā S2B 3 no 5
  gadiem (datumu maz: 1–6 uz platformu gadā). Pēc reģionālās normalizācijas
  (nobīde katram datumam atsevišķi) atlikusī atšķirība veselā mežā ir ≤ 0,1 z
  (S2A +0,02, S2B −0,06, S2C −0,08), t. i., ~4 % no sliekšņa k = 2,5. Platformu
  korekcija netiek veikta. 2025. gadā vasaras logā nav S2C datumu, jo visas 5
  pieņemtās S2C ainas ir maijā un septembrī; katalogā sezonā ir 29 S2C ainas
  (tikpat, cik S2A/S2B), tātad tā nav filtra vai platformu kartējuma kļūda.

## Zināmie ierobežojumi

- **Izšķirtspēja:** koku grupu / nogabala līmenis; atsevišķi koki netiek
  noteikti. Mazākā atzīmētā vieta: 0,1 ha (10 pikseļi).
- **"Zaļais uzbrukums"** netiek droši noteikts; rīks reaģē uz vainaga krāsas un
  mitruma izmaiņām, kas parasti parādās vēlāk.
- **Mākoņainība:** Kalsnavas testa teritorijā izmantojami ~25–35 % pārlidojumu
  (15–22 derīgi novērojumi sezonā). Garos mākoņainos periodos noteikšana
  aizkavējas.
- **Plāni mākoņi un dūmaka** netiek pilnībā atpazīti SCL slānī; to daļēji
  kompensē laikrindu dūmakas tests un noturības prasība.
- **Ģeometriskā saskaņotība starp processing baseline:** viena pārlidojuma
  04.00 un 05.10 versijas 2022. gadā atšķiras par ≤ 0,17 pikseļa (1,7 m), un
  pret 2023. gada c1 ainu tās atšķiras par ≤ 0,23 pikseļa (fāzu korelācija
  B08, `scripts/check_geometry.py`). Tas ir zem 0,5 pikseļa un analīzi būtiski
  neietekmē, bet pie asām robežām (ceļi, izcirtumu malas) var radīt nelielu
  malu troksni.
- **Meža maska:** HRL Dominant Leaf Type 2018 — "skujkoki" ietver arī priedi
  (egli no priedes neatšķir); tāpēc, ja ir pieejami nogabalu dati ar valdošo
  sugu, tie ir jāizmanto. Kopš 2018. gada izcirstās platības tiek izslēgtas ar
  bāzes perioda vasaras NDVI slieksni.
- **Cirtes un stress:** rīks atšķir cirtes (straujš NDVI kritums) no
  pakāpeniska stresa pēc heuristiskas kārtulas; tā ir jāpārbauda ar references
  datiem.
