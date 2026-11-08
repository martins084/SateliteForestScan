"""Stage 7a (user decision 2026-11-05): first models on the PILOT block only (no model for all of Latvia).

- Baselines: (i) random (score constant -> PR-AUC = share of positives in the year), (ii) distance to LVM 620 t-1 only,
  (iii) distance to LVM 620 t-2..t-3 only (L3).
- HistGradientBoosting variants: A pressure (A_mono: same with monotone constraints, sensitivity); B pressure + stand (HRL, Picea, EFDA cuts / edges / history); B_chm =
  B + CHMv2 (t >= 2020 only, NaN before -> learnt from 2020+ rows); C = B + climate (cwb_z t-1, t-1+t-2, Tsum_F1 t-1).
- Negatives subsampled 1:10 per training year with weights (L5), fixed seed. Training rows: in_set only.
- Validation in time: train on years <= t-1, test in year t, t = 2020..2024 (expanding window). Additionally spatial
  blocks: z12 quadkey tiles (~5 km here) in GroupKFold; a cell of year t is scored by a model trained on years < t
  and on other tiles only.
- Metrics per year (all cells and "new foci" = cells > 500 m from any LVM 620 t-1 polygon): PR-AUC (average
  precision) and its ratio to the share of positives, hit share (recall) and lift in the top 5 % / 10 % of the area.
  95 % CI: bootstrap over the spatial tiles of the test year (cluster bootstrap).
- Feature importance: permutation on the test year (drop in average precision), not impurity. No SHAP.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

PRESSURE = ["p620_dist_t1", "p620_ha500_t1", "p620_ha2k_t1", "p620_dist_t23", "p620_ha500_t23", "p620_ha2k_t23"]
STAND = ["hrl_conifer_100m", "hrl_conifer_share_500m", "picea_p", "picea_p500", "cut_dist_t13", "cut_dist_t110",
         "edge_s_sw_w_t13", "years_since_dist"]
CHM = ["chm_mean", "chm_p90", "chm_gt5"]
CLIMATE = ["cwb_z_t1", "cwb_z_t12", "tsum_F1_t1"]
VARIANTS = {"A": PRESSURE, "A_mono": PRESSURE, "B": PRESSURE + STAND, "B_chm": PRESSURE + STAND + CHM, "C": PRESSURE + STAND + CLIMATE}
# sensitivity (added 2026-11-05 after the first pilot run): A with monotone constraints (risk falls with distance,
# rises with 620 area) - tests whether A loses to the distance baseline because of non-monotone fits to 2023
MONO = {"A_mono": {f: (-1 if "_dist_" in f else 1) for f in PRESSURE}}
BASELINES = {"random": None, "dist_t1": "p620_dist_t1", "dist_t23": "p620_dist_t23"}


# --- metrics ----------------------------------------------------------------------------------------------------

class Ranked:
    """A score vector sorted once; metrics for any row weights (bootstrap multiplicities) in O(n)."""

    def __init__(self, y: np.ndarray, s: np.ndarray, seed: int = 0):
        rng = np.random.default_rng(seed)
        self.o = np.lexsort((rng.random(len(s)), -s))           # descending score, random order within ties
        self.y = y[self.o].astype(np.float64)
        ss = s[self.o]
        self.last = np.r_[np.nonzero(np.diff(ss))[0], len(ss) - 1]   # last row of each tie block (AP)
        self.const = bool(len(ss) and ss[0] == ss[-1])                # random baseline: expected values

    def metrics(self, w: np.ndarray | None = None, tops=(0.05, 0.10)) -> dict:
        w = np.ones(len(self.y)) if w is None else w[self.o].astype(np.float64)
        wy = w * self.y
        tp, cw = np.cumsum(wy), np.cumsum(w)
        P, W = tp[-1], cw[-1]
        out = {"prevalence": P / W if W > 0 else np.nan}
        if P <= 0:
            return out | {"ap": np.nan, "ap_ratio": np.nan} | {f"{m}{int(k * 100)}": np.nan for k in tops for m in ("hit", "lift")}
        tpl, cwl = tp[self.last], cw[self.last]
        with np.errstate(invalid="ignore", divide="ignore"):
            prec = np.where(cwl > 0, tpl / cwl, 0.0)
        rec = tpl / P
        out["ap"] = float(np.sum(np.diff(np.r_[0.0, rec]) * prec))
        out["ap_ratio"] = out["ap"] / out["prevalence"]
        for k in tops:
            if self.const:
                out[f"hit{int(k * 100)}"], out[f"lift{int(k * 100)}"] = float(k), 1.0
                continue
            sel = cw <= k * W
            n = int(sel.sum())
            hit = tp[n - 1] / P if n else 0.0
            frac = cw[n - 1] / W if n else k
            out[f"hit{int(k * 100)}"] = float(hit)
            out[f"lift{int(k * 100)}"] = float(hit / frac) if frac > 0 else np.nan
        return out


def evaluate(y, s, groups, n_boot: int, seed: int) -> dict:
    """Point metrics + 95 % cluster-bootstrap CI over `groups` (spatial tiles of the test year)."""
    r = Ranked(np.asarray(y), np.asarray(s, dtype=np.float64), seed)
    point = r.metrics()
    g_codes, g_idx = np.unique(groups, return_inverse=True)
    G = len(g_codes)
    rng = np.random.default_rng(seed + 1)
    reps = []
    for _ in range(n_boot):
        mult = np.bincount(rng.integers(0, G, G), minlength=G).astype(np.float64)
        reps.append(r.metrics(mult[g_idx]))
    rep = pd.DataFrame(reps)
    out = {"n": int(len(y)), "positives": int(np.sum(y)), "tiles": G} | {k: float(v) for k, v in point.items()}
    for k in point:
        v = rep[k].dropna()
        out[f"{k}_lo"], out[f"{k}_hi"] = (float(v.quantile(0.025)), float(v.quantile(0.975))) if len(v) else (np.nan, np.nan)
    return out


# --- data -------------------------------------------------------------------------------------------------------

def tiles(cell_id: np.ndarray, transform, width: int, zoom: int) -> np.ndarray:
    """Web Mercator tile (zoom) of each EFDA cell centre as one int (same partition as the z-level quadkey)."""
    from pyproj import Transformer

    row, col = np.divmod(cell_id.astype(np.int64), width)
    x = transform.c + (col + 0.5) * transform.a
    y = transform.f + (row + 0.5) * transform.e
    lon, lat = Transformer.from_crs(3035, 4326, always_xy=True).transform(x, y)
    n = 2 ** zoom
    tx = np.floor((np.asarray(lon) + 180) / 360 * n).astype(np.int64)
    s = np.sin(np.radians(np.asarray(lat)))
    ty = np.floor((0.5 - np.log((1 + s) / (1 - s)) / (4 * math.pi)) * n).astype(np.int64)
    return tx * n + ty


def subsample(d: pd.DataFrame, ratio: float, seed: int) -> pd.DataFrame:
    """All positives + `ratio` x as many negatives per year; weight = negatives / sampled negatives (L5)."""
    rng = np.random.default_rng(seed)
    parts = []
    for y, g in d.groupby("year"):
        pos, neg = g[g["label"] == 1], g[g["label"] == 0]
        k = min(len(neg), int(round(ratio * max(len(pos), 1))))
        take = neg.iloc[rng.choice(len(neg), k, replace=False)] if k < len(neg) else neg
        parts.append(pos.assign(w=1.0))
        parts.append(take.assign(w=len(neg) / max(len(take), 1)))
    return pd.concat(parts, ignore_index=True)


def fit(train: pd.DataFrame, feats: list[str], params: dict, seed: int, mono: dict | None = None):
    from sklearn.ensemble import HistGradientBoostingClassifier

    feats = [f for f in feats if train[f].notna().any()]    # e.g. CHMv2 when every training year is < 2020
    extra = {"monotonic_cst": [mono.get(f, 0) for f in feats]} if mono else {}
    m = HistGradientBoostingClassifier(random_state=seed, **params, **extra)
    m.fit(train[feats].to_numpy(np.float32), train["label"].to_numpy(), sample_weight=train["w"].to_numpy())
    m.feats_ = feats
    return m


def score(model, d: pd.DataFrame, feats: list[str] | None = None) -> np.ndarray:
    return model.predict_proba(d[model.feats_].to_numpy(np.float32))[:, 1]


def baseline_score(d: pd.DataFrame, name: str) -> np.ndarray:
    col = BASELINES[name]
    return np.zeros(len(d)) if col is None else -d[col].to_numpy(np.float64)


def group_folds(groups: np.ndarray, k: int, seed: int) -> dict[int, int]:
    """Tile -> fold (random assignment of tiles to k folds, fixed seed)."""
    u = np.unique(groups)
    rng = np.random.default_rng(seed)
    f = rng.permutation(len(u)) % k
    return dict(zip(u.tolist(), f.tolist()))


def paired_diff(y, s1, s2, groups, n_boot: int, seed: int, keys=("ap", "ap_ratio", "hit5", "hit10")) -> dict:
    """Metric(s2) - metric(s1) with a 95 % CI from the SAME cluster-bootstrap replicates (paired)."""
    y = np.asarray(y)
    r1, r2 = Ranked(y, np.asarray(s1, np.float64), seed), Ranked(y, np.asarray(s2, np.float64), seed)
    p1, p2 = r1.metrics(), r2.metrics()
    g_codes, g_idx = np.unique(groups, return_inverse=True)
    G = len(g_codes)
    rng = np.random.default_rng(seed + 1)
    reps = []
    for _ in range(n_boot):
        w = np.bincount(rng.integers(0, G, G), minlength=G).astype(np.float64)[g_idx]
        a, b = r1.metrics(w), r2.metrics(w)
        reps.append({k: b[k] - a[k] for k in keys})
    rep = pd.DataFrame(reps)
    out = {}
    for k in keys:
        v = rep[k].dropna()
        out[f"d_{k}"] = p2[k] - p1[k]
        out[f"d_{k}_lo"], out[f"d_{k}_hi"] = (float(v.quantile(0.025)), float(v.quantile(0.975))) if len(v) else (np.nan, np.nan)
    return out
