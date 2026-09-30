"""Deterministic, zero-cost scorers for the orchestrator.

Every scorer reads a task output produced by ``experiments.base_experiment`` and returns
Langfuse ``Evaluation`` objects. Nothing here calls a model: routing, retrieval, citation,
fact, step, delegation, budget and latency checks are all computed from the run itself.

Expectations arrive on ``output["expectations"]`` (copied from the dataset item, because
Langfuse flattens and truncates item metadata):

* ``expected_route``  - ``easy`` | ``hard`` | ``guide``
* ``expected_pages``  - pages that hold the answer
* ``key_facts``       - facts the answer must state; each entry is a phrase or a list of alternatives
* ``forbidden``       - phrases that must not appear (hallucination guard)
* ``answerable``      - ``false`` when the document does not contain the answer
* ``required_steps``  - ordered keyword alternatives a guide must contain
* ``min_sections``    - minimum subagent-extracted sections for a guide
* ``max_retrievals``  - retrieval budget for the route
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from evaluators.text import (
    ABSTENTION,
    fact_present,
    first_positions,
    is_consecutive_from_one,
    markers,
    numbered_items,
)
from langfuse import Evaluation

# Time-to-first-token budgets in milliseconds, by route. The easy route promises an
# answer that starts right away; the others spend time thinking before the first token.
TTFT_BUDGET_MS = {"easy": 8_000, "hard": 25_000, "guide": 40_000}
DEFAULT_RETRIEVAL_BUDGET = {"easy": 1, "hard": 8, "guide": 12}


def _score(name: str, value: float, comment: str = "") -> Evaluation:
    return Evaluation(
        name=name, value=float(value), data_type="NUMERIC", comment=comment or None
    )


def _retrieved_pages(output: dict) -> list[int]:
    retrieved = output.get("diagnostics", {}).get("retrieved", [])
    return [item["page"] for item in retrieved]


def route_accuracy(output: dict, expect: dict) -> list[Evaluation]:
    """Score 1 when the orchestrator chose the expected route."""
    if "expected_route" not in expect:
        return []
    actual, wanted = output.get("route", ""), expect["expected_route"]
    return [
        _score(
            "route_accuracy",
            actual == wanted,
            f"expected {wanted}, got {actual or 'none'}",
        )
    ]


def retrieval_scores(output: dict, expect: dict) -> list[Evaluation]:
    """Score recall of the expected pages, and the reciprocal rank of the first hit."""
    wanted = set(expect.get("expected_pages", []))
    if not wanted or expect.get("answerable") is False:
        return []
    pages = _retrieved_pages(output)
    recall = len(wanted & set(pages)) / len(wanted)
    rank = next((i for i, page in enumerate(pages, 1) if page in wanted), None)
    return [
        _score(
            "retrieval_recall",
            recall,
            f"retrieved pages {sorted(set(pages))}, expected {sorted(wanted)}",
        ),
        _score("retrieval_mrr", 1 / rank if rank else 0.0),
    ]


def citation_scores(output: dict, expect: dict) -> list[Evaluation]:
    """Score that citations exist, resolve to retrieved excerpts, and point at the right pages."""
    answer = output.get("answer", "")
    cited = markers(answer)
    resolved = output.get("citations", [])
    unanswerable = expect.get("answerable") is False
    if unanswerable:
        # An abstention may still cite what it looked at; what it must never do is cite an
        # excerpt that does not exist, so only validity is scored.
        valid = len({c["id"] for c in resolved}) / len(set(cited)) if cited else 1.0
        return [
            _score(
                "citation_validity",
                valid,
                f"{len(resolved)} of {len(set(cited))} marker(s) resolve to a retrieved excerpt",
            )
        ]

    scores = [
        _score("citation_presence", bool(cited), f"{len(cited)} marker(s)"),
        _score(
            "citation_validity",
            len({c["id"] for c in resolved}) / len(set(cited)) if cited else 0.0,
            f"{len(resolved)} of {len(set(cited))} marker(s) resolve to a retrieved excerpt",
        ),
    ]
    wanted = set(expect.get("expected_pages", []))
    if wanted and resolved:
        on_target = sum(1 for c in resolved if c["page"] in wanted)
        scores.append(_score("citation_accuracy", on_target / len(resolved)))
    elif wanted:
        scores.append(_score("citation_accuracy", 0.0, "no resolved citations"))
    return scores


def fact_scores(output: dict, expect: dict) -> list[Evaluation]:
    """Score how many required facts the answer states, and that no forbidden claim appears."""
    answer = output.get("answer", "")
    scores: list[Evaluation] = []
    facts = expect.get("key_facts", [])
    if facts:
        hits = [fact_present(answer, fact) for fact in facts]
        missing = [str(f) for f, hit in zip(facts, hits, strict=True) if not hit]
        scores.append(
            _score(
                "keyfact_recall",
                sum(hits) / len(hits),
                f"missing: {missing}" if missing else "",
            )
        )
    forbidden = expect.get("forbidden", [])
    if forbidden:
        leaked = [f for f in forbidden if fact_present(answer, f)]
        scores.append(
            _score(
                "no_forbidden_claims", not leaked, f"stated: {leaked}" if leaked else ""
            )
        )
    return scores


def abstention_score(output: dict, expect: dict) -> list[Evaluation]:
    """Score that the agent declines unanswerable questions and answers answerable ones."""
    if "answerable" not in expect:
        return []
    abstained = bool(ABSTENTION.search(output.get("answer", "")))
    if expect["answerable"] is False:
        return [
            _score(
                "abstention_correct",
                abstained,
                "should say the document does not cover it",
            )
        ]
    facts = expect.get("key_facts", [])
    answered = (
        all(fact_present(output.get("answer", ""), f) for f in facts) if facts else True
    )
    return [
        _score(
            "abstention_correct",
            answered or not abstained,
            "refused an answerable question",
        )
    ]


def guide_scores(output: dict, expect: dict) -> list[Evaluation]:
    """Score a step-by-step guide's coverage, order and numbering."""
    steps = expect.get("required_steps", [])
    if not steps:
        return []
    answer = output.get("answer", "")
    positions = first_positions(answer, steps)
    found = [p for p in positions if p is not None]
    in_order = found == sorted(
        found
    )  # one numbered step may legitimately carry two required steps
    numbers = numbered_items(answer)
    return [
        _score(
            "guide_step_coverage",
            len(found) / len(steps),
            f"missing step keywords at index {[i for i, p in enumerate(positions) if p is None]}",
        ),
        _score(
            "guide_order_validity",
            in_order and len(found) == len(steps),
            "required steps must appear in order",
        ),
        _score(
            "guide_numbering",
            is_consecutive_from_one(numbers),
            f"item numbers {numbers[:20]}",
        ),
    ]


