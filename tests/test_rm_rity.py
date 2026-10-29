"""mezasargs_risk stage 4: RITY-2 (Ogris 2020) and the PHENIPS-Clim threshold check, synthetic data."""

import numpy as np
import pandas as pd
import pytest

from mezasargs_risk import rity


def _year(tmax, tmin, tmean, daylight_h=15.0, year=2023):
    idx = pd.date_range(f"{year}-01-01", f"{year}-10-31", freq="D")
    f = lambda v: v(idx) if callable(v) else np.full(len(idx), float(v))  # noqa: E731
    return pd.DataFrame({"tmax": f(tmax), "tmin": f(tmin), "tmean": f(tmean),
                         "daylight_s": f(daylight_h) * 3600}, index=idx)


def test_effective_bark_temperature():
    assert rity.bteff([20.0])[0] == pytest.approx(11.7)                 # (7) BT - 8.3
    assert rity.bteff([rity.T_O])[0] == pytest.approx(22.1)             # (7) includes T_O
    assert rity.bteff([rity.T_O + 1e-9])[0] == pytest.approx(21.68, abs=0.01)   # (8) just above T_O
    assert rity.bteff([rity.DT_U - 1e-6])[0] == pytest.approx(0.014, abs=0.002)  # (8) near DT_U
    assert list(rity.bteff([8.3, 38.9, 45.0, -5.0])) == [0, 0, 0, 0]    # (9)
    assert np.isnan(rity.bteff([np.nan])[0])
    # (4)-(6) and (1)-(3)
    assert rity.bark([20.0], "mean")[0] == pytest.approx(-0.48 + 1.03 * 20)
    assert rity.forest_air([20.0], "max")[0] == pytest.approx(1.03 + 0.86 * 20)


def test_known_thermal_sum_gives_known_swarming_day():
    # I_max = 18.3 from 7 March: 10 dd per day -> 53 dd on day 6 (12 March), 155.6 dd on day 16 (22 March)
    r = rity.rity2(_year(18.3, 8.0, 13.0), 2023)
    assert r["complete"]
    assert r["swarming_doy"] == pd.Timestamp("2023-03-12").dayofyear
    assert r["infestation_doy"] == pd.Timestamp("2023-03-22").dayofyear
    # flight threshold: cold (I_max 14.0 <= 14.5) until 30 April, the sum is reached long before
    warm_from_may = lambda idx: np.where(idx < pd.Timestamp("2023-05-01"), 14.0, 20.0)  # noqa: E731
    r = rity.rity2(_year(warm_from_may, 8.0, 12.0), 2023)
    assert r["swarming_doy"] == r["infestation_doy"] == pd.Timestamp("2023-05-01").dayofyear


def test_generation_counting():
    be = np.full(320, rity.K_DD / 128)                  # Tsum_F1 = (i + 1) / 128 (exact in binary)
    on = np.ones(320, bool)
    g = rity.generations(be, on, on, infest=0)
    assert g["F1"] == (0, pytest.approx(2.5))
    assert g["F2"] == (128, pytest.approx(1.5))         # starts when Tsum_F1 > 1
    assert g["F3"] == (256, pytest.approx(0.5))         # Tsum_F1 > 2 (15); 0.5 < 0.6 -> not counted
    assert g["S1"] == (64, pytest.approx(2.0)) and g["S2"] == (192, pytest.approx(1.0)) and "S3" not in g
    short = np.arange(320) < 150                        # day length < 14.5 h from day 150
    g = rity.generations(be, on, short, infest=0)
    assert g["F2"][0] == 128 and g["F3"][0] is None and "S2" not in g
    # counting with the 0.6 hibernation rule inside rity2: constant 20 deg C mean, 25 max
    r = rity.rity2(_year(25.0, 15.0, 20.0), 2023)
    days = (pd.Timestamp("2023-10-31") - pd.Timestamp("2023-03-16")).days + 1   # infestation 16 March
    assert r["infestation_doy"] == pd.Timestamp("2023-03-16").dayofyear
    assert r["tsum_F1"] == pytest.approx(days * (-0.48 + 1.03 * 20 - 8.3) / 557, abs=1e-3)
    assert r["n_filial"] == 3
    ri = rity.rity2(_year(25.0, 15.0, 20.0), 2023, inca=True)   # (1)-(3): cooler forest air
    assert ri["tsum_F1"] < r["tsum_F1"] and ri["swarming_doy"] == r["swarming_doy"]


def test_incomplete_year_and_phenips_clim():
    d = _year(18.3, 8.0, 13.0).drop(pd.Timestamp("2023-06-01"))
    r = rity.rity2(d, 2023)
    assert not r["complete"] and "swarming_doy" not in r                     # gap -> not computed
    r = rity.rity2(_year(18.3, 8.0, 13.0).loc[:"2023-10-23"], 2023)         # running year
    assert not r["complete"] and r["swarming_doy"] == 71 and str(r["last_date"]) == "2023-10-23"
    # 100 dd above 5.12 from 1 January is reached on 21 January, but T_max >= 16.11 only from 1 April
    tmax = lambda idx: np.where(idx < pd.Timestamp("2023-04-01"), 15.0, 17.0)  # noqa: E731
    r = rity.phenips_clim_swarming(_year(tmax, 5.0, 10.0), 2023)
    assert r["phenips_clim_swarming_doy"] == pd.Timestamp("2023-04-01").dayofyear
