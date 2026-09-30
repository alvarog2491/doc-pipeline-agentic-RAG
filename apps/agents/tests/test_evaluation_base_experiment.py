"""Test the experiment task, session sharing, expectations and regression gate."""

from types import SimpleNamespace

import base_experiment
import pytest
from agent_client import AgentRun
from langfuse import Evaluation, RegressionError

from tests.experiments_under_test import make_experiment


class _Client:
    def get_current_trace_id(self):
        return "t" * 32

    def get_current_observation_id(self):
        return "o" * 16


def _item(id, input, **metadata):
    return SimpleNamespace(id=id, input=input, metadata=metadata)


async def test_task_runs_every_turn_on_one_session_and_attaches_expectations(
    monkeypatch,
):
    seen = []

    async def fake_invoke(prompt, knowledge_base_id, session_id, *, trace_context=None):
        seen.append((prompt, knowledge_base_id, session_id, trace_context))
        return AgentRun(
            answer=f"a:{prompt}",
            route="easy",
            ttft_ms=5.0,
            latency_ms=9.0,
            diagnostics={"retrievals": 1},
        )

    monkeypatch.setattr(base_experiment, "invoke_agent", fake_invoke)
    experiment = make_experiment()
    experiment._session_ids = {}

    task = experiment.build_task(_Client(), "ABCDE12345")
    output = await task(
        item=_item(
            "i1",
            {"turns": ["one", "two"]},
            expected_route="easy",
            key_facts=["x"],
            ignored="y",
        )
    )

    assert [call[0] for call in seen] == ["one", "two"]
    assert len({call[2] for call in seen}) == 1  # the same session for every turn
    assert seen[0][1] == "ABCDE12345"
    assert seen[0][3] == {"trace_id": "t" * 32, "parent_span_id": "o" * 16}
    assert output["answer"] == "a:two"  # the last turn is what gets graded
    assert output["expectations"] == {"expected_route": "easy", "key_facts": ["x"]}
    assert experiment._session_ids["i1"] == output["session_id"]


def _result(items, evaluations):
    item_results = [
        SimpleNamespace(
            item=SimpleNamespace(id=i),
            evaluations=[Evaluation(name=n, value=v) for n, v in evals],
        )
        for i, evals in zip(items, evaluations, strict=True)
    ]
    return SimpleNamespace(item_results=item_results, format=lambda: "report")


def _run(experiment, result, expected=None):
    experiment._session_ids = {}
    return experiment._run(lambda **kwargs: result, _Client(), "ABCDE12345", expected)


def test_passing_scores_return_the_result():
    experiment = make_experiment({"keyfact_recall": 0.8})
    result = _result(["a", "b"], [[("keyfact_recall", 1.0)], [("keyfact_recall", 0.7)]])

    assert _run(experiment, result) is result


def test_a_mean_below_threshold_raises_a_regression_error():
    experiment = make_experiment({"keyfact_recall": 0.8})
    result = _result(["a", "b"], [[("keyfact_recall", 0.5)], [("keyfact_recall", 0.5)]])

    with pytest.raises(RegressionError, match="keyfact_recall mean 0.500 < 0.80"):
        _run(experiment, result)


def test_items_that_never_completed_fail_the_run_and_name_their_sessions():
    experiment = make_experiment({"keyfact_recall": 0.8})
    experiment._session_ids = {}
    result = _result(["a"], [[("keyfact_recall", 1.0)]])

    def run_experiment(**kwargs):
        experiment._session_ids.update({"a": "sess-a", "b": "sess-b"})
        return result

    with pytest.raises(RegressionError, match=r"never completed: b \(session sess-b\)"):
        experiment._run(run_experiment, _Client(), "ABCDE12345")


def test_dropped_items_are_caught_by_the_expected_count():
    experiment = make_experiment({"keyfact_recall": 0.8})
    result = _result(["a"], [[("keyfact_recall", 1.0)]])

    with pytest.raises(RegressionError, match="2 of 3 item"):
        _run(experiment, result, expected=3)


def test_experiment_env_override_skips_publishing_the_fixture(monkeypatch):
    monkeypatch.setenv("EVAL_KNOWLEDGE_BASE_ID", "ZZZZZ99999")

    assert base_experiment.resolve_knowledge_base_id() == "ZZZZZ99999"
