import numpy as np
import pytest
import xarray as xr

from s2forest.indices import INDICES, compute_indices, register_index


def _ds(**bands):
    return xr.Dataset({b: xr.DataArray(np.float32(v))
                       for b, v in bands.items()})


HEALTHY = dict(B04=0.03, B05=0.07, B08=0.30, B8A=0.31, B11=0.15, B12=0.07)


def test_formulas_against_hand_computed_values():
    out = compute_indices(_ds(**HEALTHY), ["ndvi", "ndre", "ndmi", "crswir"])
    assert float(out.ndvi) == pytest.approx((0.30 - 0.03) / 0.33, abs=1e-6)
    assert float(out.ndre) == pytest.approx((0.31 - 0.07) / 0.38, abs=1e-6)
    assert float(out.ndmi) == pytest.approx((0.31 - 0.15) / 0.46, abs=1e-6)
    cont = 0.31 + (0.07 - 0.31) * (1.610 - 0.865) / (2.190 - 0.865)
    assert float(out.crswir) == pytest.approx(0.15 / cont, abs=1e-5)


def test_stress_directions():
    """Drier/damaged canopy: NIR down, SWIR up -> NDVI/NDMI down, CRSWIR up."""
    damaged = dict(HEALTHY, B08=0.22, B8A=0.23, B11=0.20, B12=0.11, B04=0.05)
    h = compute_indices(_ds(**HEALTHY), list(INDICES))
    d = compute_indices(_ds(**damaged), list(INDICES))
    for name, spec in INDICES.items():
        if name in ("ndvi", "ndre", "ndmi", "crswir"):
            assert np.sign(float(d[name]) - float(h[name])) == spec.stress_sign, name


def test_nan_and_zero_denominators():
    ds = xr.Dataset({b: xr.DataArray(np.array([np.nan, 0.0], dtype="float32"), dims=("x",))
                     for b in HEALTHY})
    out = compute_indices(ds, ["ndvi", "crswir"])
    assert np.isnan(out.ndvi.values).all() and np.isnan(out.crswir.values).all()


def test_register_new_index():
    @register_index("_test_sr", ("B08", "B04"), -1, "simple ratio")
    def sr(ds):
        return ds.B08 / ds.B04

    out = compute_indices(_ds(**HEALTHY), ["_test_sr"])
    assert float(out["_test_sr"]) == pytest.approx(10.0)
    assert out["_test_sr"].attrs["stress_sign"] == -1
    del INDICES["_test_sr"]


def test_unknown_index_raises():
    with pytest.raises(KeyError):
        compute_indices(_ds(**HEALTHY), ["nope"])
