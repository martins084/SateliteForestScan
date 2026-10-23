"""Stage 5 auxiliary sources (small files):

* GISCO NUTS 2024 level 0 / 3, 1:1M, EPSG:3035 -> cache/boundaries/
  (non-commercial use, "(c) EuroGeographics for the administrative boundaries")
* CSP tables (data: VMD) via the PxWeb API -> cache/rm5_sources/
  MEB012 forest damage by type 2013-2024, MEB010 (archive) 2013-2020,
  MEZ012 cut areas by cut type and species 2014-2025.

    python scripts/rm_fetch_sources.py
"""

from __future__ import annotations

import json
from pathlib import Path

import requests

GISCO = "https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/{}"
CSP = "https://data.stat.gov.lv/api/v1/lv/OSP_PUB/START/NOZ/ME/{}"
OWNER_TOTAL = {"code": "FOREST_OWNER", "selection": {"filter": "item", "values": ["TOTAL"]}}
TABLES = {
    "csp_MEB012.csv": ("MEB/MEB012", [OWNER_TOTAL, {"code": "FOREST_DAMAGE", "selection": {"filter": "all", "values": ["*"]}}]),
    "csp_MEB010.csv": ("A_ME/MEB010", [OWNER_TOTAL, {"code": "FOREST_DAMAGE", "selection": {"filter": "all", "values": ["*"]}}]),
    "csp_MEZ012.csv": ("MEZ/MEZ012", [OWNER_TOTAL,
                                      {"code": "FOREST_THIN", "selection": {"filter": "item", "values": ["TOTAL", "F_FL_CL", "SL_THIN", "SEL_THIN", "SW_FL"]}},
                                      {"code": "TREE_SPECIES", "selection": {"filter": "item", "values": ["TOTAL", "SPRUCE", "PINE"]}}]),
}


def main() -> None:
    b = Path("cache/boundaries")
    b.mkdir(parents=True, exist_ok=True)
    for f in ("NUTS_RG_01M_2024_3035_LEVL_3.geojson", "NUTS_RG_01M_2024_3035_LEVL_0.geojson"):
        if not (b / f).exists():
            r = requests.get(GISCO.format(f), timeout=300)
            r.raise_for_status()
            (b / f).write_bytes(r.content)
        print(b / f)
    s = Path("cache/rm5_sources")
    s.mkdir(parents=True, exist_ok=True)
    for f, (table, query) in TABLES.items():
        r = requests.post(CSP.format(table), timeout=120,
                          data=json.dumps({"query": query, "response": {"format": "csv"}}),
                          headers={"Content-Type": "application/json"})
        r.raise_for_status()
        (s / f).write_bytes(r.content)
        print(s / f)


if __name__ == "__main__":
    main()
