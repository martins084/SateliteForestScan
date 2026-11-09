"""Stage 7a: metric / sampling helpers (synthetic data, no files)."""

import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import average_precision_score

from mezasargs_risk import models as M


def test_weighted_ap_matches_sklearn_with_ties():
    rng = np.random.default_rng(1)
    y = (rng.random(4000) < 0.05).astype(int)
    s = np.round(rng.random(4000) + 0.3 * y, 2)            # many ties
    w = rng.integers(0, 3, 4000).astype(float)
    r = M.Ranked(y, s)
    assert r.metrics()["ap"] == pytest.approx(average_precision_score(y, s))
    assert r.metrics(w)["ap"] == pytest.approx(average_precision_score(y, s, sample_weight=w))


def test_random_baseline_and_top_share():
    y = np.r_[np.ones(10), np.zeros(190)]
    m = M.Ranked(y, np.zeros(200)).metrics()
    assert m["ap"] == pytest.approx(0.05) and m["ap_ratio"] == pytest.approx(1) and m["hit5"] == 0.05 and m["lift5"] == 1
    s = np.r_[np.arange(10, 0, -1) + 1000, np.arange(190)]  # all positives on top
    m = M.Ranked(y, s.astype(float)).metrics()
    assert m["ap"] == pytest.approx(1) and m["hit5"] == pytest.approx(1) and m["lift5"] == pytest.approx(20)


def test_subsample_keeps_positives_and_reweights_per_year():
    d = pd.DataFrame({"year": [1] * 1000 + [2] * 500, "label": [1] * 10 + [0] * 990 + [1] * 5 + [0] * 495})
    s = M.subsample(d, 10, 0)
    for y, n_neg in ((1, 990), (2, 495)):
        g = s[s["year"] == y]
        assert g["label"].sum() == (10 if y == 1 else 5)
        assert (g["label"] == 0).sum() == (100 if y == 1 else 50)
        assert g.loc[g["label"] == 0, "w"].sum() == pytest.approx(n_neg)


def test_paired_diff_zero_for_same_scores_and_monotone_variant():
    rng = np.random.default_rng(2)
    y = (rng.random(2000) < 0.1).astype(int)
    s = rng.random(2000) + y
    r = M.paired_diff(y, s, s, rng.integers(0, 8, 2000), 50, 0)
    assert r["d_ap"] == 0 and r["d_ap_lo"] == 0 and r["d_ap_hi"] == 0
    assert M.MONO["A_mono"]["p620_dist_t1"] == -1 and M.MONO["A_mono"]["p620_ha2k_t23"] == 1


# --- stage 7b -----------------------------------------------------------------------------------------------------

def test_weighted_evaluate_equals_expanded_rows():
    rng = np.random.default_rng(3)
    y = (rng.random(3000) < 0.05).astype(int)
    s = rng.random(3000) + 0.5 * y
    w = rng.integers(1, 4, 3000).astype(float)
    ye, se = np.repeat(y, w.astype(int)), np.repeat(s, w.astype(int))       # weights = row multiplicities
    a = M.Ranked(y, s).metrics(w)
    b = M.Ranked(ye, se).metrics()
    assert a["ap"] == pytest.approx(b["ap"]) and a["prevalence"] == pytest.approx(b["prevalence"])
    r = M.evaluate(y, s, rng.integers(0, 20, 3000), 20, 0, w)
    assert r["ap"] == pytest.approx(a["ap"]) and r["ap_lo"] <= r["ap"] <= r["ap_hi"]


def test_sample_stratum_floor_and_weights():
    rng = np.random.default_rng(0)
    g = pd.DataFrame({"label": [1] * 3 + [0] * 1000})
    s = M.sample_stratum(g, 10, 200, rng)                          # 10 x 3 = 30 < floor 200
    assert (s["label"] == 0).sum() == 200 and s.loc[s["label"] == 0, "w"].sum() == pytest.approx(1000)
    s = M.sample_stratum(pd.DataFrame({"label": [1] * 50 + [0] * 300}), 10, 200, rng)   # 500 > 300 -> all
    assert (s["label"] == 0).sum() == 300 and (s["w"] == 1).all()


def test_equal_year_weight_and_relative_pressure():
    d = pd.DataFrame({"year": [2020] * 4 + [2021] * 4, "label": [1, 0, 0, 0, 1, 1, 1, 0], "w": [1.0, 5, 5, 5, 1, 1, 1, 9]})
    w = M.equal_year_weight(d)
    assert w[d["label"].to_numpy() == 1][:1].sum() == pytest.approx(2.0)          # 2020: 1 positive -> x2
    assert w[(d["year"] == 2021).to_numpy() & (d["label"] == 1).to_numpy()].sum() == pytest.approx(2.0)
    assert w[1] == pytest.approx(10.0) and w[7] == pytest.approx(6.0)               # negatives scaled alike
    x = pd.DataFrame({"year": [2024], "p620_ha500_t1": [10.0], "p620_ha2k_t1": [20.0], "p620_ha500_t23": [3.0],
                      "p620_ha2k_t23": [6.0], "p620_dist_t1": [100.0]})
    r = M.relative_pressure(x, {2023: 1000.0, 2022: 200.0, 2021: 100.0})
    assert r["p620_ha2k_t1"].iloc[0] == pytest.approx(0.02) and r["p620_ha2k_t23"].iloc[0] == pytest.approx(0.02)
    assert r["p620_dist_t1"].iloc[0] == 100.0
    assert all(f not in M.VARIANTS7B["B_mono"] for f in ("picea_p500",)) and "picea_p" in M.VARIANTS7B["B_mono"]


def test_strong_baseline_lr_is_monotone_in_distance():
    rng = np.random.default_rng(4)
    n = 4000
    d1, d23 = rng.uniform(0, 5000, n), rng.uniform(0, 5000, n)
    y = (rng.random(n) < 0.3 * np.exp(-d1 / 800)).astype(int)
    d = pd.DataFrame({"p620_dist_t1": d1, "p620_dist_t23": d23, "label": y, "w": 1.0})
    m = M.fit_lr(d)
    coef = m[-1].coef_[0]
    assert coef[0] < 0 and abs(coef[0]) > 5 * abs(coef[1])          # risk falls with distance t-1; t-2..3 is noise
    assert M.score_lr(m, d).shape == (n,)
