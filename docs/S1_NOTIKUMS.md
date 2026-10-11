# Sentinel-1 vējgāžu modulis — 2. posms: notikums un dati

Datums: 2026-10-11. Zars `feat/s1-windthrow`. **[P]** = PĀRBAUDĪTS, **[N]** = PIEŅĒMUMS.

## Notikums (lietotāja dati, 2026-10-11)

- **Vētra 22.–23.08.2026.** Zemkopības ministrija ziņo par izgāztiem un nolauztiem kokiem
  daudzviet Latvijā; konkrētas teritorijas nav zināmas. Pirmais tests — Kalsnavas AOI
  (nav zināms, vai tur ir vējgāzes).
- Logi (parametri): **pirms** 2026-07-25 … 2026-08-21, **pēc** 2026-08-24 … 2026-09-20.
- Otrs notikums vēlākam testam (AOI vēl nav): vētra Rēzeknes novadā, LVM Rēznas un
  Rušonas iecirkņi, ~12.07.2026, ~1500 m³.
- LVM vējgāžu poligonu vēl nav (pieprasīti).

## Konfigurācija

`configs/s1_kalsnava_2026-08.yaml`: AOI, režģis EPSG:3059 10 m, PC `sentinel-1-rtc`
(VV, VH, nodata −32768 → maskēt), notikuma logi, `n_pre_max` = `n_post_max` = 5 katrā
orbītā (tuvākie notikumam), `min_aoi_cover` = 0 (daļējās orbītas 7 un 153 paliek),
meža maska HRL DLT klases 1 + 2 + ceļi 20 m, MMU 0,5 ha, sliekšņa metode — **3. posmā**
(`method: null`), S2 pārbaudes un aizvietotāja (S2 cut ≥ 0,5 ha) ceļi.
Konfigurācijas ielādes kods vēl nav uzrakstīts (3. posms).

## Izvēlētie uzņēmumi [P]

Kods: `src/s1windthrow/event.py` (`group_acquisitions`, `select_window`), meklēšana
`s1windthrow.stac.search_s1`. Tabula: `output/s1_kalsnava_2026-08/acquisition_selection.csv`
(arī STAC ID). Visi logos esošie uzņēmumi ir izmantoti (nevienā orbītā logā nav vairāk par
5; neviens nav izslēgts).

| Orbīta | Virziens | Pirms | Pēc |
|---|---|---|---|
| 7 | descending | 3 | 4 |
| 58 | ascending | 5 | 5 |
| 80 | descending | 4 | 4 |
| 153 | descending | 5 | 5 |
| 160 | ascending | 5 | 5 |

