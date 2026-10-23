"""amplitude_scope option: default identical to v0.2; 'stress_only' keeps only cuts."""

import numpy as np
import xarray as xr

from s2forest.config import ForestMaskConfig
from s2forest.pipeline import keep_only_cuts


def _feats():
    flag = np.array([[1, 1, 0, np.nan]], "float32")
    is_cut = np.array([[1, 0, 0, np.nan]], "float32")
    other = np.ones((1, 4), "float32")
    return xr.Dataset({"flag": (("y", "x"), flag), "is_cut": (("y", "x"), is_cut),
                       "z_primary": (("y", "x"), other)})


def test_default_scope_is_v02():
    assert ForestMaskConfig().amplitude_scope == "all"


def test_keep_only_cuts_in_given_pixels():
    f = _feats()
    z = xr.DataArray(np.ones((2, 1, 4), "float32"), dims=("time", "y", "x"))
    d = z.copy()
    px = np.array([[True, True, True, False]])
    f2, z2, d2 = keep_only_cuts(f, z, d, px)
    assert f2["flag"].values[0, 0] == 1 and f2["is_cut"].values[0, 0] == 1   # cut kept
    assert np.isnan(f2["flag"].values[0, 1])                                 # stress dropped
    assert np.isnan(f2["flag"].values[0, 2])                                 # unflagged -> not analysed
    assert np.isnan(f2["flag"].values[0, 3])                                 # outside pixels untouched (NaN)
    assert np.isfinite(z2.values[:, 0, 0]).all() and np.isnan(z2.values[:, 0, 1]).all()


def test_no_pixels_no_change():
    f = _feats()
    z = xr.DataArray(np.ones((2, 1, 4), "float32"), dims=("time", "y", "x"))
    f2, _, _ = keep_only_cuts(f, z, z.copy(), np.zeros((1, 4), bool))
    xr.testing.assert_identical(f, f2)
