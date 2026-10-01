import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

from s2forest.ringcontrol import ring_series, summarize_ring


def test_ring_diff_ratio_and_parts():
    times = pd.to_datetime(["2025-05-10", "2025-07-01", "2025-09-01", "2026-05-05", "2026-07-01"])
    n = 40
    x = 5 + 10 * np.arange(n)
    y = 395 - 10 * np.arange(n)
    arr = np.full((5, n, n), 0.8, dtype="float32")
    arr += np.array([0.2, 0.0, 0.05, 0.2, 0.0], dtype="float32")[:, None, None]   # spring high
    arr[2:, 15:25, 15:25] += 0.1          # polygon: +0.1 from Sep 2025 on
    poly = gpd.GeoDataFrame({"id": [7]}, geometry=[box(150, 150, 250, 250)], crs="EPSG:3059")
    mask = np.ones((n, n), bool)
    ser = ring_series(arr, times, x, y, poly, mask, ring_m=50)
    assert ser["diff"].tolist() == pytest.approx([0, 0, 0.1, 0.1, 0.1], abs=1e-3)
    assert ser.loc[3, "ratio"] == pytest.approx(1.1 / 1.0, abs=1e-3)
    s = summarize_ring(ser).set_index("year")
    assert s.loc[2025, "late_diff"] == pytest.approx(0.1, abs=1e-3)
    assert s.loc[2025, "summer_diff"] == pytest.approx(0.0, abs=1e-3)
    assert s.loc[2026, "early_diff"] == pytest.approx(0.1, abs=1e-3)
    # same absolute difference -> smaller ratio at the high spring level
    assert s.loc[2026, "early_ratio"] < s.loc[2026, "summer_ratio"]
