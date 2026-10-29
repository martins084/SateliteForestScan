# MežaSargs — riska modeļa un S2 plūsmas uzlabojumu plāns (2. posms)

Datums: 2026-10-22. Tikai plāns — kods nav rakstīts. **[P]** = pārbaudīts (fails / komanda / atvērts avots, sk.
[RM_0_STAVOKLIS.md](RM_0_STAVOKLIS.md), [RM_1_DATU_PARBAUDE.md](RM_1_DATU_PARBAUDE.md), [DATU_AVOTI.md](DATU_AVOTI.md)),
**[N]** = pieņēmums vai novērtējums. Jūsu 2. posma lēmumi ir iestrādāti; atvērtie jautājumi — 2.13.

---

## 2.1 Mērķis, jautājumi, ierobežojumi

**Modelis atbild uz jautājumu:** kurās skujkoku (vēlāk — egļu) meža 30 m šūnās nākamajā gadā t ir lielākā
varbūtība, ka notiks audzi nomainošs **vēja / mizgraužu** traucējums (EFDA klase 1), ņemot vērā tikai informāciju
līdz gada t−1 beigām. Rezultāts — relatīvs riska rangs (karte, top 5/10 % šūnu), ne absolūta varbūtība, kamēr nav
kalibrēts pret LVM datiem.

**Papildu jautājumi:** kuras pazīmes (malas, iepriekšējie traucējumi, sausums, paaudžu skaits, augstums, reljefs)
saistītas ar risku; vai modelis pārspēj vienkāršas bāzlīnijas laikā un telpā.

**Ko modelis NEspēj (no 1. posma) [P, ja nav citādi]:**
1. **Atšķirt vējgāzes no mizgraužiem** — EFDA apvieno klasi „vējš / mizgrauži“; sanitārā cirte pēc mizgraužu
   bojājuma EFDA ir „harvest“ (ESSD 2025). Latvijā klase 1 var būt **galvenokārt vējgāzes** [N] — pārbaude 2.5.
2. **Noteikt zemas intensitātes / sākotnēju mizgraužu bojājumu** — EFDA omission galvenokārt ne-audzi nomainošiem
   traucējumiem; MMU 0,27 ha; gada nobīde līdz ±1 gadam (traucējums pēc vasaras kompozīta → nākamais gads).
3. **Prognozēt atsevišķas audzes egļu īpatsvaru** — atvērtas egles daļas kartes nav; Picea varbūtības karte piesātināta.
4. **Dot aģenta kartes precizitāti** — EFDA autori to nesniedz; modeļa kļūdas vējš/mizgrauži 10,5 % / 19,1 %.
5. Darbojas 30 m mērogā, ne nogabala vai koka līmenī; Kalsnavas detalizācija (10 m S2/S1) tikai demonstrācijai.

---

## 2.2 Arhitektūra

**Jauna pakotne `src/mezasargs_risk/`** (nosaukums — priekšlikums), CLI `mezasargs-risk` ar apakškomandām:

| Komanda | Ko dara | Izvade |
|---|---|---|
| `labels` | EFDA ievade + **robežu pārbaude** + v2.1.1 krustpārbaude; vēlāk LVM | etiķešu rastri / tabula |
| `weather` | Open-Meteo `era5` dienas dati ERA5 režģa mezgliem, kešs | zarr |
| `phenology` | RITY-2 (galvenais), PHENIPS-Clim (jutīgums) gadiem / mezgliem | zarr + CSV |
| `drought` | P − ET0, SPEI veģetācijas sezonai | zarr |
| `features` | statiskie un gada pazīmju slāņi uz EFDA 30 m režģa (blokos) | COG / zarr |
| `table` | apmācības tabula (izlase), noplūdes pārbaudes | npz / CSV.gz |
| `train`, `validate` | bāzlīnijas, modelis, telpiskā / laika validācija | modeļi, metrikas, attēli |
| `predict`, `report` | riska karte gadam t, Kalsnavas demonstrācija, atskaite | COG, GPKG, HTML/MD |

**Konfigurācija:** YAML (pydantic, kā s2forest / s1windthrow), fiksēti seed, kešs `cache/rm/`, `run_metadata.json`
ar datu versijām (Zenodo DOI, Open-Meteo modelis un vaicājuma datums, CHMv2 ceļš, LĢIA faila Last-Modified) un koda
commit.

**s2forest un s1windthrow izmantošana bez izmaiņām:** tikai lasīšana (`suspects_*.gpkg`, `forest_mask.tif`,
indeksu rastri) un importējamas funkcijas (`s2forest.aoi`, `s2forest.io`, `s2forest.linear`). Kalsnavas
demonstrācijā riska karte tiek pārprojicēta uz EPSG:3059 un apvienota ar S2 suspects (2.9).

**EFDA ievades aizsardzība (1. lēmums):** `labels` vienmēr pārbauda, vai rastra robežas (pēc pārveides uz WGS84)
pārklāj Latvijas kontūru (≥ 95 % Latvijas meža) un vai Kalsnavas kontrolpunkts ir iekšā; ja nē — kļūda ar ziņojumu,
neatkarīgi no faila nosaukuma. Konfigurācijā ceļš uz arhīvu un dalībnieku, kā arī gaidāmās robežas.

### Zaru stratēģija (9. lēmums — izvēle jūsu)

Fakts [P]: vēsture ir lineāra: `master` (76aea2f) → `feat/s1-windthrow` (+7) → `feat/s1-earlysignal` (+2, satur visu
S1); nekas nav GitHub ārpus `master`.

| Variants | Plusi | Mīnusi |
|---|---|---|
| **A. Jauns zars no `master`** | tīrs sākums; riska modelis neatkarīgs no S1 eksperimentiem | S1 kods un dokumenti (S1_KOPSAVILKUMS, DATU_AVOTI konteksts) nav pieejami; vēlāk divi neatkarīgi zari jāapvieno |
| **B. Jauns zars no `feat/s1-earlysignal`** | viss pieejams uzreiz | riska modelis „mantos“ neapvienotus S1 zarus; `master` arvien vairāk atpaliek |
| **C. Vispirms `feat/s1-earlysignal` → `master` (fast-forward, bez konfliktiem), tad jauns zars `feat/risk-model` no `master`** (ieteikums) | viena lineāra vēsture; S1 iesaldēts ar tagiem; s2forest noklusējuma uzvedība nemainās (S1 ir atsevišķa pakotne); dokumenti vienuviet | `master` saņem eksperimentālu S1 kodu un `pyproject.toml` / `uv.lock` izmaiņas (CLI ieraksts, `requests` lock); push uz GitHub — atsevišķs jūsu lēmums |

RM_0, RM_1, DATU_AVOTI, EFDA_zinojums un šis plāns tiks commitoti izvēlētajā zarā.

---

## 2.3 Telpiskā vienība, mērogs, apjoms

**Vienība:** EFDA 30 m režģa šūna (EPSG:3035), tikai EFDA meža zemes lietojuma maskā **un** HRL DLT 2018 skujkoku
klasē (ar pārprojicēšanu uz 30 m kā skujkoku daļu šūnā). Kalsnavas demonstrācija — tie paši 30 m + S2/S1 10 m slāņi.

**Fakti Latvijai [P, 1. posma faili]:** EFDA v3.0 Latvijas rastrs 8 911 × 14 811 = 132 M pikseļu; mežs 43,1 M pikseļu
(~3,88 M ha); klase 1 (1985–2024, apkopots) 1,39 M pikseļu, jaukti 0,35 M. Dators: RAM 15,7 GB, **brīvi 5,0–6,7 GB**;
disks brīvi 576 GB; 10 kodoli.

**Apjoma novērtējums [N, aprēķins]:**

