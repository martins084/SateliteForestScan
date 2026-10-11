"""Hourly precipitation and temperature from the Open-Meteo historical API (no key)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import requests

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


def hourly_weather(lat: float, lon: float, start: date, end: date, cache_dir: Path) -> tuple[pd.DataFrame, dict]:
    """DataFrame indexed by UTC hour with `precip_mm`, `temp_c`; plus API metadata."""
    params = dict(latitude=round(lat, 4), longitude=round(lon, 4), start_date=str(start),
                  end_date=str(end), hourly="precipitation,temperature_2m", timezone="UTC")
    path = cache_dir / f"openmeteo_{params['latitude']}_{params['longitude']}_{start}_{end}.json"
    if path.exists():
        js = json.loads(path.read_text(encoding="utf-8"))
    else:
        r = requests.get(ARCHIVE_URL, params=params, timeout=60)
        r.raise_for_status()
        js = r.json()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(js), encoding="utf-8")
    h = js["hourly"]
    df = pd.DataFrame({"precip_mm": h["precipitation"], "temp_c": h["temperature_2m"]},
                      index=pd.to_datetime(h["time"]))
    meta = {k: js.get(k) for k in ("latitude", "longitude", "elevation")}
    return df, meta


def precip_before(w: pd.DataFrame, t: pd.Timestamp, hours: int) -> float:
    """Precipitation sum in the `hours` before `t` (UTC, tz-naive)."""
    t = pd.Timestamp(t).tz_localize(None) if pd.Timestamp(t).tzinfo else pd.Timestamp(t)
    return float(w["precip_mm"].loc[t - pd.Timedelta(hours=hours): t].sum())
