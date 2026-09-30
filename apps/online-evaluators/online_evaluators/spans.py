"""Read the few facts the evaluators need out of OpenTelemetry session spans.

AgentCore hands a code-based evaluator the session's spans as OTLP-style JSON. Field names
differ slightly between exporters (``startTimeUnixNano`` vs ``startTime``), so every accessor
tolerates the known variants and returns ``None`` instead of raising.
"""

from __future__ import annotations

from typing import Any

_ERROR_STATUSES = {"ERROR", "STATUS_CODE_ERROR", 2, "2"}


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def span_name(span: dict) -> str:
    """Return the span's name, or an empty string."""
    return str(span.get("name") or "")


def _nanos(span: dict, *keys: str) -> float | None:
    for key in keys:
        if (value := _number(span.get(key))) is not None:
            return value
    return None


def span_bounds_ms(span: dict) -> tuple[float, float] | None:
    """Return ``(start, end)`` in milliseconds, or ``None`` when the span has no timing."""
    start = _nanos(span, "startTimeUnixNano", "start_time_unix_nano", "startTime")
    end = _nanos(span, "endTimeUnixNano", "end_time_unix_nano", "endTime")
    if start is None or end is None:
        return None
    return start / 1e6, end / 1e6


def is_error(span: dict) -> bool:
    """Return whether the span failed or recorded an exception event."""
    status = span.get("status")
    code = status.get("code") if isinstance(status, dict) else status
    if code in _ERROR_STATUSES or str(code).upper() in _ERROR_STATUSES:
        return True
    return any(
        isinstance(event, dict) and event.get("name") == "exception"
        for event in span.get("events") or []
    )


def is_retrieval(span: dict) -> bool:
    """Return whether the span is a Knowledge Base ``Retrieve`` call."""
    if "retrieve" in span_name(span).lower():
        return True
    attributes = span.get("attributes")
    if not isinstance(attributes, dict):
        return False
    return any(
        isinstance(value, str)
        and value == "Retrieve"
        and any(part in str(key).lower() for part in ("operation", "method"))
        for key, value in attributes.items()
    )


def session_duration_ms(spans: list[dict]) -> float | None:
    """Return the wall-clock span of the whole session in milliseconds."""
    bounds = [b for s in spans if (b := span_bounds_ms(s)) is not None]
    if not bounds:
        return None
    return max(end for _, end in bounds) - min(start for start, _ in bounds)
