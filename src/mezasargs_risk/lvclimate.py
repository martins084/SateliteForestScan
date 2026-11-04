"""Stage 4, Latvia (user decision 2026-11-04): ERA5-Land 0.1 deg daily cubes from the hourly CDS download, RITY-2
per grid cell (2018-2026) and the climatic water balance anomaly per grid cell (P - ET0, IV-IX, 1991-2026 vs
1991-2020; not SPEI).

- Daily values: `cds.daily_from_hourly` per month (UTC days); the accumulations of a month's last day come from the
  first 00 UTC step of the next month (its `h_` file or the `acc00_` file). One year at a time (server RAM 3.7 GB).
- ET0: FAO-56 Penman-Monteith (`et0.et0_daily`) with the mean of the hourly wind speed, the cell latitude and the
  daily mean surface pressure (no elevation term in Rso, as in the pilot).
- RITY-2: `rity.rity2` unchanged; day length = FAO-56 Eq. 34 at the cell latitude [N: Ogris 2020 does not define it],
  sensitivity +-16 min. Main feature: relative thermal sums Tsum_F1 / Tsum_F2 at the last day (AVG, ERA5-Land
  direct, plan 2.22); generations in both variants (direct and INCA (1)-(3)).
- 2026 is incomplete: temperature to 2026-10-27, accumulations to 2026-10-26 (catalogue end when downloaded).
All cells of the download box with land data are computed; the Latvia mask is applied when reporting.
"""

from __future__ import annotations

import calendar
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from . import cds, et0, rity

T = "valid_time"
DAILY_VARS = ("tmax", "tmin", "tmean", "tdew", "sp_kpa", "wind_speed", "precip", "rs_mj", "pev_mm", "et0")
DAYLENGTH_SHIFT_MIN = (-16, 16)


def _open_lazy(path: Path) -> xr.Dataset:
    engine = {"netcdf4": "h5netcdf", "netcdf3": "scipy"}[cds.file_kind(path)]
    return xr.open_dataset(path, engine=engine)


def _grid(x):
    x = x.drop_vars([c for c in ("number", "expver") if c in x.coords])
    return x.assign_coords(latitude=np.round(x.latitude.values, 1), longitude=np.round(x.longitude.values, 1))


def next_00utc(folder: Path, y: int, m: int) -> xr.Dataset | None:
    """Accumulations at 00 UTC of the next month's 1st day (total of this month's last day), or None."""
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    f = cds.find_target(folder, f"h_{ny}_{nm:02d}") or cds.find_target(folder, f"acc00_{ny}_{nm:02d}")
    if f is None:
        return None
    with _open_lazy(f) as ds:
        a = ds[[v for v in cds.ACCUM if v in ds]]
        return a.sel({T: [pd.Timestamp(ny, nm, 1)]}).load()


def month_daily(folder: Path, y: int, m: int) -> xr.Dataset:
    """Daily values of one month (UTC days of that month only) incl. FAO-56 ET0."""
    ds = cds.open_any(cds.find_target(folder, f"h_{y}_{m:02d}"))
    d = cds.daily_from_hourly(ds, next_00utc(folder, y, m))
    d = d.sel({T: (d[T].dt.year == y) & (d[T].dt.month == m)})
    d = _grid(d).transpose(T, "latitude", "longitude")
    lat = d.latitude.values[None, :, None]
    doy = d[T].dt.dayofyear.values[:, None, None]
    e = et0.et0_daily(tmax=d["tmax"].values, tmin=d["tmin"].values, ea=et0.sat_vp(d["tdew"].values),
                      u2=et0.wind_2m(d["wind_speed"].values), rs=d["rs_mj"].values, lat_deg=lat, doy=doy,
                      p_kpa=d["sp_kpa"].values)
    d["et0"] = (d["tmax"].dims, e)
    return d[list(DAILY_VARS)].astype("float32")


def year_daily(folder: Path, y: int, out: Path) -> Path:
    """All downloaded months of year `y` as one daily NetCDF (cached; rebuilt when the set of downloaded months
    differs from the cached one, e.g. after the 2011-2017 phenology months were added)."""
    months = [m for m in range(1, 13) if cds.find_target(folder, f"h_{y}_{m:02d}")]
    if out.exists():
        with xr.open_dataset(out, engine="h5netcdf") as old:
            if old.attrs.get("months") == str(months):
                return out
    d = xr.concat([month_daily(folder, y, m) for m in months], T)
    d.attrs = {"source": "ERA5-Land hourly (CDS reanalysis-era5-land), UTC days", "months": str(months)}
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".part")
    d.to_netcdf(tmp, engine="h5netcdf", encoding={v: {"zlib": True, "complevel": 4} for v in d.data_vars})
    tmp.replace(out)
    return out


# --- water balance ---------------------------------------------------------------------------------------------

def seasonal_grid(d: xr.Dataset, y: int, months: tuple[int, int]) -> xr.Dataset:
    """P, ET0, P - ET0 summed over months m0..m1 of year y per cell; NaN unless every day has P and ET0."""
    m0, m1 = months
    s = d.sel({T: (d[T].dt.year == y) & (d[T].dt.month >= m0) & (d[T].dt.month <= m1)})
    expected = (pd.Timestamp(y, m1, calendar.monthrange(y, m1)[1]) - pd.Timestamp(y, m0, 1)).days + 1
    ok = (s["precip"].notnull() & s["et0"].notnull()).sum(T) == expected
    p, e = s["precip"].sum(T).where(ok), s["et0"].sum(T).where(ok)
    return xr.Dataset({"precip_mm": p, "et0_mm": e, "cwb_mm": p - e}).expand_dims(year=[y])


