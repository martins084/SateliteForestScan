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


def test_month_plan_adds_next_month_accumulation():
    months = cds.plan_months((1991, 1992), (4, 9), (1992, 1992), (1, 10))
    assert len(months) == 6 + 10 and (1992, 1) in months and (1991, 3) not in months
    from datetime import date

    jobs = cds.month_jobs(months, date(1992, 10, 20), ["2m_temperature"], ["total_precipitation"], [58, 20, 55, 28])
    names = [j["name"] for j in jobs]
    assert "acc00_1991_10" in names and "acc00_1992_11" not in names       # beyond the last available day
    assert jobs[names.index("acc00_1991_10")]["request"]["time"] == ["00:00"]
    oct92 = jobs[names.index("h_1992_10")]["request"]
    assert oct92["day"][-1] == "20" and len(oct92["time"]) == 24


class _Remote:
    def __init__(self, rid, statuses, fail_downloads=0):
        self.request_id, self._st, self.fail = rid, list(statuses), fail_downloads
        self.json = {"created": "2026-10-30T10:00:00", "started": "2026-10-30T10:01:00", "finished": "2026-10-30T10:02:00"}

    @property
    def status(self):
        return self._st.pop(0) if len(self._st) > 1 else self._st[0]

    def download(self, target):
        if self.fail:
            self.fail -= 1
            raise ConnectionError("500")
        _ds(pd.date_range("2023-04-01", periods=2, freq="D")).to_netcdf(target, engine="h5netcdf")


class _Client:
    def __init__(self, remotes):
        self.remotes, self.submitted = remotes, []

    def submit(self, dataset, request):
        rid = f"id{len(self.submitted)}"
        self.submitted.append(rid)
        return self.remotes[rid]

    def get_remote(self, rid):
        return self.remotes[rid]


def test_run_jobs_resumes_by_id_and_never_resubmits(tmp_path):
    import json

    import pytest

    jobs = [{"name": n, "dataset": cds.HOURLY, "request": {}} for n in ("a", "b", "c")]
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"a": {"job_id": "old"}}))               # submitted before an interruption
    cl = _Client({"old": _Remote("old", ["running", "successful"], fail_downloads=2),
                  "id0": _Remote("id0", ["accepted", "successful"]), "id1": _Remote("id1", ["rejected"])})
    with pytest.raises(cds.StopDownload):
        cds.run_jobs(jobs, tmp_path / "f", state, tmp_path / "log.jsonl", client=cl, echo=lambda *_: None,
                     sleep=lambda *_: None)
    assert cl.submitted == ["id0", "id1"]                                 # "a" resumed by id, not resubmitted
    st = json.loads(state.read_text())
    assert st["a"]["status"] == "done" and st["b"]["status"] == "done" and st["c"]["status"] == "rejected"
    assert cds.find_target(tmp_path / "f", "a").suffix == ".nc"
    cds.run_jobs(jobs[:2], tmp_path / "f", state, tmp_path / "log.jsonl", client=cl, echo=lambda *_: None)
    assert cl.submitted == ["id0", "id1"]                                 # cached files: nothing new
    cds.run_jobs(jobs[:2], tmp_path / "g", state, tmp_path / "log.jsonl", client=cl, echo=lambda *_: None,
                 skip_state_done=True)                               # other machine: done in state
    assert cl.submitted == ["id0", "id1"] and list((tmp_path / "g").iterdir()) == []


def test_daily_from_hourly_utc_days_and_accumulations():
    t = pd.date_range("2023-04-01", periods=48, freq="h")
    shape = (len(t), 1, 1)
    hour = np.asarray(t.hour, float).reshape(shape)
    acc = np.where(hour == 0, 5.0, 0.0) / 1000                           # 5 mm at every 00 UTC
    coords = {"valid_time": t, "latitude": [56.7], "longitude": [25.9]}
    v = lambda a, u: (("valid_time", "latitude", "longitude"), a, {"units": u})
    ds = xr.Dataset({"t2m": v(273.15 + hour, "K"), "d2m": v(np.full(shape, 273.15), "K"), "u10": v(np.full(shape, 3.0), "m s**-1"),
                     "v10": v(np.full(shape, 4.0), "m s**-1"), "sp": v(np.full(shape, 1e5), "Pa"), "tp": v(acc, "m"),
                     "ssrd": v(np.full(shape, 1e7), "J m**-2"), "pev": v(-acc, "m")}, coords=coords)
    ds = ds.isel(valid_time=slice(0, 47))                                 # 2 April incomplete (23 h)
    nxt = xr.Dataset({"tp": v(np.full((1, 1, 1), 0.002), "m"), "ssrd": v(np.full((1, 1, 1), 2e7), "J m**-2"),
                      "pev": v(np.full((1, 1, 1), -0.002), "m")}, coords=coords | {"valid_time": [pd.Timestamp("2023-04-03")]})
    d = cds.daily_from_hourly(ds, nxt).isel(latitude=0, longitude=0).to_dataframe()
    d.index = d.index.strftime("%m-%d")
    assert d.loc["04-01", "tmax"] == 23 and d.loc["04-01", "tmin"] == 0 and d.loc["04-01", "tmean"] == 11.5
    assert np.isnan(d.loc["04-02", "tmax"]) and d.loc["04-01", "wind_speed"] == 5
    assert d.loc["03-31", "precip"] == 5 and d.loc["04-01", "precip"] == 5    # 00 UTC -> previous day
    assert d.loc["04-02", "precip"] == 2 and d.loc["04-02", "rs_mj"] == 20     # last day from next month