| Elements | Apjoms | Laiks |
|---|---|---|
| EFDA LV (bez varbūtības slāņa) | ~190 MB lejupielāde (no 972 MB arhīva, range) | minūtes |
| Gada slānis uz pilna LV režģa | int16 264 MB, float32 528 MB → apstrāde **blokos 2048 × 2048** (~4 M px; 30 pazīmes float32 ≈ 0,5 GB RAM) | — |
| CHMv2 → 30 m agregāts (vid., p90, daļa > 5 m) | ~140 flīzes × 0,22 GB ≈ 30 GB pagaidu lejupielāde, rezultāts ~0,5 GB | ~1–2 h (atkarīgs no tīkla) |
| LĢIA DTM 20 m | 399 MB 7z → teksta punkti → rastrs; TWI / slīpums 30 m ~0,5 GB | stundas |
| ERA5 režģis LV + 0,25° buferis | ~350 mezgli × 40 gadi × ~8 mainīgie ≈ 40 M vērtības (~160 MB) | ~350 Open-Meteo izsaukumi (< 10 000/dienā) |
| Apmācības tabula | visi pozitīvie (vid. ~35 tk./gadā, 1,39 M / 40 [N]) + negatīvo izlase 1:10 → ~0,4 M rindas/gadā; 2000–2024 ≈ 10 M rindu × 30 pazīmes ≈ 1,2 GB | modeļa apmācība: minūtes–desmitiem minūšu (HGB) |
| Prognoze visam LV gadam | blokos, ~43 M meža šūnu | ~10–30 min [N] |

**Secinājums:** Latvijas mērogs ir iespējams ar bloku apstrādi un negatīvo izlasi; pilna tabula (43 M × 25 gadi) nav
iespējama ar 5 GB RAM. **Rezerves variants**, ja kāds solis izrādās par smagu: 4–6 reprezentatīvi 50 × 50 km bloki,
atlasīti pēc **pārbaudāmiem kritērijiem** (EFDA klases 1 biežums, HRL skujkoku daļa, ģeogrāfiskais izkliedējums pa
reģioniem), nevis ar roku.

---

## 2.4 Laika dizains (bez noplūdes)

Prognoze gadam **t** tikai no informācijas līdz **31.12.(t−1)**. Apmācības gadi t = 2000…2024 (pazīmēm vajag ≥ 15
iepriekšējos EFDA gadus un 1985–).

| Pazīme / etiķete | Laika robeža | Piezīme |
|---|---|---|
| **Etiķete** | EFDA `disturbance_agent` gadā t = 1 | gada nobīde ±1 (EFDA kompozīta datums) — sk. riskus |
| Iepriekšējie traucējumi (attālums, platība, aģents) | EFDA gadi ≤ t−1 | |
| Malas (attālums līdz ne-mežam / cirtei, malas vecums) | EFDA cirtes gadi ≤ t−1 | malas vecums = t − cirtes gads |
| Laikapstākļi, sausums, fenoloģija | sezonas ≤ t−1 (kopsavilkumi t−1, t−2, vidējie) | ziemas mēnešus t neizmanto |
| Koku augstums CHMv2 | attēli 2018–2019 [P] | **noplūdes risks:** t ≤ 2019 šūnām, kas traucētas t…2019, augstums jau rāda pēc-traucējuma stāvokli → izmanto tikai t ≥ 2020 vai izslēdz šīs šūnas (pārbaude 2.8) |
| HRL DLT 2018 | 2018 | tas pats risks t ≤ 2018 → skujkoku maska pēc stāvokļa pirms t (EFDA traucējumi pirms 2018 izslēgti) |
| Picea varbūtība | periodi 2000–2020 [P] | izmanto periodu, kas beidzas ≤ t−1 |
| Reljefs (DTM 2013–2019) | statisks | reljefs nemainās |

---

## 2.5 Etiķetes

- **Pozitīvie:** EFDA v3.0 `disturbance_agent` = 1 gadā t (Latvijai `Lithuania.zip`, ar robežu pārbaudi); jaukti
  (aggregated = 4) — atsevišķi, nav pozitīvi pēc noklusējuma.
- **Negatīvie:** skujkoku meža šūnas bez jebkāda EFDA traucējuma gadā t.
- **Izslēgšana:** šūnas, kurās EFDA reģistrējis traucējumu (jebkurš aģents) gados t−k…t−1 (k = 5 [N], kamēr audze
  nav atjaunojusies — jūsu lēmums); šūnas ar cirti gadā t (aģents 3) — ārpus kopas (nav ne pozitīvas, ne negatīvas).
- **Krustpārbaude v2.1.1:** 1985–2023 gadu un aģentu sakritība ar v3.0 pa gadiem (tabula; ja būtiska atšķirība — ziņot).
- **Pārbaude, vai klase 1 Latvijā ir galvenokārt vējgāzes [N → pārbaudīt 5. posmā, tikai pārbaudāmi avoti]:**
  1. gadu sadalījums pret **dokumentētām vētrām** no pārbaudāmiem avotiem (FORWIND un DEFID2 datubāzes — tās EFDA
     autori izmantoja apmācībai [P ESSD]; LVĢMC / VMD paziņojumi) — vispirms jāpārbauda, vai tajos ir Latvijas notikumi;
  2. sakarība ar **sausuma gadiem** (mūsu ERA5 P − ET0 / SPEI, nobīde 0–2 gadi; mizgraužu uzliesmojumi seko sausumam [N
     — avots jāatver]);
  3. **plankumu forma un izmērs** (vējgāzes — lielāki, kompaktāki gada plankumi; mizgrauži — izkliedēti) no EFDA
     rastra; tikai aprakstoši;
  4. Silava / VMD publiski minētie mizgraužu gadi (2023–2025, ziņas [P]) — tikai kvalitatīvi, jo EFDA beidzas 2024.
- **LVM sanitārās cirtes (vēlāk):** ievade kā etiķešu avots `lvm_sanitary` (poligons, datums, iemesls) → rastrs 30 m;
  mizgraužu etiķete gadā t, ja ciršanas iemesls = mizgrauži (gada piešķiršanas noteikums — jūsu lēmums, piem., cirte
  līdz 31. jūlijam → t, citādi t+1). Etiķešu tabulai ir kolonna `source`; LVM aptvertajās teritorijās LVM etiķete ir
  galvenā, EFDA — papildu; validācija primāri uz LVM. Arhitektūra: kopēja etiķešu shēma
  (`cell_id, year, label, source, confidence`), tāpēc jauni avoti nemaina pazīmes un modeļus.
- **Kvalitātes riski:** sanitārā cirte = „harvest“ (mizgrauži pazūd); gada nobīde ±1; MMU 0,27 ha; ziemeļu
  commission kļūdas; v3.0 un v2.1.1 algoritmu atšķirība; failu sajaukums (pārbaude ieviesta).

---

## 2.6 Pazīmes

| Pazīme | Avots | Aprēķins | Laiks | Gaidāmā ietekme | Literatūras pamatojums |
|---|---|---|---|---|---|
| Skujkoku daļa šūnā | HRL DLT 2018 [P] | 10 m → 30 m daļa | 2018 | + | [N: avots jāatver] |
| Egles iespējamība | Picea abies 30 m [P] | varbūtība (piesātināta) | periods ≤ t−1 | vāja | Bonannella u. c. 2022 [P DOI] |
| Koku augstums (vid., p90, daļa > 5 m) | CHMv2 [P] | 1,2 m → 30 m | 2018–19 | + (vecākas, augstākas audzes) | [N: avots jāatver] |
| Attālums līdz meža malai, malas vecums un orientācija | EFDA (cirte ≤ t−1) + meža maska | attāluma transformācija; azimuts uz malu | ≤ t−1 | + svaigām D/DR malām | S1 diagnostika: mērķi ~2× tuvāk malai [P, Kalsnava]; literatūra [N] |
| Attālums līdz iepr. vēja/mizgraužu traucējumam, platība 500 m / 2 km rādiusā | EFDA klase 1 ≤ t−1 | attālums, platība logā | t−1, t−2…t−5 | + | EFDA autoru aģentu modelis lieto ainavas pazīmes [P ESSD] |
| Paaudžu skaits, izlidošanas DOY (t−1), relatīvā termālā summa | RITY-2 uz ERA5 `era5` | Ogris 2020 vien. 4–15 [P] | t−1 | + | Ogris 2020 [P] |
| Sausums: P − ET0 (IV–IX), SPEI-3/6 (t−1, t−2) | Open-Meteo `era5` [P] | summa / standartizācija | t−1, t−2 | + | Vicente-Serrano 2010 [P DOI, PDF 403] |
| Vēja ekspozīcija (opc.) | ERA5 `wind_gusts_10m_max` [P API nosaukums] | maks. brāzmas t−1 | t−1 | + | [N] |
| Slīpums, TPI, TWI | LĢIA DTM 20 m [P] | 30 m; TWI — sk. 6. lēmumu | statisks | ± | [N] |
| S2/S1 indeksi (opc., tikai Kalsnava) | s2forest / s1windthrow izvade [P] | z, statuss | ≤ t−1 | demonstrācijai | — |

