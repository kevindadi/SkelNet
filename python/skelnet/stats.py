"""Round-8 statistics: pure functions, standard library only.

Every random quantity uses an explicit :class:`random.Random` instance, so the
same input and seed produce byte-identical output.  No network, no external
tool, no SciPy/NumPy: the normal and chi-square tails are implemented here with
series / continued-fraction expansions of the regularized incomplete gamma.
"""

from __future__ import annotations

import math
import random
import statistics

__all__ = [
    "pass_at_k", "mcnemar_exact", "stratified_mcnemar", "holm", "cochran_q",
    "chi2_sf", "wilcoxon_signed_rank", "a12", "cliffs_delta",
    "cluster_bootstrap_diff", "obf_alpha_spent", "obf_nominal_boundaries",
    "normal_cdf", "normal_ppf", "normal_pdf",
]


def pass_at_k(n: int, c: int, k: int) -> float:
    """Unbiased pass@k estimate: ``1 - C(n-c, k) / C(n, k)``.

    ``n - c < k`` means at least one of the ``k`` draws is correct for sure, so
    the estimate is 1.  ``k > n`` is a caller error.
    """
    if k > n:
        raise ValueError(f"k={k} exceeds n={n}")
    if c >= n or n - c < k:
        return 1.0
    if c <= 0:
        return 0.0
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value (D8-7).

    ``p = min(1, 2 * P(X <= min(b, c)))`` for ``X ~ Bin(b + c, 1/2)``; ``b + c
    == 0`` gives ``p = 1``.
    """
    if b < 0 or c < 0:
        raise ValueError("b and c must be non-negative")
    n = b + c
    if n == 0:
        return 1.0
    m = min(b, c)
    tail = sum(math.comb(n, i) for i in range(m + 1)) / 2 ** n
    return min(1.0, 2.0 * tail)


def stratified_mcnemar(pairs_by_model) -> dict:
    """Merge per-model discordant counts and run the exact test (D8-7).

    ``pairs_by_model`` maps a model to a list of ``(reference_ok, control_ok)``
    booleans.  ``b`` counts reference-ok/control-fail, ``c`` the reverse.
    """
    total_b = total_c = 0
    per_model: dict[str, dict[str, int]] = {}
    for model, pairs in pairs_by_model.items():
        b = c = 0
        for reference_ok, control_ok in pairs:
            if reference_ok and not control_ok:
                b += 1
            elif control_ok and not reference_ok:
                c += 1
        per_model[model] = {"b": b, "c": c}
        total_b += b
        total_c += c
    return {"b": total_b, "c": total_c, "p": mcnemar_exact(total_b, total_c),
            "per_model": per_model}


def holm(pvalues) -> list[float]:
    """Holm-Bonferroni adjusted p-values in the input order (D8-8)."""
    m = len(pvalues)
    order = sorted(range(m), key=lambda i: pvalues[i])
    adjusted = [0.0] * m
    running = 0.0
    for rank, index in enumerate(order):
        value = (m - rank) * pvalues[index]
        running = max(running, value)
        adjusted[index] = min(1.0, running)
    return adjusted


def normal_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def normal_ppf(p: float) -> float:
    """Inverse standard normal CDF by bisection (error < 1e-10)."""
    if not 0.0 < p < 1.0:
        raise ValueError("p must be in (0, 1)")
    low, high = -40.0, 40.0
    for _ in range(200):
        mid = (low + high) / 2.0
        if normal_cdf(mid) < p:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


def _gamma_series(a: float, x: float) -> float:
    """Regularized lower incomplete gamma P(a, x) by series (x < a + 1)."""
    total = 1.0 / a
    term = total
    ap = a
    for _ in range(1000):
        ap += 1.0
        term *= x / ap
        total += term
        if abs(term) < abs(total) * 3e-16:
            break
    return total * math.exp(-x + a * math.log(x) - math.lgamma(a))


def _gamma_cf(a: float, x: float) -> float:
    """Regularized upper incomplete gamma Q(a, x) by continued fraction."""
    tiny = 1e-300
    b = x + 1.0 - a
    c = 1.0 / tiny
    d = 1.0 / b
    h = d
    for i in range(1, 1000 + 1):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 3e-16:
            break
    return math.exp(-x + a * math.log(x) - math.lgamma(a)) * h


def _gamma_p(a: float, x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x < a + 1.0:
        return _gamma_series(a, x)
    return 1.0 - _gamma_cf(a, x)


def chi2_sf(x: float, df: int) -> float:
    """Upper-tail chi-square survival function P(X > x) for ``df`` degrees."""
    if df <= 0:
        raise ValueError("df must be positive")
    if x <= 0.0:
        return 1.0
    a = df / 2.0
    xx = x / 2.0
    if xx < a + 1.0:
        return 1.0 - _gamma_series(a, xx)
    # Direct continued fraction on the upper tail avoids cancellation.
    return _gamma_cf(a, xx)


def cochran_q(blocks) -> dict:
    """Cochran's Q over ``blocks`` (one row per unit, one column per group).

    Returns ``{"Q", "df", "p"}``; an all-identical block set (zero variance)
    gives ``Q = 0, p = 1``.
    """
    n = len(blocks)
    if n == 0:
        return {"Q": 0.0, "df": 0, "p": 1.0}
    k = len(blocks[0])
    if k < 2:
        return {"Q": 0.0, "df": k - 1, "p": 1.0}
    columns = [sum(row[j] for row in blocks) for j in range(k)]
    rows = [sum(row) for row in blocks]
    total = sum(columns)
    denominator = k * total - sum(r * r for r in rows)
    if denominator == 0:
        return {"Q": 0.0, "df": k - 1, "p": 1.0}
    numerator = (k - 1) * (k * sum(c * c for c in columns) - total * total)
    q = numerator / denominator
    return {"Q": q, "df": k - 1, "p": chi2_sf(q, k - 1)}


def _average_ranks(values) -> tuple[list[float], list[int]]:
    """Fractional ranks (1-based) and the sizes of the tied rank groups."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    ties: list[int] = []
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        group = j - i + 1
        ties.append(group)
        average = (i + j + 2) / 2.0  # (i+1 + j+1) / 2
        for t in range(i, j + 1):
            ranks[order[t]] = average
        i = j + 1
    return ranks, ties