| Orbīta | Virziens | Logs | Datums | Laiks UTC | Platforma | AOI pārkl. | Nokr. 6 h, mm | Nokr. 24 h, mm | T, °C |
|---|---|---|---|---|---|---|---|---|---|
| 7 | descending | pirms | 2026-07-30 | 04:26 | S1d | 0.943 | 0.0 | 0.0 | 14.8 |
| 7 | descending | pirms | 2026-08-05 | 04:26 | S1c | 0.905 | 0.0 | 0.0 | 15.5 |
| 7 | descending | pirms | 2026-08-17 | 04:26 | S1c | 0.927 | 0.0 | 1.9 | 12.8 |
| 7 | descending | pēc | 2026-08-29 | 04:26 | S1c | 0.931 | 0.0 | 0.0 | 13.3 |
| 7 | descending | pēc | 2026-09-04 | 04:26 | S1d | 0.899 | 0.5 | 4.6 | 13.5 |
| 7 | descending | pēc | 2026-09-10 | 04:26 | S1c | 0.934 | 0.0 | 0.2 | 14.5 |
| 7 | descending | pēc | 2026-09-16 | 04:26 | S1d | 0.923 | 0.0 | 0.0 | 11.7 |
| 58 | ascending | pirms | 2026-07-27 | 16:03 | S1c | 1.000 | 6.4 | 7.8 | 17.1 |
| 58 | ascending | pirms | 2026-08-02 | 16:03 | S1d | 1.000 | 0.0 | 8.3 | 20.5 |
| 58 | ascending | pirms | 2026-08-08 | 16:03 | S1c | 1.000 | 1.1 | 2.6 | 18.0 |
| 58 | ascending | pirms | 2026-08-14 | 16:03 | S1d | 1.000 | 0.0 | 0.0 | 21.4 |
| 58 | ascending | pirms | 2026-08-20 | 16:03 | S1c | 1.000 | 3.2 | 9.7 | 17.1 |
| 58 | ascending | pēc | 2026-08-26 | 16:03 | S1d | 1.000 | 0.0 | 0.0 | 17.8 |
| 58 | ascending | pēc | 2026-09-01 | 16:03 | S1c | 1.000 | 9.1 | 9.3 | 15.4 |
| 58 | ascending | pēc | 2026-09-07 | 16:03 | S1d | 1.000 | 0.0 | 0.1 | 16.7 |
| 58 | ascending | pēc | 2026-09-13 | 16:03 | S1c | 1.000 | 0.0 | 0.0 | 15.3 |
| 58 | ascending | pēc | 2026-09-19 | 16:03 | S1d | 1.000 | 1.1 | 4.1 | 15.4 |
| 80 | descending | pirms | 2026-07-29 | 04:34 | S1c | 1.000 | 0.0 | 5.7 | 11.8 |
| 80 | descending | pirms | 2026-08-04 | 04:34 | S1d | 1.000 | 0.0 | 0.0 | 13.0 |
| 80 | descending | pirms | 2026-08-10 | 04:34 | S1c | 1.000 | 0.0 | 0.0 | 13.6 |
| 80 | descending | pirms | 2026-08-16 | 04:34 | S1d | 1.000 | 0.0 | 0.0 | 16.4 |
| 80 | descending | pēc | 2026-08-28 | 04:34 | S1d | 1.000 | 0.0 | 0.0 | 10.1 |
| 80 | descending | pēc | 2026-09-03 | 04:34 | S1c | 1.000 | 0.0 | 2.9 | 12.4 |
| 80 | descending | pēc | 2026-09-09 | 04:34 | S1d | 1.000 | 0.0 | 0.0 | 13.5 |
| 80 | descending | pēc | 2026-09-15 | 04:34 | S1c | 1.000 | 0.0 | 2.0 | 9.7 |
| 153 | descending | pirms | 2026-07-28 | 04:42 | S1d | 0.802 | 0.0 | 8.3 | 12.8 |
| 153 | descending | pirms | 2026-08-03 | 04:42 | S1c | 0.826 | 0.0 | 0.4 | 12.6 |
| 153 | descending | pirms | 2026-08-09 | 04:42 | S1d | 0.813 | 0.0 | 2.6 | 12.1 |
| 153 | descending | pirms | 2026-08-15 | 04:42 | S1c | 0.808 | 0.0 | 0.0 | 13.2 |
| 153 | descending | pirms | 2026-08-21 | 04:42 | S1d | 0.844 | 0.0 | 8.7 | 12.7 |
| 153 | descending | pēc | 2026-08-27 | 04:42 | S1c | 0.813 | 0.0 | 0.0 | 9.2 |
| 153 | descending | pēc | 2026-09-02 | 04:42 | S1d | 0.831 | 0.2 | 14.2 | 13.7 |
| 153 | descending | pēc | 2026-09-08 | 04:42 | S1c | 0.816 | 0.0 | 0.1 | 10.5 |
| 153 | descending | pēc | 2026-09-14 | 04:42 | S1d | 0.812 | 0.7 | 0.9 | 11.8 |
| 153 | descending | pēc | 2026-09-20 | 04:42 | S1c | 0.842 | 1.6 | 3.1 | 12.6 |
| 160 | ascending | pirms | 2026-07-28 | 15:55 | S1d | 1.000 | 5.5 | 10.5 | 17.4 |
| 160 | ascending | pirms | 2026-08-03 | 15:55 | S1c | 1.000 | 0.0 | 0.0 | 21.2 |
| 160 | ascending | pirms | 2026-08-09 | 15:55 | S1d | 1.000 | 0.0 | 0.2 | 21.3 |
| 160 | ascending | pirms | 2026-08-15 | 15:55 | S1c | 1.000 | 0.0 | 0.0 | 25.2 |
| 160 | ascending | pirms | 2026-08-21 | 15:55 | S1d | 1.000 | 0.5 | 1.8 | 21.2 |
| 160 | ascending | pēc | 2026-08-27 | 15:55 | S1c | 1.000 | 0.0 | 0.0 | 19.8 |
| 160 | ascending | pēc | 2026-09-02 | 15:55 | S1d | 1.000 | 2.3 | 8.6 | 16.9 |
| 160 | ascending | pēc | 2026-09-08 | 15:55 | S1c | 1.000 | 0.0 | 0.0 | 19.3 |
| 160 | ascending | pēc | 2026-09-14 | 15:55 | S1d | 1.000 | 1.1 | 2.8 | 16.0 |
| 160 | ascending | pēc | 2026-09-20 | 15:55 | S1c | 1.000 | 1.1 | 6.9 | 14.6 |

