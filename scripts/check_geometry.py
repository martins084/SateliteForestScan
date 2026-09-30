"""Geometric consistency check between processing baselines (one-off diagnostic).

For 2022 overpasses that Planetary Computer serves both as baseline 04.00 and as
reprocessed 05.10, compare the two versions of the same acquisition in the
native UTM 10 m grid (no resampling) with sub-pixel phase correlation of B08.
Also compares 2022 PC 05.10 against a clear 2023 Earth Search c1 scene.

Usage: python scripts/check_geometry.py
"""

from __future__ import annotations

import sys
from datetime import date

import numpy as np
import odc.stac
import planetary_computer
import pystac_client
from odc.geo.geobox import GeoBox

BBOX = (25.75, 56.61, 25.99, 56.745)  # Kalsnava AOI + ~5 km
UTM = "EPSG:32635"


def phase_shift(a: np.ndarray, b: np.ndarray) -> tuple[float, float, float]:
    """Shift (dy, dx) in pixels of b relative to a, plus peak strength."""
    a = np.nan_to_num(a - np.nanmean(a))
    b = np.nan_to_num(b - np.nanmean(b))
    win = np.outer(np.hanning(a.shape[0]), np.hanning(a.shape[1]))
    fa, fb = np.fft.fft2(a * win), np.fft.fft2(b * win)
    r = fa * np.conj(fb)
    r /= np.abs(r) + 1e-12
    c = np.fft.ifft2(r).real
    iy, ix = np.unravel_index(np.argmax(c), c.shape)

    def sub(cm, c0, cp):  # parabolic sub-pixel peak
        d = cm - 2 * c0 + cp
        return 0.0 if d == 0 else 0.5 * (cm - cp) / d

    ny, nx = c.shape
    dy = iy + sub(c[(iy - 1) % ny, ix], c[iy, ix], c[(iy + 1) % ny, ix])
    dx = ix + sub(c[iy, (ix - 1) % nx], c[iy, ix], c[iy, (ix + 1) % nx])
    dy = dy - ny if dy > ny / 2 else dy
    dx = dx - nx if dx > nx / 2 else dx
    return -dy, -dx, float(c[iy, ix])


def load(item, band, gbox, patch=None):
    ds = odc.stac.load([item], bands=[band], geobox=gbox, resampling="nearest",
                       patch_url=patch, stac_cfg={"*": {"assets": {"*": {"data_type": "uint16", "nodata": 0}}}})
    return ds[band].isel(time=0).values.astype("float32")


def main() -> int:
    pc = pystac_client.Client.open("https://planetarycomputer.microsoft.com/api/stac/v1")
    es = pystac_client.Client.open("https://earth-search.aws.element84.com/v1")
    # Native S2 grid: pixel edges on multiples of 10 m in UTM 35N.
    gbox = GeoBox.from_bbox(BBOX, crs="EPSG:4326", resolution=0.0001).to_crs(UTM)
    gbox = GeoBox.from_bbox(gbox.boundingbox, crs=UTM, resolution=10, tight=False)

    items = list(pc.search(collections=["sentinel-2-l2a"], bbox=BBOX,
                           datetime="2022-05-01/2022-09-30",
                           query={"eo:cloud_cover": {"lte": 10}}).items())
    by_acq: dict = {}
    for it in items:
        key = (it.datetime.date(), it.properties["s2:mgrs_tile"])
        by_acq.setdefault(key, {})[it.properties["s2:processing_baseline"]] = it
    pairs = [(k, v) for k, v in sorted(by_acq.items()) if "04.00" in v and any(b.startswith("05") for b in v)]
    print(f"{len(pairs)} overpasses with both 04.00 and 05.xx (cloud <= 10 %)")

    results = []
    for (d, tile), v in pairs:
        new_key = max(b for b in v if b.startswith("05"))
        a = load(v["04.00"], "B08", gbox, planetary_computer.sign)
        b = load(v[new_key], "B08", gbox, planetary_computer.sign)
        if np.mean(a > 0) < 0.9 or np.mean(b > 0) < 0.9:
            continue
        dy, dx, peak = phase_shift(a, b)
        results.append((dy, dx))
        print(f"{d} {tile}  04.00 -> {new_key}:  dy={dy:+.2f} px  dx={dx:+.2f} px  "
              f"|d|={np.hypot(dy, dx):.2f} px  (peak {peak:.2f})")

    ref = list(es.search(collections=["sentinel-2-c1-l2a"], bbox=BBOX, datetime="2023-09-28/2023-09-28").items())
    if ref and pairs:
        r = load(ref[0], "nir", gbox)
        for (d, tile), v in pairs[:3]:
            for bl in ("04.00", max(b for b in v if b.startswith("05"))):
                x = load(v[bl], "B08", gbox, planetary_computer.sign)
                dy, dx, peak = phase_shift(r, x)
                print(f"vs c1 2023-09-28: {d} {bl}: dy={dy:+.2f} dx={dx:+.2f} |d|={np.hypot(dy, dx):.2f} px (peak {peak:.2f})")

    if results:
        m = np.max([np.hypot(*r) for r in results])
        print(f"max shift between baselines: {m:.2f} px ({m * 10:.1f} m)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
