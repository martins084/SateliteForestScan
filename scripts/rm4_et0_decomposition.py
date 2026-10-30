"""Stage 4 pilot: why is FAO-56 ET0 from ERA5-Land (CDS) ~12 % below the Open-Meteo ET0 at Kalsnava (April 2023)?
Explanation only, nothing is changed (user 2026-10-30).

Steps (sums over the common UTC days):
  E0  Open-Meteo daily `et0_fao_evapotranspiration` as used in the pilot (days in UTC+2)
  E1  Open-Meteo hourly ET0 summed over UTC days                       -> E0 - E1: day boundary
  E2  our daily FAO-56 (et0.py) with Open-Meteo inputs on UTC days    -> E1 - E2: hourly vs daily FAO-56 step
  E3  our daily FAO-56 with ERA5-Land inputs (CDS)                    -> E2 - E3: input data, split by swapping
      one input group at a time (temperature, humidity, wind, radiation, pressure) in both directions.
Open-Meteo hourly values of radiation / ET0 / precipitation are sums or means over the preceding hour
[P Open-Meteo docs], so they are shifted back by one hour before the UTC-day sums.

One Open-Meteo request (Kalsnava ERA5 node, one month, hourly) counted in the free-tier ledger; cached.
Usage: python scripts/rm4_et0_decomposition.py configs/rm_4_klimats.yaml
"""

import json
import sys
from datetime import date

import numpy as np
import pandas as pd
import requests

from mezasargs_risk import cds, et0, weather
from mezasargs_risk.config import load_config

HOURLY = ["temperature_2m", "dew_point_2m", "wind_speed_10m", "shortwave_radiation", "surface_pressure",
          "et0_fao_evapotranspiration", "precipitation"]
PRECEDING_HOUR = ["shortwave_radiation", "et0_fao_evapotranspiration", "precipitation"]


def om_hourly(lon, lat, start, end, c, cache_dir):
    path = cache_dir / f"hourly_{weather.node_id(lon, lat)}_{start}_{end}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    budget = weather.Budget(cache_dir / "ledger.csv", c.openmeteo)
    budget.spend(weather.call_weight((end - start).days + 1, len(HOURLY)))
    params = {"latitude": lat, "longitude": lon, "start_date": str(start), "end_date": str(end),
              "hourly": ",".join(HOURLY), "models": c.openmeteo.model, "timezone": "GMT", "wind_speed_unit": "ms"}
    r = requests.get(c.openmeteo.url, params=params, timeout=120)
    if r.status_code != 200:
        raise SystemExit(f"Open-Meteo HTTP {r.status_code}: {r.text[:300]}")
    js = r.json()
    js["_request"] = params
    path.write_text(json.dumps(js), encoding="utf-8")
    return js


def fao(d, lat):
    return et0.et0_daily(tmax=d["tmax"], tmin=d["tmin"], ea=d["ea"], u2=et0.wind_2m(d["u10"]), rs=d["rs"],
                         lat_deg=lat, doy=d.index.dayofyear, p_kpa=d["p"])


