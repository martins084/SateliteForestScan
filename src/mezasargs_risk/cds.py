"""Stage 4: Copernicus CDS ERA5-Land requests (plan 2.21), cached, with a request log (time, size).

- `derived-era5-land-daily-statistics`: daily max / min / mean of hourly ERA5-Land (no accumulated
  variables in this product).
- `reanalysis-era5-land` at 00 UTC: accumulations since 00 UTC of the previous day, i.e. the
  value at 00 UTC of day d+1 is the total of day d [P ECMWF ERA5-Land documentation].
All days are UTC days (user decision 2026-10-29: `time_zone = utc+00:00`).

The API key is read by `cdsapi` itself from ~/.cdsapirc; this module never opens that file.
"""

from __future__ import annotations

import json
import time
import zipfile
from datetime import datetime, timezone
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