Kur „[N: avots jāatver]“ — 4.–6. posmā pirms pazīmes ieviešanas atvēršu primāro avotu vai pazīmi atzīmēšu kā
neatbalstītu.

**Laikapstākļu režģis (3. lēmums):** Open-Meteo `models=era5` (ne `best_match`, ne `era5_land`). ERA5 0,25° mezgli
pār Latviju + 1 šūnas buferis (~350 mezgli [N]); vaicājums ar mezgla koordinātām (Open-Meteo atgriež tuvāko režģa
punktu — saglabā atgriezto lat/lon); 30 m šūna saņem **tuvākā mezgla** vērtības (alternatīva — bilineāra interpolācija
gada kopsavilkumiem; izvēle 2.13). Augstuma korekcija netiek veikta (Latvija līdzena [N]). ERA5-Land caur CDS — tikai
opcija nākotnē.

**Fenoloģija (4. lēmums):** RITY-2 ar Ogris 2020 parametriem; ievadē ERA5 dienas min/vid/maks. INCA→meža gaisa
korekcijas (vien. 1–3) ir Slovēnijas kalibrācija — vai tās lietot ERA5 datiem, ir jautājums 2.13. PHENIPS-Clim 1. tabulas
parametri — tikai jutīguma salīdzinājumam (izlidošanas datums, paaudžu skaits); tā vienādojumu forma no PDF nav
nolasāma [P] → jutīgumam varu izmantot tikai sliekšņu parametrus (Tsw_sum 100 dd virs 5,12 °C no 1. janvāra,
Tfly_min 16,11 °C), nevis pilno modeli. Saprāta pārbaude: Silava „aktīva izlidošana 20. aprīlī 2023“ (ziņas [P]).

**Egle (5. lēmums) — varianti:**

| Variants | Plusi | Mīnusi |
|---|---|---|
| E1. Tikai HRL skujkoki + Picea varbūtība kā vāja pazīme | gatavs, viegls | egle ≠ priede; Picea piesātināta |
| E2. + CHMv2 augstums / struktūra | atvērts, 1,2 m | augstums nav suga |
| E3. S2 spektrālā egle/priede klasifikācija (pavasara / vasaras kompozīti), apmācīta uz **MVR atvērtajiem nogabaliem** (valdošā suga; privātie meži) | atvērts, Latvijas etiķetes | ievērojams darbs; MVR tikai privātie meži; S2 kompozīti visai LV (lejupielāde, laiks [N]) |
| E4. LVM taksācija (pēc apstiprināšanas) | labākā | nav pieejama līdz novembrim |

**Ieteikums līdz LVM datiem:** E1 + E2 riska modelim; E3 — atsevišķs, neobligāts pētnieciskais uzdevums pēc 7. posma;
E4 — kad pieejams, kā pazīme un etiķešu filtrs.

---

## 2.7 Modeļi un atkarības

- **Bāzlīnijas:** B0 — tikai „attālums līdz pagājušā gada vēja/mizgraužu traucējumam“ (rangs); B1 — loģistiskā regresija
  ar 3–5 pazīmēm (attālums, malas, sausums t−1).
- **Sarežģītākais modelis:** gradient boosting. **Ieteikums:** vispirms `sklearn.ensemble.HistGradientBoostingClassifier`
  (jau scikit-learn, nav papildu atkarības); LightGBM tikai, ja HGB ir par lēnu vai sliktāks pie vienādiem datiem.
- **Minimālais atkarību saraksts (8. lēmums):**
  1. **scikit-learn** (BSD-3) — obligāti: loģistiskā regresija, HGB, `permutation_importance`, metrikas
     (PR-AUC, ROC-AUC, kalibrācija), grupu krosvalidācija.
  2. 7z atarhivēšana (6. lēmums): **py7zr** (LGPL-2.1+) *vai* sistēmas **7-Zip** (bez Python atkarības, jāinstalē jums).
  3. TWI: `pysheds` / `richdem` ir GPL-3 [P]; `whitebox` (MIT) lejupielādē izpildāmus failus darbības laikā [P apraksts
     nav atvērts — N] → **nav ieteicams**; alternatīva — D8 plūsmas akumulācija pašu kodā ar **numba** (BSD) vai bez
     TWI (tikai slīpums un TPI ar scipy). Izvēle 2.13.
  4. **Nav ieteicams šobrīd:** LightGBM, SHAP, xgboost, xclim / climate-indices / spei (SPEI var aprēķināt ar scipy
     log-logistisko sadalījumu, ja apstiprināsiet metodes avotu), cfgrib/cdsapi.

---

## 2.8 Validācija

- **Telpiskā bloku krosvalidācija:** bloki uz 30 m režģa; izmērs — pēc etiķešu / atlikumu telpiskās korelācijas garuma
  (empīriska semivariogramma, kā S1 diagnostikā), ne mazāks par korelācijas garumu; 5 locījumi, bloki nejauši pa
  locījumiem ar seed.
- **Laika validācija:** apmāca t ≤ 2019, testē 2020–2024 (EFDA v3 beidzas 2024 [P]); papildus „rolling origin“.
- **Metrikas:** PR-AUC (galvenā, retā klase), ROC-AUC, Brier / kalibrācijas līkne, **lift** augšējos 5 % un 10 % riska
  šūnu, atklāto pozitīvo daļa top-k; visas ar bootstrap intervāliem pa blokiem.
- **Salīdzinājums** ar B0, B1 tajos pašos locījumos.
- **Pazīmju nozīmīgums:** permutation importance uz testa locījumiem (SHAP — tikai ar jūsu atļauju).
- **Noplūdes pārbaudes saraksts:**
  1. neviena pazīme neizmanto datus pēc 31.12.(t−1) (automātisks tests uz pazīmju metadatiem);
  2. CHMv2 un HRL ietekme t ≤ 2019 / 2018 (rezultāts ar / bez šīm šūnām);
  3. etiķetes gada nobīde: rezultāts ar etiķeti t un t ∪ t+1;
  4. negatīvo izlase nav atkarīga no etiķetes nākotnē;
  5. telpiskā tuvuma noplūde (bloku izmērs; „buffer“ starp apmācības un testa blokiem);
  6. normalizācijas / skalēšanas parametri tikai no apmācības locījuma;
  7. „placebo“ — modelis uz nejauši permutētām etiķetēm (gaidāms PR-AUC ≈ pozitīvo daļa).

---

## 2.9 Integrācija ar agrīno brīdināšanu (s2forest)

- Riska karte (gads t, 30 m) → Kalsnavā pārprojicēta uz EPSG:3059 10 m režģi un agregēta uz s2forest poligoniem un drona
  mērķiem kā **informatīvs atribūts** `risk_percentile` (iesaldētā s2forest prioritāte nemainās).