def wilcoxon_signed_rank(diffs) -> dict:
    """Two-sided Wilcoxon signed-rank test (D8-10).

    Zero differences are dropped.  Without ties and ``n <= 25`` the exact
    distribution is enumerated; otherwise the normal approximation is used with
    a tie correction and a continuity correction.
    """
    nonzero = [d for d in diffs if d != 0]
    n = len(nonzero)
    if n == 0:
        return {"statistic": 0.0, "p": 1.0, "w_plus": 0.0, "w_minus": 0.0,
                "n": 0, "method": "exact", "z": None}
    ranks, ties = _average_ranks([abs(d) for d in nonzero])
    w_plus = sum(r for r, d in zip(ranks, nonzero) if d > 0)
    w_minus = sum(r for r, d in zip(ranks, nonzero) if d < 0)
    statistic = min(w_plus, w_minus)
    has_ties = any(t > 1 for t in ties)

    if n <= 25 and not has_ties:
        # Dynamic programming over the distribution of W+ (ranks 1..n).
        max_sum = n * (n + 1) // 2
        counts = [0] * (max_sum + 1)
        counts[0] = 1
        for rank in range(1, n + 1):
            for total in range(max_sum, rank - 1, -1):
                counts[total] += counts[total - rank]
        cut = int(round(statistic))
        count = sum(counts[:cut + 1]) if cut >= 0 else 0
        p = min(1.0, 2.0 * count / (1 << n))
        return {"statistic": statistic, "p": p, "w_plus": w_plus,
                "w_minus": w_minus, "n": n, "method": "exact", "z": None}

    mean = n * (n + 1) / 4.0
    tie_sum = sum(t * t * t - t for t in ties)
    variance = n * (n + 1) * (2 * n + 1) / 24.0 - tie_sum / 48.0
    if variance <= 0.0:
        return {"statistic": statistic, "p": 1.0, "w_plus": w_plus,
                "w_minus": w_minus, "n": n, "method": "normal", "z": None}
    sigma = math.sqrt(variance)
    correction = 0.5 if statistic < mean else (-0.5 if statistic > mean else 0.0)
    z = (statistic - mean + correction) / sigma
    p = min(1.0, 2.0 * normal_cdf(z))
    return {"statistic": statistic, "p": p, "w_plus": w_plus, "w_minus": w_minus,
            "n": n, "method": "normal", "z": z}


def a12(xs, ys) -> float:
    """Vargha-Delaney A12: ``P(X > Y) + 0.5 P(X = Y)`` (X is the first sample)."""
    if not xs or not ys:
        raise ValueError("samples must be non-empty")
    greater = less = equal = 0
    for x in xs:
        for y in ys:
            if x > y:
                greater += 1
            elif x < y:
                less += 1
            else:
                equal += 1
    total = len(xs) * len(ys)
    return (greater + 0.5 * equal) / total


def cliffs_delta(xs, ys) -> float:
    return 2.0 * a12(xs, ys) - 1.0


