# S1 agrīnā signāla tests — s1_earlysignal_kalsnava

Hipotēze (Hechtl u. c. 2025, Forests 16(8):1272): pirms optiski redzama mizgraužu bojājuma atpakaļizkliede samazinās ~1 dB. Mērķi ir **S2 aizdomas** (s2forest stresa poligoni), nevis apstiprināti mizgrauži. RTC GRD datiem pilnos Kennaugh elementus (K5, K8) nevar aprēķināt; izmantoti VV, VH, K0-līdzīgā 10·log10(VV+VH) un VH − VV.

## Metode (no šīs palaišanas konfigurācijas)

- Periods 2023-01-01 … 2026-10-11, visas orbītas; uzņēmumi atrasti 710, izmantoti 529. Izslēgti: temperatūra < 0 °C uzņēmuma stundā vai sniega sega > 0 (Open-Meteo; sniega dati ir).
- Katrs uzņēmums normalizēts pret stabilā meža mediānu (VV, VH atsevišķi); vienības vērtība = mediāna pikseļos (≥ 50% derīgu).
- Kontroles: 5 stabilā meža diski katram mērķim, tāda pati platība (≥ 10 px), tā pati HRL klase, 200–2000 m, ārpus visiem suspects + 50 m. Atšķirība = mērķis − kontroļu mediāna (≥ 3 kontroles).
- Izlīdzināšana: **atpakaļvērsta** 30 dienu slīdošā mediāna (vērtība datumā t izmanto tikai (t − 30 d, t], lai vēlāks kritums neparādītos agrāk). Visas orbītas kopā; orbītu skaits ar signālu savā rindā — atsevišķa kolonna.
- Bāze: atšķirības mediāna 24–12 mēnešus pirms t_first.
- Agrīnais signāls: pirmais datums pirms t_first, kad izlīdzinātā atšķirība ≤ bāze − 0.5 dB visā 60 dienu logā (≥ 3 vērtības, ≥ 45 dienas). `max_sustained_drop` = lielākais šāds noturīgs kritums pirms t_first.
- t_last_normal (mana operacionālā definīcija no s2forest izvades, tikai lasot): pēdējais S2 datums pirms t_first ar ≥ 50 % derīgu pikseļu, kurā poligona mediānais CRSWIR z < 2,5 (tā pati sezona) vai < 1,25 (iepriekšējā sezona, ja z rastri ir); ja iepriekšējās sezonas z rastru nav — iepriekšējās sezonas pēdējais derīgais S2 datums (s2forest `onset_prev_autumn` = nē) [N].
- Placebo: 50 nejauši stabilā skujkoku meža diski ar galvenās kopas mērķu platībām un datumiem (cikliski), katram 5 kontroles; superponētajās epohās placebo josla = 13 nejauši izvēlētu pseido-mērķu mediānas 5–95 % (bootstrap).

## Uzņēmumi

Izslēgti 181 no 710: temperatūra 125, sniegs 56.

| year | 7 | 58 | 80 | 153 | 160 |
|---|---|---|---|---|---|
| 2023 | 18 | 16 | 18 | 19 | 19 |
| 2024 | 18 | 21 | 21 | 19 | 20 |
| 2025 | 39 | 37 | 39 | 38 | 39 |
| 2026 | 29 | 32 | 28 | 29 | 30 |


## Mērķi un signāli