- **Lauka pārbaudes prioritāte (jauns, atsevišķs saraksts):** S2/S1 detekcijas × riska procentile → kategorijas
  („detekcija augstā riskā“, „detekcija zemā riskā“, „augsts risks bez detekcijas — profilaktiska pārbaude“).
- **Gala lietotājam:** GeoPackage (riska karte kā rastrs + poligonu slānis), CSV ar top mērķiem (WGS84), HTML/MD atskaite
  ar karti, metodes aprakstu no konfigurācijas, ierobežojumiem (2.1) un validācijas tabulu.

---

## 2.10 S2 plūsmas uzlabojumi (katrs — jauna opcija; noklusējums = `v0.2-kalsnava`)

**Regresijas pamats visiem:** „zelta“ tests — `s2forest detect` uz kešotiem Kalsnavas datiem ar noklusējuma
konfigurāciju; poligonu GPKG un anomāliju rastriem jābūt **identiskiem** `v0.2-kalsnava` izvadei (heši / `array_equal`).
Testam jābūt stabilam (sk. 3. punktu) — tāpēc nestabilos testus labo pirmos.

1. **Amplitūdas maska un jauktas audzes (S1_INVENTARIZACIJA 10.):** jauna opcija
   `forest_mask.amplitude_scope: all | stress_only` (noklusējums `all`). `stress_only`: amplitūdas maska attiecas tikai
   uz stresa noteikšanu; cirtes (audzi nomainoša izmaiņa, NDVI/NDMI kritums) tiek noteiktas arī maskas kods 5 pikseļos.
   Izpēte pirms: cik ha / poligonu mainītos Kalsnavā 2025, 2026 (pirms/pēc tabula), cut_like #1 kā testa gadījums.
2. **Attālums līdz meža malai:** jauns informatīvs atribūts `dist_to_forest_edge_m` un `edge_share_20m` stresa / cirtes
   poligoniem un drona mērķiem (no meža maskas); diagnostikas tabula (poligoni pret nejaušiem meža diskiem, kā S1).
   Detekcija nemainās.
3. **Nestabilie testi (S1_INVENTARIZACIJA 9.):** atkārtot pilno `pytest` cilpā (≥ 20×), noteikt cēloni (hipotēze —
   `ThreadPoolExecutor` + zarr keša raksti / kešs index.json [N]), labot tā, lai detekcijas rezultāti nemainās;
   pierādījums — 20 zaļas palaišanas pēc kārtas + zelta tests.
4. **Ortofoto galda pārbaude (7. lēmums, bez attēlu saglabāšanas):** komanda, kas sagatavo **QGIS projektu** (`.qgs` XML,
   bez jaunas atkarības) ar: LĢIA ortofoto WMS slāni (URL un piekļuves dati — jūs ievadāt QGIS pēc licences; projektā
   tikai vietturis, bez paroles), suspects / drona mērķu poligoniem un **CSV marķēšanas veidlapu** (`merka_id`,
   vērtējums: koki stāv / koki gulus / izcirsts / nav skaidrs, piezīmes, datums, vērtētājs). Attēli netiek saglabāti; QGIS
   tikai rāda WMS. Plus `field-import` stila ielasīšana marķējumam.

---

## 2.11 Testēšanas plāns

- **Vienību testi ar sintētiskiem datiem:** EFDA robežu pārbaude (pareizs / sajaukts / pārdēvēts fails), etiķešu un
  izslēgšanas loģika, laika robežas (neviena pazīme pēc t−1), malu attālums un vecums, bloku krosvalidācija (bloki
  nepārklājas), izlase (seed, proporcijas).
- **Fenoloģija pret publicēto:** RITY-2 vienādojumu īpašības — piemēram, (8) vienādojuma vērtība pie BT = DT_U = 38,9 °C
  ir ≈ 0 (mans aprēķins: 0,014), pie BT = T_O = 30,4 °C 21,67 pret lineāro 22,1 [P aprēķins no publicētajiem
  koeficientiem]; sintētiska temperatūras rinda ar zināmu Σ(Imax − 8,3) → izlidošanas diena pēc (10);
  paaudžu skaitīšana ar 0,6 slieksni. Salīdzinājums ar publicētiem skaitliskiem piemēriem — tikai, ja tādi atrodami
  atvērtos avotos (RITY rakstā ir tikai grafiks [P]).
- **Laikapstākļi:** Open-Meteo atbildes shēma, trūkstošās vērtības, atgrieztā režģa punkta saglabāšana (ar ierakstītu
  testa atbildi, bez tīkla).
- **Regresija:** s2forest zelta tests (2.10); s1windthrow testi nemainās; visi esošie 95 testi.
- **Tīkla testi** (atzīmēti `network`, pēc izvēles): EFDA Zenodo metadati, Open-Meteo, CHMv2 vienas flīzes logs.

---

## 2.12 Posmu secība (katrs ar apstāšanos)

| Posms | Rezultāts | Apjoms [N] |
|---|---|---|
| 3. S2 uzlabojumi (2.10): vispirms nestabilie testi un zelta tests, tad opcijas 1, 2, QGIS projekts | kods + testi + Kalsnavas pirms/pēc tabula | 2–3 darba sesijas |
| 4. Laikapstākļi, RITY-2, sausums; Kalsnava + Latvijas ERA5 režģis 2018–2026 (un 1985– pazīmēm) | moduļi, testi, karte / tabula paaudzēm un sausumam | 2 sesijas; dati ~160 MB |
| 5. EFDA ievade (robežu pārbaude, v2.1.1 krustpārbaude) un **aprakstošā** analīze; klases 1 pārbaude (2.5) | atskaite ar attēliem | 1–2 sesijas |
| 6. Pazīmju slāņi (CHMv2, DTM, malas, iepr. traucējumi, klimats) un apmācības tabula + noplūdes testi | slāņi, tabula | 2–3 sesijas; CHMv2 ~30 GB pagaidu |
| 7. Bāzlīnijas, HGB, telpiskā + laika validācija | metrikas, attēli | 1–2 sesijas |
| 8. Integrācija, Kalsnavas riska karte, atskaite `docs/RM_KOPSAVILKUMS.md` | karte, atskaite | 1 sesija |

---

## 2.13 Riski un atvērtie jautājumi jums

**Riski [N]:** (R1) EFDA klase 1 Latvijā var būt gandrīz tikai vējgāzes → modelis prognozē vējgāžu, ne mizgraužu risku;
(R2) gada nobīde un MMU vājina sakarības ar t−1 laikapstākļiem; (R3) CHMv2/HRL laika noplūde; (R4) ERA5 0,25° ir rupjš
mikroklimatam; (R5) RITY-2 Slovēnijas kalibrācija var neatbilst Latvijai; (R6) 5 GB brīvās RAM ierobežo bloku izmēru;
(R7) LĢIA WMS licence var nepieļaut arī lietojumu galda pārbaudei — jāizlasa līgums; (R8) EFDA v3 failu nosaukumus
autori var labot — robežu pārbaude to uztver, bet konfigurācijā jāmaina ceļš.

**Jautājumi (numurēti):**
1. **Zars:** A, B vai C (2.2)? Ja C — vai push uz GitHub?
2. **Etiķetes:** vai jauktos aģentus (4) izslēgt vai skaitīt kā pozitīvus? Cik gadu (k) pēc jebkura traucējuma šūna
   izslēgta no negatīvajiem (piedāvājums k = 5)?
3. **Apmācības gadi:** 2000–2024 (ieteikums) vai šaurāk (piem., 2010–2024, lai mazinātu CHMv2/HRL noplūdi)?
4. **Laikapstākļu piesaiste:** tuvākais ERA5 mezgls (ieteikums) vai bilineāra interpolācija?
5. **RITY-2 ar ERA5:** lietot INCA→meža gaisa korekcijas (vien. 1–3) kā publicētas, vai ERA5 temperatūru tieši kā meža
   gaisa temperatūru (un 1–3 tikai jutīgumam)?
