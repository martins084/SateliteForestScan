"""Stage 4: FAO-56 Penman-Monteith reference evapotranspiration ET0 (daily) and astronomical
day length, only as in

    Allen R.G., Pereira L.S., Raes D., Smith M. (1998) Crop evapotranspiration. FAO Irrigation and
    Drainage Paper 56, https://www.fao.org/4/x0490e/x0490e00.htm

Equation numbers "Eq. n" refer to that paper. The equations are images on the FAO pages; each one
was checked against the paper's worked examples (Example 8: Ra = 32.2, N = 11.7 h; Example 11:
Rnl = 3.5; Example 18: ET0 = 3.9 mm/day) in tests/test_rm_et0.py.

Reference surface: hypothetical grass, 0.12 m, surface resistance 70 s m-1, albedo 0.23 (ch. 2).
ERA5-Land `potential_evaporation` is open-water (pan) evaporation and is not ET0 (plan 2.21).
"""

from __future__ import annotations

import numpy as np

GSC = 0.0820            # solar constant, MJ m-2 min-1 (Eq. 21)
SIGMA = 4.903e-9        # Stefan-Boltzmann constant, MJ K-4 m-2 day-1 (Eq. 39)
ALBEDO = 0.23           # grass reference (Eq. 38)


def sat_vp(t):
    """Eq. 11: saturation vapour pressure e°(T) [kPa], T in deg C."""
    t = np.asarray(t, dtype=float)
    return 0.6108 * np.exp(17.27 * t / (t + 237.3))


def slope_vp(t):
    """Eq. 13: slope of the saturation vapour pressure curve at T [kPa / deg C]."""
    t = np.asarray(t, dtype=float)
    return 4098 * sat_vp(t) / (t + 237.3) ** 2


def pressure_from_elevation(z):
    """Eq. 7: atmospheric pressure [kPa] from elevation z [m]."""
    return 101.3 * ((293 - 0.0065 * np.asarray(z, dtype=float)) / 293) ** 5.26


def psychrometric(p_kpa):
    """Eq. 8: psychrometric constant [kPa / deg C]."""
    return 0.665e-3 * np.asarray(p_kpa, dtype=float)


def wind_2m(uz, z: float = 10.0):
    """Eq. 47: wind speed at 2 m from height z [m]."""
    return np.asarray(uz, dtype=float) * 4.87 / np.log(67.8 * z - 5.42)


def _sun(lat_deg, doy):
    """Eqs. 22-25: latitude [rad], inverse relative distance dr, declination, sunset hour angle."""
    phi = np.radians(np.asarray(lat_deg, dtype=float))
    j = np.asarray(doy, dtype=float)
    dr = 1 + 0.033 * np.cos(2 * np.pi / 365 * j)                    # Eq. 23
    delta = 0.409 * np.sin(2 * np.pi / 365 * j - 1.39)             # Eq. 24
    ws = np.arccos(np.clip(-np.tan(phi) * np.tan(delta), -1, 1))    # Eq. 25
    return phi, dr, delta, ws


def extraterrestrial(lat_deg, doy):
    """Eq. 21: extraterrestrial radiation Ra [MJ m-2 day-1]."""
    phi, dr, delta, ws = _sun(lat_deg, doy)
    return 24 * 60 / np.pi * GSC * dr * (ws * np.sin(phi) * np.sin(delta) + np.cos(phi) * np.cos(delta) * np.sin(ws))


def daylight_hours(lat_deg, doy):
    """Eq. 34: daylight hours N."""
    return 24 / np.pi * _sun(lat_deg, doy)[3]


def net_longwave(tmax, tmin, ea, rs, rso):
    """Eq. 39: net outgoing longwave radiation Rnl [MJ m-2 day-1]."""
    tk4 = ((np.asarray(tmax, float) + 273.16) ** 4 + (np.asarray(tmin, float) + 273.16) ** 4) / 2
    ratio = np.clip(np.asarray(rs, float) / np.asarray(rso, float), 0.0, 1.0)
    return SIGMA * tk4 * (0.34 - 0.14 * np.sqrt(ea)) * (1.35 * ratio - 0.35)


def et0_daily(tmax, tmin, ea, u2, rs, lat_deg, doy, elevation_m=None, p_kpa=None, g: float = 0.0):
    """Eq. 6 with Eq. 12 (es from Tmax / Tmin), Eq. 37 (Rso), Eq. 38 (Rns), Eq. 39 (Rnl), Eq. 40 (Rn),
    G = 0 for daily steps (Eq. 42). Inputs: deg C, kPa, m s-1 at 2 m, Rs in MJ m-2 day-1.
    Pressure: `p_kpa` if given, else Eq. 7 from `elevation_m`. Returns ET0 [mm day-1]."""
    tmax, tmin = np.asarray(tmax, float), np.asarray(tmin, float)
    tmean = (tmax + tmin) / 2
    es = (sat_vp(tmax) + sat_vp(tmin)) / 2                                      # Eq. 12
    delta = slope_vp(tmean)
    p = np.asarray(p_kpa, float) if p_kpa is not None else pressure_from_elevation(elevation_m)
    gamma = psychrometric(p)
    z = 0.0 if elevation_m is None else np.asarray(elevation_m, float)
    rso = (0.75 + 2e-5 * z) * extraterrestrial(lat_deg, doy)                    # Eq. 37
    rn = (1 - ALBEDO) * np.asarray(rs, float) - net_longwave(tmax, tmin, ea, rs, rso)   # Eqs. 38-40
    num = 0.408 * delta * (rn - g) + gamma * 900 / (tmean + 273) * u2 * (es - ea)
    return num / (delta + gamma * (1 + 0.34 * u2))
