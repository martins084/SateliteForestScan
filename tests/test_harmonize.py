import numpy as np
import xarray as xr

from s2forest.sources import BOA_ADD_OFFSET, harmonize, reflectance_offset


def test_offset_c1_uses_asset_metadata():
    # Earth Search sentinel-2-c1-l2a: baseline 05.xx, offset declared, not applied
    assert reflectance_offset({"s2:processing_baseline": "05.00"}, -0.1) == -0.1


def test_offset_legacy_already_applied_is_not_applied_twice():
    # Earth Search legacy sentinel-2-l2a: raster:bands still says -0.1 but data is shifted
    props = {"s2:processing_baseline": "04.00", "earthsearch:boa_offset_applied": True}
    assert reflectance_offset(props, -0.1) == 0.0


def test_offset_legacy_not_applied():
    props = {"s2:processing_baseline": "04.00", "earthsearch:boa_offset_applied": False}
    assert reflectance_offset(props, -0.1) == -0.1


def test_offset_from_baseline_when_no_metadata():
    # Planetary Computer: no raster:bands
    assert reflectance_offset({"s2:processing_baseline": "04.00"}, None) == BOA_ADD_OFFSET
    assert reflectance_offset({"s2:processing_baseline": "05.10"}, None) == BOA_ADD_OFFSET
    assert reflectance_offset({"s2:processing_baseline": "03.01"}, None) == 0.0
    assert reflectance_offset({}, None) == 0.0


def test_harmonize_values_and_nodata():
    dn = xr.DataArray(np.array([[0, 1000, 1300, 4000]], dtype="uint16"), dims=("y", "x"))
    r = harmonize(dn, 1e-4, -0.1).values
    assert np.isnan(r[0, 0])
    np.testing.assert_allclose(r[0, 1:], [0.0, 0.03, 0.30], atol=1e-6)


def test_same_surface_gives_same_reflectance_across_baselines():
    true = 0.25
    old_dn = xr.DataArray(np.array([round(true / 1e-4)], dtype="uint16"))           # baseline 03.xx
    new_dn = xr.DataArray(np.array([round((true + 0.1) / 1e-4)], dtype="uint16"))   # baseline 04.00+
    a = harmonize(old_dn, 1e-4, reflectance_offset({"s2:processing_baseline": "03.01"}, None))
    b = harmonize(new_dn, 1e-4, reflectance_offset({"s2:processing_baseline": "04.00"}, None))
    np.testing.assert_allclose(a.values, b.values, atol=1e-6)
