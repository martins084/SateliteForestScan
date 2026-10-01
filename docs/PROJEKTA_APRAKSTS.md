# s2-forest-screening — pilns projekta apraksts

Sentinel-2 meža stresa un egļu astoņzobu mizgrauža (*Ips typographus*) bojājumu
**skrīninga** rīks. LBTU Studentu inovāciju programma, sadarbībā ar LVM.

Šis dokuments apkopo visu, kas izstrādāts, pārbaudīts un mainīts līdz
2026-10-01: mērķi, arhitektūru, metodi, katru kalibrēto parametru ar
pamatojumu, pārbaudītos faktus par datu avotiem, rezultātus Kalsnavas testa
teritorijā, lēmumu vēsturi un atvērtos jautājumus. Lietošanas instrukcija
īsāk ir `README.md`.

---

## Saturs

1. [Mērķis, konteksts, ierobežojumi](#1-mērķis-konteksts-ierobežojumi)
2. [Uzstādīšana un lietošana](#2-uzstādīšana-un-lietošana)
3. [Arhitektūra un datu plūsma](#3-arhitektūra-un-datu-plūsma)
4. [Datu ieguve un harmonizācija](#4-datu-ieguve-un-harmonizācija)
5. [Maskēšana](#5-maskēšana)
6. [Meža maska](#6-meža-maska)
7. [Veģetācijas indeksi](#7-veģetācijas-indeksi)
8. [Bāze un anomāliju noteikšana](#8-bāze-un-anomāliju-noteikšana)
9. [Poligoni un to atribūti](#9-poligoni-un-to-atribūti)
10. [Kontroles gredzens](#10-kontroles-gredzens)
11. [Drona mērķi un misijas](#11-drona-mērķi-un-misijas)
12. [Validācija](#12-validācija)
13. [Atskaite un izvaddati](#13-atskaite-un-izvaddati)
14. [Diagnostika un kalibrēšanas skripti](#14-diagnostika-un-kalibrēšanas-skripti)
15. [Kalibrētie parametri — kopsavilkums](#15-kalibrētie-parametri--kopsavilkums)
16. [Pārbaudītie fakti par datiem](#16-pārbaudītie-fakti-par-datiem)
17. [Rezultāti Kalsnavas testa teritorijā](#17-rezultāti-kalsnavas-testa-teritorijā)
18. [Lēmumu vēsture](#18-lēmumu-vēsture)
19. [Testi](#19-testi)
20. [Zināmie ierobežojumi](#20-zināmie-ierobežojumi)
21. [Iesaldētā versija, 4. posms, lauka pārbaude, nākamie soļi](#21-iesaldētā-versija-4-posms-lauka-pārbaude-nākamie-soļi)
22. [Konfigurācijas parametru atsauce](#22-konfigurācijas-parametru-atsauce)
23. [Commit vēsture](#23-commit-vēsture)

---

## 1. Mērķis, konteksts, ierobežojumi

**Sistēmai ir divi līmeņi:**

1. **Sentinel-2 satelītu skrīnings** — atrod aizdomīgas vietas nogabala / koku
   grupu līmenī. **Šis rīks.**
2. **Drona (DJI Mavic 3M) multispektrālā verifikācija** uz vietas — rīks
   sagatavo mērķus un misijas, bet pats verifikāciju neveic.

**Ko rīks dara:** katram pikselim salīdzina monitoringa gada novērojumus ar paša
pikseļa bāzes periodu (iepriekšējie 3 gadi), atrod noturīgas novirzes stresa
virzienā, apvieno tās poligonos, atšķir cirtes no stresa, novērtē, kur sūtīt
dronu, un validē pret references datiem (piem., sanitārajām cirtēm).

**Ko rīks nedara (un tas ir skaidri norādīts README un atskaitē):**

- Nenosaka atsevišķus kokus: izšķirtspēja 10 m (NDVI) un 20 m (NDRE, NDMI,
  CRSWIR); mazākā atzīmētā vieta 0,1 ha.
- Droši nenosaka "zaļā uzbrukuma" (agrīnās, vizuāli neredzamās) stadiju. Tas ir
  skrīninga slānis, kas norāda, kur sūtīt dronu.
- HRL meža maska neatšķir egli no priedes; to risinās nogabalu dati (4. posms).

---

## 2. Uzstādīšana un lietošana

```bash
python -m pip install --user uv
python -m uv sync                     # Python 3.12 + atkarības mapē .venv
```

Projekta vieta: `C:\Users\varna\projects\s2-forest-screening`. API atslēgas
vai paroles nav vajadzīgas.

| Komanda | Ko dara |
|---|---|
| `s2forest fetch CONFIG` | STAC meklēšana, AOI izgriezumu lejupielāde kešā, diagnostika (pārlidojumi, dūmaka, harmonizācija, RGB) |
| `s2forest indices CONFIG` | indeksi, meža maska (HRL + NDVI + amplitūda + ceļi), GeoTIFF |
| `s2forest detect CONFIG [--no-closeups]` | bāze, anomālijas, poligoni, statusi, kontroles gredzens, drona mērķi un misijas |
| `s2forest validate CONFIG` | salīdzinājums ar references poligoniem |
| `s2forest report CONFIG` | vienfaila HTML atskaite latviski + PNG (200 dpi) |
| `s2forest missions CONFIG` | pārgrupē esošos mērķus misijās (pēc parametru maiņas, bez `detect`) |
| `s2forest run CONFIG` | viss process: fetch → indices → detect → validate → report |
| `s2forest stands CONFIG` | nogabalu atribūti esošam skrējienam (informatīvi) |
| `s2forest field-prepare CONFIG --id …` | lauka pārbaudes pakete (GPKG, KML, veidlapa) |
| `s2forest field-import CONFIG FORMA.csv` | aizpildītās veidlapas ielasīšana kā references |

Visas komandas izsauc ar `python -m uv run s2forest ...`.

**Jauna teritorija:** nokopēt `configs/template_aoi.yaml`, ievietot datus
`data/local/` (nav git), aizpildīt `TODO` laukus, palaist `s2forest run`.
Pirmā palaišana 5×5 km AOI ~40–60 min (4 sezonas), atkārtota no keša ~10–15 min.

**Konfigurācijas:**

| Fails | Nozīme |
|---|---|
| `configs/test_kalsnava.yaml` | pagaidu testa AOI, monitorings 2026, bāze 2023–2025; DEMO references |
| `configs/test_kalsnava_2025.yaml` | tā pati AOI, monitorings 2025, bāze 2022–2024; 2025./26. ziemas cirtes kā references |
| `configs/template_aoi.yaml` | veidne jaunai AOI (LVM) |

---

## 3. Arhitektūra un datu plūsma

```
config.yaml ─► AOI / nogabali / references (EPSG:3059)
                │
                ▼
STAC meklēšana: Earth Search c1-l2a (primārais) → Planetary Computer (robu aizpilde)
                │  dublikātu atlase pa pārlidojumiem; augstākā baseline versija
                ▼
1) tikai SCL → skaidrā daļa AOI ≥ 60 %?  ──nē──► atmests (ierakstīts indeksā)
                │ jā
                ▼
2) joslas: AOI 10 m (bilineāri) + konteksts AOI+5 km 60 m (COG overviews)
   harmonizācija (BOA_ADD_OFFSET pēc ainas) → kešs (Zarr, int16)
                │
                ▼
open_cube: SCL maska + 20 m buferis + laikrindu dūmakas tests → reflektance (time, y, x)
                │
                ▼
indeksi NDVI, NDRE, NDMI, CRSWIR; meža maska (HRL + vasaras NDVI + NDVI amplitūda + OSM ceļi)
                │
                ▼
reģionālā normalizācija (konteksts 60 m, divos soļos)
harmoniskā bāze (robusta, pa pikseļiem) → z → anomālie novērojumi → noturība (N≥2, ≥7 d)
bāzes tīrība (katrs bāzes gads pret iepriekšējiem) → izslēgšana (≥0,1 ha laukumi)
                │
                ▼
poligoni (≥0,1 ha) + tips (cirte/stress) + statuss + karogi + ticamība
                │
     ┌──────────┼──────────────┬───────────────┐
     ▼          ▼              ▼               ▼
kontroles   drona mērķi    validācija      HTML atskaite
gredzens    + misijas      (references)    + PNG 200 dpi
```

**Pakotne `src/s2forest/`:**

| Modulis | Saturs |
|---|---|
| `config.py` | visi parametri (pydantic), YAML ielāde, relatīvie ceļi |
| `aoi.py` | vektoru ielāde, režģis (GeoBox), rastrizācija |
| `sources/` | `DataSource` abstrakcija; `earthsearch.py`, `planetary.py`, `stac_common.py`, `base.py` (harmonizācija) |
| `fetch.py` | meklēšana, dublikātu atlase, divpakāpju lejupielāde, kešs, `open_cube` |
| `masking.py` | SCL maska, mākoņu buferis, derīgā daļa |
| `haze.py` | laikrindu dūmakas tests |
| `forestmask.py` | HRL DLT 2018, vasaras NDVI, sezonālais diapazons, meža daļa kontekstam |
| `linear.py` | OSM ceļi (Overpass), buferis, iegarenība |
| `indices.py` | indeksu reģistrs (`@register_index`) |
| `temporal.py` | DOY loga statistika, harmoniskais modelis (IRLS/Huber) |
| `anomaly.py` | z, anomālie novērojumi, noturība, bāzes tīrība, reģionālās nobīdes, detekcija pa blokiem (dask) |
| `vectorize.py` | poligonizācija, atribūti, statuss, ticamība |
| `ringcontrol.py` | kontroles gredzena diagnostika |
| `targets.py` | drona mērķi, cirtes malu risks, misijas, KML/GeoJSON |
| `validation.py` | references, iznākumi, metrikas, laika rindas |
| `pipeline.py` | soļi, ko izmanto CLI un notebook |
| `diagnostics.py` | sezonālās nobīdes diagnostika (z pa DOY) |
| `report.py` | HTML atskaite (Jinja2), metodes teksts no konfigurācijas |
| `viz.py` | visi grafiki (validēta krāsu palete, 200 dpi) |
| `io.py` | GeoTIFF rakstīšana |
| `cli.py` | typer komandas |

---

## 4. Datu ieguve un harmonizācija

**Avoti (bez autentifikācijas):**

1. **Element84 Earth Search, `sentinel-2-c1-l2a`** — primārais (ESA Collection-1,
   vienota apstrāde visiem gadiem).
2. **Microsoft Planetary Computer, `sentinel-2-l2a`** — aizpilda pārlidojumus,
   kuru nav primārajā avotā (2022. gada robs). URL tiek parakstīti ielādes brīdī
   ar anonīmu tokenu.

Arhitektūra ļauj pievienot Copernicus Data Space Ecosystem kā jaunu `DataSource`
klasi, nemainot pārējo kodu.

**Dublikātu atlase:** pārlidojums = platforma + datums. Katram pārlidojumam
izmanto pirmo avotu konfigurācijas secībā; avota iekšienē no vairākām
apstrādes versijām ņem augstāko processing baseline (PC 2022: 05.10 pirms 04.00).
Viena pārlidojuma MGRS flīzes tiek apvienotas (AOI uz flīžu robežas).

**Divpakāpju lejupielāde:** vispirms tikai SCL (lēts), aprēķina skaidro daļu AOI;
joslas lejupielādē tikai, ja ≥ 60 %. Latvijā ~70 % pārlidojumu tiek atmesti.

**Divi režģi:**
- AOI: EPSG:3059 (LKS-92 / Latvia TM), 10 m; 20 m joslas → 10 m bilineāri vienā solī
  ar pārprojicēšanu (NDRE, NDMI, CRSWIR tāpēc faktiski ir 20 m produkti).
- Konteksts (reģionālajai normalizācijai): AOI + 5 km, 60 m no COG pārskatiem
  (overviews), vidējošana; SCL ar "mode". Kešs vienam pārlidojumam ~4 MB (agrāk,
  visu buferi lasot 10 m, ~25 MB).

**Kešs:** `cache/<režģa_atslēga>/` — `index.json` (statuss, derīgā daļa, avots,
baseline, nobīde katram pārlidojumam), `acq/*.zarr` (AOI), `ctx/*.zarr` (konteksts),
HRL un OSM keši. Harmonizēta atstarošanās int16 ×10⁴. Maskas tiek pielietotas
nolasot, tāpēc to maiņai nav vajadzīga jauna lejupielāde. Pazeminot derīgās daļas
slieksni, atmestās ainas tiek pārvērtētas automātiski.

**Harmonizācija** (`reflectance_offset`, pārbaudīts empīriski):

| Situācija | Nobīde |
|---|---|
| Earth Search legacy `sentinel-2-l2a`, `earthsearch:boa_offset_applied = true` | 0 (DN jau nobīdīti, lai gan metadati rāda −0,1; dubulta korekcija būtu kļūda) |
| Ir `raster:bands.offset` (Earth Search c1: −0,1 visiem gadiem) | izmanto to |
| Nav metadatu (Planetary Computer) | baseline ≥ 04.00 → −0,1, citādi 0 |

Atstarošanās = DN × 10⁻⁴ + nobīde; DN = 0 → NaN.

---

## 5. Maskēšana

1. **SCL klases** 0, 1, 3, 8, 9, 10, 11 (nav datu, defektīvi, ēnas, mākoņi,
   cirrus, sniegs) + **20 m buferis** ap mākoņiem un ēnām (SCL malas ir par šaurām).
2. **Laikrindu dūmakas tests** (`haze.py`) — SCL nepamana plānus mākoņus/dūmaku:
   - atsauce: pikseļa B02 mediāna **tikai bāzes gados** ±30 d (monitoringa gads
     netiek izmantots, lai reālas izmaiņas nepiesārņo atsauci);
   - kandidāts: B02 − atsauce > **0,02**;
   - maskē tikai **īslaicīgus** lēcienus: ja nākamais derīgais novērojums tajā pašā
     sezonā arī ir paaugstināts, to nemaskē (cirte, nokaltuši koki);
   - sezonas pēdējais novērojums (nav nākamā) tiek saglabāts un uzskaitīts kā
     "neizšķirts", **izņemot**, ja neizšķirtie pikseļi aizņem ≥ 10 % AOI (plaša
     vienlaidu paaugstināšanās vienā datumā = atmosfēra);
   - diagnostika: `diagnostics/haze_by_date.csv/png` (cik nomaskēts katrā datumā).
3. Pēc masku pielietošanas aina tiek izmantota, ja ≥ 60 % AOI pikseļu ir derīgi.

---

## 6. Meža maska

Kodi rastrā `rasters/forest_mask.tif`:

| Kods | Nozīme | Kalsnava 2026 (AOI daļa) |
|---|---|---|
| 0 | nav HRL skujkoku klasē | 34,8 % |
| 1 | **analizēts** | 47,9 % |
| 2 | zems bāzes vasaras NDVI (< 0,65; cirsmas, jaunaudzes kopš 2018) | 1,7 % |
| 3 | nav vasaras novērojumu bāzē | 0,0 % |
| 4 | ≤ 20 m no OSM ceļa | 4,5 % |
| 5 | liela sezonālā amplitūda (NDVI p90−p10 > 0,22; nav slēgta skujkoku audze) | 11,1 % |

- **HRL Dominant Leaf Type 2018** (10 m, klase 2 = skujkoki) no publiskā EEA
  ImageServer, kešots. Ierobežojums: ietver priedi; 2018. gada stāvoklis.
- **OSM ceļi** (Overpass API ar User-Agent, atkārtojumi un spoguļserveri; ODbL):
  autoceļi, meža ceļi (`track`), `service` u. c.; Kalsnavā 58 ceļi (37 `track`).
  Grāvji un elektrolīnijas ir konfigurējami, noklusēti izslēgti. Ja Overpass nav
  pieejams, analīze turpinās bez ceļu maskas, un CLI brīdina.
- Kontekstam (normalizācijai): 60 m pikselis ir mežs, ja ≥ 50 % no tā ir HRL klasē
  un bāzes vasaras NDVI ≥ 0,65.

---

## 7. Veģetācijas indeksi

| Indekss | Formula | Stresa virziens |
|---|---|---|
| NDVI | (B08 − B04) / (B08 + B04) | ↓ |
| NDRE | (B8A − B05) / (B8A + B05) | ↓ |
| NDMI | (B8A − B11) / (B8A + B11) | ↓ |
| **CRSWIR** (primārais) | B11 / (B8A + (B12 − B8A) · (1,610 − 0,865) / (2,190 − 0,865)) | ↑ |

Reģistrs: jaunu indeksu pievieno ar `@register_index(nosaukums, joslas, stress_sign)`.
GeoTIFF: katram indeksam laika rinda (josla = datums) un vasaras mediāna pa gadiem.

---

## 8. Bāze un anomāliju noteikšana

### 8.1 Reģionālā normalizācija
Katram datumam un indeksam: nobīde = konteksta (AOI + 5 km, 60 m) meža pikseļu
mediānā novirze no to pašu bāzes gaidāmās vērtības. Divos soļos: 2. solī izslēdz
pikseļus, ko 1. solis atzīmēja. Noņem sausuma gadus, fenoloģijas nobīdi,
atmosfēras un platformas nobīdi. Datumi ar < 50 lietojamiem pikseļiem netiek
normalizēti. Kalsnavā 2026. gads bija mitrāks (NDMI +0,05, CRSWIR −0,08 pret bāzi).

### 8.2 Bāzes modelis (noklusēti harmonisks)
Katram pikselim un indeksam, no visiem bāzes gadu novērojumiem:
- **harmonisks modelis**: brīvais loceklis + 1 gada harmonika (cos/sin),
  robusta pielāgošana IRLS ar Huber svariem (k = 1,345, 5 iterācijas),
  vektorizēta visiem pikseļiem;
- mērogs = atlikumu MAD × 1,4826, **ne mazāks par `mad_floor`**;
- < 5 bāzes novērojumi → bāzes nav;
- alternatīva `baseline_method: window`: mediāna/MAD ±30 d logā (sezonas malās nobīdīta).

z = stresa_zīme × (x′ − gaidāmā) / mērogs, tātad z > 0 vienmēr nozīmē "stresa virzienā".

### 8.3 Anomālija un noturība
- Novērojums ir anomāls, ja **CRSWIR z ≥ 2,5** un **vismaz viens cits indekss** z ≥ 2,5.
- Pikselis tiek atzīmēts, ja anomālija ir **≥ 2 secīgos derīgos novērojumos** (mākoņaini
  datumi skrējienu nepārtrauc) **un** skrējiens aptver **≥ 7 dienas**.
- Skrējiens, kas sezonas beigās vēl nav sasniedzis 7 dienas, tiek saglabāts kā
  "gaidošs" → poligona statuss `new`.

### 8.4 Bāzes tīrība
Katrs bāzes gads tiek pārbaudīts ar to pašu kārtulu pret **iepriekšējiem** bāzes
gadiem (pirmais — pret pārējiem) un pārbaudīta cirtes pazīme. Traucētie pikseļi
tiek izslēgti no analīzes, bet tikai vienlaidu laukumi ≥ 0,1 ha (izolēti trokšņaini
pikseļi netiek uzskatīti par traucētiem). Agrāk (leave-one-year-out) traucējums,
kas turpinās 2+ gadus, varēja palikt nepamanīts.

### 8.5 Cirte vai stress
Novērojumam ir cirtes (audzi nomainošas izmaiņas) pazīme, ja NDVI ≤ 0,5 un kritums
≥ 0,25 pret bāzi **vai** NDMI kritums ≥ 0,15. Pikselis ir "cirte", ja pazīme ir ≥ 50 %
noteikšanas skrējiena novērojumu. Tips "cirte" ietver kailcirti, sanitāro cirti vai
pilnībā atmirušu audzi.

---

## 9. Poligoni un to atribūti

8-kaimiņu savienotas atzīmēto pikseļu grupas ≥ 0,1 ha. GeoPackage slānis
`suspects_<gads>`:

| Atribūts | Nozīme |
|---|---|
| `id`, `area_ha`, `n_pixels` | identifikators (pēc ticamības), platība |
| `type` | `stress` vai `cut` |
| `first_detected`, `first_detected_median` | pirmā noteikšana (agrākais / mediānais pikselis) |
| `status` | `new` (< 2 derīgi novērojumi pēc noteikšanas vai gaidošs skrējiens), `persistent` (mediānā primārā z pēc noteikšanas ≥ k/2), `recovered` (< k/2); poligoni netiek dzēsti |
| `onset_before_season` | noteikts poligona pirmajā derīgajā sezonas novērojumā — izmaiņa jau pastāvēja; **tas nav sākuma datums** |
| `prev_autumn_z`, `onset_prev_autumn` | poligona mediānais z iepriekšējā gada novērojumos no 15.08.; ≥ 1,25 → izmaiņa sākās jau iepriekšējā rudenī |
| `delta_<indekss>`, `z_<indekss>` | mediānā izmaiņa pret bāzi un z pēc noteikšanas |
| `persistence_len`, `n_indices_agree`, `baseline_obs`, `pending_share` | noturība, indeksu saskaņa, bāzes novērojumi, gaidošo pikseļu daļa |
| `elongation`, `linear_feature` | min. pagrieztā taisnstūra malu attiecība; stresa poligons ar ≥ 3 — iespējams lineāra objekta artefakts |
| `dist_to_road_m`, `near_road` | attālums līdz OSM ceļam; ≤ 30 m — informatīvs karogs |
| `confidence` | heuristisks 0–1 (0,35 z lielums + 0,25 indeksu saskaņa + 0,25 noturība + 0,15 bāzes atbalsts) — **nav varbūtība** |

Rastri `rasters/anomaly/`: statuss (0 nav, 1 stress, 2 cirte, 3 traucēts bāzē,
4 nav analizēts), pirmās noteikšanas DOY, maks. z, z laika rindas.

---

## 10. Kontroles gredzens

Standarta diagnostika katram stresa poligonam (`ringcontrol.py`): primārā indeksa
mediāna poligonā pret **100 m gredzenu analizētā mežā** ap to (tie paši laikapstākļi,
fenoloģija, atmosfēra). Pa gadiem: agrā sezona (≤ 31.05.), vasara (15.06.–14.08.),
vēlā sezona (15.08.–30.09.); starpība un attiecība (attiecība mazāk jutīga pret
augsto pavasara CRSWIR līmeni).

Izvade: `tables/ring_control_<gads>.csv`, `ring_control_series_<gads>.csv`,
`figures/ring_control_<gads>.png`, atskaites sadaļa "Kontroles gredzens";
`scripts/inspect_polygons.py` jebkuriem poligoniem.

Kāpēc tas ir svarīgi: salīdzinājums tikai ar iepriekšējiem gadiem (nenormalizētām
vērtībām) noveda pie kļūdaina secinājuma, ka 2025. gada #56/#62 "kāpj kopš 2024.
gada septembra" — gredzens parādīja, ka to rudenī novirze bija tikai +0,08…0,09,
un kāpumu redzēja arī apkārtējais mežs.

Interpretācija:
- `first_detected` sezonas sākumā nav sākuma datums: pavasarī CRSWIR augsts visur,
  un starpība ir proporcionāla līmenim (piem., #34: +0,30 pirmajā datumā, ~+0,15 vasarā).
- Ja poligons atšķiras no gredzena jau pirmajos gados, iespējama strukturāla
  atšķirība (suga, vecums, biezība) — pārbaudīs nogabalu dati.

---

## 11. Drona mērķi un misijas

**Mērķi** (`drone_targets`, GPKG + KML + GeoJSON WGS84):

| Prioritāte | Mērķis |
|---|---|
| 1 | stress, `persistent` |
| 2 | stress, `new` |
| 3 | stress ar `linear_feature` (iegarens — iespējams artefakts) |
| 4 | cirtes mala: 30 m skujkoku meža josla gar pēdējo 2 gadu cirtēm ≥ 0,3 ha (viena zona uz cirti), sakārtota pēc `risk_score` |

`near_road` ir tikai informatīvs (saulainas ceļmalas audžu malas ir ticama
uzbrukuma vieta, tāpat kā cirtes malas). `recovered` stresa poligoni mērķos netiek
iekļauti. Katram mērķim: ID (T001…), centroīds un punkts uz mērķa (WGS84),
apraksts latviski (statuss, platība, izmaiņa, ticamība, "pie ceļa", "sācies
iepriekšējā rudenī", "iegarens").

**Cirtes malas `risk_score`** (0–1, svari konfigurējami):

| Komponente | Svars | Aprēķins |
|---|---|---|
| orientācija | 0,4 | katram joslas pikselim virziens uz tuvāko cirtes pikseli (kurp vērsta atsegtā siena); (1 + cos(virziens − 225°)) / 2 — maksimums DR, D/R ≈ 0,93, Z ≈ 0,07; vidējais pa joslu |
| svaigums | 0,3 | monitoringa gada cirte 1, iepriekšējā 0,5 |
| skujkoku īpatsvars | 0,3 | analizētā skujkoku meža daļa pilnajā 30 m joslā |

Papildus `sw_exposed_share` (joslas daļa, kuras siena vērsta D…R).

**Misijas** (`drone_missions`): mantkārīga grupēšana — no augstākās prioritātes
nepiešķirtā mērķa pievieno tuvākos (≤ 500 m), kamēr buferēto (20 m) mērķu izliektā
čaula ≤ 30 ha (~1–2 Mavic 3M baterijas zemā augstumā). Kārtošana: labākā prioritāte →
riskantākais mērķis misijā → kopējā vērtība (sākotnēji pēc summas, bet tad augstākā
riska mala nonāca tikai M16). Eksportētas top 10; visi mērķi paliek ar `mission_id`.
`s2forest missions` pārgrupē bez `detect`.

---

## 12. Validācija

**Noteikumi** (saskaņoti ar komandu):
- references darbības jomā: cirtes datums no monitoringa sezonas sākuma līdz
  nākamā gada 31. martam (`reference.max_date`); agrākas → ārpus jomas;
- atbilstība: jebkura pārklāšanās ar referenci + **10 m buferis**;
- **TP tikai stresa noteikšana pirms cirtes** (`type = stress`, `first_detected` <
  cirtes datums); atsevišķi: "stress cirtes dienā vai vēlāk", "noteikts tikai kā
  cirte", "nav noteikts";
- aizkave = cirtes datums − `first_detected` (pozitīvs = agrāk);
- precision, recall, F1 (visi stresa poligoni un tikai drona statusi);
- katras references indeksu laika rinda, sadalīta pie cirtes;
- konfigurējami lauku nosaukumi (ID, datums `dd.mm.gggg` vai ISO, iemesls), iemesla
  filtrs, `description` teksts atskaitei;
- precision ir pesimistisks (references dati nav pilnīgi).

**Pārbaudes ar Kalsnavas datiem** (LVM references vēl nav):
- *DEMO* (2026): sintētiskas references no rīka paša cirtēm — pārbauda tikai
  mehāniku, neko neliecina par precizitāti.
- *2025 pret 2025./26. ziemas cirtēm*: cirtes, ko 2026. gada analīze atrada kā
  notikušas starp 2025-09-29 un 2026-05-05; cirtes datums = agrākais iespējamais
  (2025-09-30), tāpēc aizkave ir apakšējā robeža; **cirtes iemesls nav zināms**
  (visticamāk kārtējās cirtes).

---

## 13. Atskaite un izvaddati

`output/<run_name>/`:

| Ceļš | Saturs |
|---|---|
| `atskaite_<run>_<gads>.html` | vienfaila atskaite latviski ar iegultiem attēliem |
| `figures/report/*.png` | atskaites attēli 200 dpi (granta pieteikumam / prezentācijai) |
| `diagnostics/` | pārlidojumi, derīgie novērojumi, RGB, harmonizācija, dūmaka, kalibrēšana |
| `rasters/` | meža maska, indeksu laika rindas, vasaras mediānas, anomāliju rastri |
| `vectors/suspects.gpkg` | `suspects_<gads>`, `drone_targets`, `drone_missions`, `validation_references_<gads>` |
| `vectors/drone_*.kml/.geojson` | mērķi un misijas WGS84 |
| `tables/` | poligoni, statusi, mērķi, misijas, validācija, gredzens, nobīdes |
| `config.yaml`, `run_metadata.json` | izmantotā un **efektīvā** konfigurācija, versijas, pārlidojumi |

**Atskaites sadaļas:** kā lasīt (skrīnings, ne "zaļais uzbrukums"); kopsavilkums;
datu pieejamība pa mēnešiem (analīzē izmantotie / visi); pārskata karte (stress,
cirtes, misijas); poligonu statuss un stresa tabula (ar "sācies iepr. rudenī",
"iegarens", "pie ceļa"); skaidrojums, ka sezonas sākuma noteikšana nav sākuma
datums; laika rindas; kontroles gredzens; drona misijas; validācija ar references
aprakstu un aizkaves grafiku; ierobežojumi; **metode un parametri — ģenerēti no
skrējiena faktiskās konfigurācijas** (agrāk šeit bija novecojis statisks teksts).

---

## 14. Diagnostika un kalibrēšanas skripti

| Skripts | Mērķis |
|---|---|
| `calibrate_haze.py` | dūmakas sliekšņa kalibrēšana (dūmakaina pret skaidru ainu) |
| `calibrate_forest_ndvi.py` | meža maskas vasaras NDVI slieksnis |
| `calibrate_amplitude.py` | sezonālās amplitūdas slieksnis |
| `calibrate_mad_floor.py` | z mēroga grīda un viltus trauksmju īpatsvars |
| `diagnose_seasonal_bias.py` | z pa DOY veselā mežā: loga mediāna pret harmonisku |
| `check_geometry.py` | ģeometriskā nobīde starp processing baseline (fāzu korelācija) |
| `check_platform_trend.py` | vasaras CRSWIR/NDVI pa gadiem un platformām |
| `road_enrichment.py` | stresa pikseļu bagātinājums pa attāluma joslām līdz ceļam |
| `inspect_polygons.py` | kontroles gredzens izvēlētiem poligoniem |
| `make_demo_references.py` | DEMO references no rīka cirtēm |
| `make_winter_cut_references.py` | ziemas cirtes no vēlākā gada kā references agrākajam |

---

## 15. Kalibrētie parametri — kopsavilkums

Kalibrēti Kalsnavas teritorijā; jaunai teritorijai jāpārbauda ar skriptiem.

| Parametrs | Vērtība | Pamatojums |
|---|---|---|
| dūmakas B02 slieksnis | 0,02 | skaidrās dienās meža B02 novirze p95 = 0,017, p99 = 0,025; 0,02 aptver 2026-09-15 svītru kodolus (atbilst RGB); 0,015 maskē cirsmu malas, 0,03 izlaiž svītru malas |
| pēdējā novērojuma ainas daļa | 10 % | skaidrās pēdējās dienās neizšķirti 0,1–1,5 %, dūmakainās 12–24 % |
| vasaras NDVI meža maskai | 0,65 | HRL skujkoku virsotne ~0,78, σ ≈ 0,04; cirsmas/jaunaudzes 0,35–0,65; 0,65 ≈ virsotne − 3σ; izslēdz ~4 % |
| sezonālā amplitūda (NDVI p90−p10) | 0,22 | virsotne ~0,10; mediāna + 3 robustās σ = 0,21/0,22; izslēdz 6–11 %; #65 (2025, jaukta audze) = 0,30; CRSWIR to neatdalīja (0,31 pret robežu 0,33) |
| `mad_floor` | NDVI 0,035, NDRE 0,034, NDMI 0,047, CRSWIR 0,061 | pikseļu robustā mēroga p75; ar 0,02 bāzes gados 5–11 % novērojumu z ≥ 2,5, 39 % meža izslēgts kā "traucēts", 108 viltus poligoni |
| cirtes NDMI pazīme | kritums ≥ 0,15 | vizuāli apstiprinātām ziemas kailcirtēm NDMI −0,16…−0,28, bet NDVI ~0,6 (zemsedze) — tikai NDVI kārtula tās neatpazina |
| bāzes modelis | harmonisks, 1 harmonika | veselā mežā agrā pavasarī z ≥ 2,5: 0,42 % (logs) → 0,15 %; vid. \|z mediāna\| 0,12 → 0,08; 2 harmonikas nedeva uzlabojumu |
| noturības ilgums | ≥ 7 dienas | 2026. gada pirmie novērojumi 05-05 un 05-08 (3 d) — vieni laikapstākļi, nav neatkarīgi |
| ceļu buferis | 20 m (nemainīts) | bagātinājuma tests (16. sadaļa, 17.4) — efekts nenokrīt pēc 30 m |
| `near_road` | 30 m, tikai informatīvs | — |
| iepriekšējā rudens slieksnis | z ≥ 1,25 (k/2) | sakrīt ar manuālo / gredzena pārbaudi 2026 (#24, #34 jā; #23 nē) |

---

## 16. Pārbaudītie fakti par datiem

1. **Earth Search `sentinel-2-c1-l2a` nav datu ~2022-04…2022-11.** Aizpilda
   Planetary Computer (Kalsnavā 2022: 13 pieņemti, 11 × baseline 05.10, 2 × 04.00).
2. **BOA nobīde c1 attiecas uz visiem gadiem** (arī 2018–2021, pārapstrādāti ar
   05.00) — lēmums pēc ainas baseline, ne pēc datuma 25.01.2022.
3. **Earth Search legacy `boa_offset_applied = true`:** DN jau nobīdīti (pārbaudīts:
   starpība ar c1 tieši 1000 DN), metadati to neatspoguļo.
4. **Planetary Computer** nesniedz `raster:bands`; dublē 2022. gada pārlidojumus
   (04.00 un 05.10).
5. **Harmonizācijas pārbaude:** skujkoku meža atstarošanās līmeņi 2022–2026
   konsekventi abos avotos (`diagnostics/harmonization_check.png`).
6. **Ģeometrija:** viena pārlidojuma 04.00 pret 05.10 nobīde ≤ 0,17 px (1,7 m),
   pret 2023. gada c1 ≤ 0,23 px — zem 0,5 px; ierakstīts kā zināms ierobežojums.
7. **Platformas:** vasaras CRSWIR stabilā mežā 0,78 (2022) → 0,84 (2025) → 0,76 (2026),
   NDVI arī pieauga — reģionāls laikapstākļu signāls. Nenormalizēti S2A par
   0,02–0,04 augstāks par S2B 3 no 5 gadiem (maz datumu, sajaukts ar datumu); pēc
   normalizācijas veselā mežā ≤ 0,1 z (S2A +0,02, S2B −0,06, S2C −0,08). **Korekcija
   netiek veikta** (komandas lēmums); pārbaudīt atkārtoti 2026. gada beigās.
8. **S2C 2025:** katalogā sezonā 29 ainas (kā S2A/S2B), kešā 19 (pārējās > 95 %
   mākoņainas), 5 pieņemtas — visas maijā un septembrī; vasaras logā to nav
   nejaušības dēļ (2025. gada augustā 0/15 derīgu ainu visām platformām).
9. **Mākoņainība:** Kalsnavā izmantojami ~25–35 % pārlidojumu; pēc dūmakas testa
   derīgi novērojumi: 2023 — 20, 2024 — 11, 2025 — 17, 2026 — 16.
10. **Overpass API** prasa identificējošu User-Agent (citādi HTTP 406) un mēdz
    atgriezt 504 — tāpēc atkārtojumi un spoguļserveri.
11. **Nogabalu dati:** VMD Meža valsts reģistra atvērtie dati (CC0, SHP, reizi
    ceturksnī) data.gov.lv; Kalsnavas pagasts → Madonas mežniecība → Vidzemes
    virsmežniecība → `vidzemes.zip` (239,5 MB, atjaunināts 2026-07-08).

---

## 17. Rezultāti Kalsnavas testa teritorijā

**Teritorija:** pagaidu 5 × 5 km AOI pie Kalsnavas (LKS-92 612000–617000,
280500–285500; ~65 % skujkoku pēc HRL), izvēlēta, kamēr nav LVM teritorijas.
Aktīva mizgraužu perēkļa tur, visticamāk, nav.

### 17.1 Pašreizējie rezultāti (pēc visām izmaiņām)

| | 2026 (bāze 2023–25) | 2025 (bāze 2022–24) |
|---|---|---|
| analizētais mežs | 1125 ha | 1188 ha |
| izslēgts kā traucēts bāzē | 73 ha | 115 ha |
| stresa poligoni | **3** (0,33 ha), visi noturīgi | **12** (2,58 ha): 11 noturīgi, 1 atkopies |
| cirtes | 28 (29,1 ha) | 70 (77,1 ha) |
| drona mērķi | 46 (3 stress P1, 43 cirtes malas P4) | 84 (10 stress P1, 1 P3, 73 cirtes malas) |
| misijas | 20 (top 10: 32 mērķi, 219 ha) | 34 (top 10: 39 mērķi, 213 ha) |

### 17.2 2026. gada stresa poligoni (kontroles gredzens, vēlās sezonas starpība CRSWIR)

| Poligons | 2023 | 2024 | 2025 | 2026 | Secinājums |
|---|---|---|---|---|---|
| #26 (agr. #24) | +0,07 | +0,03 | **+0,24** | +0,18 | sākās 2025. gada aug.–sept.; `onset_prev_autumn` = jā |
| #31 (agr. #34) | 0,00 | +0,02 | **+0,14** | +0,17 | sācies 2025. gada rudenī; `onset_prev_autumn` = jā |
| #25 (agr. #23) | 0,00 | −0,01 | +0,02 | +0,19 | sākās starp oktobri un maiju (pēdējais 2025. gada punkts jau ~+0,07 — iespējams agrāk) |

Visi trīs ir reālas izmaiņas (gredzens 2026. gadā uzvedas normāli). Visi pirmoreiz
noteikti 05-05 — tas ir sezonas sākums, nevis izmaiņas sākums.

Piezīme par #34 → #31: agrākajā (pirms 7 dienu noturības) ģeometrijā #34 bija virs
gredzena jau 2023. gadā (~+0,10…0,15) — hronisks bojājums vai strukturāla atšķirība.
Pašreizējā, mazākajā ģeometrijā (0,11 ha) šīs hroniskās novirzes nav, kas liecina,
ka hroniskā daļa bija atsevišķos pikseļos (iespējams strukturāla). Pirmais 4. posma
tests: nogabala suga, vecums, meža tips abām ģeometrijām.

### 17.3 2025. gads
Gredzens: izteikta vēlās sezonas novirze 2025. gadā #61, #64, #76, #80, #82
(+0,14…+0,24); iepriekšējā rudenī ≥ 0,1 tikai #80 (+0,14). #57 un #61 ir gar
OSM ceļiem (#57 15 m no meža ceļa — `linear_feature`; #61 34 m no `unclassified`
ceļa); elektrolīniju OSM nav; ortofoto pārbaude atstāta drona misijai
(#57: 56,69179 N, 25,84543 E; #61: 56,68968 N, 25,84269 E).

**Validācija pret 24 ziemas cirtēm:** 1 stress pirms cirtes (ZC-019, ≥ 23 dienas
pirms cirtes), 3 tikai kā cirte, 20 bez signāla; precision 0,08, recall 0,04. Bez
signāla ir sagaidāms, ja tās ir kārtējās cirtes veselās audzēs; mizgraužu
noteikšanas precizitāti šie dati neļauj novērtēt.

### 17.4 Ceļu bagātinājuma tests (stresa pikseļu daļa / meža daļa)

| Josla | 2025 stress | 2025 cirtes | 2026 stress |
|---|---|---|---|
| 20–30 m | 1,8 | 1,1 | 0 |
| 30–50 m | 1,5 | 1,1 | 0 |
| 50–100 m | 1,9 | 1,1 | 0,8 |
| > 100 m | 0,65 | 0,95 | 1,2 |

Nenokrīt līdz ~1 pēc 30 m → ne lokāls ceļmalas efekts; paraugs mazs (pikseļi nav
neatkarīgi), iespējama telpiska korelācija ar apsaimniekošanu. Netiek turpināts;
ja turpinās — poligonu līmenī ar bootstrap.

### 17.5 Rezultātu evolūcija (2026. gada stresa poligoni)

| Stāvoklis | Stress | Cirtes | Piezīme |
|---|---|---|---|
| pirmā detekcija (logs, `mad_floor` 0,02) | 108 (48,5 ha) | 0 | 39 % meža izslēgts kā "traucēts" |
| kalibrēts `mad_floor` + bāzes izslēgšana ≥ 0,1 ha | 50 | 3 | lielākā daļa — ziemas kailcirtes |
| + NDMI cirtes pazīme | 6 | 43 | 4 no 6 — pavasara artefakti |
| + harmoniska bāze, ceļi, amplitūda | 4 | 30 | A/B ar tām pašām maskām: logs 6 → harmonisks 4 |
| + noturība ≥ 7 dienas | **3** | 28 | visi reāli (gredzens) |

2025: 19 → 16 (harmonisks; A/B: logs 15 → harmonisks 16, pirmajā datumā 11 → 8)
→ 12 (7 dienu noturība). Validācija: 34 references (2 TP — viens pavasara artefakts)
→ 24 references (1 TP).

---

## 18. Lēmumu vēsture

**Sākotnējās komandas atbildes (plāna apstiprināšana):**
- Posmu secība 0 → 1 → 2 → 3 → 5 → 6 → 4 → 7; commit pēc katra posma/punkta.
- Earth Search `sentinel-2-c1-l2a` primārais, Planetary Computer otrais.
- Meža maska bez nogabaliem: HRL Dominant Leaf Type (ne WorldCover).
- Noklusējumi: k = 2,5, N = 2, 0,1 ha, ±30 d, CRSWIR + ≥ 1 cits indekss.
- Validācija: TP tikai stress pirms cirtes; aizkave pret cirtes datumu; atsevišķi
  "tikai cirte"; konfigurējami lauki; atbilstība — pārklāšanās ar 10 m buferi.
- Bāzes tīrība: izslēgt pikseļus, kas bāzē nocirsti vai noturīgi anomāli.
- Reģionālā normalizācija ieslēgta; mediāna no AOI + 5 km meža, izslēdzot atzīmētos.

**Vēlākie lēmumi:**
- Dūmakas tests: atsauce no bāzes gadiem, tikai īslaicīgi lēcieni, pēdējais
  novērojums — konservatīvi + diagnostika (+ ainas līmeņa izņēmums, ko ieviesu pēc
  kalibrēšanas, jo kalibrēšanas aina bija tieši sezonas pēdējā).
- Buferis 60 m izšķirtspējā; meža maskai papildus vasaras NDVI.
- 2022. gada ģeometrija < 0,5 px → ierakstīt kā ierobežojumu.
- Poligonu statuss (`new`/`persistent`/`recovered`) kā statuss, ne filtrs.
- Cirtes paliek GPKG; atsevišķs `drone_targets` slānis; cirtes malu josla 30 m.
- Drona prioritizācija: `risk_score` (orientācija, svaigums, skujkoku daļa), misijas
  ~30 ha, top 10.
- Atskaite: vienfaila HTML + PNG ≥ 200 dpi, latviski.
- Harmoniska bāze (loga mediāna kā alternatīva), diagnostika pirms un pēc.
- Ceļi: OSM 20 m buferis + karogi; grāvjus nemaskēt (nevienmērīgs OSM pārklājums,
  intensīva meliorācija); bufera paplašināšana atlikta pēc bagātinājuma testa.
- Sezonālā amplitūda meža maskā (kalibrēta, NDVI).
- Platformu korekcija netiek veikta.
- Noturība: N ≥ 2 **un** ≥ 7 dienas; nepabeigts skrējiens sezonas beigās → `new`.
- `near_road` tikai informatīvs; pazemina tikai `linear_feature`.
- Kontroles gredzens — standarta diagnostika.
- Atskaites metodes teksts — no faktiskās konfigurācijas.

**Kļūdas, kas atrastas un izlabotas procesā (godīgi):**
- Pagaidu `mad_floor` 0,02 bija par zemu (108 viltus poligoni, 39 % izslēgts).
- Ziemas kailcirtes tika klasificētas kā "stress" (NDVI kārtula) → NDMI pazīme.
- Misijas kārtotas pēc vērtību summas → augstākā riska mala ārpus top 10.
- Atskaites metodes teksts bija statisks un novecojis ("±30 d logs").
- "Pirms sezonas" karogs izmantoja mediāno pikseli, ne `first_detected`.
- Manuāls secinājums par 2025. gada #56/#62 (sākums 2024. gada rudenī) bija
  pārspīlēts — gredzens to neapstiprināja.
- Bāzes tīrības leave-one-year-out nepamanīja vairākus gadus ilgu traucējumu.
- Atskaitē poligona ID nolasīts kā `71.0` (CSV) → avārija.

---

## 19. Testi

`python -m uv run pytest` — **69 bezsaistes testi** (bez interneta, sintētiski dati
ar viltotu STAC avotu), `pytest -m network` — 5 tīkla testi (kataloga pieņēmumi,
2022. gada robs, legacy nobīde, Planetary Computer nobīde, Overpass).

Testu faili: harmonizācija, maskēšana, ieguve un kešs, dūmaka (īslaicīga dūmaka
maskēta, cirte nē; pēdējais novērojums; ainas līmeņa noteikums), indeksi (formulas,
stresa virzieni, reģistrs, sezonālais diapazons), anomālijas (stress/cirte/izlēcējs/
bāzes traucējums, apstiprinošais indekss, reģionālā nobīde, noturības ilgums un
gaidošie skrējieni, iepriekšējā rudens karogs, poligonizācija), harmoniskais modelis
(atjaunošana, robustums, pavasara nobīde), lineārie objekti un prioritātes, drona
mērķi un misijas, validācija, atskaite (pieejamība, metodes teksts no konfigurācijas),
kontroles gredzens, konfigurācija (arī veidne).

---

## 20. Zināmie ierobežojumi

- Izšķirtspēja 10–20 m; mazākā vieta 0,1 ha; atsevišķi koki netiek noteikti.
- "Zaļais uzbrukums" netiek droši noteikts; noteikšana parasti nedēļas līdz mēnešus
  pēc uzbrukuma.
- Mākoņainība: maz derīgu novērojumu, garos mākoņainos periodos aizkave.
- HRL 2018: priede un egle nav atšķirtas; 2018. gada stāvoklis.
- Cirtes/stresa nošķiršana ir heuristiska.
- Sliekšņi kalibrēti vienā teritorijā (Kalsnava).
- Ticamība — heuristika, ne varbūtība.
- `first_detected` sezonas sākumā nav izmaiņas sākuma datums.
- Ģeometriskā nobīde starp baseline ≤ 0,17–0,23 px (malu troksnis).
- OSM ceļu un grāvju pārklājums nav pilnīgs.
- Validācija līdz šim tikai ar DEMO / ziemas cirtēm bez zināma iemesla.
- Nogabalu dati (sugu sastāvs) Kalsnavas valsts mežam nav pieejami atvērtajos datos.
- `detect` ilgst ~4–11 min 5×5 km AOI (divpakāpju normalizācija); nav prioritāte.

---

## 21. Iesaldētā versija, 4. posms, lauka pārbaude, nākamie soļi

**Iesaldētā versija `v0.2-kalsnava`** (git tags, 2026-10-01): detekcijas parametri
netiek mainīti līdz LVM datiem — aklā validācija (sliekšņi kalibrēti uz tās pašas
teritorijas rezultātiem). Atļautas tikai informatīvas izmaiņas (atribūti, atskaites,
lauka rīki, kļūdu labojumi bez ietekmes uz rezultātiem).

**4. posms (ierobežots, informatīvs)** — `stands.py`, `s2forest stands`:
- Avots: VMD Meža valsts reģistra atvērtie dati (data.gov.lv, CC0), `vidzemes.zip`
  (239,5 MB, 2026-07-08; Kalsnava → Madonas mežniecība → Vidzemes virsmežniecība),
  izgriezts pēc AOI uz `data/local/mvr_kalsnava.gpkg`. Klasifikators
  `data/local/vmd_klasifikatori.xlsx` (gis.vmd.gov.lv): egle = 3, citas egles = 15.
- Atvērtajos datos nav sugu koeficientu: egļu īpatsvars pēc šķērslaukuma `g10…g14`
  (rezerve — koku skaits `n10…n14`); valdošā suga = lielākais šķērslaukums; vecums
  `a1x`; meža tips `mt`. Shapefailos nav lauka `id` → `kadastrs-kvart-nog`.
- Atribūti GPKG, drona mērķos un atskaitē; **netiek izmantoti** ticamībā/prioritātē.
- **Rezultāts:** atvērtie dati ir tikai privātie meži — 73 nogabali, 1,2 % no
  analizētā meža AOI; **0 no 15 stresa poligoniem** ir nogabalos ar datiem (2026:
  #25 2,8 km, #26 207 m, #31 225 m līdz tuvākajam). #31/#34 pārbaude abām
  ģeometrijām nav iespējama (vecā #34 tikai par dažiem pikseļiem lielāka).
  LVM publiskajā nogabalu kopā sugu sastāva nav, saite atgriež 404.
  → **Vajadzīgi LVM taksācijas dati** valsts mežam (shēma konfigurējama).

**Lauka pārbaude 2026** (`fieldcheck.py`, `field-prepare`, `field-import`,
instrukcija `docs/LAUKA_PARBAUDE.md`): F01–F03 = stresa poligoni #25, #26, #31;
F04 = augstākā riska cirtes mala T004 (risks 0,81); F05 = automātiski izvēlēta
kontroles vieta (vesels skujkoku mežs, z mediāna −0,05, bāzes NDVI 0,783 / CRSWIR
0,826 pret mērķu 0,783 / 0,82). GPKG + KML (poligoni un punkti), CSV veidlapa
(`;`, UTF-8) ar pazīmēm (urbumu milti, sveķi, ieejas atveres, mizas lobīšanās,
vainaga krāsa, foto, secinājums); ielasīšana ar pārbaudēm → references `validate`
un prognozes/novērojuma tabula. Poligonu ID var mainīties, ja `detect` tiek
pārrēķināts; lauka paketē ģeometrijas ir saglabātas.

**Nākamie soļi:**
1. LVM teritorija, sanitāro ciršu references un taksācijas dati (sugu sastāvs).
2. Lauka / drona pārbaude F01–F05, veidlapas ielasīšana.
3. Platformu pārbaude atkārtoti 2026. gada beigās.

**Atmests (komandas lēmums):** 7. posma notebook, ceļu efekta bootstrap, CDSE avots,
`detect` paātrināšana.

---

## 22. Konfigurācijas parametru atsauce

Noklusējumi (`src/s2forest/config.py`). Obligāti: `run_name`, `aoi`, `time.monitor_year`.

**time:** `baseline_years` 3, `season_start` 05-01, `season_end` 09-30.

**data:** `sources` [earthsearch/sentinel-2-c1-l2a, planetary/sentinel-2-l2a],
`crs` EPSG:3059, `resolution` 10, `context_resolution` 60, `max_scene_cloud_cover` 95,
`min_valid_fraction` 0,6, `workers` 4, `reflectance_resampling` bilinear.

**masking:** `invalid_scl` [0,1,3,8,9,10,11], `cloud_buffer_m` 20;
`haze`: `enabled` true, `b02_threshold` 0,02, `doy_window` 30, `min_ref_obs` 3,
`last_obs_scene_share` 0,10.

**forest_mask:** `source` hrl_dlt_2018, `classes` [2], `min_summer_ndvi` 0,65,
`summer_start` 06-01, `summer_end` 08-31, `seasonal_range_index` ndvi,
`max_seasonal_range` 0,22.

**linear_features:** `enabled` true, `buffer_m` 20, `highway_types` (motorway … track,
service, *_link), `include_waterways` false (ditch, drain, canal),
`include_power_lines` false, `elongation_threshold` 3,0, `near_road_m` 30,
`control_ring_m` 100.

**indices:** [ndvi, ndre, ndmi, crswir].

**anomaly:** `baseline_method` harmonic, `harmonics` 1, `robust_iterations` 5,
`huber_k` 1,345, `z_threshold` 2,5, `persistence` 2, `persistence_min_days` 7,
`prev_autumn_start` 08-15, `onset_prev_autumn_z` 1,25, `doy_window` 30,
`min_baseline_obs` 5, `mad_floor` {ndvi 0,035, ndre 0,034, ndmi 0,047, crswir 0,061},
`primary_index` crswir, `min_confirming` 1, `min_area_ha` 0,1, `cut_ndvi_max` 0,5,
`cut_ndvi_drop` 0,25, `cut_ndmi_drop` 0,15, `status_min_obs` 2;
`normalization`: `enabled` true, `buffer_m` 5000, `min_forest_fraction` 0,5,
`min_pixels` 50.

**targets:** `statuses` [new, persistent], `cut_edge_enabled` true,
`cut_edge_width_m` 30, `cut_edge_years` 2, `cut_edge_min_cut_ha` 0,3,
`cut_edge_min_area_ha` 0,05, `risk_weights` {orientation 0,4, freshness 0,3,
conifer 0,3}, `risk_peak_azimuth` 225, `mission_max_area_ha` 30,
`mission_buffer_m` 20, `mission_max_gap_m` 500, `max_missions` 10.

**reference:** `path`, `id_field`, `date_field`, `reason_field`, `reason_values`,
`description`, `match_buffer_m` 10, `max_date` (noklusēti nākamā gada 31. marts).

**stands:** `path`, `id_field` (id; rezerve kadastrs-kvart-nog), `species_fields` s10…s14, `basal_area_fields` g10…g14, `tree_count_fields` n10…n14, `age_fields` a10…a14, `forest_type_field` mt, `spruce_values` [3, 15] (informatīvi).

---

## 23. Commit vēsture

| Commit | Laiks | Saturs |
|---|---|---|
| `96c2885` | 2026-09-30 20:54 | 0.–1. posms: skelets, STAC ieguve ar kešu, harmonizācija, SCL maska |
| `98317f7` | 2026-09-30 23:11 | 2.–3. posms: indeksi, dūmakas tests, meža maska, anomālijas, poligoni |
| `2f5d562` | 2026-09-30 23:47 | 3. posma pabeigšana un 5. posms: statuss, drona mērķi, validācija, `run` |
| `b667d9f` | 2026-10-01 00:44 | mērķu prioritizācija, misijas, 2025 ziemas ciršu validācija, HTML atskaite (6. posms) |
| `be50163` | 2026-10-01 01:02 | harmoniskā bāze + sezonālās nobīdes diagnostika |
| `87bc2d2` | 2026-10-01 01:06 | OSM ceļu buferis + `linear_feature` |
| `a16e7c4` | 2026-10-01 01:12 | sezonālās amplitūdas maska (NDVI) |
| `ff69b1b` | 2026-10-01 01:23 | starpgadu / platformu pārbaude (bez korekcijas) |
| `4363bf8` | 2026-10-01 10:39 | metodes teksts no faktiskās konfigurācijas |
| `06b960b` | 2026-10-01 10:39 | noturība ≥ 7 dienas, gaidošie skrējieni, iepriekšējā rudens karogs |
| `19cba28` | 2026-10-01 10:40 | ceļu bagātinājuma tests, `near_road` |
| `fdaf3d5` | 2026-10-01 11:27 | atskaite: ID nolasīšana no CSV |
| `7ebc630` | 2026-10-01 11:37 | kontroles gredzens kā standarta izvade; `near_road` informatīvs |
