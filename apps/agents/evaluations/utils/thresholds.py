"""Evaluate aggregate experiment scores against regression thresholds."""

import logging

logger = logging.getLogger(__name__)


def check_regressions(
    scores: dict[str, list[float]],
    thresholds: dict[str, float],
    *,
    item_count: int,
) -> list[tuple[str, float, float]]:
    """Find evaluator means that fall below their regression thresholds.

    Args:
        scores: Numeric values grouped by evaluator name.
        thresholds: Minimum acceptable mean for each gated evaluator.
        item_count: Number of dataset items executed by the experiment.

    Returns:
        Tuples of evaluator name, observed mean, and required minimum for each regression.
        A run with no items returns a synthetic regression; evaluators with no numeric scores
        are logged and skipped.
    """
    if item_count == 0:
        return [("<no dataset items ran>", 0.0, 0.0)]

    misses: list[tuple[str, float, float]] = []
    for name in sorted(thresholds):
        values = scores.get(name)
        if not values:
            logger.warning(
                "Evaluator %r produced no numeric score - gate not applied", name
            )
            continue
        mean = sum(values) / len(values)
        if mean < thresholds[name]:
            misses.append((name, mean, thresholds[name]))
    return misses
