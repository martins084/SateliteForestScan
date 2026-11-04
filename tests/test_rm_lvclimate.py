"""mezasargs_risk stage 4, Latvia: daily cubes from hourly ERA5-Land, water balance per cell, RITY-2 per cell
(synthetic files, no network)."""

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from mezasargs_risk import et0, lvclimate as L, rity, waterbalance

LAT, LON = [56.8, 56.7], [25.8, 25.9]


def _hourly(path, start, hours, acc_only=False):
    t = pd.date_range(start, periods=hours, freq="h")
    sh = (len(t), len(LAT), len(LON))
    hour = np.broadcast_to(np.asarray(t.hour, float)[:, None, None], sh)
    acc = np.where(hour == 0, 4.0, 1.0) / 1000              # 00 UTC = 4 mm (previous day), else 1 mm so far
    v = lambda a, u: (("valid_time", "latitude", "longitude"), np.asarray(a, "float32"), {"units": u})  # noqa: E731
    data = {"tp": v(acc, "m"), "ssrd": v(np.full(sh, 1.2e7), "J m**-2"), "pev": v(-acc, "m")}
    if not acc_only:
        data |= {"t2m": v(278.15 + hour / 2, "K"), "d2m": v(np.full(sh, 275.15), "K"), "u10": v(np.full(sh, 3.0), "m s**-1"),
                 "v10": v(np.full(sh, 4.0), "m s**-1"), "sp": v(np.full(sh, 1.0e5), "Pa")}
    xr.Dataset(data, coords={"valid_time": t, "latitude": LAT, "longitude": LON}).to_netcdf(path, engine="h5netcdf")


def test_month_daily_takes_last_day_accumulation_from_next_month(tmp_path):
    _hourly(tmp_path / "h_2023_04.nc", "2023-04-01", 30 * 24)
    _hourly(tmp_path / "h_2023_05.nc", "2023-05-01", 2 * 24)
    d = L.month_daily(tmp_path, 2023, 4)
    assert d.sizes["valid_time"] == 30 and pd.Timestamp(d.valid_time.values[0]) == pd.Timestamp("2023-04-01")
    c = d.sel(latitude=56.7, longitude=25.9).to_dataframe()
    assert c["precip"].iloc[-1] == pytest.approx(4.0) and c["precip"].notnull().all()   # 30 April from 1 May 00 UTC
    assert c["tmax"].iloc[0] == pytest.approx(5 + 23 / 2) and c["wind_speed"].iloc[0] == pytest.approx(5.0)
    e = et0.et0_daily(tmax=c["tmax"], tmin=c["tmin"], ea=et0.sat_vp(c["tdew"]), u2=et0.wind_2m(c["wind_speed"]),
                      rs=c["rs_mj"], lat_deg=56.7, doy=c.index.dayofyear, p_kpa=c["sp_kpa"])
    assert np.allclose(c["et0"], e, atol=1e-4)
    # next month only as the 00 UTC accumulation file; without it the last day has no accumulations
    (tmp_path / "h_2023_05.nc").unlink()
    assert np.isnan(L.month_daily(tmp_path, 2023, 4)["precip"].values[-1]).all()
    _hourly(tmp_path / "acc00_2023_05.nc", "2023-05-01", 1, acc_only=True)
    assert L.month_daily(tmp_path, 2023, 4)["precip"].values[-1] == pytest.approx(4.0)


def test_water_balance_grid_equals_point_functions():
    t = pd.date_range("2001-04-01", "2003-09-30")
    rng = np.random.default_rng(1)
    sh = (len(t), len(LAT), len(LON))
    d = xr.Dataset({"precip": (("valid_time", "latitude", "longitude"), rng.gamma(1, 2, sh)),
                    "et0": (("valid_time", "latitude", "longitude"), rng.gamma(2, 1.5, sh))},
                   coords={"valid_time": t, "latitude": LAT, "longitude": LON})
    d["precip"][100, 0, 0] = np.nan                                   # 2001 incomplete in one cell
    g = L.anomaly_grid(xr.concat([L.seasonal_grid(d, y, (4, 9)) for y in (2001, 2002, 2003)], "year"), (2001, 2003))
    assert np.isnan(g["cwb_mm"].sel(year=2001, latitude=56.8, longitude=25.8))
    assert np.isnan(g["cwb_z"].sel(latitude=56.8, longitude=25.8)).all()   # reference incomplete -> no anomaly
    p = d.sel(latitude=56.7, longitude=25.9).to_dataframe()[["precip", "et0"]]
    ref = waterbalance.anomaly(waterbalance.seasonal(p, (4, 9)), (2001, 2003))
    assert np.allclose(g["cwb_z"].sel(latitude=56.7, longitude=25.9).values, ref["cwb_z"].values)
    assert np.allclose(g["cwb_mm"].sel(latitude=56.7, longitude=25.9).values, ref["cwb_mm"].values)


def test_rity_cell_uses_eq34_day_length_and_grids_back():
    t = pd.date_range("2023-01-01", "2023-10-31")
    tm = 12 - 14 * np.cos(2 * np.pi * (t.dayofyear.values - 15) / 365)
    v = lambda a: (("valid_time", "latitude", "longitude"), np.broadcast_to(a[:, None, None], (len(t), 2, 2)))  # noqa: E731
    d = xr.Dataset({"tmax": v(tm + 5), "tmin": v(tm - 5), "tmean": v(tm)},
                   coords={"valid_time": t, "latitude": LAT, "longitude": LON})
    rows = L.rity_cell(d, 56.7, 25.9, 2023, ["AVG", "MIN", "MAX"])
    assert len(rows) == 3 * 2 + 2 * 2
    day = pd.DataFrame({"tmax": tm + 5, "tmin": tm - 5, "tmean": tm,
                        "daylight_s": et0.daylight_hours(56.7, t.dayofyear) * 3600}, index=t)
    assert {k: v for k, v in rows[0].items() if k in rity.rity2(day, 2023)} == rity.rity2(day, 2023)
    tab = L.cell_table(d, 56.7, 25.9, 16)
    assert np.allclose(tab["daylight_s"] - day["daylight_s"], 16 * 60)
    w = L.pheno_wide(pd.DataFrame(rows))
    assert len(w) == 1 and {"n_filial_inca", "tsum_F2_inca", "n_filial_dl-16", "n_filial_inca_dl+16"} <= set(w.columns)
    g = L.to_grid(w, ["tsum_F1"], np.array(LAT), np.array(LON))
    assert g["tsum_F1"].sel(year=2023, latitude=56.7, longitude=25.9) == pytest.approx(w["tsum_F1"].iloc[0])
    assert int(g["tsum_F1"].notnull().sum()) == 1
