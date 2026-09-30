import numpy as np
import xarray as xr

from s2forest.config import DEFAULT_INVALID_SCL
from s2forest.masking import valid_fraction, valid_mask


def _scl():
    scl = np.full((2, 20, 20), 4, dtype="uint8")
    scl[0, 10, 10] = 9      # single cloud pixel
    scl[0, 0, :] = 0        # nodata row (must not be buffered)
    scl[1, 5, 5] = 11       # snow (not buffered)
    scl[1, 15, 15] = 5      # bare soil is valid
    return xr.DataArray(scl, dims=("time", "y", "x"))


def test_classes_masked_without_buffer():
    m = valid_mask(_scl(), DEFAULT_INVALID_SCL, 0).values
    assert not m[0, 10, 10] and not m[0, 0, 3] and not m[1, 5, 5]
    assert m[1, 15, 15] and m[0, 10, 12]


def test_cloud_buffer_grows_clouds_only():
    m = valid_mask(_scl(), DEFAULT_INVALID_SCL, 2).values
    assert not m[0, 10, 12] and not m[0, 12, 10]   # within 2 px of cloud
    assert m[0, 10, 13]                            # 3 px away
    assert m[0, 1, 5] and m[1, 5, 7]               # nodata and snow not grown


def test_dask_and_numpy_agree():
    scl = _scl()
    a = valid_mask(scl, DEFAULT_INVALID_SCL, 2).values
    b = valid_mask(scl.chunk({"time": 1, "y": 7, "x": 7}), DEFAULT_INVALID_SCL, 2).values
    np.testing.assert_array_equal(a, b)


def test_valid_fraction_inside_region():
    mask = xr.DataArray(np.array([[[True, False], [True, True]]]), dims=("time", "y", "x"))
    region = np.array([[True, True], [False, False]])
    assert float(valid_fraction(mask, region)[0]) == 0.5
