"""mezasargs_risk stage 4: Open-Meteo ERA5 handling (recorded response, no network) and water balance."""

import json
import shutil
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

from mezasargs_risk import waterbalance, weather
from mezasargs_risk.config import ClimateConfig, OpenMeteoConfig

SAMPLE = Path(__file__).parent / "data" / "openmeteo_era5_daily_sample.json"   # recorded 2026-10-29


def test_parse_recorded_response():
    js = json.loads(SAMPLE.read_text(encoding="utf-8"))
    df, meta = weather.parse_daily(js, OpenMeteoConfig().daily)
    assert list(df.columns) == ["tmax", "tmin", "tmean", "precip", "et0", "daylight_s"]
    assert len(df) == 4 and df.index[0] == pd.Timestamp("2023-04-18")
    assert df.loc["2023-04-20", "tmax"] == 15.8
    assert meta["lat_returned"] == 56.75 and meta["lon_returned"] == 25.75 and meta["elevation_m"] == 168.0
    bad = json.loads(json.dumps(js))
    del bad["daily"]["et0_fao_evapotranspiration"]
    with pytest.raises(weather.SchemaError):
        weather.parse_daily(bad, OpenMeteoConfig().daily)
    bad = json.loads(json.dumps(js))
    bad["daily_units"]["temperature_2m_max"] = "°F"
    with pytest.raises(weather.SchemaError):
        weather.parse_daily(bad, OpenMeteoConfig().daily)
    gap = json.loads(json.dumps(js))
    gap["daily"]["precipitation_sum"][1] = None
    df, _ = weather.parse_daily(gap, OpenMeteoConfig().daily)
    assert np.isnan(df["precip"].iloc[1])


def test_cache_is_used_without_network(tmp_path):
    om = OpenMeteoConfig()
    p = weather.cache_path(tmp_path, om, 25.75, 56.75, date(2023, 4, 18), date(2023, 4, 21))
    p.parent.mkdir(parents=True)
    shutil.copy(SAMPLE, p)
    js = weather.fetch(25.75, 56.75, date(2023, 4, 18), date(2023, 4, 21), om, tmp_path, budget=None)
    assert js["latitude"] == 56.75
    with pytest.raises(weather.BudgetExceeded):          # not cached and no budget -> no request
        weather.fetch(25.75, 56.75, date(2023, 4, 22), date(2023, 4, 23), om, tmp_path, budget=None)


def test_nodes_windows_and_weights():
    assert weather.nearest_node(25.8688, 56.6771) == (25.75, 56.75)
    assert weather.nearest_node(24.13, 56.87) == (24.25, 56.75)
    n = weather.era5_nodes(box(25.0, 56.0, 25.3, 56.2), buffer_cells=1)
    assert n["core"].sum() == 4 and len(n) == 16 and n["node"].is_unique
    assert weather.call_weight(14, 6) == 1 and weather.call_weight(183, 6) == pytest.approx(183 / 14)
    assert weather.call_weight(14, 15) == pytest.approx(1.5)              # pricing page example
    w = weather.windows(ClimateConfig(), today=date(2026, 10, 29))
    assert w[0] == (date(1991, 4, 1), date(1991, 9, 30)) and len(w) == 36
    assert (date(2018, 1, 1), date(2018, 10, 31)) in w and w[-1] == (date(2026, 1, 1), date(2026, 10, 23))


def test_budget_waits_and_persists(tmp_path):
    t = [1000.0]
    slept = []
    om = OpenMeteoConfig(max_per_minute=10, max_per_hour=15, max_per_day=100)
    b = weather.Budget(tmp_path / "ledger.csv", om, max_wait_s=7200, clock=lambda: t[0],
                       sleep=lambda s: (slept.append(s), t.__setitem__(0, t[0] + s)))
    b.spend(6)
    assert b.wait_s(4) == 0 and b.wait_s(5) == pytest.approx(60)         # minute cap
    b.spend(5)                                                            # waits ~60 s
    assert slept and slept[0] == pytest.approx(61)
    assert b.wait_s(5) == pytest.approx(3600 - 61)                        # hour cap (11 used)
    b2 = weather.Budget(tmp_path / "ledger.csv", om, max_wait_s=60, clock=lambda: t[0])
    assert b2.used(3600) == 11                                            # ledger reloaded
    with pytest.raises(weather.BudgetExceeded):
        b2.spend(5)


def _wb_days(years, precip):
    idx = pd.date_range(f"{years[0]}-01-01", f"{years[1]}-12-31", freq="D")
    return pd.DataFrame({"precip": [precip(d.year) for d in idx], "et0": 3.0}, index=idx)


def test_water_balance_and_anomaly():
    d = _wb_days((1991, 2022), lambda y: 2.0 if y % 2 else 3.0)          # CWB IV-IX: -183 or 0 mm
    s = waterbalance.seasonal(d, (4, 9))
    assert s.loc[s.year == 1991, "cwb_mm"].item() == pytest.approx(-183.0)
    assert s.loc[s.year == 1992, "cwb_mm"].item() == pytest.approx(0.0)
    a = waterbalance.anomaly(s, (1991, 2020))
    ref = np.array([-183.0 if y % 2 else 0.0 for y in range(1991, 2021)])
    assert a.loc[a.year == 2021, "cwb_z"].item() == pytest.approx((-183 - ref.mean()) / ref.std(ddof=1))
    gap = d.drop(pd.Timestamp("2021-07-01"))
    s2 = waterbalance.seasonal(gap, (4, 9))
    assert not s2.loc[s2.year == 2021, "complete"].item() and np.isnan(s2.loc[s2.year == 2021, "cwb_mm"].item())
    with pytest.raises(ValueError):
        waterbalance.anomaly(waterbalance.seasonal(d.drop(pd.Timestamp("1995-05-05")), (4, 9)), (1991, 2020))
