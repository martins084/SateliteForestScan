"""mezasargs_risk stage 4: CDS ERA5-Land request building and file handling (offline, synthetic files)."""

import zipfile

import numpy as np
import pandas as pd
import xarray as xr

from mezasargs_risk import cds
from mezasargs_risk.config import CdsConfig


def _ds(times):
    lat, lon = [56.8, 56.7, 56.6], [25.8, 25.9, 26.0]
    v = np.arange(len(times) * 9, dtype="float32").reshape(len(times), 3, 3)
    return xr.Dataset({"tp": (("valid_time", "latitude", "longitude"), v, {"units": "m"})},
                      coords={"valid_time": times, "latitude": lat, "longitude": lon})


def test_requests_use_utc_days_and_area():
    k = CdsConfig()
    r = cds.daily_request(2023, 4, [1, 2], "daily_mean", k.daily_mean_vars, k.area, k.time_zone, k.frequency)
    assert r["time_zone"] == "utc+00:00" and r["month"] == "04" and r["day"] == ["01", "02"]
    assert r["area"] == [58.2, 20.8, 55.5, 28.4] and r["frequency"] == "1_hourly"
    h = cds.hourly_request(2023, 4, [1], ["00:00"], k.accum_vars, k.area)
    assert h["time"] == ["00:00"] and h["data_format"] == "netcdf" and "potential_evaporation" in h["variable"]


def test_open_netcdf4_zip_and_accumulation_days(tmp_path):
    times = pd.date_range("2023-04-01", periods=3, freq="D")
    nc = tmp_path / "a.nc"
    _ds(times).to_netcdf(nc, engine="h5netcdf")
    assert cds.file_kind(nc) == "netcdf4"
    z = tmp_path / "b.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.write(nc, "inner.nc")
    assert cds.file_kind(z) == "zip"
    for p in (nc, z):
        ds = cds.open_any(p)
        d = cds.describe(ds)
        assert d["time_name"] == "valid_time" and d["vars"]["tp"]["units"] == "m" and d["n_time"] == 3
    s = cds.point_series(cds.open_any(nc), 25.91, 56.69)          # nearest -> (25.9, 56.7)
    assert s["tp"].tolist() == [4.0, 13.0, 22.0]
    days = cds.accum_to_days(s)                                    # 00 UTC value -> previous UTC day
    assert days.index[0] == pd.Timestamp("2023-03-31")
    assert cds.wind_speed([3.0], [4.0])[0] == 5.0