6. **7z:** `py7zr` atkarība vai sistēmas 7-Zip?
7. **TWI:** numba + paša D8, vai iztikt ar slīpumu un TPI (bez TWI)?
8. **Atkarības:** apstiprināt scikit-learn (un, ja 7. jautājumā — numba; ja 6. — py7zr)?
9. **SPEI:** vai drīkstu SPEI metodi balstīt uz sekundāru atvērtu aprakstu (piem., `spei` / `climate-indices` pakotņu
   dokumentācija), jo oriģinālraksta PDF neatvērās, vai lietot tikai P − ET0?
10. **Egle:** apstiprināt E1 + E2 līdz LVM datiem; vai E3 (S2 egle/priede ar MVR) iekļaut kā neobligātu uzdevumu?
11. **Reģionu rezerves variants:** vai pieņemams 4–6 blokos 50 × 50 km, ja Latvijas mērogs izrādās par smagu?
12. **LVM etiķešu gada noteikums:** sanitārā cirte līdz 31. jūlijam → bojājums gadā t, vēlāk → t+1 (priekšlikums) vai cits?

---

## 2.14 Apstiprinātie lēmumi un labojumi (lietotājs, 2026-10-22)

Plāns apstiprināts ar šiem labojumiem; tie ir **prioritāri** pār iepriekšējo tekstu, kur tie atšķiras.

**Labojumi:**
- **L1 (selekcijas kļūda):** analīzes kopa = **EFDA meža zemes lietojuma maska**, nevis HRL 2018 skujkoki (pirms 2018
  traucētās šūnas HRL 2018 var vairs nerādīt kā skujkokus → pozitīvie izkristu traucējuma dēļ). HRL skujkoku daļa — pazīme;
  skujkoku apakškopa — papildu variants.
- **L2 (CHMv2):** galvenais modelis 2000–2024 **bez CHMv2**; variants ar CHMv2 tikai t ≥ 2020 (telpiskā CV šajos gados).
- **L3 (gada nobīdes pseidonoplūde):** viena notikuma bojājumi var sadalīties t−1 un t. Jutīguma variants: iepriekšējo
  vēja/mizgraužu traucējumu pazīmes no **t−2**; metrikas atsevišķi šūnām **> 500 m** no t−1 klases 1 traucējumiem; tas pats
  bāzlīnijai B0.
- **L4:** metrikas **katram testa gadam atsevišķi** (PR-AUC, lift top 5/10 %) un pozitīvo skaits katrā gadā.
- **L5:** negatīvo izlase 1:10 → kalibrācijai un Brier izmanto **svarus vai prevalences korekciju**; dokumentē.
- **L6:** ja 5. posms rāda, ka klase 1 Latvijā ir galvenokārt vējgāzes, modeli un atskaites sauc „**dabisko traucējumu
  (galvenokārt vējgāžu) riska modelis**“ līdz LVM mizgraužu etiķetēm.
- **L7 (secība):** 3 (S2) → 5 (EFDA aprakstoši; sausuma salīdzinājums atlikts) → 4 (laikapstākļi, RITY-2, ūdens bilance)
  → 5b (sausuma salīdzinājums) → 6 → 7 → 8.

**Atbildes uz 2.13:**
1. Zars **C**: fast-forward `feat/s1-earlysignal` → `master`, tad `feat/risk-model` no `master`. Pirms push `.gitignore`
   ieraksts `data/lvm/` (LVM dati nekad netiek commitoti) un pārbaude, ka repozitorijā nav ne-atvērtu datu. Push: `master`,
   `feat/risk-model` un visi tagi, izņemot `backup-*` un `backup-before-rewrite` (paliek lokāli).
2. Klase 4 izslēgta pilnībā (jutīgumam — kā pozitīvi). k = 5, jutīgumam k = 10.
3. Apmācības gadi 2000–2024 (ar L1/L2).
4. Tuvākais ERA5 mezgls.
5. ERA5 temperatūra tieši; INCA korekcijas (Ogris 2020 vien. 1–3) tikai jutīgumam.
6. Sistēmas 7-Zip (lietotājs instalēs; jāpasaka, kad vajag).
7. Pašu D8 neveido. Pārbaudīt Copernicus HRL Water & Wetness (pieejamība, licence, izšķirtspēja, gads, Kalsnavas tests
   ≤ 200 MB); ja der — aizstāj TWI, ja ne — tikai slīpums un TPI.
8. scikit-learn apstiprināts; numba un py7zr — nē.
9. **Ne SPEI.** Lieto P − ET0 un standartizētu anomāliju (z pret 1991–2020 tā paša perioda vērtībām), nosaukums bez
   „SPEI“ (piem., „standartizēta klimatiskās ūdens bilances anomālija“).
10. E1 + E2; E3 atlikts.
11. Reģionu rezerves variants pieņemams.
12. LVM gada noteikums — parametrs; noklusējums: cirte I–IV mēnesī → bojājuma gads t−1, V–XII → t. **Jāprecizē ar LVM**
    (ideāli bojājuma konstatēšanas datums, nevis cirtes datums).

## 2.15 Etiķešu stratēģija pēc 5. posma (lietotājs, 2026-10-23)

Lēmums pēc 5. posma rezultātiem (`docs/RM_5_EFDA_ANALIZE.md`). Tas ir **prioritārs** pār 2.5 un 2.14 tekstu,
kur tie atšķiras; iepriekšējais teksts paliek nemainīts kā vēsture.

- **EFDA klase 1 netiek izmantota kā etiķete** (ne v3.0, ne v2.1.1), jo tā nesakrīt ar oficiālajiem VMD datiem
  (CSP MEB012, 2013–2024: v3.0 klase 1 pret vējgāzēm ρ = −0,43, pret kaitēkļu stumbru bojājumiem ρ = −0,01, n = 12).
- **EFDA paliek pazīmju avots:** cirtes vēsture, meža malas, malas vecums, iepriekšējie traucējumi. Klases 3
  kvalitāte pārbaudīta RM_5 7.2 sadaļā.
- **Galvenās etiķetes:** LVM sanitārās cirtes (pēc apstiprināšanas).
- **Papildu etiķešu kandidāti:** DEFID2 un VMD atvērtie dati (pārbaude RM_5 7. sadaļā).
- **CSP MEB011** (reģioni, 2021–2025): agregēta validācija. Vai modeļa vidējais risks reģionā korelē ar oficiālajiem
  bojājumiem? Tikai aprakstoši, jo n ir mazs.
- **L6 (pārdēvēšana par vējgāžu modeli) vairs nav aktuāls.**

## 2.16 LVM atvērtie bojājumu dati kā etiķetes (lietotājs, 2026-10-23)

Galvenais etiķešu avots valsts mežiem ir **LVM_BOJAJUMI** (CC0). Pašreizējā publikācijas vieta nav atrasta, tāpēc
izmanto Internet Archive kopiju no 2025-05-03; proveniences dati un sha256 ir `DATU_AVOTI.md`. Faili paliek `cache/`.
Apraksts un pārbaudes: `docs/RM_5a_LVM_BOJAJUMI.md`.

- **Pozitīvie:** stumbra kaitēkļi (`DAMAGESUBT = 620`) pēc reģistrācijas gada (`DISTRBYEAR`).
- **Negatīvie = „nav reģistrēts”** (positive-unlabeled). Tāpēc modeli vērtē kā rangu (PR-AUC, lift top 5/10 %), nevis
  kā absolūtu varbūtību. Kalibrāciju (L5) interpretē tikai relatīvi.
- **Reģistrācijas gads ≠ uzbrukuma gads.** Laika saikne pārbaudīta empīriski RM_5a 2. sadaļā: EFDA cirte šajos
  poligonos visbiežāk ir gadā r+1 un r+2. Gada noteikums paliek parametrs.
