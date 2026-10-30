"""Stage 4: Copernicus CDS ERA5-Land requests (plan 2.21), cached, with a request log (time, size).

- `derived-era5-land-daily-statistics`: daily max / min / mean of hourly ERA5-Land (no accumulated
  variables in this product).
- `reanalysis-era5-land` at 00 UTC: accumulations since 00 UTC of the previous day, i.e. the
  value at 00 UTC of day d+1 is the total of day d [P ECMWF ERA5-Land documentation].
All days are UTC days (user decision 2026-10-29: `time_zone = utc+00:00`).
Full download (user decision 2026-10-30): hourly `reanalysis-era5-land` only, one request per month, daily values
computed here (`daily_from_hourly`); sequential and resumable by CDS job id (`run_jobs`).

The API key is read by `cdsapi` itself from ~/.cdsapirc; this module never opens that file.
"""

from __future__ import annotations

import json
import time
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

DAILY = "derived-era5-land-daily-statistics"
HOURLY = "reanalysis-era5-land"


def daily_request(year: int, month: int, days: list[int], statistic: str, variables: list[str],
                  area: list[float], tz: str = "utc+00:00", frequency: str = "1_hourly") -> dict:
    return {"variable": variables, "year": str(year), "month": f"{month:02d}", "day": [f"{d:02d}" for d in days],
            "daily_statistic": statistic, "time_zone": tz, "frequency": frequency, "area": area}


def hourly_request(year: int, month: int, days: list[int], times: list[str], variables: list[str],
                   area: list[float]) -> dict:
    return {"variable": variables, "year": str(year), "month": f"{month:02d}", "day": [f"{d:02d}" for d in days],
            "time": times, "area": area, "data_format": "netcdf", "download_format": "unarchived"}


def target_path(cache: Path, dataset: str, name: str) -> Path:
    return cache / dataset / f"{name}.nc"


