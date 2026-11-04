"""Stage 4: daily ERA5 (0.25 deg) from the Open-Meteo historical API (`models=era5`), cached per
ERA5 node and year window, with a persistent budget of weighted API calls.

Open-Meteo returns the centre of the grid cell it used (`latitude`, `longitude`); both the
requested node and the returned coordinates are kept. Weighting (pricing page, 2026-10-29): a
request counts as several calls if it covers "more than 2 weeks for a single location" or "more
than 10 weather variables" (example: 2 weeks with 15 variables = 1.5 calls).
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from shapely.geometry import box

from .config import ClimateConfig, OpenMeteoConfig

STEP = 0.25                      # ERA5 grid spacing (deg)
UNITS = {"temperature_2m_max": "°C", "temperature_2m_min": "°C", "temperature_2m_mean": "°C",
         "precipitation_sum": "mm", "et0_fao_evapotranspiration": "mm", "daylight_duration": "s"}
COLUMNS = {"temperature_2m_max": "tmax", "temperature_2m_min": "tmin", "temperature_2m_mean": "tmean",
           "precipitation_sum": "precip", "et0_fao_evapotranspiration": "et0", "daylight_duration": "daylight_s"}


class SchemaError(ValueError):
    pass


class BudgetExceeded(RuntimeError):
    pass


def nearest_node(lon: float, lat: float) -> tuple[float, float]:
    """Nearest ERA5 0.25 deg node (independent rounding is exact on a regular lon/lat grid)."""
    return round(round(lon / STEP) * STEP, 2), round(round(lat / STEP) * STEP, 2)


def era5_nodes(area, buffer_cells: int = 1) -> pd.DataFrame:
    """Nodes whose 0.25 deg cell (centred on the node) intersects `area` (EPSG:4326 geometry),
    plus `buffer_cells` rings of neighbours. Column `core` = cell touches the area."""
    x0, y0, x1, y1 = area.bounds
    lons = np.arange(np.floor(x0 / STEP) * STEP, x1 + STEP, STEP)
    lats = np.arange(np.floor(y0 / STEP) * STEP, y1 + STEP, STEP)
    h = STEP / 2
    core = {(round(lo, 2), round(la, 2)) for lo in lons for la in lats
            if box(lo - h, la - h, lo + h, la + h).intersects(area)}
    r = range(-buffer_cells, buffer_cells + 1)
    allnodes = {(round(lo + i * STEP, 2), round(la + j * STEP, 2)) for lo, la in core for i in r for j in r}
    df = pd.DataFrame(sorted(allnodes, key=lambda p: (-p[1], p[0])), columns=["lon", "lat"])
    df["core"] = [(lo, la) in core for lo, la in zip(df["lon"], df["lat"])]
    df.insert(0, "node", [node_id(lo, la) for lo, la in zip(df["lon"], df["lat"])])
    return df


def node_id(lon: float, lat: float) -> str:
    return f"N{lat:.2f}_E{lon:.2f}"


def call_weight(n_days: int, n_vars: int) -> float:
    """Weighted API calls of one single-location request [interpretation of the pricing page]."""
    return max(1.0, n_days / 14) * max(1.0, n_vars / 10)


def windows(c: ClimateConfig, today: date | None = None) -> list[tuple[date, date]]:
    """Request windows per year: baseline-only years -> water balance months; years in
    `c.years` -> phenology window (covers the water balance months). Ends at today - delay."""
    today = today or date.today()
    last = today - timedelta(days=c.openmeteo.delay_days)
    m0, m1 = c.wb_months
    out = []
    for y in range(min(c.baseline[0], c.years[0]), max(c.baseline[1], c.years[1]) + 1):
        if y >= c.years[0]:
            s, e = date.fromisoformat(f"{y}-{c.pheno_start}"), date.fromisoformat(f"{y}-{c.pheno_end}")
        else:
            s = date(y, m0, 1)
            e = (pd.Timestamp(y, m1, 1) + pd.offsets.MonthEnd(0)).date()
        e = min(e, last)
        if s <= e:
            out.append((s, e))
    return out


class Budget:
    """Rolling minute / hour / day budget of weighted calls, persisted in a CSV ledger so that
    interrupted runs keep counting. `clock` and `sleep` are injectable for tests."""

    def __init__(self, ledger: Path, om: OpenMeteoConfig, max_wait_s: float = 3600.0,
                 clock=lambda: time.time(), sleep=time.sleep):
        self.ledger, self.om, self.max_wait_s, self.clock, self.sleep = ledger, om, max_wait_s, clock, sleep
        self.entries: list[tuple[float, float]] = []
        if ledger.exists():
            for line in ledger.read_text(encoding="utf-8").splitlines()[1:]:
                t, w = line.split(",")
                self.entries.append((float(t), float(w)))

    def used(self, seconds: float) -> float:
        now = self.clock()
        return sum(w for t, w in self.entries if now - t < seconds)

    def wait_s(self, weight: float) -> float:
        """Seconds until `weight` fits into all three windows (0 = now)."""
        now = self.clock()
        need = 0.0
        for span, cap in ((60, self.om.max_per_minute), (3600, self.om.max_per_hour), (86400, self.om.max_per_day)):
            if weight > cap:
                raise BudgetExceeded(f"one request ({weight:.1f}) exceeds the {span} s cap {cap}")
            inside = sorted((t, w) for t, w in self.entries if now - t < span)
            total = sum(w for _, w in inside)
            for t, w in inside:            # drop the oldest entries until it fits
                if total + weight <= cap:
                    break
                total -= w
                need = max(need, t + span - now)
        return need

    def spend(self, weight: float) -> None:
        w = self.wait_s(weight)
        if w > self.max_wait_s:
            raise BudgetExceeded(f"next request needs a wait of {w / 3600:.1f} h (> {self.max_wait_s / 3600:.1f} h)")
        if w > 0:
            self.sleep(w + 1)
        t = self.clock()
        self.entries.append((t, weight))
        new = not self.ledger.exists()
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger.open("a", encoding="utf-8") as f:
            if new:
                f.write("utc_epoch,weight\n")
            f.write(f"{t:.1f},{weight:.4f}\n")


def parse_daily(js: dict, variables: list[str]) -> tuple[pd.DataFrame, dict]:
    """Open-Meteo daily JSON -> DataFrame (date index, short column names) + metadata. Checks the
    schema: `daily` with `time` and every variable, equal lengths, expected units. JSON nulls -> NaN."""
    if "error" in js and js.get("error"):
        raise SchemaError(f"API error: {js.get('reason')}")
    for k in ("latitude", "longitude", "daily", "daily_units"):
        if k not in js:
            raise SchemaError(f"missing key `{k}`")
    d, u = js["daily"], js["daily_units"]
    if "time" not in d:
        raise SchemaError("missing daily.time")
    n = len(d["time"])
    for v in variables:
        if v not in d:
            raise SchemaError(f"missing daily variable `{v}`")
        if len(d[v]) != n:
            raise SchemaError(f"`{v}` has {len(d[v])} values for {n} days")
        if v in UNITS and u.get(v) != UNITS[v]:
            raise SchemaError(f"`{v}` unit {u.get(v)!r}, expected {UNITS[v]!r}")
    df = pd.DataFrame({COLUMNS.get(v, v): pd.to_numeric(pd.Series(d[v], dtype="object"), errors="coerce")
                       .astype(float).values for v in variables},
                      index=pd.DatetimeIndex(pd.to_datetime(d["time"], format="ISO8601"), name="date"))
    meta = {"lat_returned": js["latitude"], "lon_returned": js["longitude"], "elevation_m": js.get("elevation"),
            "timezone": js.get("timezone"), "utc_offset_seconds": js.get("utc_offset_seconds")}
    return df, meta


def cache_path(cache_dir: Path, om: OpenMeteoConfig, lon: float, lat: float, start: date, end: date) -> Path:
    return cache_dir / om.model / node_id(lon, lat) / f"{start}_{end}.json"


def fetch(lon: float, lat: float, start: date, end: date, om: OpenMeteoConfig, cache_dir: Path,
          budget: Budget | None, session: requests.Session | None = None, retries: int = 5) -> dict:
    """Cached GET for one node and window; counts the weighted calls in `budget`."""
    path = cache_path(cache_dir, om, lon, lat, start, end)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    if budget is None:
        raise BudgetExceeded(f"not cached and no budget given: {path.name}")
    params = {"latitude": lat, "longitude": lon, "start_date": str(start), "end_date": str(end),
              "daily": ",".join(om.daily), "models": om.model, "timezone": om.timezone}
    s = session or requests.Session()
    budget.spend(call_weight((end - start).days + 1, len(om.daily)))
    for k in range(retries):
        r = s.get(om.url, params=params, timeout=120)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(min(60 * 2 ** k, 900))
            continue
        r.raise_for_status()
        js = r.json()
        parse_daily(js, om.daily)                        # schema check before caching
        js["_request"] = params | {"fetched_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(js), encoding="utf-8")
        return js
    raise RuntimeError(f"Open-Meteo: no success after {retries} tries ({r.status_code})")


def load_node(lon: float, lat: float, c: ClimateConfig, cache_dir: Path, budget: Budget | None = None,
              today: date | None = None) -> tuple[pd.DataFrame, dict]:
    """All windows of one node (fetched if missing and a budget is given) as one daily table."""
    frames, meta = [], {}
    for s, e in windows(c, today):
        js = fetch(lon, lat, s, e, c.openmeteo, cache_dir, budget)
        df, meta = parse_daily(js, c.openmeteo.daily)
        frames.append(df)
    out = pd.concat(frames).sort_index()
    out = out[~out.index.duplicated()]
    return out, {"node": node_id(lon, lat), "lon": lon, "lat": lat, **meta,
                 "missing_values": int(out.isna().sum().sum())}


def planned_weight(n_nodes: int, c: ClimateConfig, today: date | None = None) -> float:
    return n_nodes * sum(call_weight((e - s).days + 1, len(c.openmeteo.daily)) for s, e in windows(c, today))
