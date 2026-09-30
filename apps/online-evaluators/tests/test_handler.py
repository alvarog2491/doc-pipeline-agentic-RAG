import pytest
from online_evaluators import handler
from online_evaluators.spans import is_error, is_retrieval, session_duration_ms

MS = 1_000_000


def _span(name="op", start=0, end=1000, status="OK", **extra):
    return {
        "name": name,
        "startTimeUnixNano": start * MS,
        "endTimeUnixNano": end * MS,
        "status": {"code": status},
        **extra,
    }


def _event(name, spans):
    return {
        "schemaVersion": "1.0",
        "evaluatorName": name,
        "evaluationLevel": "SESSION",
        "evaluationInput": {"sessionSpans": spans},
    }


def test_error_free_scores_the_share_of_healthy_spans():
    spans = [
        _span(),
        _span(),
        _span(status="ERROR"),
        _span(events=[{"name": "exception"}]),
    ]

    result = handler.lambda_handler(_event("ErrorFree", spans))

    assert result["score"] == 0.5 and result["label"] == "FAIL"
    assert "2 of 4" in result["explanation"]


def test_error_free_passes_a_clean_session():
    assert (
        handler.lambda_handler(_event("ErrorFree", [_span(), _span()]))["label"]
        == "PASS"
    )


def test_latency_budget_uses_the_whole_session_window(monkeypatch):
    monkeypatch.setenv("LATENCY_BUDGET_MS", "10000")
    fast = [_span(start=0, end=4000), _span(start=1000, end=9000)]
    slow = [_span(start=0, end=20000)]

    assert handler.lambda_handler(_event("LatencyBudget", fast))["score"] == 1.0
    assert handler.lambda_handler(_event("LatencyBudget", slow))["score"] == 0.5


def test_latency_needs_timing_information():
    result = handler.lambda_handler(_event("LatencyBudget", [{"name": "x"}]))

    assert result["errorCode"] == "NoTiming"


def test_retrieval_spans_are_recognised_by_name_or_operation_attribute():
    assert is_retrieval({"name": "BedrockAgentRuntime.Retrieve"})
    assert is_retrieval({"name": "x", "attributes": {"rpc.method": "Retrieve"}})
    assert not is_retrieval(
        {"name": "ChatBedrockConverse", "attributes": {"rpc.method": "Converse"}}
    )


def test_grounded_retrieval_requires_at_least_one_search():
    searched = [_span("BedrockAgentRuntime.Retrieve"), _span()]

    assert (
        handler.lambda_handler(_event("GroundedRetrieval", searched))["label"] == "PASS"
    )
    assert (
        handler.lambda_handler(_event("GroundedRetrieval", [_span()]))["score"] == 0.0
    )


def test_retrieval_budget_penalises_runaway_searching(monkeypatch):
    monkeypatch.setenv("MAX_RETRIEVALS", "2")
    spans = [_span("Retrieve") for _ in range(4)]

    result = handler.lambda_handler(_event("RetrievalBudget", spans))

    assert result["score"] == 0.5 and "budget 2" in result["explanation"]


def test_registered_names_may_carry_an_environment_suffix():
    result = handler.lambda_handler(_event("ErrorFreeProd", [_span()]))

    assert result["label"] == "PASS"


@pytest.mark.parametrize(
    "event,code",
    [
        (_event("Nope", [_span()]), "UnknownEvaluator"),
        (_event("ErrorFree", []), "NoSpans"),
        ({"evaluatorName": "ErrorFree"}, "NoSpans"),
    ],
)
def test_bad_payloads_return_an_error_contract_not_an_exception(event, code):
    assert handler.lambda_handler(event)["errorCode"] == code


def test_status_codes_are_read_in_every_known_shape():
    assert is_error({"status": {"code": "STATUS_CODE_ERROR"}})
    assert is_error({"status": {"code": 2}})
    assert is_error({"status": "ERROR"})
    assert not is_error({"status": {"code": "OK"}})
    assert session_duration_ms([{"startTime": 0, "endTime": 5 * MS}]) == 5.0
