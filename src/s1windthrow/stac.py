"""Minimal STAC search for Sentinel-1 RTC on Microsoft Planetary Computer.

Separate from `s2forest.sources.stac_common.stac_search`, which always filters on
`eo:cloud_cover` (a property Sentinel-1 items do not have). Anonymous access: asset
URLs are signed with `planetary_computer.sign` only when they are read.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd
import pystac
import pystac_client

PC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
COLLECTION = "sentinel-1-rtc"


@dataclass
class S1Scene:
    item: pystac.Item
    datetime: datetime
    platform: str            # e.g. "sentinel-1a"
    rel_orbit: int | None    # sat:relative_orbit
    direction: str | None    # sat:orbit_state: ascending / descending
    polarizations: tuple[str, ...]
    epsg: int | None         # proj:epsg of the item (native grid)


def open_client(url: str = PC_URL) -> pystac_client.Client:
    return pystac_client.Client.open(url)


def search_s1(bbox_wgs84: tuple[float, float, float, float], start: date, end: date,
              client: pystac_client.Client | None = None,
              collection: str = COLLECTION) -> list[S1Scene]:
    """All items intersecting the bbox in [start, end] (no property filter)."""
    client = client or open_client()
    search = client.search(collections=[collection], bbox=bbox_wgs84,
                           datetime=f"{start.isoformat()}/{end.isoformat()}T23:59:59Z")
    scenes = []
    for it in search.items():
        p = it.properties
        epsg = p.get("proj:epsg")
        if epsg is None and p.get("proj:code", "").startswith("EPSG:"):
            epsg = int(p["proj:code"].split(":")[1])
        scenes.append(S1Scene(
            item=it,
            datetime=it.datetime,
            platform=str(p.get("platform", "")).lower(),
            rel_orbit=p.get("sat:relative_orbit"),
            direction=p.get("sat:orbit_state"),
            polarizations=tuple(p.get("sar:polarizations", [])),
            epsg=epsg,
        ))
    return sorted(scenes, key=lambda s: s.datetime)


def scenes_table(scenes: list[S1Scene]) -> pd.DataFrame:
    return pd.DataFrame([{
        "id": s.item.id, "datetime": s.datetime, "platform": s.platform,
        "rel_orbit": s.rel_orbit, "direction": s.direction,
        "polarizations": "+".join(s.polarizations), "epsg": s.epsg,
    } for s in scenes])
