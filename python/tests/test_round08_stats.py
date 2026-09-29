"""T4: numeric tests for the pure statistics functions.

Every expected value here is hand-derived (or taken from the task sheet); no
expected value was produced by the function under test.
"""

import math
import random

import pytest

from skelnet import stats


def test_pass_at_k_values():
    assert stats.pass_at_k(3, 1, 1) == pytest.approx(1 / 3)
    assert stats.pass_at_k(3, 1, 3) == 1.0
    assert stats.pass_at_k(5, 2, 3) == pytest.approx(0.9)
    assert stats.pass_at_k(3, 0, 3) == 0.0
    with pytest.raises(ValueError):
        stats.pass_at_k(2, 1, 3)


def test_mcnemar_exact_values():
    assert stats.mcnemar_exact(10, 2) == pytest.approx(158 / 4096)
    assert stats.mcnemar_exact(0, 0) == 1.0
    assert stats.mcnemar_exact(5, 5) == 1.0


def test_stratified_mcnemar_merges_models():
    pairs = {
        "A": [(True, False), (True, False), (False, True)],
        "B": [(True, False), (False, True), (False, True)],
    }
    result = stats.stratified_mcnemar(pairs)
    assert result["b"] == 3 and result["c"] == 3
    assert result["per_model"]["A"] == {"b": 2, "c": 1}
    assert result["per_model"]["B"] == {"b": 1, "c": 2}
    assert result["p"] == stats.mcnemar_exact(3, 3)


def test_holm_monotone_and_order_preserving():
    assert stats.holm([0.01, 0.04, 0.03, 0.005]) == pytest.approx(
        [0.03, 0.06, 0.06, 0.02])


def test_cochran_q_worked_example():
    blocks = [[1, 1, 0], [1, 0, 0], [1, 1, 1], [0, 0, 0], [1, 0, 0],
              [1, 1, 0]]
    result = stats.cochran_q(blocks)
    assert result["Q"] == pytest.approx(6.0)
    assert result["df"] == 2
    assert result["p"] == pytest.approx(math.exp(-3), abs=1e-6)


def test_cochran_q_zero_variance():
    result = stats.cochran_q([[1, 1], [1, 1], [0, 0]])
    assert result == {"Q": 0.0, "df": 1, "p": 1.0}


def test_chi2_sf_known_points():
    assert stats.chi2_sf(7.8147, 3) == pytest.approx(0.05, abs=1e-4)
    assert stats.chi2_sf(11.0705, 5) == pytest.approx(0.05, abs=1e-4)
    assert stats.chi2_sf(6.0, 2) == pytest.approx(math.exp(-3), abs=1e-6)


def test_wilcoxon_exact_worked_example():
    result = stats.wilcoxon_signed_rank([1.5, -0.5, 2.0, 3.0, -1.0, 2.5, 0.7])
    assert result["w_plus"] == 24
    assert result["w_minus"] == 4
    assert result["method"] == "exact"
    assert result["p"] == pytest.approx(0.109375)


def test_wilcoxon_drops_zero_differences():
    result = stats.wilcoxon_signed_rank([1, -1, 0])
    assert result["n"] == 2
    assert result["p"] == 1.0


def test_wilcoxon_tie_normal_approximation():
    # diffs [1,1,2,-2,3,-3,4]: |d| ties are {1:2, 2:2, 3:2, 4:1}.
    # average ranks: 1.5,1.5,3.5,5.5,3.5,5.5,7 -> W+=19, W-=9, W=9.
    # mu = 7*8/4 = 14; sigma^2 = 7*8*15/24 - (3*(8-2)+(1-1))/48 = 35 - 18/48
    # = 34.625; sigma = 5.88430114796991.
    # z = (9 - 14 + 0.5)/sigma = -0.7647467195917572.
    # p = 2*Phi(z) = 0.4444223801830105 (math.erf).
    result = stats.wilcoxon_signed_rank([1, 1, 2, -2, 3, -3, 4])
    assert result["method"] == "normal"
    assert result["w_plus"] == 19 and result["w_minus"] == 9
    assert result["z"] == pytest.approx(-0.7647467195917572)
    assert result["p"] == pytest.approx(0.4444223801830105)


def test_wilcoxon_large_n_uses_normal():
    # n = 26 > 25, no ties: mu = 175.5, sigma^2 = 1550.25,
    # sigma = 39.3726995; W=0 -> z = (0-175.5+0.5)/sigma = -4.444646020263513,
    # p = 8.803669768964184e-06.
    result = stats.wilcoxon_signed_rank(list(range(1, 27)))
    assert result["method"] == "normal"
    assert result["statistic"] == 0
    assert result["z"] == pytest.approx(-4.444646020263513)
    assert result["p"] == pytest.approx(8.803669768964184e-06)


