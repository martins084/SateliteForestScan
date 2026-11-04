"""Stage 4: RITY-2 phenology of Ips typographus, only as published in

    Ogris N. (2020) Calculation procedure for RITY - a phenology model of Ips typographus.
    MethodsX 7:100845, doi:10.1016/j.mex.2020.100845, PMC7076557 (CC BY 4.0).

Equation numbers "(n)" below refer to that paper. RITY-2 was calibrated for Slovenia with INCA
air temperatures (I_min, I_mean, I_max). User decision (plan 2.13, point 5): ERA5 temperature is
used directly as forest air temperature AT; the INCA -> forest air corrections (1)-(3) only in a
sensitivity variant. The thresholds of (10)-(15) are applied to I_max = ERA5 daily maximum in both
variants, as in the paper.

Interpretations not stated in the paper [N], all marked in the code: the degree-day sums in (10),
(11) count only positive parts (I_max - 8.3); the day that reaches a threshold counts towards it;
F3 starts at Tsum_F1 > 2 exactly as printed in (15); sister broods are counted separately from the
filial generations F1-F3.

PHENIPS-Clim (Jakoby, Lischke & Wermelinger 2019, GCB, doi:10.1111/gcb.14766, Table 1) is only a
sensitivity check of the swarming date and only through its thresholds: annual thermal sum
Tsw_sum = 100 dd above Tdev_min = 5.12 deg C from 1 January (diapause end, its Eq. 4) and the
minimum flight temperature Tfly_min = 16.11 deg C. Its maturation feeding and hourly flight
model are not reproduced, so the date is a lower bound [N].
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# (1)-(3) forest air temperature from INCA: AT = a + b * I   (sensitivity variant only)
FOREST_AIR = {"min": (1.44, 0.82), "mean": (0.50, 0.81), "max": (1.03, 0.86)}
# (4)-(6) bark temperature from forest air temperature: BT = a + b * AT
BARK = {"min": (0.56, 0.99), "mean": (-0.48, 1.03), "max": (0.03, 0.99)}
# (7)-(9) effective bark temperature
DT_L, T_O, DT_U = 8.3, 30.4, 38.9
ALPHA, BETA, GAMMA, TMAX = 0.02876507, 3.5922336, 1.24657367, 40.9958913      # (8)
SWARM_DD = 53.0            # (10) onset of swarming
INFEST_DD = 155.6          # (11) onset of infestation
FLIGHT_TMAX = 14.5         # (10)-(15) I_max threshold for flight activity (deg C)
K_DD = 557.0               # (12)-(15) thermal sum for total development
DAYLENGTH_H = 14.5         # (13)-(15) day length for sister broods / F2 / F3
HIBERNATION = 0.6          # text after (15): generations with Tsum < 0.6 at 31 Oct are ignored
START, END = "03-07", "10-31"                  # daily from 7 March to 31 October
SCENARIOS = {"MIN": "min", "AVG": "mean", "MAX": "max"}
COL = {"min": "tmin", "mean": "tmean", "max": "tmax"}

# PHENIPS-Clim Table 1 (sensitivity only)
PC_TSW_SUM, PC_TDEV_MIN, PC_TFLY_MIN = 100.0, 5.12, 16.11


def forest_air(i: np.ndarray, kind: str) -> np.ndarray:
    """(1)-(3)."""
    a, b = FOREST_AIR[kind]
    return a + b * np.asarray(i, dtype=float)


def bark(at: np.ndarray, kind: str) -> np.ndarray:
    """(4)-(6)."""
    a, b = BARK[kind]
    return a + b * np.asarray(at, dtype=float)


def bteff(bt: np.ndarray) -> np.ndarray:
    """(7) linear between DT_L and T_O, (8) non-linear between T_O and DT_U, (9) zero outside."""
    bt = np.asarray(bt, dtype=float)
    lin = bt - DT_L
    nonlin = (T_O - DT_L) * (np.exp(ALPHA * bt) - np.exp(ALPHA * TMAX - (TMAX - bt) / BETA) - GAMMA)
    out = np.where((bt > DT_L) & (bt <= T_O), lin, 0.0)
    out = np.where((bt > T_O) & (bt < DT_U), nonlin, out)
    return np.where(np.isnan(bt), np.nan, out)


def first(mask: np.ndarray, start: int = 0) -> int | None:
    idx = np.flatnonzero(mask[start:])
    return int(idx[0]) + start if len(idx) else None


def onset(imax: np.ndarray, threshold_dd: float) -> int | None:
    """(10) / (11): first day with I_max > 14.5 and sum(I_max - 8.3) >= threshold since the start
    (positive parts only, the day itself included [N])."""
    cs = np.cumsum(np.maximum(imax - DT_L, 0.0))
    return first((cs >= threshold_dd) & (imax > FLIGHT_TMAX))


def generations(be: np.ndarray, flight: np.ndarray, long_day: np.ndarray, infest: int) -> dict:
    """(12)-(15) from the onset of infestation: relative thermal sums (Tsum = sum(BTeff) / K) of
    F1, sister broods S_j (start when Tsum_F1 > j - 0.5), F2 (Tsum_F1 > 1) and F3 (Tsum_F1 > 2,
    as printed in (15) [N]); S_j / F2 / F3 also need I_max > 14.5 and day length >= 14.5 h.
    Returns start indices and Tsum at the last day."""
    n = len(be)
    be = np.nan_to_num(be)

    def tsum_from(i: int | None) -> np.ndarray:
        t = np.zeros(n)
        if i is not None:
            t[i:] = np.cumsum(be[i:]) / K_DD
        return t

    f1 = tsum_from(infest)
    ok = flight & long_day
    res = {"F1": (infest, float(f1[-1]))}
    for name, level in (("F2", 1.0), ("F3", 2.0)):
        i = first((f1 > level) & ok)
        res[name] = (i, float(tsum_from(i)[-1]) if i is not None else np.nan)
    j = 1
    while True:
        i = first((f1 > j - 0.5) & ok)
        if i is None:
            break
        res[f"S{j}"] = (i, float(tsum_from(i)[-1]))
        j += 1
    res["_f1_complete"] = first(f1 >= 1.0)
    return res


def rity2(day: pd.DataFrame, year: int, scenario: str = "AVG", inca: bool = False) -> dict:
    """One year at one location. `day`: daily table with tmax, tmin, tmean (deg C) and daylight_s,
    covering 7 March - 31 October of `year`."""
    d = day.loc[f"{year}-{START}":f"{year}-{END}"]
    n_expected = (pd.Timestamp(f"{year}-{END}") - pd.Timestamp(f"{year}-{START}")).days + 1
    gapless = (len(d) > 0 and d.index[0] == pd.Timestamp(f"{year}-{START}")
               and len(d) == (d.index[-1] - d.index[0]).days + 1
               and not d[["tmax", "tmin", "tmean", "daylight_s"]].isna().any().any())
    out = {"year": year, "scenario": scenario, "variant": "inca_1-3" if inca else "era5_direct",
           "days": len(d), "last_date": d.index[-1].date() if len(d) else None,
           "complete": gapless and len(d) == n_expected}
    # a running year (data end before 31 October) is computed up to its last day, `complete` False
    if not gapless:
        return out
    kind = SCENARIOS[scenario]
    imax = d["tmax"].to_numpy()
    at = d[COL[kind]].to_numpy()
    if inca:
        at = forest_air(at, kind)
    be = bteff(bark(at, kind))
    sw, inf = onset(imax, SWARM_DD), onset(imax, INFEST_DD)
    doy = lambda i: int(d.index[i].dayofyear) if i is not None else np.nan  # noqa: E731
    out |= {"swarming_doy": doy(sw), "swarming_date": d.index[sw].date() if sw is not None else None,
            "infestation_doy": doy(inf)}
    if inf is None:
        return out | {"n_filial": 0, "n_sister": 0}
    g = generations(be, imax > FLIGHT_TMAX, d["daylight_s"].to_numpy() / 3600 >= DAYLENGTH_H, inf)
    fil = [k for k in ("F1", "F2", "F3") if g[k][0] is not None and g[k][1] >= HIBERNATION]
    sis = [k for k in g if k.startswith("S") and g[k][1] >= HIBERNATION]
    out |= {f"tsum_{k}": round(v[1], 3) for k, v in g.items() if not k.startswith("_")}
    out |= {f"onset_doy_{k}": doy(v[0]) for k, v in g.items() if not k.startswith("_") and k != "F1"}
    out |= {"f1_complete_doy": doy(g["_f1_complete"]), "n_filial": len(fil), "n_sister": len(sis)}
    return out


def phenips_clim_swarming(day: pd.DataFrame, year: int) -> dict:
    """PHENIPS-Clim thresholds (sensitivity, lower bound [N]): first day after 1 January with
    sum(T_mean - 5.12)+ >= 100 dd and T_max >= 16.11 deg C (daily ERA5 instead of hourly values)."""
    d = day.loc[f"{year}-01-01":f"{year}-{END}"]
    if d.empty or d.index[0] != pd.Timestamp(f"{year}-01-01") or d[["tmean", "tmax"]].isna().any().any():
        return {"year": year, "phenips_clim_swarming_doy": np.nan}
    cs = np.cumsum(np.maximum(d["tmean"].to_numpy() - PC_TDEV_MIN, 0.0))
    i = first((cs >= PC_TSW_SUM) & (d["tmax"].to_numpy() >= PC_TFLY_MIN))
    return {"year": year, "phenips_clim_swarming_doy": int(d.index[i].dayofyear) if i is not None else np.nan}