| uid | area_ha | status | t_first | t_last_normal | t_last_normal_rule | main_group | n_controls |
|---|---|---|---|---|---|---|---|
| 2025#57 | 0.46 | persistent | 2025-05-02 | 2024-09-20 | iepr. sezonas pēdējais derīgais (z nav; onset_prev_autumn = nē) [N] | False | 5 |
| 2025#60 | 0.50 | recovered | 2025-05-30 | 2025-05-20 | z ≥ 2,5 (tā pati sezona) | False | 5 |
| 2025#61 | 0.11 | persistent | 2025-05-20 | 2025-05-12 | z ≥ 2,5 (tā pati sezona) | True | 5 |
| 2025#62 | 0.23 | persistent | 2025-05-02 | 2024-09-20 | iepr. sezonas pēdējais derīgais (z nav; onset_prev_autumn = nē) [N] | True | 5 |
| 2025#64 | 0.16 | persistent | 2025-06-04 | 2025-06-01 | z ≥ 2,5 (tā pati sezona) | True | 5 |
| 2025#71 | 0.11 | persistent | 2025-09-07 | 2025-07-14 | z ≥ 2,5 (tā pati sezona) | True | 5 |
| 2025#72 | 0.12 | persistent | 2025-05-02 | 2024-09-20 | iepr. sezonas pēdējais derīgais (z nav; onset_prev_autumn = nē) [N] | True | 5 |
| 2025#75 | 0.15 | persistent | 2025-05-02 | 2024-09-20 | iepr. sezonas pēdējais derīgais (z nav; onset_prev_autumn = nē) [N] | True | 5 |
| 2025#76 | 0.22 | persistent | 2025-05-02 | 2024-09-20 | iepr. sezonas pēdējais derīgais (z nav; onset_prev_autumn = nē) [N] | True | 5 |
| 2025#79 | 0.22 | persistent | 2025-09-07 | 2025-07-14 | z ≥ 2,5 (tā pati sezona) | True | 5 |
| 2025#80 | 0.19 | persistent | 2025-07-11 | 2025-06-14 | z ≥ 2,5 (tā pati sezona) | True | 5 |
| 2025#82 | 0.11 | persistent | 2025-05-02 | 2024-09-20 | iepr. sezonas pēdējais derīgais (z nav; onset_prev_autumn = nē) [N] | True | 5 |
| 2026#25 | 0.12 | persistent | 2026-05-05 | 2025-09-25 | iepr. sezona, z ≥ 1.25 | True | 5 |
| 2026#26 | 0.10 | persistent | 2026-05-05 | 2025-07-14 | iepr. sezona, z ≥ 1.25 | True | 5 |
| 2026#31 | 0.11 | persistent | 2026-05-05 | 2025-07-11 | iepr. sezona, z ≥ 1.25 | True | 5 |


### VV (placebo P95 noturīgam kritumam: 0.96 dB)

| uid | main_group | baseline_db | baseline_n | signal_date | lead_vs_t_first_months | lead_vs_t_last_normal_months | before_t_last_normal | max_sustained_drop_db | > placebo P95 | orbits_with_signal | n_orbits |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2025#57 | False | 0.14 | 95 | NaT |  |  | False | 0.50 | False | 2 | 5 |
| 2025#60 | False | -1.78 | 75 | NaT |  |  | False | 0.33 | False | 0 | 5 |
| 2025#61 | True | 0.98 | 92 | 2025-05-16 | 0.10 | -0.16 | False | 1.01 | True | 3 | 5 |
| 2025#62 | True | 0.41 | 95 | NaT |  |  | False | 0.34 | False | 1 | 5 |
| 2025#64 | True | 0.82 | 79 | 2024-09-22 | 8.34 | 8.25 | True | 0.62 | False | 4 | 5 |
| 2025#71 | True | 1.72 | 82 | NaT |  |  | False | 0.35 | False | 1 | 5 |
| 2025#72 | True | 1.20 | 95 | NaT |  |  | False | 0.01 | False | 4 | 5 |
| 2025#75 | True | 0.79 | 95 | NaT |  |  | False | 0.50 | False | 2 | 5 |
| 2025#76 | True | 0.68 | 95 | 2023-09-30 | 19.02 | 11.66 | True | 0.95 | False | 2 | 5 |
| 2025#79 | True | 1.46 | 92 | 2025-01-29 | 7.23 | 5.42 | True | 0.95 | False | 5 | 5 |
| 2025#80 | True | 0.11 | 75 | 2024-10-30 | 8.31 | 7.42 | True | 0.90 | False | 1 | 5 |
| 2025#82 | True | 0.69 | 92 | NaT |  |  | False | 0.24 | False | 3 | 5 |
| 2026#25 | True | 0.84 | 107 | NaT |  |  | False | 0.35 | False | 4 | 5 |
| 2026#26 | True | 1.07 | 107 | 2025-08-31 | 8.08 | -1.61 | False | 0.97 | True | 3 | 5 |
| 2026#31 | True | 0.34 | 94 | NaT |  |  | False | 0.33 | False | 3 | 5 |


### VH (placebo P95 noturīgam kritumam: 0.72 dB)