def _percentile(sorted_values: list[float], fraction: float) -> float:
    """Inclusive linear-interpolation percentile (fraction in [0, 1])."""
    n = len(sorted_values)
    if n == 0:
        raise ValueError("no values")
    if n == 1:
        return sorted_values[0]
    position = fraction * (n - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return sorted_values[lower]
    weight = position - lower
    return sorted_values[lower] + weight * (sorted_values[upper]
                                            - sorted_values[lower])


def cluster_bootstrap_diff(units, *, n_boot: int, seed: int,
                           alpha: float = 0.05) -> dict:
    """Cluster (task) bootstrap CI for a pooled mean difference (D8-6).

    ``units`` is a sequence of ``(task, difference)`` pairs.  Each iteration
    resamples the *tasks* with replacement; a drawn task brings all of its
    units.  Returns the point estimate and the percentile CI.
    """
    by_task: dict[str, list[float]] = {}
    total = 0.0
    count = 0
    for task, diff in units:
        by_task.setdefault(task, []).append(diff)
        total += diff
        count += 1
    if count == 0:
        return {"point": float("nan"), "ci_low": float("nan"),
                "ci_high": float("nan"), "n_boot": n_boot, "n_tasks": 0}
    point = total / count
    tasks = sorted(by_task)
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(n_boot):
        total_draw = 0.0
        draw_count = 0
        for _ in tasks:
            drawn = tasks[rng.randrange(len(tasks))]
            values = by_task[drawn]
            total_draw += sum(values)
            draw_count += len(values)
        means.append(total_draw / draw_count)
    means.sort()
    return {"point": point, "ci_low": _percentile(means, alpha / 2.0),
            "ci_high": _percentile(means, 1.0 - alpha / 2.0),
            "n_boot": n_boot, "n_tasks": len(tasks)}


def obf_alpha_spent(t: float, alpha: float = 0.05) -> float:
    """Lan-DeMets O'Brien-Fleming cumulative alpha spent at information ``t``."""
    if not 0.0 < t <= 1.0:
        raise ValueError("t must be in (0, 1]")
    z = normal_ppf(1.0 - alpha / 2.0)
    return 2.0 * (1.0 - normal_cdf(z / math.sqrt(t)))


def _simpson(values, a: float, b: float) -> float:
    """Composite Simpson integral of ``values`` on ``n+1`` nodes of ``[a, b]``."""
    n = len(values) - 1
    if n <= 0:
        return 0.0
    if n == 1:
        return (values[0] + values[1]) * (b - a) / 2.0
    if n % 2 == 1:
        # Trapezoid on the last interval, Simpson on the rest.
        h = (b - a) / n
        tail = (values[-2] + values[-1]) * h / 2.0
        return _simpson(values[:-1], a, b - h) + tail
    h = (b - a) / n
    total = values[0] + values[-1]
    for i in range(1, n):
        total += (4.0 if i % 2 else 2.0) * values[i]
    return total * h / 3.0


_OBF_NODES = 1000


def _crossing_probability(f, grid, c_prev: float, c: float, rho: float,
                          sigma: float) -> float:
    """P(no crossing before |Z_k| >= c) for the next analysis."""
    values = []
    for z, density in zip(grid, f):
        upper = 1.0 - normal_cdf((c - rho * z) / sigma)
        lower = normal_cdf((-c - rho * z) / sigma)
        values.append(density * (upper + lower))
    return _simpson(values, -c_prev, c_prev)


def _solve_boundary(f, grid, c_prev: float, rho: float, sigma: float,
                    target: float) -> float:
    low, high = 0.0, 12.0
    for _ in range(60):
        mid = (low + high) / 2.0
        if _crossing_probability(f, grid, c_prev, mid, rho, sigma) > target:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


def _propagate(f, grid, c_prev: float, c_new: float, rho: float,
               sigma: float):
    """Sub-density of Z_{k+1} on [-c_new, c_new] given the no-crossing density."""
    new_grid = [-c_new + 2.0 * c_new * i / _OBF_NODES
                for i in range(_OBF_NODES + 1)]
    out = []
    for z_next in new_grid:
        values = [density * normal_pdf((z_next - rho * z) / sigma) / sigma
                  for z, density in zip(grid, f)]
        out.append(_simpson(values, -c_prev, c_prev))
    return out, new_grid


def obf_nominal_boundaries(looks, alpha: float = 0.05) -> list[float]:
    """Nominal two-sided alpha at each analysis from the OBF spending function.

    ``looks`` are information fractions (the futility-only first look is not
    included).  The recursion follows Armitage-McPherson-Rowe with composite
    Simpson integration and the conditional density
    ``Z_{k+1} | Z_k = z ~ N(rho z, 1 - rho^2)``, ``rho = sqrt(t_k / t_{k+1})``.
    """
    looks = [float(t) for t in looks]
    if not looks:
        return []
    spent = [obf_alpha_spent(t, alpha) for t in looks]
    increments = [spent[0]] + [spent[i] - spent[i - 1]
                               for i in range(1, len(looks))]
    if increments[0] <= 0.0:
        boundaries = [0.0]
        c_prev = 0.0
    else:
        c_prev = normal_ppf(1.0 - increments[0] / 2.0)
        boundaries = [increments[0]]
    grid = [-c_prev + 2.0 * c_prev * i / _OBF_NODES
            for i in range(_OBF_NODES + 1)]
    f = [normal_pdf(z) for z in grid]
    for k in range(1, len(looks)):
        t_prev, t = looks[k - 1], looks[k]
        rho = math.sqrt(t_prev / t)
        sigma = math.sqrt(max(1e-12, 1.0 - t_prev / t))
        c = _solve_boundary(f, grid, c_prev, rho, sigma, increments[k])
        boundaries.append(2.0 * (1.0 - normal_cdf(c)))
        f, grid = _propagate(f, grid, c_prev, c, rho, sigma)
        c_prev = c
    return boundaries


def median(values):
    return statistics.median(values)
