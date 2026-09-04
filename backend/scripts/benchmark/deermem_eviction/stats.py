"""Paired statistics pinned by the versioned config.

The exact McNemar test uses the two-sided exact binomial on discordant pairs.
The paired bootstrap resamples cases with replacement using the seeded
``random.Random`` stream from ``statistics.bootstrap_seed`` and reports the
percentile interval at ``statistics.alpha``; the percentile rule is pinned as
``sorted_diffs[floor((alpha / 2) * n)]`` and
``sorted_diffs[floor((1 - alpha / 2) * n) - 1]``.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass


@dataclass(frozen=True)
class McNemarResult:
    both_correct: int
    both_wrong: int
    only_first_correct: int
    only_second_correct: int
    p_value: float


@dataclass(frozen=True)
class BootstrapResult:
    mean_difference: float
    lower: float
    upper: float
    iterations: int
    seed: int
    alpha: float


def exact_mcnemar(pairs: list[tuple[bool, bool]]) -> McNemarResult:
    if not pairs:
        raise ValueError("McNemar requires at least one pair")
    both_correct = sum(1 for first, second in pairs if first and second)
    both_wrong = sum(1 for first, second in pairs if not first and not second)
    only_first = sum(1 for first, second in pairs if first and not second)
    only_second = sum(1 for first, second in pairs if not first and second)
    discordant = only_first + only_second
    if discordant == 0:
        p_value = 1.0
    else:
        tail = sum(math.comb(discordant, k) for k in range(min(only_first, only_second) + 1)) * 0.5**discordant
        p_value = min(1.0, 2.0 * tail)
    return McNemarResult(both_correct=both_correct, both_wrong=both_wrong, only_first_correct=only_first, only_second_correct=only_second, p_value=p_value)


def paired_bootstrap_difference(pairs: list[tuple[bool, bool]], *, seed: int, iterations: int, alpha: float) -> BootstrapResult:
    if not pairs:
        raise ValueError("The paired bootstrap requires at least one pair")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be between 0 and 1")
    generator = random.Random(seed)
    count = len(pairs)
    differences: list[float] = []
    for _ in range(iterations):
        resample = [pairs[generator.randrange(count)] for _ in range(count)]
        differences.append(sum(second for _, second in resample) / count - sum(first for first, _ in resample) / count)
    differences.sort()
    lower_index = math.floor((alpha / 2) * iterations)
    upper_index = math.floor((1 - alpha / 2) * iterations) - 1
    mean_difference = sum(second for _, second in pairs) / count - sum(first for first, _ in pairs) / count
    return BootstrapResult(
        mean_difference=mean_difference,
        lower=differences[max(0, lower_index)],
        upper=differences[min(iterations - 1, max(0, upper_index))],
        iterations=iterations,
        seed=seed,
        alpha=alpha,
    )