def main(config):
    cfg = load_config(config)
    c = cfg.climate
    p = c.points[0]
    k = c.cds
    y, m = k.pilot_year, k.pilot_month
    lon, lat = weather.nearest_node(p.lon, p.lat)
    start, end = date(y, m, 1), (pd.Timestamp(y, m, 1) + pd.offsets.MonthEnd(0) + pd.Timedelta(days=1)).date()
    js = om_hourly(lon, lat, start, end, c, cfg.cache_dir / "rm" / "openmeteo")
    units = js["hourly_units"]
    h = pd.DataFrame(js["hourly"]).set_index("time")
    h.index = pd.to_datetime(h.index)
    for v in PRECEDING_HOUR:
        h[v] = h[v].shift(-1)                 # value at hh:00 covers the preceding hour -> label the hour start
    g = h.groupby(h.index.normalize())
    n = g.size()
    om = pd.DataFrame({"tmax": g["temperature_2m"].max(), "tmin": g["temperature_2m"].min(),
                       "ea": et0.sat_vp(g["dew_point_2m"].mean()), "u10": g["wind_speed_10m"].mean(),
                       "rs": g["shortwave_radiation"].sum() * 3600 / 1e6, "p": g["surface_pressure"].mean() / 10,
                       "et0_hourly_sum": g["et0_fao_evapotranspiration"].sum(min_count=24),
                       "precip": g["precipitation"].sum(min_count=24)})[n == 24]
    # ERA5-Land (hourly download, same cell as the pilot)
    ds = cds.open_any(cds.find_target(cfg.cache_dir / "rm" / "cds" / cds.HOURLY / "hourly", f"h_{y}_{m:02d}"))
    dd = cds.daily_from_hourly(ds).sel(longitude=p.lon, latitude=p.lat, method="nearest")
    lat_cds = float(dd.latitude)
    e5 = dd.to_dataframe()
    e5.index = pd.DatetimeIndex(e5.index)
    e5 = pd.DataFrame({"tmax": e5["tmax"], "tmin": e5["tmin"], "ea": et0.sat_vp(e5["tdew"]), "u10": e5["wind_speed"],
                       "rs": e5["rs_mj"], "p": e5["sp_kpa"], "precip": e5["precip"]})
    # Open-Meteo daily ET0 used in the pilot (UTC+2 days)
    w = next(w for w in weather.windows(c) if w[0] <= start <= w[1])          # cached pilot window
    od, _ = weather.parse_daily(weather.fetch(lon, lat, *w, c.openmeteo, cfg.cache_dir / "rm" / "openmeteo", None),
                                c.openmeteo.daily)
    days = om.index.intersection(e5.dropna().index).intersection(od.index)
    om, e5 = om.loc[days], e5.loc[days]
    E0 = float(od.loc[days, "et0"].sum())
    E1 = float(om["et0_hourly_sum"].sum())
    E2 = float(fao(om, lat).sum())
    E3 = float(fao(e5, lat_cds).sum())
    groups = {"temperatūra (Tmax, Tmin)": ["tmax", "tmin"], "mitrums (e_a)": ["ea"], "vējš (u)": ["u10"],
              "radiācija (R_s)": ["rs"], "spiediens (P)": ["p"]}
    rows = []
    for gname, cols in groups.items():
        a = e5.copy()
        a[cols] = om[cols]
        up = float(fao(a, lat_cds).sum()) - E3                     # ERA5-Land base, this group from Open-Meteo
        b = om.copy()
        b[cols] = e5[cols]
        down = E2 - float(fao(b, lat).sum())                       # Open-Meteo base, this group from ERA5-Land
        rows.append({"ievade": gname, "delta_no_era5land_bazes": round(up, 2), "delta_no_openmeteo_bazes": round(down, 2),
                     "delta_videja": round((up + down) / 2, 2),
                     "era5land_vid": round(float(e5[cols].mean().mean()), 3), "openmeteo_vid": round(float(om[cols].mean().mean()), 3)})
    tab = pd.DataFrame(rows)
    steps = {"days": len(days), "first": str(days.min().date()), "last": str(days.max().date()),
             "E0_openmeteo_daily_utc+2": round(E0, 2), "E1_openmeteo_hourly_utc": round(E1, 2),
             "E2_fao56_daily_openmeteo_inputs": round(E2, 2), "E3_fao56_daily_era5land": round(E3, 2),
             "total_E0_minus_E3": round(E0 - E3, 2), "day_boundary_E0_minus_E1": round(E0 - E1, 2),
             "hourly_vs_daily_fao56_E1_minus_E2": round(E1 - E2, 2), "inputs_E2_minus_E3": round(E2 - E3, 2),
             "inputs_sum_of_mean_deltas": round(float(tab["delta_videja"].sum()), 2),
             "openmeteo_node": [lon, lat], "era5land_cell_lat": lat_cds, "openmeteo_units": units,
             "rs_daily_mj_mean": {"era5land": round(float(e5["rs"].mean()), 3), "openmeteo": round(float(om["rs"].mean()), 3)}}
    tdir = cfg.run_dir / "tables"
    tab.to_csv(tdir / f"et0_decomposition_kalsnava_{y}{m:02d}.csv", index=False)
    (tdir / f"et0_decomposition_kalsnava_{y}{m:02d}.json").write_text(json.dumps(steps, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(steps, indent=1, ensure_ascii=False))
    print(tab.to_string(index=False))


if __name__ == "__main__":
    main(sys.argv[1])
