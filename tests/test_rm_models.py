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