- **Tikai valsts meži.** Analīzes kopa = **LVM zemes vienības** (`LVM_ZEMES_VIENIBAS`, Wayback 2025-04-21,
  1,61 milj. ha) ∩ EFDA meža maska. 99,1 % LVM bojājumu poligonu reprezentatīvo punktu ir LVM zemes vienībās [P].
- **MVR `P_CIRP = 31` ar `BV` 621/625** ir papildu etiķete privātajiem mežiem.
  - Ierobežojumi: tikai pēdējā cirte nogabalā (momentuzņēmums); pēc cirtes iemesls nav redzams.
  - **[P] MVR satur arī LVM zemi**, tāpēc privāto mežu etiķetēm MVR nogabalus ņem **ārpus** LVM zemes vienībām.
  - Kalsnavas MPS mežu MVR praktiski nav (RM_5a 3. sadaļa).

## 2.17 Kalsnava un 5b posms — s2forest aklā validācija uz LVM zemes (lietotājs, 2026-10-23)

- **Kalsnava = LBTU Meža pētīšanas stacijas (MPS) mežs** (RM_5a 3. sadaļa). Kalsnavas validācijai vajag MPS sanitāro
  ciršu datus (datums, iemesls); tos pieprasīs lietotājs. Līdz tam Kalsnava ir **demonstrācijas AOI**.
- **5b posms (pirms 4. posma):** s2forest iesaldētā v0.2 konfigurācija uz jauna 5 × 5 km AOI LVM zemē, monitoringa gadi
  2023 un 2024; mainās tikai AOI un gadi. Validācija pret LVM 620 un citiem bojājumu veidiem: detekcija pēc objekta
  (r−1, r, r+1), „neapstiprināti” poligoni, laika nobīde, placebo (100 permutācijas), ar un bez `stress_only`
  (informatīvi). Rezultāts: `docs/RM_5b_S2_VALIDACIJA_LVM.md`.
  - AOI kritēriji: ≥ 80 % LVM zeme; HRL skujkoki ≥ 50 %; ≥ 30 LVM 620 poligoni ≥ 0,5 ha (2023–2024); pēc iespējas
    Vidzemē, tuvu Kalsnavai. AOI izvēlas lietotājs no 3 kandidātiem.
- **Nosaukums:** L7 „5b (sausuma salīdzinājums)” turpmāk ir **„sausuma salīdzinājums”** pēc 4. posma; „5b” ir šis
  validācijas posms. Secība: 5a → 5b → 4 → sausuma salīdzinājums → 6 → 7 → 8.
- **5b lēmumi (lietotājs, 2026-10-23):** AOI = 1. kandidāts (Vidzeme, `data/aoi_lvm5b_vidzeme.geojson`);
  monitoringa gadi 2022–2025; 2025. gada detekcijas bez reģistrācijas = „neapstiprinātas (reģistrs beidzas 2025-04)”;
  `reference` / `stands` noņemti; vējgāzes un citi bojājumi atsevišķi. Rezultāts: `docs/RM_5b_S2_VALIDACIJA_LVM.md`.

## 2.18 Secinājums pēc s2forest validācijas (lietotājs, 2026-10-29)

Avots: `docs/RM_5b_S2_VALIDACIJA_LVM.md` (AOI 1 Vidzeme un AOI 3 Rīgas reģions; iesaldētā v0.2 konfigurācija,
2022–2025, placebo 100 permutācijas, p = 0,010 ir mazākā iespējamā).

- **s2forest ir apstiprināts kā bojājumu seku (ciršu) detektors** [P]:

  | LVM 620 ≥ 0,5 ha, jebkurā gadā r−1..r+1 | AOI 1 (n = 81) | AOI 3 (n = 101) |
  |---|---|---|
  | ≤ 20 m (placebo) | 69,1 % (36,2 %), p 0,010 | 87,1 % (61,5 %), p 0,010 |
  | s2forest pārklāj ≥ 25 % (placebo) | 32,1 % (8,2 %), p 0,010 | 61,4 % (19,8 %), p 0,010 |
  | atrasti kā cut (≤ 20 m) | 55 no 56 | 85 no 88 |

  Atrastie bojājumi ir galvenokārt cirtes gadā r un r+1, lielākoties ziemas cirtes pēc reģistrācijas.
- **S2 stress nav agrīnais brīdinājums gadu iepriekš** [P]: gadā r−1 stingrais rādītājs abos AOI ir placebo līmenī
  (AOI 1: 2,5 % pret 2,6 %, p 0,61; AOI 3: 10,9 % pret 6,6 %, p 0,11, un visas 11 sakritības ir cirtes).
- **Daļējs, vienā AOI novērots rezultāts (nav vispārinājums)** [P]: AOI 3 stresa poligoni reģistrācijas logā sakrīt ar
  LVM bojājumiem biežāk nekā nejauši (62,2 % pret 39,1 %, p 0,020; ar 620: 40,0 % pret 23,8 %, p 0,030), lielākoties
  **tajā pašā gadā** kā reģistrācija (17 no 25), un 12 no 25 nākamajā gadā pārklāj cirte. Tātad S2 stress **var**
  signalizēt par jau notiekošu bojājumu tās pašas sezonas laikā. AOI 1 tas neatkārtojas (p 0,14 un 0,48), un
  LVM poligoniem ir tikai gads, tāpēc secība gada iekšienē nav zināma [N].
- **S2 stress nav etiķete.** S2 laika rindu pazīmes (piem., z, statuss, stresa poligona tuvums) ir tikai
  **kandidātpazīmes**; to vērtību nosaka modeļa validācija (7. posms), nevis šis secinājums.
- **Lomas:**
  - **riska modelis** = agrīnā brīdināšana (prognoze pirms sezonas no t−1 pazīmēm);
  - **S2 (s2forest)** = notikušo bojājumu un sanitāro ciršu monitorings; tās pašas sezonas stresa signāls — pārbaudāma
    hipotēze ar LVM datiem (datums + iemesls);
  - **S1** = papildinājums mākoņainā laikā (S1 darbs iesaldēts līdz LVM datiem, `docs/S1_KOPSAVILKUMS.md`).

## 2.19 LVM datu integrācija (plāns; dati vēl nav saņemti)

- **Gaidāmie dati (pieprasījums LVM):**
  1. sanitārās cirtes 2018–2026 ar **datumu** un **iemeslu** (mizgrauži / vējgāzes / cits), poligoni;
  2. aktuālais bojājumu reģistrs 2025–2026 (Wayback kopija beidzas 2025-04-27);
  3. taksācija: nogabali ar sugu sastāvu, vecumu, augstumu, krāju;
  4. 2026. gada vējgāžu poligoni (tie arī atsāk iesaldēto S1 darbu).
- **Ko tie aizstās:**
  - **galvenā etiķete** = sanitārā cirte ar iemeslu „mizgrauži” (datums + iemesls), nevis Wayback `LVM_BOJAJUMI`
    620 reģistrācijas gads (2.16). Wayback dati paliek salīdzinājumam un gadiem, kurus jaunie dati nesedz;
  - **egles aizstājēji E1 / E2** (HRL skujkoki + Picea varbūtība; CHMv2 augstums, 2.6) → taksācijas egles daļa,
    vecums, augstums, krāja LVM zemei. E1 / E2 paliek privātajiem mežiem;
  - **5b validācija** atkārtojama ar cirtes datumu: vai S2 stress ir pirms cirtes tās pašas sezonas laikā (2.18).
- **Etiķešu gada noteikums:** parametrs; noklusējums — cirte I–IV mēnesī → bojājuma gads t−1, V–XII → t (2.14,
  12. punkts). **Jāprecizē ar LVM**; ideāli — bojājuma konstatēšanas datums, nevis cirtes datums.
