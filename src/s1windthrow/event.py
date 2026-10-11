"""Pre/post-event acquisition selection, per relative orbit."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from .stac import S1Scene


@dataclass
class Acquisition:
    """One overpass: all STAC slices with the same date, platform and relative orbit."""
    date: date
    platform: str
    rel_orbit: int
    direction: str
    scenes: list[S1Scene] = field(default_factory=list)
    aoi_cover: float = 0.0   # share of the AOI inside the footprint (WGS84 areas)

    @property
    def ids(self) -> list[str]:
        return [s.item.id for s in self.scenes]


def group_acquisitions(scenes: list[S1Scene], aoi_wgs84: BaseGeometry) -> list[Acquisition]:
    groups: dict[tuple, Acquisition] = {}
    for s in scenes:
        key = (s.datetime.date(), s.platform, s.rel_orbit, s.direction)
        if key not in groups:
            groups[key] = Acquisition(*key)
        groups[key].scenes.append(s)
    for a in groups.values():
        foot = unary_union([shape(s.item.geometry) for s in a.scenes])
        a.aoi_cover = float(foot.intersection(aoi_wgs84).area / aoi_wgs84.area)
    return sorted(groups.values(), key=lambda a: (a.rel_orbit, a.date))


def select_window(acqs: list[Acquisition], start: date, end: date, n_max: int,
                  event: date, min_aoi_cover: float) -> tuple[list[Acquisition], list[tuple[Acquisition, str]]]:
    """Acquisitions in [start, end] with enough AOI cover; if more than `n_max`, keep the
    ones closest to the event. Returns (selected, [(rejected, reason)])."""
    inside = [a for a in acqs if start <= a.date <= end]
    rejected = [(a, f"AOI pārklājums {a.aoi_cover:.3f} < {min_aoi_cover}")
                for a in inside if a.aoi_cover < min_aoi_cover]
    ok = [a for a in inside if a.aoi_cover >= min_aoi_cover]
    ok.sort(key=lambda a: abs((a.date - event).days))
    rejected += [(a, f"ārpus {n_max} tuvākajiem notikumam") for a in ok[n_max:]]
    return sorted(ok[:n_max], key=lambda a: a.date), rejected


def selection_table(selected: dict[str, list[Acquisition]],
                    rejected: dict[str, list[tuple[Acquisition, str]]]) -> pd.DataFrame:
    rows = []
    for window, acqs in selected.items():
        for a in acqs:
            rows.append({"window": window, "rel_orbit": a.rel_orbit, "direction": a.direction,
                         "date": a.date, "platform": a.platform, "aoi_cover": round(a.aoi_cover, 3),
                         "used": True, "reason": "", "ids": ";".join(a.ids)})
    for window, rej in rejected.items():
        for a, why in rej:
            rows.append({"window": window, "rel_orbit": a.rel_orbit, "direction": a.direction,
                         "date": a.date, "platform": a.platform, "aoi_cover": round(a.aoi_cover, 3),
                         "used": False, "reason": why, "ids": ";".join(a.ids)})
    return pd.DataFrame(rows).sort_values(["rel_orbit", "window", "date"], ignore_index=True)
