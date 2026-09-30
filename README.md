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

```bash
python -m uv run s2forest fetch   configs/test_kalsnava.yaml   # datu ieguve + diagnostika
python -m uv run s2forest indices configs/test_kalsnava.yaml   # indeksi, meža maska, GeoTIFF
python -m uv run s2forest detect  configs/test_kalsnava.yaml   # anomālijas, poligoni (GPKG)
```

Rezultāti: `output/<run_name>/`

| Mape | Saturs |
|---|---|
| `diagnostics/` | pārlidojumu tabula, derīgo novērojumu grafiks, RGB priekšskatījumi, harmonizācijas un dūmakas testa pārbaude |
| `rasters/` | meža maska, indeksu laika rindas (viena josla = viens datums), vasaras mediānas pa gadiem |
| `rasters/anomaly/` | statusa rastrs, pirmās noteikšanas diena, z-vērtības |
| `vectors/suspects.gpkg` | aizdomīgie poligoni (atverami QGIS un QField) |
| `tables/` | poligonu atribūti CSV, reģionālās nobīdes |
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
6. **Anomālijas.** Katram pikselim bāzes līnija no iepriekšējiem 3 gadiem tajā
   pašā sezonas logā (±30 dienas), robusta novirze ar mediānu un MAD.
   Novērojums ir anomāls, ja CRSWIR z ≥ 2,5 un vismaz viens cits indekss arī
   pārsniedz 2,5; pikselis tiek atzīmēts, ja tas atkārtojas ≥ 2 secīgos
   derīgos novērojumos. Poligoni < 0,1 ha tiek atmesti.

## Kalibrētie parametri (Kalsnavas testa teritorija, 2026)

Visi sliekšņi ir konfigurējami; kalibrēšanas skripti ir mapē `scripts/`, un tie
jāpārpalaiž jaunai teritorijai.

| Parametrs | Vērtība | Pamatojums |
|---|---|---|
| Dūmakas tests, B02 pārsniegums (`masking.haze.b02_threshold`) | 0,02 | Skaidrās dienās meža pikseļu B02 novirze no bāzes: p95 = 0,017, p99 = 0,025. Ar 0,02 tiek aptverti 2026-09-15 mākoņu svītru kodoli (atbilst RGB). Ar 0,015 skaidrās dienās maskētu cirsmu malas, ar 0,03 izkrīt svītru malas. `scripts/calibrate_haze.py` |
| Sezonas pēdējais novērojums (`last_obs_scene_share`) | 10 % | Pēdējam novērojumam nav nākamā, tāpēc to pēc noklusējuma saglabā. Izņēmums: ja neizšķirtie pikseļi aizņem ≥ 10 % no AOI, to uzskata par atmosfēras efektu. Skaidrās pēdējās dienās tie bija 0,1–1,5 %, dūmakainajās 12–24 %. |
| Meža maska, bāzes vasaras NDVI (`forest_mask.min_summer_ndvi`) | 0,65 | HRL skujkoku pikseļu vasaras NDVI mediānas virsotne ir ~0,78 (σ ≈ 0,04); izcirtumi un jaunaudzes veido asti 0,35–0,65. 0,65 ≈ virsotne − 3σ; izslēdz ~4 % HRL pikseļu (cirsmas, ceļus, grāvjus). `scripts/calibrate_forest_ndvi.py` |
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