- **Datu drošība:**
  - LVM faili tikai `data/lvm/` (`.gitignore`); nekādas LVM datu kopijas `output/` failos, ko commito, vai `docs/`;
  - dokumentācijā un attēlos tikai agregāti (skaits, ha, daļas, kartes bez nogabalu atribūtiem);
  - pirms katra push: pārbaude, ka commitos nav `data/local`, `data/lvm`, `cache`, `output` (kā līdz šim).
- **Ielādes un pārbaudes posms** (kā 5a, pirms modeļa): lauki un kodi, gadi un datumi (diapazons, trūkstošie),
  ģeometrijas (derīgums, dublikāti, pārklāšanās, platības sadalījums), salīdzinājums ar Wayback `LVM_BOJAJUMI` (cik
  620 poligonu ir sanitārās cirtes; laika nobīde reģistrācija → cirte) un ar CSP (MEB011 / MEB012 pa gadiem un
  reģioniem). Atskaite `docs/RM_LVM_DATI.md`, apstāšanās.

## 2.20 Laika plāns pēc apstiprināšanas inkubatorā

- **Mērķis:** 2027. gada riska karte gatava **pirms mizgraužu izlidošanas**, lai to var pārbaudīt ar dronu un dabā
  maijā–jūnijā. RITY-2 (ERA5, Kalsnava) izlidošana 2018–2026 bija 2.–28. aprīlī (2024 un 2025: 2.–3. aprīlis) [P,
  `RM_4`]; Silava 2023: 20. aprīlis [P]. Orientējošais termiņš — aprīļa beigas; **ieteikums — 1. aprīlis**, jo siltos
  gados izlidošana var būt aprīļa sākumā [N].
- **Kāpēc tas ir iespējams:** karte balstās uz t−1 = 2026 pazīmēm. 2026. gada laikapstākļi IV–X ir pieejami
  novembrī (ERA5-Land ~5 dienu aizture, galīgie dati ~2 mēn. vēlāk [P ECMWF]).
- **Pazīmju aktualitātes risks [P/N]:** EFDA v3.0 beidzas ar 2024. gadu, tāpēc traucējumu vēsture 2025–2026 no EFDA
  nav. Varianti: LVM sanitārās cirtes (2.19; valsts meži), s2forest ciršu detekcija (tikai AOI), EFDA atjauninājums
  [N: nav zināms]. Bez tā t−1 = 2026 malu / traucējumu pazīmes ir novecojušas.

| Laiks [N] | Darbs | Atkarība |
|---|---|---|
| 2026. g. novembris | CDS ERA5-Land lejupielāde (pēc apstiprinājuma, 2.21), Kalsnavas salīdzinājums, Latvijas RITY-2 / ūdens bilance; sausuma salīdzinājums | CDS atslēga; LVM pieprasījums nosūtīts |
| 2026. g. decembris–2027. g. janvāris | 6. posms: pazīmju slāņi (CHMv2, DTM, malas, traucējumi, klimats), apmācības tabula, noplūdes testi | LVM dati, ja saņemti (citādi Wayback etiķetes) |
| 2027. g. janvāris–februāris | 7. posms: bāzlīnijas, HGB, telpiskā + laika validācija | 6. posms |
| 2027. g. marts | 8. posms: 2027. gada karte (t−1 = 2026), atskaite; drona misiju saraksts | 7. posms |
| 2027. g. aprīlis | RITY-2 izlidošanas sekošana pēc ERA5-Land-T (tagadne, ne prognoze [N]) | CDS |
| 2027. g. maijs–jūnijs | drona un lauka pārbaude | karte |

- **Dators [P, 2026-10-29]:** RAM 15,7 GB (brīvi novēroti 1,8–6,7 GB), CPU i5-13450HX (10 kodoli, 16 pavedieni),
  GPU RTX 5060 Laptop (Windows rāda 4 GB VRAM; lauks ir ierobežots līdz 4 GB, īstā vērtība nav pārbaudīta [N]),
  disks brīvi 544 GB.
- **Kas iespējams uz šī datora [N, aprēķins]:**
  - **6. posms LVM zemei:** jā, blokos. Analīzes kopa ~1,61 M ha ≈ 18 M 30 m šūnu (pirms skujkoku filtra); CHMv2
    ~30 GB pagaidu lejupielāde un agregācija (tīkla ierobežota, stundas); DTM 20 m.
  - **7. posms LVM zemei:** jā. Tabula ≤ 10 M rindu × 30 pazīmes ≈ 1,2 GB float32; HGB ar telpisko + laika
    krosvalidāciju (k = 5) — stundas.
- **Kam vajag RTU HPC [N]:**
  - visu īpašnieku Latvijas tabula (~43 M meža šūnu × 25 gadi) un prognoze ar daudzām pazīmēm;
  - plaša hiperparametru meklēšana, atkārtota krosvalidācija, permutāciju nozīmīgums lielā apjomā;
  - **S2 laika rindu pazīmes visai Latvijai:** 5b AOI 3 palaišana (25 km², 1 gads) aizņēma 13–34 min [P, `output/rm5b_lvm_aoi3/run_all.out`];
    ~38 800 km² meža (EFDA, 2.3) ≈ 1 550 šādu AOI ≈ 340–880 h vienam gadam [N] — tikai HPC (vai tikai AOI).

## 2.21 Laikapstākļu avots (lietotājs, 2026-10-29)

- **Galvenais: Copernicus CDS ERA5-Land** (0,1°). **Open-Meteo** (`era5`, 0,25°) — tikai **Kalsnavas prototips**
  (`docs/RM_4_KLIMATS_FENOLOGIJA.md`), Latvijas mērogam netiek lietots.
- **Pamatojums:**
  - **licence / lietošana:** Open-Meteo bezmaksas līmenis ir nekomerciālai lietošanai, projekts inkubatorā ir vērsts uz
    produktu; ERA5-Land CDS licence CC-BY-4.0 [P, CDS katalogs];
  - **apjoms:** Open-Meteo svērtie izsaukumi Latvijai = 161 091 (~18 dienas pie bezmaksas limita) [P, `RM_4`];
  - **izšķirtspēja:** ERA5-Land 0,1° (~9 km) pret ERA5 0,25° (~25 km) [P].
- **Atkarības (apstiprinātas):** `cdsapi` 0.7.7 (Apache-2.0; velk līdzi `ecmwf-datastores-client` Apache-2.0,
  `multiurl` Apache-2.0, `tqdm` MPL-2.0/MIT) un `h5netcdf` 1.8.2 (BSD) ar `h5py` 3.16 (BSD-3, 3,2 MB) — vieglākais
  netCDF4 lasītājs (`netCDF4` 1.7.5: 22 MB + `cftime`) [P, PyPI]. Ja CDS atdod netCDF3, pietiek ar esošo `scipy` [N:
  formāts tiks pārbaudīts pilotā]. **Vēl nav instalētas.**
- **API atslēga:** `~/.cdsapirc` ieraksta lietotājs; kods to nemeklē un nelasa (izņemot `cdsapi` pašu).
  2026-10-29 fails **nav atrasts** (`test -f`).

### CDS datu kopas [P, CDS katalogs un API apraksti, 2026-10-29]

| Datu kopa | Izšķirtspēja | Periods | Ko dod | Piezīmes |
|---|---|---|---|---|
| `derived-era5-land-daily-statistics` | 0,1° | 1950-01-01 – 2026-10-23 | dienas vid. / maks. / min. no 1 / 3 / 6 h ievades; `time_zone` maiņa | **nav akumulēto mainīgo** („accumulated variables (such as total precipitation and runoff) are omitted”); statistika aprēķināta pieprasījuma laikā; 1 gads + 1 mēnesis vienā pieprasījumā |
| `reanalysis-era5-land` (stundu) | 0,1° | 1950 – 2026-10-23 | `total_precipitation`, `surface_solar_radiation_downwards`, `potential_evaporation` u. c. akumulētie | akumulācija no 00 UTC; vērtība 00 UTC = iepriekšējās dienas summa [P ECMWF]; m, J m⁻²; 1 mēnesis vienā pieprasījumā |
| `derived-era5-single-levels-daily-statistics` | 0,25° (ERA5) | — | ietver `daily_sum` akumulētajiem | rupjāka izšķirtspēja → tikai rezerves variants |

