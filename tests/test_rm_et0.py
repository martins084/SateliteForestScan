"""mezasargs_risk stage 4: FAO-56 ET0 against the worked examples of FAO Irrigation and Drainage Paper 56."""

import pytest

from mezasargs_risk import et0


def test_example_8_and_9_extraterrestrial_radiation():
    # 3 September (J = 246) at 20 deg S: dr 0.985, delta 0.120, omega_s 1.527, Ra 32.2, N 11.7 h
    phi, dr, delta, ws = et0._sun(-20.0, 246)
    assert float(dr) == pytest.approx(0.985, abs=0.001)
    assert float(delta) == pytest.approx(0.120, abs=0.001)
    assert float(ws) == pytest.approx(1.527, abs=0.001)
    assert float(et0.extraterrestrial(-20.0, 246)) == pytest.approx(32.2, abs=0.05)
    assert float(et0.daylight_hours(-20.0, 246)) == pytest.approx(11.7, abs=0.05)


def test_example_11_net_longwave():
    # Rio de Janeiro, May: Tmax 25.1, Tmin 19.1, ea 2.1, Rs 14.5, Rso 18.8 -> Rnl 3.5 (the example rounds
    # its intermediate values inconsistently, 3.5-3.6)
    assert float(et0.net_longwave(25.1, 19.1, 2.1, 14.5, 18.8)) == pytest.approx(3.55, abs=0.1)


def test_example_18_daily_et0():
    # Uccle, 50 deg 48' N, 100 m, 6 July (J = 187): Tmax 21.5, Tmin 12.3, ea 1.409 kPa, wind 2.78 m/s at
    # 10 m, Rs 22.07 MJ m-2 day-1 -> ETo = 3.88 ~ 3.9 mm/day
    assert float(et0.wind_2m(2.78, 10)) == pytest.approx(2.078, abs=0.002)
    assert float(et0.pressure_from_elevation(100)) == pytest.approx(100.1, abs=0.05)
    assert float(et0.psychrometric(100.1)) == pytest.approx(0.0666, abs=0.0001)
    assert float(et0.slope_vp(16.9)) == pytest.approx(0.122, abs=0.001)
    assert float(et0.extraterrestrial(50.8, 187)) == pytest.approx(41.09, abs=0.05)
    assert float(et0.net_longwave(21.5, 12.3, 1.409, 22.07, 30.90)) == pytest.approx(3.71, abs=0.02)
    e = et0.et0_daily(21.5, 12.3, 1.409, et0.wind_2m(2.78, 10), 22.07, 50.8, 187, elevation_m=100)
    assert float(e) == pytest.approx(3.88, abs=0.02)
