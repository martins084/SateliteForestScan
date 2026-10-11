# Sentinel-1 vējgāžu modulis — 1. posms: datu pieejamība

Datums: 2026-10-11. Zars `feat/s1-windthrow`. Apzīmējumi: **[P]** = PĀRBAUDĪTS
(komanda / fails), **[N]** = PIEŅĒMUMS.

## Kā pārbaudīts

- Jauna minimāla meklēšana `src/s1windthrow/stac.py` (`search_s1`): Planetary Computer
  STAC, kolekcija `sentinel-1-rtc`, tikai `bbox` + datumi, **bez** `eo:cloud_cover`
  filtra. Esošais `s2forest.sources.stac_common.stac_search` nav mainīts.
- AOI: `data/test_aoi_kalsnava.geojson` (tā pati, ko lieto s2forest), bbox WGS84
  25,8269–25,9107 E, 56,6540–56,7001 N. Periods 2023-01-01 … 2026-10-11.
- Palaišana ar `PYTHONPATH=src .venv/Scripts/python.exe` (pakotne vēl nav reģistrēta
  `pyproject.toml` — to darīs 3. posmā). Starprezultāti (nav git):
  `output/s1_stage1/s1_items.csv` (716 STAC vienumi), `s1_acquisitions.csv`
  (710 uzņēmumi), `s1_monthly.csv`, `monthly_table.md`.

## Kolekcija [P]

| Īpašība | Vērtība | Avots |
|---|---|---|
| Nosaukums | „Sentinel 1 Radiometrically Terrain Corrected (RTC)“ | `get_collection("sentinel-1-rtc")` |
| Laika apjoms | 2014-10-10 … atvērts (bez beigu datuma) | kolekcijas `extent` |
| Produkts | GRD, IW režīms, C josla; gamma nulle (γ⁰) ar radiometrisko reljefa korekciju | `summaries`, `item_assets.vv.description` |
| Kolekcijas `platform` kopsavilkumā | SENTINEL-1A, -1B, -1C (1D nav minēts, bet vienumi ar `sentinel-1d` ir) | `summaries.platform`, vienumi |
| **Pēdējais uzņēmums AOI** | **2026-10-10 04:26 UTC** (S1D, orbīta 7) — kolekcija tiek atjaunināta | `search_s1` |
| `s1:product_timeliness` | visiem 716 vienumiem `NRT-3h` | vienumu īpašības |

## Uzņēmumi AOI [P]

716 STAC vienumi = **710 uzņēmumi** (6 uzņēmumi sadalīti divos šķēlumos;
uzņēmums = datums + platforma + relatīvā orbīta). Visiem polarizācija **VV+VH**.

| Relatīvā orbīta | Virziens | Stunda (UTC) | Uzņēmumi | Pirmais | Pēdējais | AOI pārklājums (min / mediāna / max) |
|---|---|---|---|---|---|---|
| 58 | ascending | 16 | 139 | 2023-01-07 | 2026-10-07 | 0,001 / 1,000 / 1,000 |
| 160 | ascending | 15 | 140 | 2023-01-02 | 2026-10-08 | 1,000 / 1,000 / 1,000 |
| 80 | descending | 04 | 144 | 2023-01-09 | 2026-10-09 | 1,000 / 1,000 / 1,000 |
| 7 | descending | 04 | 142 | 2023-01-04 | 2026-10-10 | 0,810 / 0,884 / 0,955 |
| 153 | descending | 04 | 145 | 2023-01-02 | 2026-10-08 | 0,690 / 0,808 / 0,905 |

- AOI pārklājums = uzņēmuma footprint ∩ AOI / AOI (WGS84). Orbītas **7 un 153 nekad
  nepārklāj visu AOI** (AOI ir joslas malā) — tās var izmantot tikai pārklātajai daļai.
- Orbītā 58 viens uzņēmums (2024-12-03) pārklāj tikai 0,1 % AOI, vairāki — 99,8 %.

| Platforma | Pirmais AOI | Pēdējais AOI | Uzņēmumi |
|---|---|---|---|
| sentinel-1a | 2023-01-02 | 2026-06-29 | 505 |
| sentinel-1c | 2025-03-29 | 2026-10-09 | 148 |
| sentinel-1d | 2026-05-12 | 2026-10-10 | 57 |

### Uzņēmumi pa mēnešiem (visas orbītas, arī daļēji pārklājošās)

Kolonnas S1a/S1c/S1d — pa platformām; 58A, 160A (ascending), 80D, 7D, 153D
(descending) — pa relatīvajām orbītām.

