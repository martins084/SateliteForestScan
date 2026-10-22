# Datu avoti (MežaSargs riska modelis)

Katram avotam: licence, versija / DOI, lejupielādes vai pārbaudes datums, nepieciešamā atsauce. Pārbaudes
detaļas — [RM_1_DATU_PARBAUDE.md](RM_1_DATU_PARBAUDE.md). **[P]** = pārbaudīts (atvērts URL / lejupielāde),
**[N]** = pieņēmums. Pārbaudes datums visiem: **2026-10-22**, ja nav norādīts citādi.

## Jau izmantoti (s2forest / s1windthrow)

| Avots | Licence | Versija / DOI | Atsauce |
|---|---|---|---|
| Sentinel-2 L2A (Earth Search `sentinel-2-c1-l2a`, Planetary Computer `sentinel-2-l2a`) | Copernicus Sentinel datu brīvā licence [N: teksts šeit nav atvērts] | STAC kolekcijas | „Contains modified Copernicus Sentinel data [gads]“ |
| Sentinel-1 RTC (Planetary Computer `sentinel-1-rtc`) | kā iepriekš [N] | STAC kolekcija | kā iepriekš |
| HRL Dominant Leaf Type 2018 (EEA ImageServer) | Copernicus Land Monitoring Service [N: licences teksts nav atvērts] | 2018 | Copernicus Land Monitoring Service |
| OpenStreetMap (Overpass) | ODbL [P iepriekš, README] | — | „© OpenStreetMap contributors“ |
| Open-Meteo vēsturiskais API | CC BY 4.0 [P] https://open-meteo.com/en/terms | — | Open-Meteo + datu avots (ERA5 / ERA5-Land), sk. zemāk |

## Pārbaudīti 1. posmā

| Avots | Licence | Versija / DOI | Atsauce |
|---|---|---|---|
| **European Forest Disturbance Atlas (EFDA)** | CC BY 4.0 [P] | **v3.0.0**, 2026-09-13, doi:10.5281/zenodo.21722408 (koncepts 10.5281/zenodo.8389085); iepriekšējā v2.1.1 doi:10.5281/zenodo.13333034 | Viana-Soto, A., Senf, C. (2025). ESSD 17(6), 2373–2404, doi:10.5194/essd-17-2373-2025; Viana-Soto, A., Mense, J. A., Kowalski, K., Pauls, J., Gieseke, F., Senf, C. (2026). Remote Sensing of Environment, in press [P: Zenodo metadati] |
| **Open-Meteo vēsturiskais API (ERA5, ERA5-Land)** | CC BY 4.0 [P] | API, modeļi `era5`, `era5_land`, `era5_seamless` | Open-Meteo; ERA5: Hersbach u. c. [N: precīza atsauce no Open-Meteo citēšanas sadaļas jāpārraksta 4. posmā]; „Generated using Copernicus Climate Change Service information“ [P, Open-Meteo lapa] |
| **ERA5-Land (Copernicus CDS)** | CC-BY [P, CDS lapa] | doi:10.24381/cds.e2161bac [P] | Copernicus C3S, ERA5-Land hourly data [N: pilnā atsauce nav atvērta] |
| **LĢIA atvērtie dati: DTM 20 m, aerolāzerskenēšanas punkti (LAS)** | „Atvērto datu licence CC BY“ (Creative Commons Attiecinājums 4.0) [P, LĢIA lapa + PDF nosaukums] | DTM: 2013–2019 skenēšana, fails 2023-12-14 [P]; LAS: 2013–2019 [P] | „Latvijas Ģeotelpiskās informācijas aģentūra“ [N: precīzs atsauces teksts licences PDF nav izlasīts] |
| **LĢIA ortofoto WMS 2022–2024 (8. cikls)** | „Free data, authorized access after signing the license“; WMS datus „cannot be modified, deleted or downloaded“ [P, LĢIA WMS lapa] | 8. cikls, 20 cm [P] | LĢIA [N] |
| **Copernicus DEM GLO-30** (Planetary Computer `cop-dem-glo-30`) | „proprietary“ STAC laukā; saite uz CSCDA ESA Mission-specific Annex [P] — licences teksts nav izlasīts [N] | GLO-30 | Copernicus DEM, © DLR / Airbus [N: precīzs teksts] |
| **Canopy Height Maps v2 (Meta / WRI)** | CC BY 4.0 [P, AWS Open Data reģistrs] | CHMv2, 2026 (`forests/v2/global/dinov3_global_chm_v2_ml3`) | „Meta and World Resources Institute (WRI) – 2026. Version 2 High Resolution Canopy Height Maps (CHMv2). Source imagery for CHM © 2016 Vantor“ [P] |
| **Norway spruce (Picea abies) potential & realized distribution, 30 m, Eiropa** | CC BY 4.0 [P] | version 3, 2022-07-25, doi:10.5281/zenodo.6961187 (v1 10.5281/zenodo.5881700) | Bonannella u. c. (2022) [N: pilnā atsauce no Zenodo apraksta jāpārraksta] |
| **RITY-2 fenoloģijas modelis** | raksts CC BY 4.0 [P] | Ogris (2020) MethodsX 7:100845, doi:10.1016/j.mex.2020.100845, PMC7076557 | Ogris u. c. (2019) Ecol. Model. 410:108775 (oriģināls, nav atvērts) |
| **PHENIPS-Clim** | raksts — WSL DORA autora manuskripts [P: lejupielādējams] | Jakoby, Lischke, Wermelinger (2019) Global Change Biology, doi:10.1111/gcb.14766 | kā norādīts |
| **PHENIPS (oriģināls)** | **slēgta piekļuve** [P: OpenAlex `is_oa: False`] | Baier, Pennerstorfer, Schopf (2007) For. Ecol. Manage. 249:171–186, doi:10.1016/j.foreco.2007.05.020 | vērtības tikai caur atvērtiem sekundāriem avotiem (Ogris 2020) |
| **SPEI metode** | raksts „bronze OA“ (OpenAlex), PDF lejupielāde atgrieza HTTP 403 [P] | Vicente-Serrano u. c. (2010) J. Climate 23(7), doi:10.1175/2009JCLI2909.1 | kā norādīts |

## Bibliotēkas (tikai pārbaudīta licence, NAV instalētas)

| Pakotne | Versija (PyPI) | Licence [P] |
|---|---|---|
| scikit-learn | 1.9.1 | BSD-3-Clause |
| lightgbm | 4.7.0 | MIT (GitHub LICENSE) |
| xgboost | 3.4.1 | Apache-2.0 |
| shap | 0.54.1 | MIT |
| spei | 0.8.2 | MIT |
| climate-indices | 3.0.0 | BSD |
| xclim | 0.62.0 | Apache-2.0 |
| pyet | 1.5.0 | MIT |
