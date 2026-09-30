"""AgentCore code-based evaluator entrypoint.

One Lambda serves every evaluator; ``evaluatorName`` in the payload selects the check. All
checks are session-level and deterministic, so scoring live traffic costs a Lambda invocation
rather than model tokens:

* ``ErrorFree``          - fraction of spans that did not fail
* ``LatencyBudget``      - the session finished within ``LATENCY_BUDGET_MS``
* ``GroundedRetrieval``  - the agent searched the Knowledge Base at least once
* ``RetrievalBudget``    - the agent used at most ``MAX_RETRIEVALS`` searches (no runaway loops)
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from online_evaluators.spans import (
    is_error,
    is_retrieval,
    session_duration_ms,
)

DEFAULT_LATENCY_BUDGET_MS = 90_000.0
DEFAULT_MAX_RETRIEVALS = 12


def _result(score: float, explanation: str) -> dict[str, Any]:
    score = max(0.0, min(1.0, score))
    return {
        "label": "PASS" if score >= 1.0 else "FAIL",
        "score": round(score, 4),
        "explanation": explanation,
    }


def error_free(spans: list[dict]) -> dict[str, Any]:
    """Score the share of spans that completed without an error or exception."""
    failed = sum(1 for span in spans if is_error(span))
    return _result(1 - failed / len(spans), f"{failed} of {len(spans)} span(s) failed")


def latency_budget(spans: list[dict]) -> dict[str, Any]:
    """Score 1.0 within the latency budget, otherwise the budget over the actual duration."""
    budget = float(os.environ.get("LATENCY_BUDGET_MS", DEFAULT_LATENCY_BUDGET_MS))
    duration = session_duration_ms(spans)
    if duration is None:
        return {
            "errorCode": "NoTiming",
            "errorMessage": "spans carry no start/end times",
        }
    score = 1.0 if duration <= budget else budget / duration
    return _result(score, f"session took {duration:.0f} ms, budget {budget:.0f} ms")


def grounded_retrieval(spans: list[dict]) -> dict[str, Any]:
    """Pass when the session searched the Knowledge Base at least once."""
    count = sum(1 for span in spans if is_retrieval(span))
    return _result(1.0 if count else 0.0, f"{count} Knowledge Base search(es)")


def retrieval_budget(spans: list[dict]) -> dict[str, Any]:
    """Score 1.0 within the retrieval budget, otherwise the budget over the count used."""
    limit = int(os.environ.get("MAX_RETRIEVALS", DEFAULT_MAX_RETRIEVALS))
    count = sum(1 for span in spans if is_retrieval(span))
    score = 1.0 if count <= limit else limit / count
    return _result(score, f"{count} Knowledge Base search(es), budget {limit}")


EVALUATORS: dict[str, Callable[[list[dict]], dict[str, Any]]] = {
    "ErrorFree": error_free,
    "LatencyBudget": latency_budget,
    "GroundedRetrieval": grounded_retrieval,
    "RetrievalBudget": retrieval_budget,
}


def lambda_handler(event: dict, _context: object = None) -> dict[str, Any]:
    """Score one agent session.

    Args:
        event: AgentCore evaluation payload (``schemaVersion`` 1.0) carrying
            ``evaluatorName`` and ``evaluationInput.sessionSpans``.
        _context: Lambda context (unused).

    Returns:
        ``{"label", "score", "explanation"}`` on success, or ``{"errorCode", "errorMessage"}``
        when the evaluator is unknown or the payload has no spans.
    """
    name = str(event.get("evaluatorName", ""))
    # AgentCore may suffix names with the environment; match on the registered base name.
    evaluator = next(
        (fn for key, fn in EVALUATORS.items() if name.startswith(key)), None
    )
    if evaluator is None:
        return {
            "errorCode": "UnknownEvaluator",
            "errorMessage": f"no evaluator named {name!r}",
        }
    spans = (event.get("evaluationInput") or {}).get("sessionSpans") or []
    spans = [span for span in spans if isinstance(span, dict)]
    if not spans:
        return {
            "errorCode": "NoSpans",
            "errorMessage": "the payload contains no session spans",
        }
    return evaluator(spans)