def anomaly_grid(wb: xr.Dataset, ref: tuple[int, int]) -> xr.Dataset:
    """z = (CWB - mean_ref) / sd_ref per cell (ddof = 1), as `waterbalance.anomaly`; cells without a complete
    reference period get NaN."""
    r = wb["cwb_mm"].sel(year=slice(ref[0], ref[1]))
    full = r.notnull().sum("year") == ref[1] - ref[0] + 1
    mu, sd = r.mean("year").where(full), r.std("year", ddof=1).where(full)
    return wb.assign(cwb_ref_mean=mu, cwb_ref_sd=sd, cwb_z=(wb["cwb_mm"] - mu) / sd)


# --- RITY-2 per cell -------------------------------------------------------------------------------------------

def cell_table(d: xr.Dataset, lat: float, lon: float, shift_min: float = 0.0) -> pd.DataFrame:
    p = d[["tmax", "tmin", "tmean"]].sel(latitude=lat, longitude=lon)
    df = pd.DataFrame({k: p[k].values.astype(float) for k in ("tmax", "tmin", "tmean")},
                      index=pd.DatetimeIndex(p[T].values).normalize())
    df["daylight_s"] = (et0.daylight_hours(lat, df.index.dayofyear) + shift_min / 60) * 3600
    return df


def rity_cell(d: xr.Dataset, lat: float, lon: float, y: int, scenarios: list[str]) -> list[dict]:
    """RITY-2 rows of one cell and year: every scenario x (direct, INCA) with Eq. 34 day length, the AVG
    scenario of both variants with day length -16 / +16 min, and the PHENIPS-Clim threshold date."""
    base = cell_table(d, lat, lon)
    pc = rity.phenips_clim_swarming(base, y)["phenips_clim_swarming_doy"]
    rows = []
    for sc in scenarios:
        for inca in (False, True):
            rows.append(rity.rity2(base, y, sc, inca) | {"daylength_shift_min": 0})
    for s in DAYLENGTH_SHIFT_MIN:
        t = cell_table(d, lat, lon, s)
        for inca in (False, True):
            rows.append(rity.rity2(t, y, "AVG", inca) | {"daylength_shift_min": s})
    return [r | {"latitude": lat, "longitude": lon, "phenips_clim_swarming_doy": pc} for r in rows]


def land_cells(d: xr.Dataset) -> list[tuple[float, float]]:
    m = d["tmax"].notnull().any(T)
    la, lo = np.nonzero(m.values)
    return [(float(m.latitude[i]), float(m.longitude[j])) for i, j in zip(la, lo)]


def pheno_wide(ph: pd.DataFrame, main: str = "AVG") -> pd.DataFrame:
    """One row per (cell, year): main scenario, ERA5-Land direct, Eq. 34 day length, plus generations / Tsum of the
    other scenarios, of the INCA variant and of the day-length sensitivity."""
    key = ["latitude", "longitude", "year"]
    b = ph[ph["daylength_shift_min"] == 0]
    m = b[(b["variant"] == "era5_direct") & (b["scenario"] == main)].copy()

    def add(sel, cols, suffix):
        return sel[key + cols].rename(columns={c: f"{c}_{suffix}" for c in cols})

    for sc in sorted(set(b["scenario"]) - {main}):
        m = m.merge(add(b[(b["variant"] == "era5_direct") & (b["scenario"] == sc)], ["n_filial"], sc), on=key, how="left")
    m = m.merge(add(b[(b["variant"] == "inca_1-3") & (b["scenario"] == main)], ["n_filial", "tsum_F1", "tsum_F2"], "inca"),
                on=key, how="left")
    for s in DAYLENGTH_SHIFT_MIN:
        tag = f"dl{s:+d}"
        x = ph[(ph["daylength_shift_min"] == s) & (ph["scenario"] == main)]
        m = m.merge(add(x[x["variant"] == "era5_direct"], ["n_filial", "tsum_F2", "onset_doy_F2"], tag), on=key, how="left")
        m = m.merge(add(x[x["variant"] == "inca_1-3"], ["n_filial"], f"inca_{tag}"), on=key, how="left")
    return m


def to_grid(df: pd.DataFrame, cols: list[str], lat: np.ndarray, lon: np.ndarray) -> xr.Dataset:
    """(year, latitude, longitude) rasters of table columns on the ERA5-Land grid."""
    years = sorted(int(y) for y in df["year"].unique())
    yi = pd.Index(years).get_indexer(df["year"].astype(int))
    la = pd.Index(np.round(lat, 1)).get_indexer(np.round(df["latitude"].to_numpy(float), 1))
    lo = pd.Index(np.round(lon, 1)).get_indexer(np.round(df["longitude"].to_numpy(float), 1))
    if (la < 0).any() or (lo < 0).any():
        raise ValueError("table cells not on the grid")
    out = {}
    for c in cols:
        a = np.full((len(years), len(lat), len(lon)), np.nan, dtype="float32")
        a[yi, la, lo] = pd.to_numeric(df[c], errors="coerce").to_numpy(dtype=float)
        out[c] = (("year", "latitude", "longitude"), a)
    return xr.Dataset(out, coords={"year": years, "latitude": lat, "longitude": lon})