| uid | main_group | baseline_db | baseline_n | signal_date | lead_vs_t_first_months | lead_vs_t_last_normal_months | before_t_last_normal | max_sustained_drop_db | > placebo P95 | orbits_with_signal | n_orbits |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2025#57 | False | -0.07 | 95 | NaT |  |  | False | 0.29 | False | 2 | 5 |
| 2025#60 | False | -1.03 | 75 | NaT |  |  | False | -0.01 | False | 1 | 5 |
| 2025#61 | True | 1.07 | 92 | 2024-08-12 | 9.20 | 8.94 | True | 1.26 | True | 4 | 5 |
| 2025#62 | True | -0.14 | 95 | NaT |  |  | False | 0.26 | False | 2 | 5 |
| 2025#64 | True | 0.59 | 79 | NaT |  |  | False | 0.27 | False | 2 | 5 |
| 2025#71 | True | 2.33 | 82 | 2024-11-28 | 9.26 | 7.46 | True | 1.02 | True | 3 | 5 |
| 2025#72 | True | 0.33 | 95 | 2024-06-27 | 10.12 | 2.76 | True | 0.58 | False | 3 | 5 |
| 2025#75 | True | 0.01 | 95 | NaT |  |  | False | -0.03 | False | 1 | 5 |
| 2025#76 | True | 0.29 | 95 | 2024-11-11 | 5.62 | -1.74 | False | 0.52 | False | 2 | 5 |
| 2025#79 | True | 1.60 | 92 | 2024-11-28 | 9.26 | 7.46 | True | 0.62 | False | 4 | 5 |
| 2025#80 | True | -0.35 | 75 | NaT |  |  | False | 0.25 | False | 2 | 5 |
| 2025#82 | True | 0.21 | 92 | NaT |  |  | False | -0.02 | False | 2 | 5 |
| 2026#25 | True | -0.25 | 107 | NaT |  |  | False | 0.27 | False | 1 | 5 |
| 2026#26 | True | 0.70 | 107 | 2025-07-28 | 9.20 | -0.49 | False | 0.51 | False | 5 | 5 |
| 2026#31 | True | -0.64 | 94 | 2025-01-29 | 15.11 | 5.32 | True | 0.51 | False | 2 | 5 |


### K0-līdzīgā 10·log10(VV+VH) (placebo P95 noturīgam kritumam: 0.71 dB)

| uid | main_group | baseline_db | baseline_n | signal_date | lead_vs_t_first_months | lead_vs_t_last_normal_months | before_t_last_normal | max_sustained_drop_db | > placebo P95 | orbits_with_signal | n_orbits |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2025#57 | False | 0.06 | 95 | 2025-03-11 | 1.68 | -5.68 | False | 0.77 | True | 2 | 5 |
| 2025#60 | False | -1.44 | 75 | NaT |  |  | False | 0.05 | False | 0 | 5 |
| 2025#61 | True | 0.93 | 92 | NaT |  |  | False | 0.26 | False | 3 | 5 |
| 2025#62 | True | 0.14 | 95 | NaT |  |  | False | 0.31 | False | 2 | 5 |
| 2025#64 | True | 0.75 | 79 | NaT |  |  | False | 0.19 | False | 4 | 5 |
| 2025#71 | True | 2.07 | 82 | 2024-10-11 | 10.84 | 9.03 | True | 1.18 | True | 1 | 5 |
| 2025#72 | True | 0.73 | 95 | NaT |  |  | False | 0.00 | False | 4 | 5 |
| 2025#75 | True | 0.26 | 95 | NaT |  |  | False | 0.42 | False | 2 | 5 |
| 2025#76 | True | 0.39 | 95 | NaT |  |  | False | 0.18 | False | 2 | 5 |
| 2025#79 | True | 1.44 | 92 | 2024-11-28 | 9.26 | 7.46 | True | 0.74 | True | 3 | 5 |
| 2025#80 | True | -0.14 | 75 | NaT |  |  | False | 0.36 | False | 0 | 5 |
| 2025#82 | True | 0.47 | 92 | NaT |  |  | False | 0.47 | False | 4 | 5 |
| 2026#25 | True | 0.23 | 107 | NaT |  |  | False | 0.16 | False | 1 | 5 |
| 2026#26 | True | 0.90 | 107 | 2025-07-21 | 9.43 | -0.26 | False | 0.84 | True | 2 | 5 |
| 2026#31 | True | -0.25 | 94 | NaT |  |  | False | 0.17 | False | 2 | 5 |