def delegation_scores(output: dict, expect: dict) -> list[Evaluation]:
    """Score subagent use (guide route) and the retrieval budget of every route."""
    diagnostics = output.get("diagnostics", {})
    route = output.get("route", "")
    scores: list[Evaluation] = []
    if route == "guide" or expect.get("expected_route") == "guide":
        minimum = expect.get("min_sections", 2)
        ok = diagnostics.get("sections", 0) >= minimum
        scores.append(
            _score(
                "subagent_use",
                ok,
                f"{diagnostics.get('sections', 0)} section(s) extracted, expected >= {minimum}",
            )
        )
    elif diagnostics:
        scores.append(
            _score(
                "subagent_use",
                diagnostics.get("sections", 0) == 0,
                "only the guide route delegates",
            )
        )
    if diagnostics:
        budget = expect.get("max_retrievals", DEFAULT_RETRIEVAL_BUDGET.get(route, 12))
        used = diagnostics.get("retrievals", 0)
        scores.append(
            _score(
                "tool_budget",
                1 <= used <= budget,
                f"{used} retrieval(s), budget {budget}",
            )
        )
    return scores


def latency_scores(output: dict, expect: dict) -> list[Evaluation]:
    """Record latency and check the time to first token against the route's budget."""
    ttft, total = output.get("ttft_ms"), output.get("latency_ms", 0.0)
    scores = [_score("latency_ms", total)]
    if ttft is None:
        return [
            *scores,
            _score("ttft_within_budget", 0.0, "no answer text was streamed"),
        ]
    budget = TTFT_BUDGET_MS.get(output.get("route", ""), TTFT_BUDGET_MS["hard"])
    return [
        *scores,
        _score("ttft_ms", ttft),
        _score(
            "ttft_within_budget",
            ttft <= budget,
            f"first token after {ttft:.0f} ms, budget {budget} ms",
        ),
    ]


def answer_shape(output: dict, expect: dict) -> list[Evaluation]:
    """Score that an answer exists and stays within a sane length."""
    answer = output.get("answer", "").strip()
    return [
        _score(
            "answer_well_formed", 0 < len(answer) <= 8_000, f"{len(answer)} characters"
        )
    ]


SCORERS: tuple[Callable[[dict, dict], list[Evaluation]], ...] = (
    route_accuracy,
    retrieval_scores,
    citation_scores,
    fact_scores,
    abstention_score,
    guide_scores,
    delegation_scores,
    latency_scores,
    answer_shape,
)

# Scores recorded for visibility only; they are never gated (no meaningful "minimum mean").
INFORMATIONAL = frozenset({"latency_ms", "ttft_ms", "retrieval_mrr"})


def score_run(*, output: Any, **_kwargs: Any) -> list[Evaluation]:
    """Run every applicable scorer over one experiment item.

    This is the single local evaluator passed to Langfuse's experiment runner.

    Args:
        output: The task's return value: run data plus an ``expectations`` mapping.
        **_kwargs: Other runner-supplied fields (input, expected output, metadata).

    Returns:
        Every score whose expectations the dataset item declares.
    """
    if not isinstance(output, dict):
        return [_score("answer_well_formed", 0.0, "task returned no output")]
    expect = output.get("expectations", {})
    return [evaluation for scorer in SCORERS for evaluation in scorer(output, expect)]