| Mēnesis | S1a | S1c | S1d | 58A | 160A | 80D | 7D | 153D | kopā |
|---|---|---|---|---|---|---|---|---|---|
| 2023-01 | 14 | 0 | 0 | 3 | 3 | 2 | 3 | 3 | 14 |
| 2023-02 | 10 | 0 | 0 | 2 | 2 | 2 | 2 | 2 | 10 |
| 2023-03 | 13 | 0 | 0 | 2 | 3 | 2 | 3 | 3 | 13 |
| 2023-04 | 12 | 0 | 0 | 3 | 2 | 3 | 2 | 2 | 12 |
| 2023-05 | 13 | 0 | 0 | 2 | 3 | 2 | 3 | 3 | 13 |
| 2023-06 | 11 | 0 | 0 | 2 | 2 | 3 | 2 | 2 | 11 |
| 2023-07 | 13 | 0 | 0 | 2 | 3 | 2 | 3 | 3 | 13 |
| 2023-08 | 13 | 0 | 0 | 2 | 3 | 3 | 2 | 3 | 13 |
| 2023-09 | 13 | 0 | 0 | 3 | 2 | 3 | 3 | 2 | 13 |
| 2023-10 | 11 | 0 | 0 | 1 | 3 | 2 | 3 | 2 | 11 |
| 2023-11 | 12 | 0 | 0 | 3 | 2 | 3 | 2 | 2 | 12 |
| 2023-12 | 11 | 0 | 0 | 2 | 2 | 1 | 3 | 3 | 11 |
| 2024-01 | 12 | 0 | 0 | 3 | 2 | 3 | 2 | 2 | 12 |
| 2024-02 | 8 | 0 | 0 | 2 | 2 | 1 | 1 | 2 | 8 |
| 2024-03 | 10 | 0 | 0 | 3 | 2 | 3 | 1 | 1 | 10 |
| 2024-04 | 13 | 0 | 0 | 2 | 3 | 2 | 3 | 3 | 13 |
| 2024-05 | 12 | 0 | 0 | 3 | 2 | 3 | 2 | 2 | 12 |
| 2024-06 | 13 | 0 | 0 | 2 | 3 | 2 | 3 | 3 | 13 |
| 2024-07 | 11 | 0 | 0 | 2 | 1 | 3 | 2 | 3 | 11 |
| 2024-08 | 13 | 0 | 0 | 3 | 2 | 3 | 3 | 2 | 13 |
| 2024-09 | 12 | 0 | 0 | 2 | 3 | 2 | 2 | 3 | 12 |
| 2024-10 | 12 | 0 | 0 | 3 | 2 | 3 | 2 | 2 | 12 |
| 2024-11 | 13 | 0 | 0 | 2 | 3 | 2 | 3 | 3 | 13 |
| 2024-12 | 12 | 0 | 0 | 3 | 2 | 3 | 2 | 2 | 12 |
| 2025-01 | 13 | 0 | 0 | 2 | 3 | 2 | 3 | 3 | 13 |
| 2025-02 | 11 | 0 | 0 | 2 | 2 | 3 | 2 | 2 | 11 |
| 2025-03 | 12 | 1 | 0 | 1 | 3 | 3 | 3 | 3 | 13 |
| 2025-04 | 12 | 8 | 0 | 3 | 2 | 5 | 5 | 5 | 20 |
| 2025-05 | 13 | 11 | 0 | 5 | 5 | 4 | 5 | 5 | 24 |
| 2025-06 | 11 | 13 | 0 | 4 | 5 | 5 | 5 | 5 | 24 |
| 2025-07 | 13 | 10 | 0 | 5 | 5 | 5 | 4 | 4 | 23 |
| 2025-08 | 13 | 14 | 0 | 5 | 6 | 5 | 5 | 6 | 27 |
| 2025-09 | 12 | 13 | 0 | 5 | 5 | 5 | 5 | 5 | 25 |
| 2025-10 | 13 | 13 | 0 | 5 | 5 | 6 | 5 | 5 | 26 |
| 2025-11 | 13 | 12 | 0 | 5 | 5 | 5 | 5 | 5 | 25 |
| 2025-12 | 13 | 0 | 0 | 2 | 3 | 2 | 3 | 3 | 13 |
| 2026-01 | 11 | 0 | 0 | 3 | 1 | 3 | 2 | 2 | 11 |
| 2026-02 | 10 | 0 | 0 | 2 | 2 | 2 | 1 | 3 | 10 |
| 2026-03 | 13 | 0 | 0 | 3 | 2 | 3 | 3 | 2 | 13 |
| 2026-04 | 12 | 0 | 0 | 2 | 3 | 1 | 3 | 3 | 12 |
| 2026-05 | 12 | 6 | 8 | 5 | 4 | 6 | 6 | 5 | 26 |
| 2026-06 | 11 | 5 | 9 | 6 | 6 | 4 | 4 | 5 | 25 |
| 2026-07 | 0 | 12 | 11 | 5 | 4 | 5 | 5 | 4 | 23 |
| 2026-08 | 0 | 13 | 11 | 5 | 5 | 5 | 4 | 5 | 24 |
| 2026-09 | 0 | 12 | 13 | 5 | 5 | 5 | 5 | 5 | 25 |
| 2026-10 | 0 | 5 | 5 | 2 | 2 | 2 | 2 | 2 | 10 |