- **Aizture:** ERA5-Land-T ~5 dienas, galīgie dati ~2 mēnešus pēc mēneša beigām [P ECMWF dokumentācija].
- **Zināmās problēmas [P ECMWF]:** mēneša vidējie akumulētie lauki 2022-09 – 2024-02 ir kļūdaini (mēs tos neizmantojam,
  ņemam stundu datus); kopš 2020-01-01 iespējams neliels pārrāvums piekrastē (MIR interpolācija) — jāpārbauda
  bāzes un 2020+ salīdzināmība piekrastes mezglos.
- **Limiti:** aktuālie ierobežojumi ir uz datu kopu un mainās; ECMWF iesaka pieprasīt pa mēnesim; ERA5-Land
  ierobežojums tika paaugstināts no 1 000 uz 12 000 laukiem [P forums, datums nav zināms]. Mūsu lielākais pieprasījums:
  5 mainīgie × 31 diena × 24 h = 3 720 stundu lauki (< 12 000); precīzi pārbaudīs pilots.

### ET0 izvēle

- **Izvēle: FAO-56 Penman–Monteith (Eq. 6) dienas solī no ERA5-Land mainīgajiem**, nevis ERA5-Land
  `potential_evaporation`.
  - ERA5-Land `pev` „is computed as an open water evaporation (Pan evaporation)” un atšķiras no ERA5 definīcijas
    [P ECMWF ERA5-Land dokumentācija]; FAO-56 ET0 ir hipotētiska zāles references virsma (0,12 m, 70 s m⁻¹, albedo
    0,23) [P FAO-56 2. nod.]. Tās nav viena un tā pati lieluma definīcija.
  - Open-Meteo `et0_fao_evapotranspiration` ir „ET₀ Reference Evapotranspiration of a well watered grass field” [P],
    tātad FAO-56 aprēķins dod salīdzināmu lielumu ar Kalsnavas prototipu.
  - `pev` lejupielādēsim tikai salīdzinājumam (tas pats pieprasījums, papildu mainīgais).
- **Ievade (FAO-56 3. nod. vienādojumi):** T_max, T_min (dienas maks. / min. no 1 h, `utc+02:00`); e_a no dienas vidējā
  rasas punkta (Eq. 14); u₂ no 10 m vēja (Eq. 47); R_s = `ssrd` dienas summa; R_so (Eq. 37 ar R_a Eq. 21); R_ns =
  0,77·R_s (Eq. 38); R_nl (Eq. 39); R_n = R_ns − R_nl (Eq. 40); G = 0 (Eq. 42); P no `surface_pressure` dienas
  vidējā (vai Eq. 7). Pārbaude: FAO-56 **Example 18** (Uccle, 6. jūlijs, ET0 = 3,9 mm/dienā ar visām starpvērtībām) kā
  vienības tests.
- **Zināmas novirzes [N]:** (a) dienas vējš no dienas vidējiem u un v komponentiem ir mazāks par vidējo ātrumu
  (vektoru vidējošana) — pilotā novērtēšu ar stundu u/v Kalsnavai vienam mēnesim; (b) `tp` / `ssrd` ir UTC dienas,
  temperatūra `utc+02:00` (2 h nobīde); (c) dienas garums RITY-2 sliekšņiem: FAO-56 Eq. 34 (astronomiskais N) pret
  Open-Meteo `daylight_duration` (aprēķins nav aprakstīts) — atšķirība ietekmē 14,5 h slieksni, jāsalīdzina Kalsnavā.

### Pieprasījumi un apjoms Latvijai (+ 0,1° buferis) [N, aprēķins]

- **Apgabals:** N 58,2, W 20,8, S 55,5, E 28,4 → 77 × 28 = 2 156 režģa punkti (jūras punkti ERA5-Land ir tukši).
- **Mēneši:** ūdens bilancei IV–IX 1991–2026 (216 mēneši); RITY-2 / PHENIPS-Clim papildus I–III un X 2018–2026
  (36 mēneši; 2026. gada oktobris daļējs) → 252 mēneši.
- **Pieprasījumi:**
  - dienas statistika: 3 uz mēnesi (`daily_maximum` t2m, `daily_minimum` t2m, `daily_mean` t2m + d2m + u10 + v10 + sp;
    ārpus IV–IX tikai t2m) → 756;
  - stundu akumulētie (`tp`, `ssrd`, `pev`; tikai 00 UTC): 6 mēneši + 1. oktobris gadā → 252;
  - **kopā ~1 010 pieprasījumi.**
- **Apjoms:** ~0,6 GB neiepakotu float32 vērtību (dienas statistika ~0,43 GB, akumulētie ~0,17 GB), `cache/rm/cds/`.
- **Laiks:** CDS rindas laiks nav zināms; dienas statistika tiek aprēķināta pieprasījuma laikā. Novērtējums
  0,5–2 dienas [N] — **pilotā izmērīšu**.
- **Kalsnavas atsevišķa lejupielāde nav vajadzīga:** pieprasījumu skaits ir atkarīgs no mēnešiem, nevis no apgabala,
  tāpēc Kalsnavu ņem no Latvijas datiem.

### Kalsnavas salīdzinājums ar Open-Meteo prototipu (pēc lejupielādes)

- Punkti: tuvākais ERA5-Land punkts Kalsnavas AOI centroīdam un vidējais ERA5-Land 0,25° šūnā 56,75 / 25,75.
- Dienas T_max / T_min / T_mean, P, ET0 (mūsu FAO-56 pret Open-Meteo ET0; `pev` informatīvi): vidējā novirze, RMSE,
  korelācija; P − ET0 IV–IX un z pa gadiem.
- RITY-2 pa gadiem 2018–2026: izlidošanas DOY, invāzijas DOY, Tsum_F1 / Tsum_F2, paaudzes (tiešā ERA5-Land un INCA);
  Silava 2023 pārbaude atkārtoti.
- Rezultāts: tabula un attēls `RM_4` papildinājumā; skaitļi tikai no palaišanas.

### Secība (katrs solis ar apstāšanos)

1. Lietotājs ieraksta `~/.cdsapirc` un pieņem datu kopu licences CDS vietnē.
2. Atkarību instalēšana (`cdsapi`, `h5netcdf`, `h5py`).
3. **Pilots:** 2023. gada aprīlis Latvijai (3 dienas statistikas + 1 stundu pieprasījums; + stundu u/v Kalsnavai šim
   mēnesim): formāts, laiks, izmērs, vēja novirze, salīdzinājums ar Open-Meteo šim mēnesim. **Apstāšanās.**
4. Pilnā lejupielāde (~1 010 pieprasījumi, atsākama, kešs) → Kalsnavas salīdzinājums → Latvijas kartes.

## 2.22 Fenoloģijas pazīmes riska modelim (lietotājs, 2026-10-29)

- **Galvenā pazīme: relatīvā termālā summa** (nepārtraukta; RITY-2 Tsum_F1 un Tsum_F2 31. oktobrī, AVG scenārijs),
  nevis veselu paaudžu skaits.
- **Iemesls:** Slovēnijas kalibrācija Kalsnavā dod 2 paaudzes katru gadu (AVG), kas Latvijā, visticamāk, ir par daudz;
  ar INCA korekcijām — 1 paaudze (2024: 2) [P, `RM_4`].
- **Sekundāra pazīme:** paaudžu skaits ar **abiem** variantiem (tiešā ERA5 / ERA5-Land un INCA (1)–(3)).
- Izlidošanas DOY paliek kā pazīme (t−1) un pavasara sekošanai.
