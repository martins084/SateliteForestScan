"""mezasargs_risk stage 5a: LVM open damage polygons (synthetic data)."""

from datetime import date
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Polygon, box

from mezasargs_risk.config import LvmConfig
from mezasargs_risk.lvm import annual, inventory, meb011_compare, target_cells

X0, Y0 = 500_000.0, 300_000.0   # LKS-92 TM


def _cfg():
    return LvmConfig(damage=Path("d.zip"), damage_snapshot=date(2025, 4, 27), land_units=Path("l.zip"))


def _damage():
    geoms = [box(X0, Y0, X0 + 100, Y0 + 100),            # 1 ha, 620, 2023
             box(X0 + 200, Y0, X0 + 250, Y0 + 50),       # 0.25 ha, 620, 2023
             box(X0 + 6000, Y0, X0 + 6100, Y0 + 100),    # 1 ha, 620, 2024, other 5 km cell
             box(X0, Y0 + 300, X0 + 100, Y0 + 400),      # 1 ha, 100, 2823 (year error)
             Polygon(),                                  # empty geometry
             Polygon([(X0, Y0), (X0 + 10, Y0 + 10), (X0 + 10, Y0), (X0, Y0 + 10)])]  # bow-tie (invalid)
    g = gpd.GeoDataFrame({"DISTRBYEAR": [2023, 2023, 2024, 2823, 2020, 2020],
                          "DAMAGESUBT": [620, 620, 620, 100, 620, 999]}, geometry=geoms, crs=3059)
    g["year_raw"] = g["DISTRBYEAR"]
    g["year"] = g["DISTRBYEAR"].astype("Int64")
    g["subtype"] = g["DAMAGESUBT"].astype("Int64")
    g["empty"] = g.geometry.isna() | g.geometry.is_empty
    g["valid"] = ~g["empty"] & g.geometry.is_valid
    g["ha"] = g.area.where(~g["empty"]) / 1e4
    return g


def test_inventory_flags_problems():
    g = _damage()
    land = gpd.GeoDataFrame(geometry=[box(X0 - 10, Y0 - 10, X0 + 1000, Y0 + 1000)], crs=3059)
    inv = inventory(g, land, _cfg()).set_index("check")["value"]
    assert inv["geometry null/empty"] == 1
    assert inv["geometry invalid (non-empty)"] == 1
    assert inv["DISTRBYEAR outside 2000-2025"] == 1 and inv["DISTRBYEAR values outside range"] == "2823"
    assert inv["DAMAGESUBT not in classifier"] == 1
    assert float(inv["polygon point inside LVM land units"]) == pytest.approx(4 / 5)   # the 2024 polygon is outside


def test_annual_and_target_cells():
    g = _damage()
    a = annual(g, _cfg()).set_index(["year", "subtype"])
    assert a.loc[(2023, 620), "n"] == 2 and a.loc[(2023, 620), "ha"] == pytest.approx(1.25)
    assert 2823 not in a.index.get_level_values("year")
    t = target_cells(g, _cfg(), years=(2023, 2024))
    assert list(t["n"]) == [1, 1]                    # the 0.25 ha polygon is below min_target_ha
    assert set(t["x0"]) == {500_000, 505_000}


def test_meb011_compare_maps_regions():
    reg = pd.DataFrame({"lvm_land_ha": [100.0], 2023: [10.0], 2024: [20.0]}, index=["Kurzeme"])
    reg.index.name = "NAME_LATN"
    m = pd.DataFrame({"Meža īpašuma forma": ["Valsts meži"] * 3,
                      "Teritoriālā vienība": ["Kurzemes statistiskais reģions (no 01.01.2024.)"] * 2
                      + ["Kurzemes statistiskais reģions (līdz 01.01.2024.)"],
                      "Meža bojājumi": ["..kaitēkļu izraisīti stumbru bojājumi"] * 3,
                      "indicator": ["Bojā aizgājušās audzes, ha"] * 3, "year": [2023, 2024, 2023],
                      "value": [1.0, 2.0, 99.0]})
    out = meb011_compare(reg, m).set_index(["region", "year"])
    assert out.loc[("Kurzeme", 2024), "lvm_ha"] == 20.0
    assert out.loc[("Kurzeme", 2023), "csp_state_dead_stands_ha"] == 1.0   # old boundaries ignored