Nokrišņi: Open-Meteo vēsturiskais API (`archive-api.open-meteo.com/v1/archive`, bez atslēgas),
stundu `precipitation` un `temperature_2m`, punkts AOI centrā; API atgrieza režģa punktu
56,696 N, 25,795 E (5,0 km uz rietumziemeļrietumiem no AOI centra, ārpus AOI), augstums 105 m. Summa par 6 h un
24 h līdz uzņēmuma brīdim. [N: modeļa / reanalīzes avots (ERA5 u. c.) API atbildē netika
pārbaudīts; tas ir modelēts, nevis mērīts lielums.]

## Novērojumi [P]

1. **Orbītā 7 pirms logā ir tikai 3 uzņēmumi:** S1D 2026-08-11 katalogā nav (meklēts
   2026-08-08…08-26). Pirms/pēc skaits 3/4, pārējās orbītās 4–5.
2. **Uzņēmumi pašā vētras laikā netiek izmantoti** (ārpus logiem): orbīta 80 2026-08-22
   04:34 UTC (S1C) un orbīta 7 2026-08-23 04:26 UTC (S1D).
3. **Nokrišņi:** logu summa (dienas summas, AOI punkts) pirms **66,5 mm**, pēc **109,2 mm**;
   vētras dienās 22.08. — 31,2 mm, 23.08. — 11,1 mm. Uzņēmumi ar ≥ 5 mm 6 stundās pirms
   uzņēmuma: pirms — 58/07-27 (6,4), 160/07-28 (5,5); pēc — 58/09-01 (9,1). Ar ≥ 8 mm
   24 stundās: pirms — 58/08-02, 58/08-20, 153/07-28, 153/08-21, 160/07-28; pēc —
   58/09-01, 153/09-02, 160/09-02.
   Slapja veģetācija palielina atpakaļizkliedi; „pēc“ logs kopumā ir slapjāks, tāpēc
   reģionāla pozitīva nobīde ir iespējama — to jāredz stabila meža kontroles sadalījumā.
4. **S2 neatkarīgai pārbaudei** esošajā s2forest izvadē
   (`output/test_kalsnava/rasters/indices/crswir_timeseries.tif`, 64 joslas, EPSG:3059 10 m)
   ir datumi 2026-07-29 (×2), 08-11, 08-13 (pirms) un 08-28, 09-12, 09-15 (pēc). Daļa var būt
   maskēta (mākoņi / dūmaka) — pārbaudīšu 3. posmā, lasot tikai rastrus.
5. **Aizvietotāja (S2 cut) laiks:** 2026. gada cirtes ≥ 0,5 ha — 14, no tām 13 noteiktas
   2026-05-05 (ziemas cirtes, notikušas starp 2025-09-29 un 2026-05-05) un 1 — 2026-07-12;
   2025. gadā 35 cirtes ≥ 0,5 ha. **Neviena nav notikuma logos**, tāpēc vētras pirms/pēc
   kompozīts tās neaptver. Zīmes jautājumam katrai cirtei vajadzīgi savi pirms/pēc logi
   (sk. jautājumu 2).

## Jautājumi pirms 3. posma

1. **Slieksnis:** stabilā meža kontroles zonā (meža maska bez S2 poligoniem, ceļu buferiem
   un, piem., ≥ 100 m no tiem) — robustais z (mediāna, MAD) ar k = ? vai procentile (piem.,
   p99)? Vējgāzes zīme pēc Rüetschi — pieaugums, tātad vienpusējs tests (Δ > slieksnis)?
2. **Aizvietotāja logi S2 cirtēm:** priekšlikums — katrai cirtei „pirms“ = līdz 5
   uzņēmumiem katrā orbītā pirms cirtes intervāla sākuma (ziemas cirtēm 2025-09-29),
   „pēc“ = līdz 5 pēc `first_detected` (2026-05-05); 2025. gada cirtēm intervālu ņemt no
   S2 novērojumiem. Ziemas cirtēm „pirms“ (rudens) un „pēc“ (maijs) ir dažādas sezonas —
   fenoloģijas un mitruma atšķirība sajauksies ar cirtes efektu. Vai pieņemams, vai
   aizvietotāju ierobežot tikai ar 2026-07-12 cirti un 2025. gada vasaras cirtēm?
3. **Slapji uzņēmumi:** tikai pierakstīt (kā norādīts) vai arī izslēgt uzņēmumus ar
   nokrišņiem > X mm 6 h pirms uzņēmuma? Ja izslēgt — kāds X?