**Pārklājuma izmaiņas** (no tabulas, [P]):
- 2023-01 … 2025-02: tikai S1A → katrā orbītā 1–3 uzņēmumi mēnesī (12 dienu atkārtojums).
- 2025-04 … 2025-11: S1A + S1C → 4–6 uzņēmumi mēnesī katrā orbītā (6 dienu atkārtojums).
- **2025-12 … 2026-04: S1C AOI nav neviena uzņēmuma** — atkal tikai S1A. Cēlonis nav
  zināms [N: S1C darbības pārtraukums vai kataloga robs; nav pārbaudīts ESA avotos;
  lietotāja lēmums 2026-10-11 — atstāt kā pieņēmumu].
- 2026-05 … 2026-06: S1A + S1C + S1D.
- **No 2026-07 S1A AOI vairs nav** (pēdējais 2026-06-29); turpina S1C + S1D, kopā ~5
  uzņēmumi mēnesī katrā orbītā. **[P — avots: lietotājs, 2026-10-11]** Tās ir oficiāli
  ESA plānotās konstelācijas izmaiņas: S1A izslēgšana 29.06.2026 un S1C manevrs jūnija
  otrajā pusē; paliek S1C + S1D. Avoti: https://dataspace.copernicus.eu/node/3176,
  https://dataspace.copernicus.eu/node/3949 (avotus pats neatvēru).
- Ziemas mēnešos 2025/26 (dec.–apr.) — vienīgi S1A, t. i., 1–3 uzņēmumi orbītā mēnesī:
  ja vētra būtu šajā periodā, „~5 pirms + ~5 pēc“ vienā orbītā aptvertu ~2 mēnešus
  katrā pusē.

## Izšķirtspēja, CRS, vērtības [P]

Pārbaudīts ar vienu uzņēmumu `S1D_IW_GRDH_1SDV_20260802T160328_..._rtc` (2026-08-02,
S1D, orbīta 58 ascending), parakstīts ar `planetary_computer.sign`.

| Īpašība | Vērtība |
|---|---|
| Natīvā CRS | EPSG:32635 (UTM 35N); visiem vienumiem 32635, izņemot 1 vienumu 32634 |
| Pikselis | 10 × 10 m, float32, COG ar pārskatiem 2…64 |
| Nodata | −32768 (`raster:bands.nodata`) |
| Vērtības | **lineāra** γ⁰ (nav dB) |
| 1 × 1 km izgriezums AOI centrā (natīvi) VV | min 0,009, p1 0,030, mediāna 0,143 (−8,4 dB), p99 0,444, max 0,790; 0 nodata |
| tas pats VH | min 0,004, p1 0,010, mediāna 0,041 (−13,9 dB), p99 0,125, max 0,202; 0 nodata |
| Ielāde ar `odc.stac.load` uz EPSG:3059 10 m (AOI režģis 500 × 500, bilineāri) | VV mediāna 0,140, VH 0,040; 0 NaN |

**Svarīgi par nodata [P]:** daļēji pārklājošā orbītā 7 (2026-08-05, S1C) `odc.stac.load`
uz AOI režģi atstāja **23 286 pikseļus ar vērtību −32768 un 0 NaN** (`attrs.nodata` =
−32768). Tātad nodata **netiek automātiski pārvērsts par NaN** — modulim tas jāmaskē
pašam pirms vidējošanas, citādi lineārais vidējais tiks sabojāts.

## Secinājumi

- Kolekcija pieejama anonīmi, aptver AOI visā periodā 2023-01-01 … 2026-10-10 un tiek
  atjaunināta (pēdējais uzņēmums vakar). **Apstāšanās nosacījums nav izpildījies.**
- Pilnībā AOI pārklāj 3 orbītas: **58 A, 160 A, 80 D**; 7 D un 153 D — daļēji.
- Polarizācijas VV+VH visiem uzņēmumiem; 10 m; lineārs γ⁰ → dB pārvēršana pēc vidējošanas.
- Riski: mainīgs atkārtojuma biežums (S1C robs 2025-12…2026-04, S1A beigas 2026-06);
  viss katalogs AOI ir `NRT-3h` produkti — **zems risks** (lietotāja vērtējums
  2026-10-11: pirms/pēc kompozīti ir viena tipa; ģeometrijas precizitāte nav pārbaudīta); nodata −32768 jāmaskē manuāli; reprojicēšana no UTM 35N uz EPSG:3059
  ar bilineāru interpolāciju lineārajās vērtībās.
