# Lauka un drona pārbaude — instrukcija

## 1. Sagatavošana

```bash
python -m uv run s2forest field-prepare configs/test_kalsnava.yaml --id 25 --id 26 --id 31
```

Rezultāts mapē `output/<run_name>/field_check/`:

| Fails | Saturs |
|---|---|
| `field_check_<gads>.gpkg` | slāņi `targets` (poligoni) un `points` (punkts katra mērķa iekšpusē) |
| `field_check_<gads>_targets.kml` | poligoni drona lidojuma plānošanai |
| `field_check_<gads>_points.kml` | punkti GPS navigācijai |
| `field_check_<gads>.csv` | mērķu saraksts ar koordinātām (WGS84) un aprakstiem |
| `lauka_veidlapa_<gads>.csv` | veidlapas veidne (viena rinda katram mērķim) |

Mērķi (2026, Kalsnava):

| ID | Veids | Avots | Piezīme |
|---|---|---|---|
| F01 | stress | poligons #25 | izmaiņa starp 2025. g. oktobri un 2026. g. maiju |
| F02 | stress | poligons #26 | izmaiņa sākusies 2025. g. rudenī |
| F03 | stress | poligons #31 | izmaiņa sākusies 2025. g. rudenī |
| F04 | cirtes mala | T004 | augstākā riska cirtes mala (risks 0,81) |
| F05 | kontrole | — | vesels skujkoku mežs (z ≈ 0), bāzes NDVI/CRSWIR līmenis kā F01–F03 |

**Kontroles vieta** izvēlēta automātiski: analizēts skujkoku mežs bez anomālijas,
2026. gada z mediāna ≈ 0 un maksimums < 1,5, ≥ 100 m no jebkura poligona vai
cirtes malas, ≥ 50 m no ceļa, 4 × 4 pikseļi (0,16 ha); no kandidātiem — tas, kura
bāzes vasaras NDVI un CRSWIR ir tuvākais pārbaudāmajiem stresa poligoniem.
Sugas un vecuma dati valsts mežam nav pieejami, tāpēc **uz vietas jāpārliecinās**,
ka audze ir līdzīga (egle, līdzīgs vecums). Ja nav, atzīmēt `piezimes`.

## 2. Veidlapa (`lauka_veidlapa_<gads>.csv`)

Atvērt ar Excel / LibreOffice (atdalītājs `;`, UTF-8). Viena rinda katram mērķim;
ja vienā mērķī apskatītas vairākas vietas, var pievienot rindas ar to pašu `merka_id`.

| Kolonna | Vērtība |
|---|---|
| `merka_id` | F01…F05 (jau aizpildīts) |
| `datums` | 2026-10-15 vai 15.10.2026 |
| `laiks` | 14:30 |
| `gps_platums`, `gps_garums` | WGS84 grādos (piem., 56.69209, 25.89034) |
| `gps_precizitate_m` | metri |
| `apsekotajs` | vārds |
| `apskatito_koku_skaits` | vesels skaitlis |
| `koki_ar_urbumu_miltiem` | koku skaits ar urbumu miltiem (brūni milti mizas spraugās, pie stumbra pamata) |
| `koki_ar_sveku_tecem` | koku skaits ar sveķu tecēm |
| `koki_ar_ieejas_atverem` | koku skaits ar ieejas atverēm mizā (~2–3 mm) |
| `koki_ar_mizas_lobisanos` | koku skaits ar mizas lobīšanos / dzeņu kaltiem |
| `vainaga_krasa` | `zala`, `dzeltenzala`, `sarkanbruna`, `peleka`, `jaukta` |
| `foto_numuri` | piem., IMG_0123–IMG_0131 |
| `secinajums` | `mizgrauzi`, `cits_bojajums`, `vesels`, `nav_skaidrs` |
| `cita_bojajuma_veids` | ja `cits_bojajums` (vējgāze, sakņu trupe, sausums, ciršana u. c.) |
| `piezimes` | brīvs teksts (audzes suga/vecums, ja atšķiras; grāvis; u. c.) |

## 3. Ielasīšana

```bash
python -m uv run s2forest field-import configs/test_kalsnava.yaml lauka_veidlapa_2026.csv
```

Komanda pārbauda vērtības (nepareizi datumi, secinājumi, krāsas vai skaitļi tiek
uzrādīti, un ielasīšana apstājas), saglabā `field_references_<gads>.gpkg` un izdrukā
tabulu **prognoze (stress / cirtes mala / kontrole) pret lauka secinājumu**.

Validācijai ar `s2forest validate` konfigurācijā:

```yaml
reference:
  path: ../output/test_kalsnava/field_check/field_references_2026.gpkg
  id_field: merka_id
  date_field: datums          # notikuma datums = apsekošanas datums
  reason_field: secinajums
  reason_values: [mizgrauzi]
  description: "Lauka pārbaude 2026 (5 mērķi, ieskaitot kontroli)"
```

Ar 5 mērķiem tas ir **pārbaudes protokols, nevis statistiska validācija**; galvenais
rezultāts ir prognozes/novērojuma tabula katram mērķim.