def test_a12_and_cliffs_delta():
    assert stats.a12([1, 2, 3], [1, 1, 1]) == pytest.approx(7.5 / 9)
    assert stats.cliffs_delta([1, 2, 3], [1, 1, 1]) == pytest.approx(
        2 * 7.5 / 9 - 1)


def test_bootstrap_is_seed_deterministic():
    units = [("a", 1.0), ("a", 0.0), ("b", 1.0), ("b", 0.0), ("c", 0.0)]
    first = stats.cluster_bootstrap_diff(units, n_boot=500, seed=7)
    second = stats.cluster_bootstrap_diff(units, n_boot=500, seed=7)
    assert first == second


def test_bootstrap_all_equal_diffs_is_a_point():
    units = [("a", 0.3), ("b", 0.3), ("c", 0.3)]
    result = stats.cluster_bootstrap_diff(units, n_boot=200, seed=1)
    assert result["ci_low"] == pytest.approx(0.3)
    assert result["ci_high"] == pytest.approx(0.3)


def test_bootstrap_single_task_degenerates():
    result = stats.cluster_bootstrap_diff([("a", 1.0), ("a", -1.0)],
                                          n_boot=200, seed=1)
    assert result["ci_low"] == result["ci_high"] == pytest.approx(0.0)


def test_bootstrap_resamples_tasks_not_units():
    # Task A: 30 units of +1; task B: 3 units of 0.  Resampling tasks can draw
    # only B (mean 0), so the lower bound is 0; resampling units cannot leave
    # the mean near 0.
    units = [("A", 1.0)] * 30 + [("B", 0.0)] * 3
    result = stats.cluster_bootstrap_diff(units, n_boot=5000, seed=20260928)
    assert result["ci_low"] == 0.0

    rng = random.Random(11)
    diffs = [1.0] * 30 + [0.0] * 3
    means = []
    for _ in range(5000):
        draw = [diffs[rng.randrange(len(diffs))] for _ in diffs]
        means.append(sum(draw) / len(draw))
    means.sort()
    unit_low = means[int(0.025 * len(means))]
    assert unit_low > 0.5


def test_obf_alpha_spent():
    assert stats.obf_alpha_spent(0.6) == pytest.approx(0.011396, abs=1e-6)
    assert stats.obf_alpha_spent(1.0) == pytest.approx(0.05, abs=1e-9)


def test_obf_nominal_boundaries():
    # Reference values from an independent SciPy computation (the reviewer used
    # `multivariate_normal` rectangle probabilities and nested
    # `scipy.integrate.quad`), not from this implementation.
    cases = {
        (0.6, 1.0): [0.0113964, 0.0456610],
        (0.45, 0.8): [0.0034808, 0.0270731],
        (0.3, 1.0): [0.0003457, 0.0498488],
        (0.9, 1.0): [0.0388300, 0.0376624],
        (0.3, 0.7, 1.0): [0.0003457, 0.0190047, 0.0429893],
        (0.6, 0.8, 1.0): [0.0113964, 0.0243841, 0.0391598],
    }
    for looks, expected in cases.items():
        got = stats.obf_nominal_boundaries(list(looks))
        assert got == pytest.approx(expected, abs=2e-5), looks
    assert stats.obf_nominal_boundaries([1.0])[0] == pytest.approx(
        0.05, abs=2e-5)


def test_normal_cdf_and_ppf():
    assert stats.normal_ppf(0.975) == pytest.approx(1.959964, abs=1e-6)
    assert stats.normal_cdf(0.0) == pytest.approx(0.5)
    assert stats.normal_cdf(-1.959964) == pytest.approx(0.025, abs=1e-6)


def test_wilcoxon_exact_dp_large_n():
    # n=20, all differences negative -> W+=0, W-=210.  Exact two-sided
    # p = 2 * 1 / 2^20 = 1.9073486328125e-06 (single subset of size 0).
    result = stats.wilcoxon_signed_rank([-i for i in range(1, 21)])
    assert result["method"] == "exact"
    assert result["w_plus"] == 0 and result["w_minus"] == 210
    assert result["p"] == pytest.approx(2 / 2 ** 20)


def test_wilcoxon_exact_matches_textbook_n10():
    # n=10, no ties: negative ranks {1,2,3} -> W=6.  Subsets of {1..10} with
    # sum <= 6 number 14 (sums 0,1,2,3(x2),4(x2),5(x3),6(x4)); two-sided
    # p = 2*14/2^10 = 0.02734375.
    diffs = [4, 5, 6, 7, 8, 9, 10, -1, -2, -3]
    result = stats.wilcoxon_signed_rank(diffs)
    assert result["method"] == "exact"
    assert result["statistic"] == 6
    assert result["p"] == pytest.approx(0.02734375)