def retrieve(dataset: str, request: dict, target: Path, log: Path, client=None) -> dict:
    """Download once (cached); append time and size to the JSON-lines `log`."""
    if target.exists():
        return {"dataset": dataset, "target": str(target), "cached": True, "bytes": target.stat().st_size}
    import cdsapi

    c = client or cdsapi.Client()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".part")
    t0 = time.time()
    c.retrieve(dataset, request, str(tmp))
    dt = time.time() - t0
    tmp.replace(target)
    rec = {"dataset": dataset, "target": str(target), "cached": False, "seconds": round(dt, 1),
           "bytes": target.stat().st_size, "request": request,
           "utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


def file_kind(path: Path) -> str:
    """'zip', 'netcdf4' (HDF5 signature), 'netcdf3' (CDF signature) or 'grib'."""
    head = path.read_bytes()[:8]
    if head[:2] == b"PK":
        return "zip"
    if head[:4] == b"\x89HDF":
        return "netcdf4"
    if head[:3] == b"CDF":
        return "netcdf3"
    if head[:4] == b"GRIB":
        return "grib"
    return f"unknown {head!r}"


def open_any(path: Path) -> xr.Dataset:
    """Open a CDS netCDF (netCDF4 via h5netcdf, netCDF3 via scipy) or a zip of netCDF files."""
    kind = file_kind(path)
    if kind == "zip":
        out = path.with_suffix("")
        with zipfile.ZipFile(path) as z:
            z.extractall(out)
        return xr.merge([open_any(p) for p in sorted(out.glob("*.nc"))])
    engine = {"netcdf4": "h5netcdf", "netcdf3": "scipy"}.get(kind)
    if engine is None:
        raise ValueError(f"{path.name}: unsupported file type {kind}")
    return xr.open_dataset(path, engine=engine).load()


def describe(ds: xr.Dataset) -> dict:
    """Names, units, dims and the time axis of a dataset (format check)."""
    tname = next((n for n in ("valid_time", "time", "date") if n in ds.coords or n in ds.dims), None)
    t = pd.to_datetime(ds[tname].values) if tname else None
    return {"vars": {k: {"units": v.attrs.get("units"), "long_name": v.attrs.get("long_name"), "dims": list(v.dims)}
                     for k, v in ds.data_vars.items()},
            "coords": list(ds.coords), "time_name": tname,
            "time_first": str(t.min()) if t is not None else None, "time_last": str(t.max()) if t is not None else None,
            "n_time": int(len(t)) if t is not None else None,
            "lat": [float(ds.latitude.min()), float(ds.latitude.max()), int(ds.latitude.size)] if "latitude" in ds else None,
            "lon": [float(ds.longitude.min()), float(ds.longitude.max()), int(ds.longitude.size)] if "longitude" in ds else None}


def point_series(ds: xr.Dataset, lon: float, lat: float) -> pd.DataFrame:
    """Nearest grid point as a DataFrame indexed by time."""
    tname = describe(ds)["time_name"]
    p = ds.sel(longitude=lon, latitude=lat, method="nearest")
    df = p.drop_vars([c for c in p.coords if c != tname], errors="ignore").to_dataframe()
    df.index = pd.DatetimeIndex(pd.to_datetime(df.index), name="time")
    return df


def accum_to_days(df: pd.DataFrame) -> pd.DataFrame:
    """00 UTC accumulations -> totals of the previous UTC day."""
    out = df.copy()
    out.index = out.index.normalize() - pd.Timedelta(days=1)
    return out


def wind_speed(u, v):
    return np.hypot(np.asarray(u, float), np.asarray(v, float))


# --- full download: hourly ERA5-Land only (user decision 2026-10-30) -------------------------------

INSTANT = ("t2m", "d2m", "u10", "v10", "sp")
ACCUM = ("tp", "ssrd", "pev")
FINAL = ("successful",)
FAILED = ("failed", "rejected", "dismissed", "deleted")


def plan_months(wb_years: tuple[int, int], wb_months: tuple[int, int], pheno_years: tuple[int, int],
                pheno_months: tuple[int, int]) -> list[tuple[int, int]]:
    """(year, month) needed: water-balance months over `wb_years` plus phenology months over `pheno_years`."""
    s = {(y, m) for y in range(wb_years[0], wb_years[1] + 1) for m in range(wb_months[0], wb_months[1] + 1)}
    s |= {(y, m) for y in range(pheno_years[0], pheno_years[1] + 1) for m in range(pheno_months[0], pheno_months[1] + 1)}
    return sorted(s)


def _next(y: int, m: int) -> tuple[int, int]:
    return (y + 1, 1) if m == 12 else (y, m + 1)


def month_jobs(months: list[tuple[int, int]], last_day: date, variables: list[str], accum_vars: list[str],
               area: list[float]) -> list[dict]:
    """One request per month (24 h, every variable, days up to `last_day`) and, when the following month is not
    downloaded itself, a 00 UTC accumulation request for its 1st day: ERA5-Land accumulations run from 00 UTC,
    so the total of day d is the value at 00 UTC of day d+1, and the last day of a month needs the next month."""
    import calendar

    have, jobs = set(months), []
    for y, m in months:
        days = [d for d in range(1, calendar.monthrange(y, m)[1] + 1) if date(y, m, d) <= last_day]
        if not days:
            continue
        jobs.append({"name": f"h_{y}_{m:02d}", "dataset": HOURLY,
                     "request": hourly_request(y, m, days, [f"{h:02d}:00" for h in range(24)], variables, area)})
        ny, nm = _next(y, m)
        if (ny, nm) not in have and date(ny, nm, 1) <= last_day:
            jobs.append({"name": f"acc00_{ny}_{nm:02d}", "dataset": HOURLY,
                         "request": hourly_request(ny, nm, [1], ["00:00"], accum_vars, area)})
    return jobs


def find_target(folder: Path, name: str) -> Path | None:
    for suf in (".nc", ".zip"):
        if (folder / f"{name}{suf}").exists():
            return folder / f"{name}{suf}"
    return None


def _write_state(path: Path, state: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
    tmp.replace(path)


class StopDownload(RuntimeError):
    pass


def run_jobs(jobs: list[dict], folder: Path, state_path: Path, log: Path, client=None, poll_s: float = 30,
             tries: int = 20, echo=print, sleep=time.sleep) -> dict:
    """Sequential, resumable download (one CDS job at a time). The job id is written to `state_path` right after
    submission; a job with a stored id is never submitted again (only polled / downloaded). Status-poll and download
    errors are retried on the same job; a failed / rejected job or a lost id stops the run (no new requests)."""
    if client is None:
        import cdsapi

        client = cdsapi.Client(quiet=True).client
    folder.mkdir(parents=True, exist_ok=True)
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    done = 0
    for i, job in enumerate(jobs, 1):
        name = job["name"]
        if find_target(folder, name):
            continue
        st = state.get(name, {})
        if st.get("job_id"):
            try:
                remote = client.get_remote(st["job_id"])
            except Exception as e:                        # expired / unknown id: never resubmit automatically
                st["status"] = f"lost: {type(e).__name__}: {e}"
                _write_state(state_path, state)
                raise StopDownload(f"{name}: job {st['job_id']} not found ({e}); not resubmitted")
            echo(f"[{i}/{len(jobs)}] {name}: resume job {st['job_id']}")
        else:
            remote = client.submit(job["dataset"], job["request"])
            st = state[name] = {"job_id": remote.request_id, "dataset": job["dataset"],
                                "submitted_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            _write_state(state_path, state)
            echo(f"[{i}/{len(jobs)}] {name}: submitted job {remote.request_id}")
        errors = 0
        while True:
            try:
                status = remote.status
                errors = 0
            except Exception as e:                        # connection / 5xx while polling: same job, wait
                errors += 1
                if errors > tries:
                    raise StopDownload(f"{name}: status polling failed {tries}x ({e})")
                sleep(120)
                continue
            if status in FINAL:
                break
            if status in FAILED:
                st["status"] = status
                _write_state(state_path, state)
                raise StopDownload(f"{name}: job {st['job_id']} {status}")
            sleep(poll_s)
        tmp = folder / f"{name}.part"
        for k in range(tries):
            try:
                remote.download(str(tmp))
                break
            except Exception as e:                        # download only; the job is not submitted again
                echo(f"  download error {k + 1}: {type(e).__name__}: {e}")
                sleep(120)
                remote = client.get_remote(st["job_id"])
        else:
            raise StopDownload(f"{name}: download failed {tries}x")
        target = folder / f"{name}{'.zip' if file_kind(tmp) == 'zip' else '.nc'}"
        tmp.replace(target)
        j = remote.json
        t = {k: datetime.fromisoformat(j[k]) for k in ("created", "started", "finished") if j.get(k)}
        rec = {"dataset": job["dataset"], "target": str(target), "cached": False, "job_id": st["job_id"],
               "seconds": round((t["finished"] - t["created"]).total_seconds(), 1) if len(t) == 3 else None,
               "queue_seconds": round((t["started"] - t["created"]).total_seconds(), 1) if len(t) == 3 else None,
               "bytes": target.stat().st_size, "request": job["request"],
               "utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        with log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        st |= {"status": "done", "bytes": rec["bytes"], "seconds": rec["seconds"], "queue_seconds": rec["queue_seconds"]}
        _write_state(state_path, state)
        done += 1
        echo(f"  done: {rec['seconds']} s (queue {rec['queue_seconds']} s), {rec['bytes'] / 1e6:.2f} MB")
    return {"downloaded": done, "jobs": len(jobs)}


def daily_from_hourly(ds: xr.Dataset, acc00: xr.Dataset | None = None) -> xr.Dataset:
    """UTC-day values from hourly ERA5-Land. Instantaneous variables: days with all 24 hours; tmax / tmin / tmean
    and tdew (deg C), sp (kPa), u10 / v10 means and the mean of hourly wind speed (m/s). Accumulations: total of day
    d = value at 00 UTC of day d+1 (from `ds` and, for the month's last day, `acc00`); precip / pev in mm, rs in
    MJ m-2. Tmax / Tmin are the extremes of the 24 hourly values (ERA5-Land has no 2 m max / min variable)."""
    t = "valid_time"
    ds = ds.drop_vars([c for c in ("number", "expver") if c in ds.coords])
    inst = ds[[v for v in INSTANT if v in ds]]
    r = inst.resample({t: "1D"})
    mx, mn, me = r.max(), r.min(), r.mean()
    out = xr.Dataset({"tmax": mx["t2m"] - 273.15, "tmin": mn["t2m"] - 273.15, "tmean": me["t2m"] - 273.15,
                      "tdew": me["d2m"] - 273.15, "sp_kpa": me["sp"] / 1000, "u10": me["u10"], "v10": me["v10"],
                      "wind_speed": np.hypot(inst["u10"], inst["v10"]).resample({t: "1D"}).mean()})
    out = out.where(inst["t2m"].resample({t: "1D"}).count() == 24)
    acc = [x.drop_vars([c for c in ("number", "expver") if c in x.coords])[[v for v in ACCUM if v in x]]
           for x in (ds, acc00) if x is not None]
    a = xr.concat(acc, t) if len(acc) > 1 else acc[0]
    a = a.sel({t: a[t].dt.hour == 0})
    a = a.assign_coords({t: a[t].dt.floor("D") - np.timedelta64(1, "D")})
    a = xr.Dataset({"precip": a["tp"] * 1000, "rs_mj": a["ssrd"] / 1e6, "pev_mm": a["pev"] * 1000})
    return xr.merge([out, a], join="outer")