### VH − VV (placebo P95 noturīgam kritumam: 1.08 dB)

| uid | main_group | baseline_db | baseline_n | signal_date | lead_vs_t_first_months | lead_vs_t_last_normal_months | before_t_last_normal | max_sustained_drop_db | > placebo P95 | orbits_with_signal | n_orbits |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2025#57 | False | -0.04 | 95 | NaT |  |  | False | 0.09 | False | 1 | 5 |
| 2025#60 | False | 0.82 | 75 | NaT |  |  | False | 0.07 | False | 1 | 5 |
| 2025#61 | True | 0.43 | 92 | NaT |  |  | False | 0.26 | False | 3 | 5 |
| 2025#62 | True | -0.32 | 95 | NaT |  |  | False | -0.01 | False | 3 | 5 |
| 2025#64 | True | -0.30 | 79 | NaT |  |  | False | -0.17 | False | 1 | 5 |
| 2025#71 | True | 0.23 | 82 | NaT |  |  | False | 0.34 | False | 2 | 5 |
| 2025#72 | True | -0.67 | 95 | NaT |  |  | False | -0.02 | False | 4 | 5 |
| 2025#75 | True | -1.12 | 95 | NaT |  |  | False | -0.28 | False | 1 | 5 |
| 2025#76 | True | -0.30 | 95 | NaT |  |  | False | 0.43 | False | 2 | 5 |
| 2025#79 | True | 0.23 | 92 | 2025-07-20 | 1.58 | -0.23 | False | 0.60 | False | 2 | 5 |
| 2025#80 | True | 0.22 | 75 | NaT |  |  | False | 0.23 | False | 2 | 5 |
| 2025#82 | True | -0.58 | 92 | NaT |  |  | False | -0.15 | False | 2 | 5 |
| 2026#25 | True | -0.84 | 107 | NaT |  |  | False | 0.23 | False | 3 | 5 |
| 2026#26 | True | -0.30 | 107 | 2024-11-30 | 17.08 | 7.39 | True | 0.56 | False | 1 | 5 |
| 2026#31 | True | -0.72 | 94 | NaT |  |  | False | 0.32 | False | 2 | 5 |


## Kopsavilkums

| var | group | n | n_signal | share_signal | n_before_t_last_normal | share_before_t_last_normal | n_drop_above_placebo_p95 | placebo_p95_drop_db |
|---|---|---|---|---|---|---|---|---|
| vv | galvenā (13) | 13 | 6 | 0.46 | 4 | 0.31 | 2 | 0.96 |
| vv | visi (15) | 15 | 6 | 0.40 | 4 | 0.27 | 2 | 0.96 |
| vv | placebo (pseudo) | 50 | 13 | 0.26 | 10 | 0.20 | 3 | 0.96 |
| vh | galvenā (13) | 13 | 7 | 0.54 | 5 | 0.38 | 2 | 0.72 |
| vh | visi (15) | 15 | 7 | 0.47 | 5 | 0.33 | 2 | 0.72 |
| vh | placebo (pseudo) | 50 | 14 | 0.28 | 11 | 0.22 | 3 | 0.72 |
| k0 | galvenā (13) | 13 | 3 | 0.23 | 2 | 0.15 | 3 | 0.71 |
| k0 | visi (15) | 15 | 4 | 0.27 | 2 | 0.13 | 4 | 0.71 |
| k0 | placebo (pseudo) | 50 | 7 | 0.14 | 6 | 0.12 | 3 | 0.71 |
| vh_minus_vv | galvenā (13) | 13 | 2 | 0.15 | 1 | 0.08 | 0 | 1.08 |
| vh_minus_vv | visi (15) | 15 | 2 | 0.13 | 1 | 0.07 | 0 | 1.08 |
| vh_minus_vv | placebo (pseudo) | 50 | 14 | 0.28 | 8 | 0.16 | 3 | 1.08 |


Attēli: `figures/superposed_epochs.png`, `figures/targets_k0.png`, `figures/targets_vh.png`. Tabulas: `tables/`.
